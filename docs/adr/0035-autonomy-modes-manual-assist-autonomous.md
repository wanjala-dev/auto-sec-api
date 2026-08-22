# ADR 0035 — Autonomy modes: MANUAL, ASSIST, AUTONOMOUS

Status: **PROPOSED** — awaiting Henry
Date: 2026-08-21
Relates to: ADR 0031 (tool contract + risk tiers), ADR 0033 D5 (evaluation execution
mode), ADR 0005 (response actions), SEE-201 (autonomous-principal cap), SEE-203 (risk
tiers), task #140 (agent accountability).

## Context

Henry asked what mechanism would turn the system into three modes: manual, assist,
autonomous.

The honest starting point is that **most of it already exists and is hardcoded as a
boolean.** `components/agents/application/policies/tool_risk.py` is titled "per-tool risk
tiers + the approval/**autonomy** policy" and already carries:

```python
def tool_risk_refusal(risk, *, is_autonomous, approval_granted) -> str | None
```

- Three risk tiers — `read` / `reversible_write` / `irreversible` — with `read` the safe
  default and an explicit instruction to classify UP when unsure.
- One enforcement point: `_risk_gated` in
  `components/agents/infrastructure/adapters/langchain/base.py`, wrapping every promoted
  tool, so the gate is per CALL and not per run.
- `is_autonomous` derived at call time from `is_ai_service_principal(...)` — i.e. from
  IDENTITY, not from configuration.
- A refusal that is a `str` subclass, so a blocked call records as `Failure.DENIED`
  rather than counting as a success.

And the seam has already been shown to take a third value. ADR 0033 D5 added
`EVALUATION_EXECUTION_MODE = "evaluation"`, checked FIRST inside `_risk_gated`, under
which only explicitly-declared `read` tools execute and anything undeclared is refused.
That is a third mode in everything but name, shipped and running.

Adjacent machinery that already implements mode-like behaviour without being called one:

- `ResponseActionExecution` — `status=PROPOSED` and `dry_run=True` by DEFAULT, with
  decision / execution / rollback stamps (ADR 0005).
- Draft-PR remediation — proposes a PR, never merges.
- `workspace.ai_teammate_enabled` — the kill switch.
- `sign_off` — the human approval gate for high-risk artefacts.
- `audit` — the immutable trail.

So this ADR is not proposing a subsystem. It is proposing to **turn two booleans into one
policy object, and to write down what the three settings mean.**

## What the field says

Human-in-the-loop is a spectrum, and the question is *where the gates go* rather than
whether they exist. The load-bearing finding for our design: an agent performing a
low-risk step and a high-risk step inside one workflow needs different oversight at each
step, so oversight must be **dynamic, policy-driven and enforced at the action**
([explainX](https://explainx.ai/blog/human-in-the-loop-ai-when-to-let-agent-run-2026),
[Strata](https://www.strata.io/blog/agentic-identity/practicing-the-human-in-the-loop/)).

That is an argument FOR the shape we already have — per-tool-call risk gating — and
against the obvious alternative of a single global "autonomy switch" consulted once at
run start.

SOC deployments overwhelmingly sit at human-in-the-loop or human-on-the-loop, with the
agent doing triage and evidence gathering and escalating impact
([ReliaQuest](https://reliaquest.com/cyber-knowledge/autonomous-soc/),
[Omdia](https://omdia.tech.informa.com/blogs/2025/nov/the-agentic-soc-secops-evolution-into-agentic-platforms)).

EU AI Act Article 14 requires high-risk AI systems to provide human-machine interface
tools enabling effective oversight by natural persons. That obligation came into force on
**2 August 2026** — three weeks before this ADR — so for EU customers the oversight
surface is a compliance artefact, not only a product one.

## Decisions

**D1 — A mode is a POLICY OBJECT resolved once at run start and carried on the run.**
Not a global flag consulted per call, and not re-read mid-run. A long run must not have
its rules change underneath it because someone toggled a setting while it was executing.
The object answers one question — `permits(risk, approval_granted)` — and
`tool_risk_refusal`'s two booleans collapse into it.

**D2 — Three modes, defined by what they permit:**

| Mode | `read` | `reversible_write` | `irreversible` | Initiated by |
|---|---|---|---|---|
| **MANUAL** | execute | **propose** | **propose** | a human, every run |
| **ASSIST** *(today's behaviour)* | execute | execute | approval required | human or event |
| **AUTONOMOUS** | execute | execute | approval required | scheduler, unattended |

**D3 — AUTONOMOUS does NOT raise the risk ceiling. Irreversible always needs sign-off.**

This is the decision most likely to be argued with, so the reasoning is explicit: the axis
between ASSIST and AUTONOMOUS is *who starts the run and whether a human is waiting* —
not what the agent is permitted to do. If AUTONOMOUS unlocked irreversible actions, the
mode selector would become the most dangerous control in the product, and one dropdown
would separate a customer from unattended destructive writes.

It also preserves the existing SEE-201 cap rather than reversing it: today an autonomous
run is *already* denied irreversible tools and expected to surface a finding instead.
D3 makes that a stated rule instead of an implementation detail.

**D4 — MANUAL proposes; it does not merely refuse.** Today a gated write returns a refusal
string and the work is lost. In MANUAL, a `reversible_write` becomes a
`ResponseActionExecution` in `PROPOSED` state — the machinery ADR 0005 already built,
defaulting to `dry_run=True`. MANUAL is therefore "the agent does the thinking and hands
you the action", not "the agent is crippled". A mode whose only behaviour is refusal
teaches operators to leave it off.

**D5 — The mode is recorded on the run AND on every tool observation, at call time.**

`_risk_gated` resolves a tier per call and `tool_observation` rows persist it; the module
already documents why re-deriving a historical tier from a live map is wrong — "empty the
map and every `delete_task` call already in the database retroactively reports as a
`read`". The same argument applies with more force to mode: "what autonomy was this run
under?" must be answerable from the row, not reconstructed from today's settings. Without
this, an operator who switches to AUTONOMOUS on Friday makes every historical ASSIST run
look autonomous.

For a product selling provenance, this is the part I would build first.

**D6 — Per WORKSPACE to start, not per agent.** Per-agent modes multiply the surface
before anyone has asked for it, and the first question a customer asks is "is the AI
allowed to change things in my account", which is a workspace-level question. Per-agent
override is a later phase, and D1's policy object is what makes it cheap when it comes.

> **Built 2026-08-22 — and the build found that D2's "Initiated by" column was
> the only thing giving AUTONOMOUS a job, while nothing read it.** Eligibility
> for unattended runs came from `ai_teammate_enabled` alone, so the kill switch
> was silently doing D7's job *and* this one. The consequence was worse than an
> inert dial: a workspace could receive a teammate cycle every five minutes
> while its mode displayed ASSIST. `iter_enabled_seeds` now requires BOTH gates
> — power (`ai_teammate_enabled`) and policy (`autonomy_mode == AUTONOMOUS`) —
> and migration `workspaces/0007` moves the workspaces that were already running
> unattended onto AUTONOMOUS, so the set of scheduled workspaces is unchanged and
> the dial stops misreporting them.

**D7 — The kill switch is NOT a fourth mode.** `ai_teammate_enabled` is a separate,
orthogonal axis: OFF means nothing runs at all. Folding it into the mode enum would make
"off" and "manual" look like neighbours on one dial when one is a power switch and the
other is a policy. They also fail differently: OFF should be instantaneous and global,
while a mode change applies to runs started after it.

**D8 — A mode change is an audited event.** Who changed it, from what, to what, when.
It is the single highest-consequence setting in the product and the one an incident
review will ask about first.

**D9 — Enforcement stays at the SINGLE existing point.** Everything goes through
`_risk_gated`. No second gate in a service, a task, or a controller. Two enforcement
points mean two policies the moment one is edited, and the risk map's own history —
eight tool names that survived for months because nothing checked — is this codebase's
evidence for what unenforced duplication becomes.

## Consequences

- `tool_risk_refusal`'s signature changes. It is called from one place, and the
  architecture tests already assert the tool-risk map is live, so the blast radius is
  small and checkable.
- MANUAL needs `ResponseActionExecution` to accept proposals from a wider set of tools
  than it does today — that is the only genuinely new code path.
- The migration is one field on the workspace plus one on the run/observation rows;
  existing rows carry no mode and must render as UNKNOWN rather than being back-filled to
  a default, for the same reason `risk: null` was not back-filled.
- Default stays ASSIST: it is what the product does today, so nobody's behaviour changes
  on deploy.

## Open questions for Henry

0. ~~**What does selecting AUTONOMOUS actually change?**~~ **ANSWERED by the
   build:** it decides whether the scheduler starts runs on its own — exactly
   what D2's "Initiated by" column already said, and what nothing enforced until
   2026-08-22. MANUAL and ASSIST are now never scheduler-initiated.

1. **Does AUTONOMOUS ever raise the ceiling (D3)?** I recommend never. If you disagree,
   the alternative worth considering is a per-tool allowlist an admin opts into
   explicitly, rather than the mode implying it.
2. **Is MANUAL per-workspace useful, or is it really a per-USER preference** — "I want to
   review everything" — while the workspace stays on ASSIST?
3. **Should AUTONOMOUS require a passed evaluation before it can be selected?** We now
   have EVALUATE (ADR 0033). Gating the most permissive mode on measured agent quality is
   available to us and would be difficult for a competitor to copy — but it couples two
   subsystems, and a workspace with no mined cases could never turn it on.
