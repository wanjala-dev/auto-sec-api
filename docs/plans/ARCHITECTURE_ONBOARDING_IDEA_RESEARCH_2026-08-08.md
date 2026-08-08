# Architecture Self-Serve for AI-Native Builders — Idea Research (2026-08-08)

*Research only. No build authorized by this document. Five research sweeps, three candidate shapes, four adversarial judges, plus in-repo verification performed 2026-08-08.*

---

## 1. Verdict up front

**The observation is correct and the product is not.** Henry has identified a real and well-measured failure — AI-native builders ship systems whose architecture nobody chose, and they cannot ask for help because they cannot name what is missing. But every part of the idea that is *shaped like a place people go to ask* is already free, already commoditized, and already losing: six incumbents (AWS, Azure, Google, Thoughtworks, CNCF, Humanitec) give architecture guidance away permanently as a loss-leader; StackAdvisor.ai and CloudKompas ship the exact "beginner asks, gets architecture + CI/CD + hosting" flow at $0 today; roadmap.sh proves this job converts 2.8M registered users into approximately zero revenue; and the beginner in question is already inside a chat window that answers better than any product Henry could ship. The only half with money in it is the half Henry already owns and already ships — **enforcement that runs unasked and produces a consequence** — and the market prices those two halves roughly 30× apart (Boot.dev ~$1.3M ARR teaching individuals; CodeRabbit ~$40M ARR gating a team's pull requests). All four judges independently ranked the three candidate shapes in the same order, which is unusual and worth weighting. **This month Henry should build nothing from this idea.** Three actions, in order: (a) finish SAST P2 — the triage routing that is already in flight as task #112 — and run the existing P1 pack against Tom's real repository, recording precision, because that single measurement answers the only surviving version of this idea for free; (b) write the thesis down once, one page in `docs/product/STATE_AND_VISION.md`, so this idea stops costing five research agents every six weeks; (c) leave everything else in the drawer next to ADR 0018. The winning shape is a two-day rule pack, it is gated behind Tom's loops being green, and — stated plainly — **it is a feature, not a company, and it is not even the idea Henry dictated.**

---

## 2. The idea, restated precisely

### The steelman

Henry's dictated idea, stated at its strongest:

> Software architecture knowledge is distributed by apprenticeship. You learn Clean vs. Hexagonal vs. MVC, when a monorepo pays for itself, why CI matters before it hurts, and where to host a small app — by working near people who already know. AI has severed that transmission line. It lets someone with no apprenticeship produce a running system, which means the *output* now arrives without the *judgment* that used to be prerequisite to producing it. The result is a generation of builders whose systems work and whose systems are unmaintainable, and who have no mechanism to discover this. A self-serve surface that sets someone up end-to-end — architecture, CI/CD, infrastructure, hosting — delivered as basic drills rather than reference documentation, would restore the transmission line.

### The sharpest part, and it is genuinely sharp

**"They don't know what they don't know, so they can't even ask AI the right question."**

This is the load-bearing insight and it is not a platitude — it is a structural claim about why the obvious rebuttal ("just ask Claude") fails. Every existing tool in this space, without exception, is **query-shaped**: it answers a question you already knew to form. Spring Initializr makes you pick starters. JHipster asks twenty questions about technology you must already understand. `create-t3-app` explains why *its* choices are good with, on inspection, zero "when NOT to use this" guidance. Cookiecutter is a template renderer with no opinions by design. An LLM chat is the purest case — it is *entirely* query-shaped, and its answer quality is bounded by the question. A person who does not know that authorization and authentication are different concerns cannot ask which one they are missing.

The research validates this precisely. Anthropic's January 2026 RCT (52 junior engineers) is the strongest single result in the entire corpus: AI-assisted learners scored **50% vs 67%** on comprehension, with **debugging showing the steepest decline** — *except* for participants who used AI to ask conceptual questions, who retained far more. The delivery mechanism, not the content, determined whether AI taught or de-skilled. METR's July 2025 RCT adds the calibration half: 16 experienced developers were **19% slower** with AI while believing they were **20–24% faster**. If experts misjudge their own throughput by ~40 points on repositories they have known for five years, novices have no calibration signal whatsoever. Henry's insight is correct and it is measured.

### Where the framing is imprecise

Four places, each of which changes the answer:

1. **"A place people can self-serve and ask" contradicts the insight that precedes it.** If the user cannot form the query, a destination that requires them to arrive and ask is unreachable by construction. The premise and the proposed mechanism are in direct tension. Every judge caught this independently. The mechanism the *evidence* supports is the opposite: guidance injected unasked into the moment of work.

2. **"Set up your development end to end" conflates four markets with four different economics.** Architecture guidance is free (six incumbents). Scaffolding is free and commoditized (Cookiecutter 10.18M PyPI downloads/month, create-next-app 1.82M/month). CI/CD setup is a template. Hosting advice monetizes at a flat $25 CPA from DigitalOcean, or roughly $6–25 lifetime per referred beginner — a content site, not a company. Bundling four zero-margin goods does not produce a positive-margin good.

3. **"Drills, very basic, for people new to this" is the right instinct pointed at the wrong user.** Drills are the one delivery form the Anthropic result supports. But it collides with the timing finding in §4: the cohort does not feel this pain at t=0, so a drill they must choose to start is a drill nobody starts.

4. **The dictated idea and the surviving shape are not the same idea.** This must be said clearly, because it is the mechanism by which a two-day task becomes a two-week one. Henry dictated a self-serve advisor covering architecture, CI/CD, infrastructure, and hosting. The only shape that survives adversarial review deletes all four and ships five security rules inside a product he already sells. Calling that "the idea, scoped down" is a category error. It is a different idea that happens to share a word.

---

## 3. What already exists

### 3a. Scaffolders and generators — solved, free, and the opinionated ones are dying

| Tool | Stars | Downloads | Status |
|---|---|---|---|
| Cookiecutter | 25,049 | 10.18M/mo (PyPI) | active |
| cookiecutter-django | 13,586 | — | pushed 2026-08-08 |
| Copier | 3,518 | 2.49M/mo | active |
| **create-t3-app** | 29,073 | **2,430/mo** | **last push 2025-12-13** |
| create-better-t-stack | 5,621 | 9,415/mo | active |
| JHipster | 22,437 | 57,189/wk | v9.1.0, 2026-05-27 |
| Nx | 29,206 | 10.06M/wk | v23, June 2026 |
| Turborepo | 30,872 | 20.73M/wk | active |
| create-next-app | — | 1.82M/mo | active |
| Yeoman (meta-generator) | 10,109 | — | **last push 2022-10-18** |

Two trajectories tell the whole story.

**Yeoman** — the framework-agnostic meta-generator, structurally the same position a "set up your whole practice" tool would occupy — has not been pushed since October 2022, though `yeoman-generator` still draws 6.08M npm downloads/month as a transitive dependency inside other people's CLIs. Microsoft explicitly retired it for the SharePoint Framework in favour of first-party tooling from SPFx v1.22, citing an "effectively unmaintained" dependency. **Generic meta-generators lose to per-framework first-party CLIs.**

**create-t3-app** is the closest thing the ecosystem has ever produced to "a scaffolder that exercises architectural judgment" — explicit published axioms, a stated refusal to include libraries that are "simple npm installs," a policy against state libraries. Its downloads went 19,193/mo (Jan 2024) → 6,812 (Jun 2025) → **2,430 (Jul 2026)**, roughly **−87%**, with the repo dormant since December 2025. Its de-facto successor, `create-better-t-stack`, won by going the *opposite* direction — *"roll your own stack: you pick only the parts you need"* — less judgment, more menu, plus an **MCP server so an AI agent can drive the scaffolder**. The market's revealed preference in 2025–26 is that judgment migrates to the agent and the scaffolder degrades into a parameterized emitter.

**Nx 23 (June 2026)** completes the picture: it now ships *prompt-only migrations* (an AI-instruction file, when a change cannot be performed deterministically) and *hybrid migrations* (generator does the deterministic part, an agent finishes). Its tagline is now literally "amplifies both developers and AI agents." The ecosystem has converged on "machine-readable rules + agent" — which validates the **format** Henry already uses while removing any wedge in generation.

Direct competitors to the advisor half already exist and are free: **StackAdvisor.ai** (explicitly targets "non-technical founders and teams who lack senior architects" → questioning → architecture diagrams, multi-cloud stack + cost, GDPR/HIPAA/PCI detection, roadmap; free starter tier) and **CloudKompas Architecture Advisor** (question flow → blueprint in 60s, free, no signup). **Architecto** (Product Hunt, ~Apr 2026) does the beginner-facing version with STRIDE analysis, compliance checks and 240+ patterns — and sits at 93 upvotes and 88 followers, i.e. hobby scale.

**What scaffolders structurally never do:** they don't *select* (you must already know which generator to run — the exact knowledge the beginner lacks); they fire once at t=0 (only Copier `update`, Nx `migrate` and Angular schematics touch day 2); they never *subtract* (no mainstream generator says "you don't need Kubernetes"); they don't teach (output is a directory, not an explanation); and none spans architecture → CI/CD → infra → hosting as one reasoned chain.

### 3b. Golden paths and internal developer platforms — the pattern does not degrade to N=1

"Golden Path" was coined publicly by Spotify Engineering on **2020-08-17**, and the load-bearing details are usually dropped: it is **authored by a platform org**, **consumed by new engineers in their first two weeks**, and exists to solve **"fragmentation in our software ecosystem"** and **"rumour-driven development."** It presupposes autonomous teams plus a centralized platform organization with the authority and staffing to maintain it.

**This is the crux.** A golden path is a *variance-reduction artifact for N teams*. A solo builder has no variance to reduce and nobody to align. What a beginner needs is not a golden path — it is a correct default. Different products, different economics.

Who authors, who consumes, who pays:

| Artifact | Author | Price | Who actually pays |
|---|---|---|---|
| AWS Well-Architected Framework + Tool + Lenses | AWS (since 2015) | **Free**, incl. API and custom lenses | AWS — consumption + partner services |
| Azure CAF / WAF / Architecture Center | Microsoft | Free | Microsoft — Azure consumption |
| Google Cloud Architecture Framework | Google | Free *(pattern-inferred; page 301'd on fetch)* | Google |
| Thoughtworks Technology Radar Vol 34 (2026-04-15) | Thoughtworks TAB | Free | Thoughtworks — consulting lead-gen |
| CNCF Platform Engineering Maturity Model (2023-11-20) | CNCF TAG volunteers | Free | CNCF members |
| Humanitec reference architectures | Humanitec + McKinsey | Free / OSS | Humanitec — sells the orchestrator |

**Nobody on earth charges for architecture guidance.** Six players give it away and can afford to forever. That is the single most important number in this document: the price of the artifact Henry's idea would sell is **$0**, and it is set exogenously.

What people *do* pay for is the portal seat, and it has a hard floor: **Port** — free ≤15 seats, then $30/seat/mo with a **50-seat minimum**; **Roadie** — $24/dev/mo for 50–150 developers, with both tiers now marked **"Existing subscribers only"** (they have stopped selling down-market); **self-hosted Backstage** — $200k–$1.2M year one, 85–92% of it headcount. **The commercial floor of this category is ~50 developers**, and below that it is actively retreating.

It is also failing where funded. Gartner: 80% of *large* engineering organizations will have platform teams by 2026, but **fewer than 30% will achieve measurable productivity gains**. Down-market attempts did not compound — Shipa acquired by Mirantis (Jan 2023) and down to ~1 employee; Coherence raised $9.2M and sits at 4 employees; Qovery ($13M Series A, Sept 2025) is the lone exception.

**The genuinely new signal points at Henry.** Three independent 2025–26 sources converge on golden paths being rewritten for **AI agents as the consumer**. **Port raised $100M Series C at $800M (2025-12-11)**, 300% YoY revenue growth, on the explicit thesis that *"AI coding tools address roughly 10% of developer work; we target the other 90%"* with *"agents taking the operational load, humans staying in control."* **Microsoft** now describes reference architectures as machine-consumable blueprints where the agent selects the pattern and **opens a PR with diagram-linked justification**, with guardrails moved *into the agent's instructions*, and predicts platform teams will define **"agent golden paths"** treating agents as a persona with RBAC and quotas. **Thoughtworks Radar Vol 34** warns of **"cognitive debt as AI generates increasingly larger amounts of code"** and names harnesses to keep *"coding agents on a leash."*

Henry's `.claude/rules/*.md` plus `tests/architecture/` **is an agent golden path enforced by a fitness function, built before either vendor named the category.** That is a real observation. It is also, as §3c shows, not a moat.

### 3c. AI builders and the governance layer — the format war is over

**The builders impose architecture and never explain it.** Bolt.new runs in WebContainers; Lovable and Base44 default to React + Supabase; v0 to Next.js/Vercel; Replit to its own agent and hosting. I searched specifically for pedagogical framing and found none — the uniform marketing frame is "describe the app, get the app." The decision Henry wants to teach is made silently, at prompt time, by the vendor. This is a large market: Lovable $330M Series B at $6.6B (Dec 2025), reportedly ~$500M ARR by mid-2026; Wix acquired Base44 for $80M cash (June 2025); Replit ~35–40M users.

**AGENTS.md won, decisively, and is now neutral infrastructure.** 60,000+ open-source repos; stewardship moved to the **Agentic AI Foundation under the Linux Foundation**; read natively by Codex, Cursor, Copilot Coding Agent, Jules, Gemini CLI, Devin, Windsurf, Junie, Aider, Zed, Warp and 20+ more. **Nobody will ever pay for a rules-file format.** The tooling that grew around it (rulesync, Ruler, a Sync AI Agent Rules GitHub Action, a VS Code extension) solves **sync**, not **quality** — one source of truth fanned out to many files. I found no product that tells you what your rules should *say*, or grades them. That whitespace is real, and it is empty because it is unmonetizable, not because it is unnoticed.

**The layers with money are already taken, and they consume rules files for free.** **CodeRabbit**: $60M Series B at ~$550M (Sept 2025), ~**$40M ARR by April 2026, +700% YoY**, 8,000+ companies, positioned explicitly on *"vibe coding triggers a need for new code quality standards."* **Greptile**: $25M Series A led by Benchmark, ~$180M valuation, 2,000+ customers — and its own announcement states it **"auto-detects all the common file patterns"** including `CLAUDE.md` and `.cursor/rules` and *"automatically pulls them into context."* **Henry's rules file is already a free input to a funded competitor.**

**And the enforcement layer is being absorbed by the incumbent right now.** **SonarQube Server 2026.4 (July 2026)** shipped (a) **architecture management** — *"architects can now visualize current architecture, define which components are allowed to depend on each other, and let SonarQube automatically flag violations"* — and (b) a **"Sonar way for Agentic AI" quality gate** with supply-chain conditions for *"agents that autonomously pull in typosquatted, hallucinated, or vulnerable packages."* Meanwhile the open-source enforcement layer (ArchUnit, ArchUnitTS, dependency-cruiser, import-linter, deptrac, eslint-plugin-boundaries, NetArchTest, depguard) is mature, free, and **largely unadopted** — a fact that matters enormously in §5.

Adjacent: **GitHub Spec Kit** (MIT, constitution → spec → plan → tasks → implement) and **AWS Kiro** (spec-first IDE) give the constitution/spec layer away at $0. **Catio** — "the first AI-powered copilot for tech architecture," a multi-agent system maintaining a digital twin of your stack, $9.65M raised — is the closest funded exact match to Henry's idea, and it deliberately sells to *"larger startups and Fortune 100s."*

### 3d. Learning platforms — proven willingness-to-pay is for interviews, not for building

**roadmap.sh** is the incumbent for the exact job Henry describes: **364K GitHub stars** (6th–7th most-starred repo on GitHub), 2.8M registered users, 50K Discord, 150K newsletter — and it runs on ~2.5 staff, is essentially unmonetized, and **has already shipped an AI Tutor**. The map layer is a commodity with a well-funded free incumbent.

Ceilings elsewhere: **ByteByteGo** $3.5M revenue (2024), 26 people; **Boot.dev** ~$1.3M ARR, 16 staff; **Scrimba** ~$1.9M across 500K customers, i.e. **~$4/customer/year**; Educative $149–249/yr. Critically, ByteByteGo, Educative and DesignGurus monetize **system-design job interviews** — the proven purchase is a *hiring* purchase, not a *building* purchase.

The sector is in a wipeout: **Chegg** revenue −30% (Q1 2025), 22% layoffs (May 2025), a further **45% cut (Oct 2025)**, stock −99%; **Coursera acquired Udemy (closed 2026-05-11)** with combined guidance of a **2–4% revenue decline**; Skillsoft laid off the entire Codecademy curriculum team; **Turing School** filed bankruptcy intent (Apr 2025); BloomTech, Kenzie, Rithm, Code Fellows, Momentum, Codeup, Epicodus all shut or shrank to waitlists. The peer channel is gone too: **Stack Overflow posted 3,862 questions in December 2025, −78% YoY, its lowest since 2009.**

### So what is actually missing?

Stripping it down, exactly two things are absent from the prior art:

1. **Diagnosis without a question** — something that reads what you built and volunteers what you did not know to ask, including an explicit *subtraction* list ("you do not need a monorepo / Kubernetes / hexagonal architecture at your size"). No mainstream tool subtracts.
2. **Adoption-cost-free enforcement** — a fitness function you can turn on today without hand-authoring a ruleset and without facing 4,000 day-one violations.

Both gaps are real. Neither is defensible. The first is a prompt with a repo reader attached, and the beginner is already in the chat window. The second is a GitHub App and one Postgres table, and Sonar is shipping the enterprise version of it now. **The gap is real; the moat is not.**

---

## 4. Is the problem real?

### Evidence for — unusually strong

**Scale.** 84% of 48,892 Stack Overflow respondents use or plan to use AI tools (2025); DORA 2025 (~5,000 respondents) puts it at 90%, +14% YoY; JetBrains 85% of 24,534 developers. Y Combinator W25: ~25% of the batch had codebases ≥95% AI-generated. Platform scale is real — Replit ~40M users / ~$253M ARR (Oct 2025), Lovable $400M ARR (Mar 2026), Bolt 5M users in six months, v0 ~6M developers.

**Architecture specifically degrades — this is the finding that matters, because the idea is architecture-shaped, not lint-shaped.**

- **GitClear "Maintainability Gap" (Jan 2026, 623M changes, 2023–2026):** refactoring collapsed from **21% of changed lines (2022) to 3.8%**; block duplication **+81%**; cross-file function calls **−35%**; legacy-code maintenance **−74%**; error-masking constructs **+47%**. Developers are now **~5× more likely to copy/paste than refactor**, a reversal of 2022's 2:1 preference *for* refactoring.
- **Apiiro, Fortune 50 enterprises (via CSA, 2026-04-04):** AI-assisted developers commit at 3–4× the rate; monthly security findings rose from ~1,000 to **>10,000**; privilege-escalation paths **+322%**; **architectural design flaws +153%.** This is the closest thing to direct proof that the *design layer* fails, not merely the syntax layer.
- **DORA 2025:** AI now correlates positively with throughput (reversing 2024) but **still increases delivery instability**. DORA's own framing — AI is an *amplifier* of existing organizational strengths and weaknesses, and "speed without stability is accelerated chaos" — is Henry's premise restated by Google.

**Comprehension degrades, invisibly.** The Anthropic RCT (50% vs 67%, debugging worst) and METR (19% slower while feeling 20–24% faster) are covered in §2. Add **Clutch (June 2025, 800 professionals): 59% use AI-generated code they do not fully understand**; Stack Overflow 2025: 66% cite "almost right, but not quite" as their top frustration, 45.2% say debugging AI code takes longer, and **20% report decreased confidence in their own problem-solving.** Addy Osmani names the mechanism qualitatively: beginners produce "house of cards code," enter a "fix a bug → break two things" loop, and lack "the mental models to understand what's actually going wrong."

**Security consequences are severe.** Veracode (2025, 100+ LLMs, 80+ tasks): **45%** of AI-generated code introduces an OWASP Top 10 flaw (Java 72%, XSS 86%, log injection 88%) — and newer/larger models did **not** improve, with CSA confirming the pass rate unchanged (~55%) from 2025 to 2026. Lovable's **CVE-2025-48757** (mass Supabase RLS misconfiguration) hit 170+ apps and 303 endpoints, leaking emails, API keys, payment status and home addresses.

### Evidence against, and the honest gaps

**Numbers that must not be used.** The widely-repeated *"63% (or 84%) of AI app-builder users have no coding background"* traces only to unsourced marketing blogs which name no primary source. The vibe-coding security statistics that circulate most (70% of Lovable apps shipped with RLS disabled; 96% of scanned apps had an issue; 41% exposed secrets) all trace to **commercial scanner marketing sites**. Directionally consistent, methodologically opaque. **Do not cite these to an investor.** The better-sourced security scans — Symbiotic (2026-06-02, 1,072 Supabase-backed apps, 98% with ≥1 vulnerability) and Escape.tech (~1,400 apps, 2,038 critical vulns, 400+ leaked secrets) — are real but vendor-run.

**No credible survey segments AI-builder outcomes by prior engineering skill.** That is the biggest measurement gap under Henry's thesis: the cohort he describes is not sized anywhere.

### The crux: timing of felt pain

**Every discovery mechanism in the entire corpus is external and late.** The Symbiotic, Escape and Lovable findings were surfaced by third-party scanners and researchers — **not by the builders**. I checked the Symbiotic methodology explicitly: it does not establish whether builders knew, whether the apps were in production, or who built them. Georgia Tech's Vibe Security Radar shows CVEs attributed to AI tools going 6 (Jan 2026) → 15 (Feb) → 35 (Mar) — a *lagging* discovery curve on code written months earlier. GitClear's own framing is that maintainability costs "arrive deferred — the bill arrives when you can least afford it," and that two-week churn is a *lagging* signal. DORA's instability metric measures unplanned deployments caused by critical issues, i.e. pain after shipping. METR and Anthropic both show the deficit is invisible *at the moment of work*.

**Verdict: this cohort does not seek architecture guidance up front.** The felt pain is post-hoc — a breach, a rewrite, a first engineering hire, a stalled fundraise, or a contractor asking where staging is. I could not find a single credible dataset showing pre-build guidance-seeking by AI-first builders, and that absence is itself the finding.

**This is fatal to the dictated framing and it is worth being precise about why.** A self-serve pre-build advisor sells insurance to people who do not yet know they are exposed. That is the hardest thing to sell in software, and it is being sold against six free incumbents to a segment with documented ~$0 willingness-to-pay.

### Named evidence gaps (all cheap to close, none worth closing yet)

1. No credible sizing of the non-engineer AI-builder cohort.
2. **No study measures time-to-discovery of an architectural defect by its own author** — the single most decision-relevant missing number.
3. No data on post-breakage tool-seeking behaviour: at the moment it breaks, does the builder reach for a diagnostic, or paste the error back into the AI that built it?
4. No independent, non-vendor security study of vibe-coded applications.
5. No willingness-to-pay data for pre-build guidance at any price point.

---

## 5. The three shapes, compared

| | **A — Groundwork** (teach) | **B — Ratchet** (govern) | **C — Rule pack** (feature) |
|---|---|---|---|
| **Pitch** | Free CLI reads the app you already built with AI, names the five architectural decisions already made for you, which two break first at *your* scale, what you explicitly don't need — then opens three fix PRs and keeps checking | GitHub App derives the architecture you already have, compiles it to both an agent rules file and a CI check, and blocks any PR — human or agent — that adds a new violation; allowed count only ever falls | Auto-Sec's code scanner gains a second rule pack catching *structural* hazards in AI codegen (missing authz, missing tenant filter, unauthenticated route), filed as findings on the existing board with existing triage and existing draft-PR |
| **Buyer** | Nobody. Named user is a beginner (WTP ≈ $0); pivots mid-pitch to the inheriting contractor / fractional CTO | VP Eng or first platform hire at a 15–80 dev company where 60–80% of new code is agent-written | Tom. Already signed, already has a security budget line |
| **Wedge** | Diagnosis without a question, plus subtraction — every incumbent answers a question you already knew to ask | Adoption cost, not better rules: derived from your code, ratcheted from your current state, live in one PR | The **join** — "this handler has no authz check" **and** "it is internet-reachable via this IAM path." Requires the cloud graph Auto-Sec already holds |
| **Price** | Free forever; $19/mo aspirational; $99/seat/mo agency tier (untested) | $12/dev/mo, annual, 10-seat minimum ($1,440/yr floor) | **No new price.** Rides existing code-security entitlement. Honest incremental ARPU: $0 |
| **Riskiest assumption** | At the moment of breakage, does the builder reach for a tool that says they built it wrong — or re-prompt the AI that built it? **Unevidenced, not merely risky** | Will a team tolerate a merge-blocking check on an architecture rule with no regulator behind it? **Legitimacy risk** | Can absence-shaped rules be written at acceptable precision? A noisy pack degrades the loop Tom actually needs |

### Judge scores

| Shape | Money | Tech (feasibility × defensibility) | Strategy | Kill | **Consensus** |
|---|---|---|---|---|---|
| **C — Rule pack** | **7** | **7** (7 × 7) | **7** | **7** | **7** |
| **B — Ratchet** | 5 | 5 (5 × 4) | 4 | 4 | ~4.5 |
| **A — Groundwork** | 2 | 3 (8 × 1) | 2 | 2 | ~2 |

**Ranking: C > B > A, unanimous across four independently-run adversarial lenses.** That unanimity is worth weighting — but see §7, because the money judge spotted the tell inside it.

### Reasoning, and where the judges genuinely disagree

**On C, the judges agree on the score and disagree on the reason it is small.** The money judge scores it 7 while stating flatly *"I would not fund it"* — and names the tell: **"the highest-scoring shape is the one that is not fundable. That is the whole answer."** I find this the single most clarifying sentence in the corpus. C wins because it is cheap and rides existing distribution, not because it is valuable.

**On B, the judges disagree substantively about the cause of death, and this matters.**
- *Money* and *tech* converge on **legitimacy**: architecture enforcement has no regulator, no CVE, no auditor behind it, so the first blocked Friday release produces a `skip-arch-check` label and the gate dies in six weeks.
- *Kill* adds **distribution** as an independent killer: $12/dev at a 10-seat floor requires bottom-up developer adoption at scale, and Henry has no dev-tool audience, no OSS following, no npm surface. Selling it means becoming a dev-tools founder, which means abandoning Auto-Sec.
- *Tech* adds a third, purely engineering killer the others missed: the **per-language import-graph treadmill**. This is why import-linter, deptrac, dependency-cruiser and ArchUnit are four separate projects rather than one — the derivation work does not generalize, and it is the only hard part.

**I find all three credible and they compound rather than compete.** But I weight *distribution* highest, because it is the only one that is unfixable by product decisions. Legitimacy can be fixed (put a security obligation behind the gate — at which point you have described Auto-Sec). The treadmill can be scoped (TypeScript only). Not having a developer audience cannot be fixed inside this decision.

**One point of real cross-judge agreement worth acting on:** *tech* and *strategy* independently identify **the ratchet mechanic** — baseline existing violations, allow the count only to fall — as the single genuinely novel idea in the entire corpus, and independently recommend stealing it rather than building around it. The tech judge is sharpest on why it matters: it is *"the one artifact in these three shapes no chat window can hold."* Free fitness-function tooling is mature and unadopted precisely because day one is thousands of red violations. That mechanic transfers directly into Auto-Sec as "new findings only, baseline frozen" on the code-security board. It is a note in the drawer, not a project — but it is the most valuable thing this research produced that Henry does not already own.

**On A, the judges are unanimous and unusually blunt.** The kill judge's framing is the correct one and I adopt it: the premise is **self-refuting as a distribution strategy**. "They don't know what they don't know" is simultaneously the pitch and the reason nobody can find the product. Worse, it is an `npx` CLI aimed at people whose defining characteristic is that they never learned to reach for a CLI — they are inside Lovable, Bolt and a chat window, which is where the pain fires and where the evidenced behaviour is to re-prompt. The tech judge scores its feasibility highest of all three (8) and its defensibility lowest of all three (1), which is the exact signature of a thin wrapper: trivially buildable, trivially replaced. Cursor and Claude Code ship this as a slash command.

---

## 6. The kill shots

Every serious objection at full strength, with a ruling on each.

**K1. The advisory half is free, permanently, from six players who can afford it to be.** AWS, Azure, Google, Thoughtworks, CNCF and Humanitec all give architecture guidance away as a loss-leader for consumption, consulting or seats. StackAdvisor.ai and CloudKompas already ship Henry's exact flow at $0. **SURVIVES — decisive.** There is no version of selling architecture advice that clears this.

**K2. The beginner does not pay, and this is documented rather than assumed.** The Val Town retrospective (2025-11-11) is the cleanest evidence available, from a company in precisely this niche: hobbyists dominated adoption, "teenagers or hobbyists" would not open their wallets, vibe-coding users "use the tools *a lot*, and they really don't want to pay for them," margins were negative, and the company **pivoted monetization away from individual users entirely**. Scrimba ~$4/customer/year. roadmap.sh 2.8M users, ~$0, already shipping an AI Tutor. **SURVIVES — decisive.**

**K3. The pain is felt late and discovered externally, so a pre-build advisor is unsellable.** Every discovery mechanism in the corpus is a third-party scanner. No dataset shows pre-build guidance-seeking. **SURVIVES.** This kills the *dictated* framing specifically, independent of K1 and K2.

**K4. "You can't prompt for what you don't know" is true of advice but not of enforcement — and enforcement is the half that already exists everywhere.** The insight is real but it argues *against* a destination and *for* unasked injection. **SURVIVES as a reframe, not a kill** — it is the reason C is the only shape left standing.

**K5. Generation is a zero-price commodity and the opinionated generator is the one dying.** Cookiecutter 10.18M/mo, create-next-app 1.82M/mo, create-t3-app −87%, Yeoman dormant since 2022, better-t-stack winning by offering *less* opinion plus an MCP server. **SURVIVES** — removes any scaffolding component from consideration.

**K6. Sonar is shipping the enforcement product now, inside an existing enterprise sale.** SonarQube Server 2026.4 (July 2026): architecture management plus an agentic-AI quality gate. **SURVIVES against Shape B.** Do not race an incumbent to a commodity it is bundling.

**K7. The rules file is already a free input to two funded competitors.** Greptile explicitly auto-detects `CLAUDE.md` and `.cursor/rules` and pulls them into context; CodeRabbit sits at ~$40M ARR. AGENTS.md is now Linux Foundation infrastructure across 60,000+ repos. **SURVIVES** — no moat exists in the rules artifact itself.

**K8. Architecture enforcement has no regulator, so the gate lacks legitimacy and gets skipped.** Security and license gates survive because failure is externally attributable. "You imported infrastructure into a use case" is taste with a red X. **SURVIVES against Shape B** — and it is the objection Shape B's own author raised, which is the strongest form of it.

**K9. Henry has no distribution for a developer tool.** No OSS following, no npm surface, no dev audience. Roadie stopped selling under 50 devs; Port carries a 50-seat minimum. **SURVIVES against Shape B**, and it is the one killer unfixable by product decisions.

**K10. Shape C is not the idea Henry dictated.** He asked for a self-serve end-to-end advisor covering architecture, CI/CD, infra and hosting. C ships five security rules inside an existing product. **SURVIVES as an honesty constraint** — the danger is scope creep back toward the dictated version, which is how a two-day task becomes two weeks.

**K11. Absence-shaped rules are what pattern engines are worst at.** *(New, verified in-repo — see §8.)* **SURVIVES, and it reshapes C rather than killing it.**

**K12. Shape C's downstream seam is half-built as of today.** *(New, verified in-repo.)* **SURVIVES — it sets the timing.**

**K13. Everything here competes with hardening Tom's loops.** Standing priority is production-perfect AWS connect, GitHub connect, and draft PR for a real operator. **SURVIVES** — the binding constraint on all three shapes.

### Objections I do NOT find persuasive

**"It's just ask Claude."** Half true and worth stating plainly for the advisor — an LLM in the IDE beats anything Henry could ship there, free. But it is wrong about enforcement, for three reasons no chat session can satisfy: it **runs unasked** on someone else's PR (including an agent's at 2am), it **holds durable state** (the ratchet baseline is a record of what was allowed, on what date, at what count), and it **carries an owner and an audit trail**. Prompted advice and unprompted enforcement are different products with a documented ~30× price gap.

**"The category is dead, so don't bother."** Too broad. The *knowledge-good* category is dead — CodeSee (sunset 2024-02-22), StackShare (acquired twice, enterprise product discontinued), Swimm (pivoted to COBOL/mainframe modernization), Stack Overflow (−78% YoY). But the common cause of death is specific and instructive: **they all sold a one-time-consumption knowledge good.** A map, a doc, a stack list, a boilerplate, an answer. Value lands once, at setup, and never recurs — no retention, no expansion, no budget owner. Every survivor migrated to a recurring enforcement surface or was absorbed. That diagnosis is what makes C viable and A hopeless; it does not condemn the space wholesale.

---

## 7. Strategic read

### The pattern is real, and it is one thesis

Three ideas in roughly six weeks — institutional-memory training, ADR 0018's judgment flywheel, and this — are the same idea: **capture senior judgment and deliver it to people who lack it.** It is coherent, it is Henry's genuine intellectual pull, and it is not a distraction magnet in the sense of being unfocused. It is worse than that: it is a *consistent* pull that researches to the same verdict every time.

All three independently reached **feature, not company**. ADR 0018's research even found the precedent — Huntress acquired Curricula for $22M as a platform *feature*. **Three independent confirmations of the same conclusion is not triangulation. It is a rut, and the consistency is the tell.**

The thesis needs one correction to be useful, and the correction is the whole strategic finding: **it is not "teach judgment." It is "enforce judgment, unasked, at the moment of work, with a consequence."** Teaching is the half that keeps dying (CodeSee, StackShare, Stack Overflow, Chegg, every bootcamp, roadmap.sh at 2.8M users and ~$0). Enforcement is the half worth $40M ARR in three years. Henry has already built the canonical instance of the corrected thesis and ships it today: **finding → AI triage → guardrailed draft PR → Remediation Memory.** The thesis is not waiting to be discovered. It is in production.

**Recommendation: write it down once, as Auto-Sec's thesis rather than as a thesis seeking a product.** One page in `docs/product/STATE_AND_VISION.md` — *"Auto-Sec is judgment enforcement for AI-written systems"* — and then treat every future idea of this shape as **already answered**. The next time this pull arrives it should cost an hour, not five research agents. That page is the highest-ROI artifact this entire research pass can produce.

### Focus cost against the Tom-first priority

The standing priority (2026-08-03) is that Tom will use Auto-Sec in his real organization, so the core loops — AWS connect + scan, GitHub connect + scan, auto-generated draft PR — must be production-perfect rather than demo-perfect, before any breadth.

- **Shape A** costs two weeks minimum to validate something with a $1–2M ceiling in a segment Henry has never sold to. **Unaffordable and unjustified.**
- **Shape B** costs a company. Not a project — a different founder identity. **Unaffordable.**
- **Shape C** costs two days *and only after the loops are green*. The verified timing finding below tightens this further.

### Does anything here deepen Auto-Sec's moat?

**Exactly one thing, and it is worth isolating because it survived all four adversarial passes.** It is the kill judge's own concession, and I agree with it:

> "This handler has no authorization check" is a commodity finding. "**…and it is internet-reachable via this IAM path**" is a claim only something holding the cloud graph can make — and Auto-Sec already holds it.

Sonar cannot say the second half. Neither can CodeRabbit, Greptile, or Cursor. It is not a teaching product, not a golden path, and not a scaffolder — it is a **severity function**, and it is the only capability in ~8,000 words of research that Henry can build and no funded competitor can copy this year. Everything else in this idea space is commodity.

The tech judge independently arrived at the same place from the engineering side and turned it into a design instruction, which is the most actionable output of the whole exercise: **do not write absence-anchored rules — write exposure-anchored ones.** Match a route that is reachable per the asset graph *and* lacks the guard. Same rule, one extra join. **This converts C's riskiest assumption (a precision problem, which is hard) into a filter problem (which is tractable) — and the filter is the moat.** Two judges reaching this from opposite directions is the strongest signal in the corpus.

---

## 8. If we did it: the smallest honest version

**Winning shape: C, scoped harder than originally proposed, and re-anchored per the tech judge.**

### Verified state of the seam (checked in-repo, 2026-08-08)

This is the part no research sweep covered, and it changes the timing. All items below were verified directly:

| Fact | Status | Evidence |
|---|---|---|
| SAST pillar first shipped | **2026-08-07 — yesterday** | `git log --reverse` on `components/code_security/` → PR #260 |
| ADR 0019 (SAST pillar) merged | 2026-08-07 | PR #259 |
| Pack manifest | 1 pack, `autosec-p1-core`, `audited: "2026-08-07"` | `components/code_security/rules/packs.yaml` |
| P1 rules | 15, first-party only | `packs/autosec_p1_core.yaml` |
| **Rule shape** | **All 15 presence-shaped. Zero absence-shaped.** | All 11 `pattern-not` usages are intra-expression narrowings (e.g. `pattern-not: eval("...")` excludes literal args) — none asserts absence across a file |
| Board wiring | **Done** — `code_security.opengrep` → `ai.code_security` | `_SOURCE_BOARD` in `finding_raised_board_handler.py:291` |
| **Triage routing** | **NOT done** | `ai.code_security` appears in exactly one non-test source file (the board handler); it is absent from `ROUTABLE_SOURCE_TYPES` |
| SAST P2 (triage tool + routing) | **In progress right now** | Tracker task #112 |

**Two consequences, both of which the research briefs could not have known:**

1. **The tech judge's rule-shape claim is confirmed empirically.** The P1 pack contains no absence assertions, and this is not a stylistic accident — Opengrep is the pre-relicense Semgrep OSS fork and lacks Pro's interfile/cross-function analysis. "This DRF view has no `permission_classes`" is false the moment authz lives on a mixin base class, a `urls.py` decorator, or `DEFAULT_PERMISSION_CLASSES` — which is every real Django application, **including Auto-Sec's own.** Naïve absence rules would flood the board, which is the exact failure Tom and William both named as fatal.
2. **The strategy judge's timing objection is confirmed and is stronger than stated.** The brief said "propose a second pack for a pillar days old." The verified position is worse: the pillar is **one day old**, its first pack has never run against Tom's real repository, and the triage routing that Shape C's value depends on **does not exist on `main` yet** — it is mid-build. Proposing to ride a seam that is actively under construction is precisely the fork failure mode `verify-dont-guess.md` exists to prevent: extending a foundation you have not checked.

### The v1, if and only if the gates in §9 clear

**Five to eight exposure-anchored rules** in the existing pack format, as `packs/autosec_p2_structural.yaml` plus one manifest entry with its license audit.

Not "find handlers missing authz." Instead: **find handlers that lack a guard *and* are reachable per the asset graph.** Candidate targets: a route registered without an auth class on an internet-reachable service; a queryset returning user data with no tenant/owner filter in a multi-tenant path; permissive CORS or wildcard IAM in generated config; secrets in generated settings.

Output rides the existing path unchanged: finding on the SSOT → card on the board → triage → draft PR with the fix and **one sentence of why** in the PR body. That sentence is the entire teaching layer, and it is the only part of Henry's original "drills" instinct that survives — delivered in-flow, which is the one form the Anthropic RCT supports.

### What it reuses (nothing new is built)

- `components/code_security/rules/packs.yaml` — manifest, license-audit discipline, severity ceiling
- `infrastructure/services/ruleset.py` — merges packs, rejects duplicate ids
- `infrastructure/adapters/opengrep_scanner.py` — engine + SARIF → SSOT normalization
- `_SOURCE_BOARD["code_security.opengrep"]` — **already wired**
- `AiFindingRouterDetector.ROUTABLE_SOURCE_TYPES` + the SAST triage tool — **from task #112, must land first**
- `_finding_processing.py::process_pending_finding` — shared triage choreography
- `open_draft_pr_use_case.py` — draft PR + provenance stamping
- ADR 0013 contextual risk / the cloud-graph exposure join — **the moat; this is the new dependency**

### Effort

**Two days** for the pack itself, matching the original estimate — *conditional on* SAST P2 having landed and the exposure join being queryable from the rule-evaluation path. If the join is not reachable from that path, this is not a two-day task and should be re-scoped rather than pushed through. **No new bounded context, no new model, no new UI, no new board mapping, no ADR, no new price.** If a proposal for this ever requires more than a pack file plus a manifest entry, it has stopped being this idea and should be killed on sight.

---

## 9. Validation plan

Three experiments. None requires building the product. They are ordered — **Experiment 1 gates the other two**, and it is work Henry is already committed to.

### Experiment 1 — Measure P1 precision on Tom's real repo (the free answer)

**This is not a new experiment. It is the existing roadmap, instrumented.** SAST P1 shipped yesterday and has never run in anger. Finish task #112, run the 15-rule pack against Tom's real repository, and **hand-label every hit.**

- **Who:** Tom. No recruiting, no new conversation.
- **What to put in front of them:** the findings the existing pack produces, on the existing board.
- **The number that matters:** **precision of the P1 pack on a real repo**, plus **the count of findings Tom acts on within 7 days.**
- **PASS:** precision ≥80% and Tom acts on ≥3 findings. The pillar works, the board is not a wall of noise, and a second pack is a reasonable next increment.
- **KILL:** precision <80%, or Tom disables/ignores the pillar. **Then Shape C is dead on the same evidence that would have killed it later, learned for free** — and no absence-rule work should begin.
- **Cost:** zero incremental. It is the standing priority.

### Experiment 2 — The exposure-anchored precision probe (two days, only if 1 passes)

Write five **exposure-anchored** rules against `packs/` conventions. Run `opengrep` locally over Tom's real repo plus three AI-generated open-source apps. Hand-label every hit. **No product surface, no UI, no PR to `main` until it clears.**

- **The number that matters:** **precision of the best single rule**, and **true-positive count across the whole corpus.**
- **PASS:** ≥80% precision on the best rule **and** ≥3 true findings across the corpus.
- **KILL:** below either bar. Bin the pack; the engine cannot express the rule class at acceptable cost, exactly as predicted.
- **Secondary check, and it is the real one:** can the exposure join actually be reached from the rule-evaluation path? If not, stop — the moat is unavailable and what remains is commodity linting that Sonar does better.

### Experiment 3 — The cohort mom-test (optional; only if Henry still wants the standalone question answered)

I recommend **against** running this — Experiments 1 and 2 answer the only decision actually in front of Henry, and this one costs operator-interview time that is better spent on Tom. It is specified here so that if the pull returns, it costs an hour of planning rather than another research pass.

- **Who:** 8 people who shipped an AI-built app with real users (Lovable/Bolt/Replit Discords, r/vibecoding, Product Hunt makers) — plus, more importantly, **3 contractors or fractional CTOs who have inherited such a codebase**, since they are the only segment with budget authority in Shape A's world.
- **What to put in front of them:** nothing built. A free 30-minute repo review, done by hand with Claude and a checklist, delivered as a written report plus three concrete fix suggestions. **Mom-test discipline: ask what happened last time it broke, not whether they would use a tool.**
- **The numbers that matter, in priority order:**
  1. **Surprise rate** — "how much of this did you already know?" **>60% already known = there is no information asymmetry and this is a linter, not a product.** This is the cheapest disqualifier; measure it first.
  2. **Post-break behaviour** (closes evidence gap #3, the most decision-relevant one): "when it last broke, what did you actually do?" **If ≥6 of 8 say they re-prompted the AI, Shape A is structurally unreachable and the question is permanently closed.**
  3. **Card commitment** from the contractors — a card, not a verbal yes.
- **PASS:** surprise rate >60% **and** ≥2 of 3 contractors put a card down.
- **KILL:** anything less. Note METR's finding — developers were 19% slower while believing they were faster — which means **self-reported opinion in these interviews is actively misleading.** Only behaviour counts.

### What NOT to do

Do not publish `.claude/rules/*` + `tests/architecture/` as an open-source constitution *yet*, despite two judges offering it as a free fallback. It is not free: it is a public artifact that invites issues, questions and maintenance, and it advertises an architecture whose SAST pillar is one day old. It is a reasonable move **after** Tom's loops are green and the pillar has proven itself — as credibility marketing, not as validation. Deferring it costs nothing.

---

## 10. Sources

**Scaffolders and generators**
- GitHub / npm / PyPI APIs — star and download figures fetched live, 2026-08-08
- create-t3-app — github.com/t3-oss/create-t3-app (last push 2025-12-13; v7.40.0 released 2025-11-05)
- create-better-t-stack — npmjs.com/package/create-better-t-stack
- Microsoft SPFx CLI replacing Yeoman — spknowledge.com, 2026-05-08
- Nx 23 release (prompt-only + hybrid migrations) — nx.dev/blog/nx-23-release, June 2026
- JHipster 9.0.0 — jhipster.tech/2026/03/10/jhipster-release-9.0.0.html; 9.1.0, 2026-05-27
- cookiecutter-django docs — cookiecutter-django.readthedocs.io
- StackAdvisor.ai — stackadvisor.ai (free starter tier; no verifiable user count)
- CloudKompas Architecture Advisor — cloudkompas.com, 2026
- Architecto — producthunt.com/products/architecto, ~2026-04
- GitHub Spec Kit — github.com/github/spec-kit (MIT); Microsoft Learn training module
- Catio — PRNewswire 2025-03-25 ($3M; $9.65M total); VentureBeat

**Golden paths / IDP**
- Spotify Engineering, "How We Use Golden Paths…" — 2020-08-17
- AWS Well-Architected Framework + Lenses — aws.amazon.com (free, incl. API)
- Microsoft Azure CAF — learn.microsoft.com/en-us/azure/cloud-adoption-framework/overview
- Thoughtworks Technology Radar Vol 34 — thoughtworks.com/radar, 2026-04-15
- CNCF Platform Engineering Maturity Model — cncf.io, 2023-11-20
- Humanitec reference architectures — humanitec.com/reference-architectures
- Port pricing — port.io/pricing (50-seat minimum); Series C: Calcalist, 2025-12-11 ($100M at $800M)
- Roadie pricing — roadie.io/pricing ($24/dev/mo, 50–150 devs, "Existing subscribers only")
- Backstage self-hosted cost — platformengineeringcost.com/backstage-cost, verified 2026-06-09
- Gartner: 80% of large orgs / <30% productivity gains, 2026
- Golden-paths adoption-failure claim — tasrieit.com, 2026 *(secondary; no primary study located)*

**AI builders + governance**
- AGENTS.md — agents.md (60,000+ repos; Agentic AI Foundation / Linux Foundation)
- AGENTS.md `.agents/rules/` proposal — github.com/agentsmd/agents.md/issues/179
- Sync AI Agent Rules — github.com/marketplace/actions/sync-ai-agent-rules
- SonarQube Server 2026.4 (architecture management + agentic-AI gate) — sonarsource.com, July 2026
- Greptile Series A (auto-detects CLAUDE.md / .cursor/rules) — greptile.com/blog/series-a, Sept 2025
- Greptile ~$180M valuation — techfundingnews.com; SiliconANGLE, 2025-09-23
- CodeRabbit Series B — Businesswire, 2025-09-16; ~$40M ARR Apr 2026 — Sacra, sacra.com/c/coderabbit
- AI builder comparison — altar.io, 2026; layout.dev, 2026
- Lovable valuation/ARR — valueaddvc.com *(secondary; treat ARR as estimate)*
- CVE-2025-48757 (Lovable Supabase RLS) — 170+ apps, 303 endpoints

**Cohort evidence**
- Anthropic RCT, 52 junior engineers, 50% vs 67% — 2026-01-29
- METR RCT, 16 devs / 246 tasks, 19% slower vs 20–24% perceived faster — July 2025
- GitClear "Maintainability Gap," 623M changes — Jan 2026; earlier edition 211M lines, 2025
- Apiiro Fortune-50 data (+153% design flaws, +322% priv-esc) — via CSA note, 2026-04-04
- DORA 2025 State of AI-assisted Software Development, ~5,000 respondents — Google Cloud, Sept 2025
- Stack Overflow Developer Survey 2025 (48,892 respondents) — published Dec 2025
- Clutch, 800 professionals, 59% ship code they don't understand — June 2025
- Veracode, 100+ LLMs / 80+ tasks, 45% OWASP-flawed — 2025
- Symbiotic Security, 1,072 Supabase-backed apps, 98% ≥1 vuln — 2026-06-02 *(vendor-run)*
- Escape.tech, ~1,400 apps — *(vendor-run)*
- Georgia Tech Vibe Security Radar (6→15→35 CVEs, Jan–Mar 2026) — via CSA
- Addy Osmani, "The 70% Problem" — 2024-12-04
- Stack Overflow question decline (3,862 in Dec 2025, −78% YoY) — devclass.com, 2026-01-05

**Market / graveyard**
- Val Town retrospective (Tom MacWright) — macwright.com/2025/11/11/val-town
- roadmap.sh — Starter Story breakdown; Flagsmith podcast (2.8M users, ~2.5 staff, unmonetized)
- Boot.dev ~$1.3M ARR; Scrimba ~$1.9M / 500K customers — getlatka
- Chegg — CNBC 2025-05-12 (22% layoffs); Forbes 2025-10-29 (45% cut, −99%)
- Coursera–Udemy close — Class Central; COUR 8-K, 2026-05-11
- CodeSee — sunset 2024-02-22, acquired by GitKraken May 2024
- StackShare — DigitalOcean May 2023 → FOSSA Aug 2024; enterprise discontinued
- Swimm — pivot to COBOL/JCL/PL-I legacy modernization
- Turing School bankruptcy intent — Apr 2025; accreditation withdrawn May 2025
- ShipFast / Marc Lou 2025 revenue — newsletter.marclou.com
- Gartner AI-governance market ($492M 2026, >$1B 2030) — 2026-02-17
- DigitalOcean ($25 CPA) / Cloudways affiliate terms; Vercel $9.3B / $300M Series F, Sept 2025; Railway $100M Series B, Jan 2026

**In-repo verification (performed 2026-08-08)**
- `components/code_security/rules/packs.yaml` — 1 pack, `audited: "2026-08-07"`, 15 first-party rules, opengrep v1.26.0
- `components/code_security/rules/packs/autosec_p1_core.yaml` — all 11 `pattern-not` usages intra-expression; zero absence assertions
- `git log --reverse -- components/code_security/` — pillar first shipped 2026-08-07 (PR #260); ADR 0019 merged 2026-08-07 (PR #259)
- `components/agents/application/handlers/finding_raised_board_handler.py:291` — `code_security.opengrep` → `ai.code_security` board mapping present
- `grep -rn "ai.code_security" components/ --include="*.py"` — exactly one non-test hit (board handler); **absent from `ROUTABLE_SOURCE_TYPES`**
- Tracker task #112 "SAST P2: triage tool + routing" — **in progress**
- `tests/architecture/` — 25 fitness-function test modules
