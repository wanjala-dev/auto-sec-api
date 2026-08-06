# ADR 0018 — The Judgment Flywheel: captured judgment, incident copilot, human-layer drills

**Status:** Proposed (design locked in principle — BUILD DEFERRED; Henry: "I want to build it, but
not today." P0 concierge validations may run before any code.)
**Date:** 2026-08-06
**Deciders:** Henry
**Related:** ADR 0012 (Remediation Memory), ADR 0011 (sample-data isolation), ADR 0005 (response
actions), ADR 0016 (delivery channels), ADR 0009 (compliance evidence), ADR 0013 (contextual risk),
`sign_off` context, PromptRegistry versioning.
**External grounding:** Taimur Ijlal, "Why Every Cybersecurity Professional Needs a Self-Improving
AI Agent" (Medium, 2026-07) — the *knowledge-capture-not-training* framing and procedural-memory
thesis; market research pass 2026-08-06 (see §Context).

---

## 1. Context

Security teams generate enormous professional judgment daily — which log to check first, when
isolation is proportionate, why an encoded command is a signal but not a conclusion — and almost
none of it survives the closed ticket. Two weeks later the same alert repeats and the reasoning is
reconstructed from scratch. **This is a knowledge-capture problem, not a training problem.**

The idea began as an "AI teaches anything" learning platform. Research narrowed it hard:

- Consumer AI tutoring is a kill zone (Chegg collapse; Coursera–Udemy merged at ~$1.8B, *down* from
  announcement; OpenAI/Google ship free tutors).
- Generic corporate "docs→courses" AI is table stakes (Sana/Workday $1.1B, Docebo, 360Learning);
  standalone "stay-current-from-connectors" products died (CodeSee dead, Swimm pivoted).
- Generic security training is commoditizing: KnowBe4 private at $4.6B; **Vanta/Drata bundle free
  awareness training**; compliance frameworks mandate annual training (the built-in buyer).
- **Nobody generates training, drills, or CTFs from the customer's OWN infrastructure** — verified
  white space. **Huntress bought Curricula ($22M) and bundled it as a platform feature** — the
  direct precedent for the decision below.

Auto-Sec uniquely holds the raw material: the asset graph, real findings + CVEs, IAM/provenance,
logs, RCAs as pipeline byproducts, and **Remediation Memory — an already-built, per-tenant,
sign-off-gated, outcome-verified judgment store retrieved at triage.** The article's
"procedural memory" organ exists here; this ADR points it at the org's humans.

Henry's constraint: people are busy — nothing may feel like assigned training. His reframe:
*"maybe we don't think about this as learning."* Correct: it is a **readiness system**.

## 2. Decision

**D0 — Not an LMS. One flywheel, three legs: capture → deliver → test.** No course catalog, no
assigned-training surface, no parallel content pipeline. The three legs below share one knowledge
substrate (Remediation Memory, extended) and close a loop: corrections become playbooks (capture),
playbooks arrive mid-incident (deliver), drills prove them and generate new corrections (test).
This ships as an **Auto-Sec pillar, not a separate company** (Huntress–Curricula precedent; the
connectors already pay for themselves — the CodeSee/Swimm failure mode does not apply).

**D1 — Captured Judgment (procedural memory).** Extend Remediation Memory capture from *fixes* to
*reasoning*: every operator correction is a capture candidate — a rejected proposal, an edited
patch, an escalation override, a "don't isolate for this" decision, a triage re-route. Captures
become **versioned playbooks** (the PromptRegistry versioning discipline), pass the existing
**sign-off accept-gate** ("skills reviewed like code" — the article's condition, already our D1
in ADR 0012), and are retrieved by the triage/specialist agents exactly as remediation entries are
today. Ten corrections in, the tenth triage starts with nine lessons — org-owned, not trapped in
one analyst's head.

**D2 — Incident Copilot (delivery leg).** When an alert/finding fires, the **humans** in the Slack
thread (and the finding callout) get what the agent already retrieves: *"seen before — 2026-06-12,
same class; the accepted fix; why we didn't isolate."* Implementation = the existing Remediation
Memory retrieval + finding history, formatted for humans, delivered via the ADR-0016 channel. Zero
training time; knowledge appears only at the moment of need. Redaction standards apply (summaries
+ deep links; never raw tool-IO; Option-A boundaries).

**D3 — Human-layer drills ("Chaos Monkey for the human layer", test leg).** On a schedule (weekly
ritual), inject a **safe, staged incident** derived from the workspace's real finding classes into
an isolated surface — the ADR-0011 sample-data isolation and/or sandboxed scan-substrate replicas;
**never live resources** — and measure the humans: detection, response, escalation (human
MTTD/MTTR). Delivered as the Friday Slack challenge (CTF-style variants included), leaderboard on
the HUD social surfaces. This simultaneously *tests the captured playbooks against a genuinely
different case* (the article's skipped step) and replaces the annual consultant tabletop with
automated micro-GameDays.

**D4 — Metrics are the product.** Participation, human MTTD/MTTR trend, and **repeat-finding rate
per lesson class** (the number that proves the flywheel works). These roll into a readiness record
that doubles as **compliance training evidence** (ADR 0009: first-party, provable — the training
analog of "Vanta collects, we generate"). A formal external attestation artifact (insurance /
questionnaires) is a later layer, deliberately out of P1.

**D5 — Safety & governance.** Nothing self-improves in production: captures activate only through
the sign-off gate; drills inject only into isolated/sample surfaces (ADR-0011 event-bypass
verified); drill scenarios are identification/defense-oriented and must not constitute attack
instructions against live infra; deliveries follow the established redaction taxonomy. The
OpenAI–HuggingFace escape incident is the cautionary reference: goal-driven agents treat controls
as obstacles — our response actions stay dry-run + human-gated, and drill sandboxes are hard
boundaries, not conventions.

**D6 — Asset reuse map.** `codenry/courses` (Subject→Course→Module→polymorphic Content + API) is
the content spine **only if/when** the onboarding-curriculum leg ships (P4) — the one moment humans
*want* a course ("our stack + our incident history" for new hires). It is not imported before then.

## 3. Consequences

**Positive:** compounds three existing moats (Remediation Memory, connectors, compliance evidence);
whole-team weekly touch (seat expansion; today only the operator sees Auto-Sec); measurable — the
repeat-finding metric either proves it or kills it honestly; each leg is independently shippable
and cheap because the substrate exists.
**Costs/risks:** capture-quality depends on operator engagement (mitigation: corrections are
captured from actions they already take, not extra work); drill fatigue if cadence/difficulty are
wrong (mitigation: weekly, 10-minute, opt-in ritual with social proof, not mandate); sandbox
discipline is safety-critical (D5); the copilot must not become alert noise (it posts into the
existing alert thread, never new channels).

## 4. Phases (build deferred — P0 may run pre-code)

- **P0 — Concierge validation (no code):** (a) hand-generate ONE Friday drill/CTF from the demo
  workspace's real findings → Slack → measure engagement (Henry, later Tom's team); (b) manually
  surface a Remediation-Memory "seen before" note in one real alert thread. Signal before build,
  per the validate-before-build rule.
- **P1 — Incident Copilot:** human-facing retrieval formatter + Slack-thread hook + finding-callout
  "history" section. (Cheapest leg; retrieval exists.)
- **P2 — Captured Judgment:** correction-capture hooks (reject/edit/override events) → playbook
  entries → sign-off gate → agent retrieval; playbook versioning.
- **P3 — Drills:** scenario generator from finding classes → sandbox injection → scoring →
  leaderboard → weekly beat.
- **P4 — Onboarding curriculum + attestation artifact** (courses-spine import; ADR-0009 evidence
  export; insurance-facing readiness report).

## 5. Open questions (Henry)

1. Drill cadence + audience: whole workspace weekly, or per-team rotation?
2. Copilot placement: Slack thread only, or also auto-comment on the board card?
3. Does a correction capture require explicit operator confirmation ("save this as a playbook?")
   or capture-by-default with sign-off review later? (Rec: capture-by-default, gate on activation.)
4. Naming: "drills" vs "CTF" vs "GameDay" for the customer-facing ritual.
5. When P4 arrives: import `codenry/courses` code, or rebuild the spine inside a bounded context
   per house architecture? (Rec: rebuild to Explicit Architecture; reuse the schema design only.)
