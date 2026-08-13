# auto-sec.ai — Landing Page Design

> **Status:** Design doc · **Date:** 2026-08-09 · **Build status: NOT BUILT — reference doc only.**
> Henry's instruction: *"do not build it — write a document that we will reference later."*
>
> **Scope:** the apex `auto-sec.ai` pre-launch page. One viewport, no scroll, terminal/HUD-flavoured,
> a message + an email capture. This doc decides; it does not survey.

---

## 0. The decisions, up front

| # | Question | Decision |
|---|---|---|
| 1 | Aesthetic | **Direction B — "HUD-minimal"**: our own V2 primitives, dark, monospace, one chamfered card, one lunar callout. Not a literal terminal emulator. |
| 2 | Layout | Single centred column in one viewport. Wordmark → headline → two-line proof → email field → one status line. Lunar callout is an inline reveal for *"what is this?"*. |
| 3 | No-scroll on mobile | `min-height: 100svh`, **never** `overflow:hidden` on body. Below a height threshold the page becomes a taller, scrollable mobile layout. Locking the viewport would break WCAG reflow. |
| 4 | Tech | **New repo `auto-sec-landing`**, Vite + React, vendoring a ~10-file `hud/` kit copied from V2. Not a route in the HUD app, not hand-rolled HTML. |
| 5 | Hosting | `workloads/marketing` in auto-sec-infra — `modules/s3-bucket` + `modules/cloudfront-s3-private`, own state, data-sourcing the existing apex+wildcard ACM cert. |
| 6 | Email capture | ⚠️ **SUPERSEDED by ADR 0027 (2026-08-12)** — capture is standalone CloudFront → Lambda Function URL → DynamoDB, NOT a `shared_platform` surface behind `api.auto-sec.ai`. The API dependency made a pre-launch page depend on launching (see §12). ~~Original:~~  A new ~10-file `waitlist` surface in `components/shared_platform`, POSTed cross-origin to `api.auto-sec.ai`. **Not** the inherited newsletter machinery (it's unrouted, workspace-coupled and untested), not a third-party form service, not a Lambda. |
| 7 | Out of scope v1 | Pricing, docs, blog, logos/social proof, demo video, analytics beyond CloudFront logs, i18n, light mode. |

---

## 1. Why this page exists, and what it must not become

The apex is reserved (auto-sec-infra `terraform/README.md` §"future marketing": *"The apex `auto-sec.ai`
is deliberately unclaimed — reserved for the future marketing workload"*). Today it resolves to nothing.

This page has exactly **one job**: convert a technical visitor who heard about Auto-Sec into a known
email address, and do it in a way that makes them think *"these people can build."* It is a **pre-launch
waitlist page**, not a feature-marketing site. Every feature we could list is a reason to add scroll, and
scroll is the thing Henry has ruled out.

**The counter-example is in our own org.** `wanjala-dev/octopus` — "landing page for octopus" — is a
purchased React template (`startix-reactjs`: bootstrap, gsap, swiper, jarallax, marquee3000, ~28 MB repo).
It is a multi-section scrolling marketing site. Auto-Sec's landing page should be its deliberate
anti-thesis: one viewport, our own components, no template, near-zero dependencies. The medium is part of
the message — a security product whose landing page ships 1 MB of carousel libraries is telling on itself.

### The one honest tension in this brief

A survey of ~20 archived pre-launch dev/security pages (§11) surfaces a real pattern: **page density
splits by what you're selling.**

- Selling a **primitive** (Resend, Modal, Terra) → one viewport, no scroll, no nav. The reader already
  knows they need an email API; you only have to say you exist.
- Selling **judgement or workflow** (Prophet Security, Zed, Dropzone) → a long scroll that argues the
  problem *first*, because the reader must be convinced the problem is theirs before the product means
  anything. Prophet devotes a whole block to alert fatigue before mentioning its product.

**Auto-Sec is the second kind, and Henry has specified the first kind's layout.** That is a genuine
constraint, not a mistake — but it must be named, because it relocates the difficulty:

> If the page gets one viewport, **the headline has to *be* the argument** (Prophet's alert-fatigue block
> compressed to one sentence), and **the proof has to be a single artifact**, not a five-step walkthrough.

That is achievable — §2 is built precisely this way — but it is a **harder writing problem than a layout
problem**, and it is where the effort should go. If a reviewer ever feels the page is thin, the fix is a
sharper headline and a more concrete receipt (§2.2b), **not** more sections.

### The audience
Tom/Isaac-shaped (`docs/product/STATE_AND_VISION.md` §2.1, §2.3): technical founders and small teams
shipping fast with AI-generated code, on AWS, no security team, no budget for one. They are allergic to
marketing language and they can read. They will judge the page's *craft* as a proxy for the product's
craft. This audience rewards specificity and punishes adjectives.

---

## 2. The copy

Drafted in Henry's register: declarative, concrete, no adjectives doing load-bearing work.

### 2.1 Recommended — "the moat sentence"

The single best piece of copy we own is already written, in `STATE_AND_VISION.md` §1.1:

> *"This handler has no authorization check"* is a commodity finding. *"…**and it is internet-reachable
> via this IAM path**"* can only be said by something holding the cloud graph.

That is the whole wedge in two clauses, it is technical, it is verifiable, and no competitor can say the
second clause. It becomes the hero.

```
AUTO-SEC
AUTOMATIC SECURITY

Your AI writes code faster than anyone can judge it.

  "This handler has no authorization check"
   — every scanner says this.

  "…and it's internet-reachable via this IAM path"
   — this one needs the cloud graph. We hold the graph.

  [ you@company.com                    ] [ NOTIFY ME ]

  ▪ PRE-LAUNCH · we'll email once, when it's ready.
```

- **Headline:** `Your AI writes code faster than anyone can judge it.`
  Names the reader's actual situation, not our product category. It is the §1.1 thesis in nine words.
- **Proof block:** the two quoted findings, dimmed/accented as a diff. This *is* the subline — it shows
  rather than claims, and it is the one thing on the page a competitor can't copy.
- **CTA button:** `NOTIFY ME` (not "Join the waitlist", not "Get early access" — both are marketing mush
  and imply scarcity theatre we haven't earned).
- **Reassurance line:** `we'll email once, when it's ready.` This is the highest-value sentence on the
  page for a technical audience: it caps the commitment. Do not replace with "no spam!"

### 2.2 Alternates (keep on file)

**B — the ICP framing** (validated by Tom, §2.1):
```
The security team you don't hire.

Cloud, code, and containers — scanned, correlated on one graph,
triaged by agents that open the pull request with the fix.
```
Truer to the product's full shape, weaker as a hook — "security team you don't hire" is a category
claim, and categories invite comparison. Use this as the lunar-callout body, not the headline (see §4).

**C — the blunt one:**
```
45% of AI-generated code ships an OWASP Top 10 flaw.
Nobody is reviewing yours.
```
Cites Veracode (2025, 100+ models — `STATE_AND_VISION.md` §1.1). Highest-tension option. Risk: leads
with fear and a borrowed stat rather than our own capability. Hold in reserve for paid-acquisition
variants, not the apex.

### 2.2b The receipt — the strongest upgrade available to this page

A survey of ~20 archived pre-launch dev/security pages (§11) produces one finding that outranks the
rest: **at zero customers, the two things that build trust are pedigree and receipts — and for a security
tool, receipts win.** A receipt is a *verifiable artifact a stranger can click and confirm*.

The benchmark is **Antithesis** (2023 pre-launch), whose page had no signup form at all but did carry a
section headed *"a few of the bugs Antithesis found"* — a list of clickable upstream issue URLs in
MongoDB, FoundationDB, CockroachDB, Materialize and Prysm. A reader verifies the claim in one click.
Nothing else on a pre-launch page comes close to that.

**We can do this, and we uniquely should.** `STATE_AND_VISION.md` §1.1 records that the full loop is
*"proven end-to-end on a real dogfood draft PR"* — our own agent found a real issue in our own
infrastructure and opened a real pull request with the fix. `auto-sec-api` is already a public repo.

**Recommendation:** under the proof block, one dim line:

```
▪ we ran this on ourselves — PR #NNN
```

…linking a genuine agent-opened draft PR. It converts the entire page from a claim into a demonstration,
it costs one line of vertical space, and it is the one thing on the page a funded competitor cannot
fake. **This needs Henry's call** — it means pointing prospects at a specific PR in our own repo, so pick
one that reads well (clear finding, clean patch, one sentence of *why* in the body).

If we don't want to point at a specific PR, the fallback rung is **pedigree** (Linear's founder
one-liners; RunSybil's *"alumni from OpenAI, Bishop Fox, Rapid7, Crowdstrike"*), and below that
**anonymised-but-titled** quotes (Wiz's *"CISO, Fortune 50 company"*). Both are weaker. Do not fabricate
either.

### 2.3 Copy rules for whoever builds it
- No word that could appear on any other security company's page ("comprehensive", "seamless",
  "next-generation", "end-to-end", "AI-powered").
- No claim we cannot demo today. Specifically: **do not claim runtime protection** (we have none —
  §0 of STATE_AND_VISION lists it as an honest gap) and **do not imply GA**.
- Lowercase the reassurance line; uppercase + letter-spacing for labels only. That is the HUD's own
  typographic rule and it carries the aesthetic for free.

---

## 3. The layout — one viewport

```
┌──────────────────────────────────────────────────────────────────────┐
│                          [starfield + grid]                          │
│                                                                      │
│                              ◉  (GlitchHex)                          │
│                            AUTO-SEC                                  │
│                        AUTOMATIC SECURITY                            │
│                                                                      │
│         Your AI writes code faster than anyone can judge it.         │
│                                                                      │
│      ╭──────────────────────────────────────────────╮╱               │
│      │  "no authorization check"        COMMODITY   │                │
│      │  "…internet-reachable via this   ← THE GRAPH │                │
│      │   IAM path"                                  │                │
│      │                                              │                │
│      │  ┌────────────────────────┐ ┌──────────────┐ │                │
│      │  │ you@company.com        │ │  NOTIFY ME   │ │                │
│      │  └────────────────────────┘ └──────────────┘ │                │
│      ╰──────────────────────────────────────────────╯                │
│                                                                      │
│         ▪ PRE-LAUNCH · we'll email once, when it's ready.            │
│                                        [ what is this? ] ──┐         │
│                                                            │         │
└────────────────────────────────────────────────────────────┼─────────┘
                                                    (lunar callout)
```

**Vertical budget** (at 1440×900, the modal desktop case): wordmark block ~180px, headline ~60px,
card ~240px, status line ~40px, generous whitespace absorbing the rest. Comfortable. The design must
survive 1366×768 and 1280×720 without crowding — that is the real desktop constraint, not 1080p.

**One card, not three.** The chamfered `HudCard` holds the proof block *and* the email field. Putting the
input inside the card is what makes the page read as a HUD instrument rather than a hero + form.

### The lunar callout — what it does here
Henry named the lunar callouts specifically. On the landing page, `SlideInHexPanel` is the answer to
**"what is this?"** — a single dim link at the bottom-right. Clicking it springs open a callout with the
elbow lead-line drawn from the link to the panel, containing ~60 words: the alternate-B copy (§2.2),
what we scan (AWS, repos, container images), and the honest status ("private beta, first customers
onboarding"). Clicking anywhere else, or `Esc`, retracts it.

This is the correct use of the primitive because:
- It **never leaves the page** — no route, no scroll, no modal takeover. Preserves the one-viewport rule.
- It gives the curious visitor depth without taxing the visitor who already knows what they want.
- It is the single most distinctive thing in our design language, and it is *demonstrated* rather than
  described — the page becomes a small sample of the product's interface.

Placement: use `computeSideCalloutPlacement(rect, contRect, …)` (`v2Constants.js:657`, 36 self-contained
lines) or a hardcoded `placement` object. **Do not** use `computeHexPanelPlacement` — it is ring-centric
and assumes a centre core to avoid, which we don't have.

### Interaction inventory (deliberately tiny)
| Element | Behaviour |
|---|---|
| Email input | **No `autofocus` — not even on desktop** (see below). `type="email"`, `inputmode="email"`, `autocomplete="email"`, a real `<label>`. |
| Enter | Submits. |
| `NOTIFY ME` | Submits; becomes a `HexLoader` for the request; then the card body swaps to the success state in place. |
| `what is this?` | Toggles the lunar callout. |
| `Esc` | Closes the callout. |
| Everything else | Nothing. No nav, no menu, no scroll, no cookie banner (we set no cookies — see §7). |

**Success state:** the card body is replaced in place — no redirect, no page change.
```
▪ REGISTERED
you@company.com — check your inbox to confirm.
```
Redirecting to a /thanks page would break the one-page rule and lose the aesthetic for no gain.

---

## 4. Aesthetic directions

### 4.0 What Henry's two references actually teach

Both references were studied. The useful lesson from each is the *opposite* of "add terminal chrome".

**[awesome-tuis](https://github.com/rothgar/awesome-tuis)** (rothgar) — 13 categories (Dashboards,
Development, Docker/K8s, Editors, File Managers, Games, …). The strongest entries — `btop++`, `k9s`,
`lazygit`, `lazydocker`, `bottom`, `htop`, `yazi` — share a consistent design language:

| TUI idiom | Does it belong on our page? |
|---|---|
| **Box-drawing borders** (`┌─┐│└┘`) for panels | **Conceptually yes — we already have it.** Our chamfered `HudCard` *is* our box-border. Don't literally draw `┌─┐` in text; that's the costume version. |
| **Status bar at the bottom** with keybinding hints (`q:quit  ?:help`) | **Yes — steal this.** It's the single most characteristic TUI idiom, and our `▪ PRE-LAUNCH · we'll email once, when it's ready.` line is exactly that shape. |
| **Colour-coded status** (green/red/amber) | **Sparingly.** One accent only. The HUD's severity palette is a product surface, not a landing-page one. |
| **Multi-pane density** (2–3 columns of live data) | **No.** Density is what makes a *tool* good and a *landing page* bad. |
| **Vi keybindings** (`hjkl`) | **No.** Charming in a tool you live in; friction on a page with one field. |

**[terminal-apps.dev](https://terminal-apps.dev/)** — a curated showcase (lazygit 79.2K★, lazydocker
51.3K★, yazi, btop, superfile, posting, gh-dash, oha). The instructive thing is that **the site itself is
not skinned like a terminal.** It's a clean card list: functional minimalism, no animations, no flashy
interactions, consistent metadata (language, licence, stars) per entry. A site *about* terminal apps
declines to cosplay as one — and it reads as more credible for it.

### 4.0b The finding that should give us pause — and why we proceed anyway

A sweep of security-company homepages found **almost none use the terminal aesthetic**. Checked and
rejected as non-terminal: ProjectDiscovery, GreyNoise, runZero, Semgrep, watchTowr, Trail of Bits,
Latacora, Shodan, Chainguard, Teleport, Infisical, Zellic, Hack The Box. The sharpest data point:
**ProjectDiscovery — the company that makes Nuclei, a CLI scanner — has zero monospace elements on its
homepage** and a "Talk to an expert" CTA. Warp, a *terminal company*, sells with a light enterprise SaaS
site and "Book a demo."

This is a convention, not an oversight: security sells to buyers who sign contracts, and a page that
reads as a hobby project undermines the thing being sold. Terminal aesthetics live in devtools and
AI-infra, where **the buyer is the user**.

**Why we proceed:** our ICP *is* the user — engineers with no security team, not a CISO running an RFP
(§1). The convention we'd be breaking was built for a buyer we aren't selling to yet. But the risk is
real and it sets a bar: **the execution has to read as competence, not costume**, because for a security
vendor "they don't check their work" is disqualifying.

**The one security exemplar worth studying is [Dreadnode](https://dreadnode.io)** — near our exact
category (AI infrastructure for security agents). Measured: sans for prose, mono for *technical chrome
only*, at roughly **25% of elements**; near-black `#030303`; one hot accent (`#EF562F`); ALL-CAPS mono
eyebrows; zero-padded step numbers. And structurally: **DreadIndex, a public model-eval leaderboard,
sits above the pitch as a credibility artifact** — which is the same move as our §2.2b receipt.

We diverge on one point deliberately: Dreadnode's ~25% mono ratio suits a sans-prose page, whereas our
HUD is monospace-first by design and that *is* our identity. Keep the mono, but take the lesson that
**mono should be carrying technical meaning**, not decorating prose.

**The specific trap for us:** a fake terminal printing scan output our product didn't actually produce
is the one thing that would get mocked — and it directly contradicts our own standing rule that findings
must carry real artifacts. If we show a readout, it must be a *real* one (§2.2b).

### 4.0c Synthesis

**The synthesis, and it is the argument for Direction B:** what makes terminal-adjacent design feel
*deliberate* is **restraint and information honesty** — monospace, tight alignment, a status line, no
decoration that isn't carrying meaning. What makes it feel *gimmicky* is simulated chrome: scanlines, CRT
curvature, phosphor bloom, fake `$` prompts, and typed-output animation. None of the top TUIs use any of
those; they're a web affectation applied *to* the aesthetic, not *from* it.

So: adopt the **discipline** of the terminal (mono, alignment, a status line, no ornament), not its
**costume**.

---

Three genuinely distinct options. Recommendation follows.

### Direction A — Literal terminal emulator
A framed terminal window; content is a simulated session. Typed prompt, blinking block cursor, the
email field is a shell input line.

```
┌─ auto-sec ─────────────────────────────── ─ ▢ ✕ ┐
│ $ autosec scan --all                            │
│ ▸ aws         connected                         │
│ ▸ repos       3 linked                          │
│                                                 │
│ CRITICAL  handler: no authz check               │
│           └─ internet-reachable via IAM path    │
│                                                 │
│ $ notify-me _                                   │
│ > you@company.com▊                              │
└─────────────────────────────────────────────────┘
```

**For:** maximally on-brief for "CLI/TUI-flavoured". Instantly legible to the audience.
**Against:** it is a costume, not our product — the HUD looks nothing like this, so the page sets an
expectation the app then breaks. It is also the single most *imitated* dev-marketing aesthetic of the
last three years, so it reads as generic rather than distinctive. Fake terminal output is a claim we'd
be simulating rather than showing. And typed-output animation fights the no-scroll constraint (content
height changes as it types) and needs a `prefers-reduced-motion` fallback that removes the entire idea.

### Direction B — HUD-minimal ✅ RECOMMENDED
The login shield, refined. Starfield + faint grid, `GlitchHex` mark, monospace small-caps wordmark, one
chamfered `HudCard`, one lunar callout, one accent (`#2EDBE8`). Exactly the vocabulary of the real app.

**For:**
- **It is already built.** `AuthShell.jsx` (80 LOC) is literally a single-viewport, `fixed inset-0`,
  starfield + chamfered-card shell, and its entire dependency closure (`StarField`, `GlitchHex`,
  `HudCard`, `HudText`) imports nothing but React. See §5.
- **It is honest.** The visitor who signs up and later logs in sees the *same* interface. The landing
  page becomes a truthful preview instead of a costume.
- **It is ours.** The chamfer + lunar callout + hex language is a real design system nobody else has;
  the terminal look is public domain.
- It satisfies "terminal-flavoured" anyway — the HUD is monospace-first with uppercase letter-spaced
  labels. It reads as terminal-adjacent without cosplay.

**Against:** less immediately "clever" than A. Requires the chamfer/callout details to be executed
precisely or it just looks like a dark landing page.

### Direction C — Typographic brutalist
No chrome at all. Off-black, one monospace, left-aligned, no card, no starfield. Rules instead of
borders. The email field is an underlined input inline in a sentence.

```
AUTO-SEC / AUTOMATIC SECURITY
─────────────────────────────────────────────

Your AI writes code faster than anyone
can judge it.

"no authorization check"                COMMODITY
"…internet-reachable via this IAM path" OURS

notify me at ________________________  ⏎
─────────────────────────────────────────────
PRE-LAUNCH
```

**For:** the truest reading of "very very minimum". Weightless (<20 KB), unimpeachable accessibility,
ages well, impossible to get wrong on mobile.
**Against:** discards the HUD equity Henry explicitly asked to borrow, and the lunar callout has nowhere
to live. It says "minimal" but not "Auto-Sec".

### Recommendation
**Direction B**, with C's discipline applied to it: use the HUD vocabulary, but resist adding anything
the login page doesn't already have. Specifically — **no scanlines, no CRT curvature, no phosphor glow,
no typing animation.** Those are the cheapening moves; the HUD has never used them and adding them for
the landing page would make it *less* like our product, not more.

The one motion allowance: the `GlitchHex` mark (already in `AuthShell`, one small canvas RAF) and the
lunar callout's spring + line-draw on open. Both must be disabled under `prefers-reduced-motion`.

**The no-scanlines call is not just taste — it's a safety finding, and it inverts the design instinct.**
Full-viewport scanline overlays are a repeating stripe pattern, and clinical pattern-glare research puts
**peak discomfort at ~3 cycles/degree**, disproportionately affecting people with migraine or visual
stress. At normal viewing distance that maps to roughly a **13 px stripe period** — meaning the chunky,
obviously-retro scanlines people reach for (8–16 px) sit *closest to the worst frequency*, while hairline
1–2 px scanlines are both safer and more CRT-accurate. MDN, citing the Epilepsy Foundation working group,
separately flags patterns with **more than five light-dark stripe pairs**; a full-viewport overlay has
hundreds.

And the widely-copied CRT *flicker* animation (Alec Lownes' canonical snippet) runs at **0.15 s/cycle ≈
6.7 Hz** — inside the 5–30 Hz seizure-provocative band and roughly **double the 3 Hz limit** of
**WCAG 2.3.1 (Level A)**. It is a plain Level A failure. Do not ship it, and do not ship a softened
variant without measuring the rate.

Honest caveat: there is no published design critique of CRT effects on marketing pages, so the
"it cheapens the page" half of this argument is *constructed*, not cited. The safety half is sourced and
is sufficient on its own.

---

## 5. Borrowing the HUD — precisely what ports

Source: `/Users/henrywanjala/Desktop/auto-sec/auto-sec-frontend/src/components/V2/` (101 files, ~18k LOC).

### Tier A — trivially portable (copy file, drop `prop-types`)
| Component | LOC | Notes |
|---|---|---|
| `HudCard` | 65 | **The canonical chamfer.** Two-layer clip: outer div in border colour with `padding:1.5px`, inner div same clip carrying the surface. The 1.5px gap *is* the border, diagonal included. Zero deps. |
| `HudText` | 88 | The whole mono type scale (title 12px/bold/.12em → tiny 7px). Always emits `font-mono`. |
| `StarField` | 42 | Pure SVG, `useMemo`-stable positions. **Also copy `@keyframes cc-twinkle`** — it lives inline in `CommandCenterV2Page.jsx:5619`, not in a stylesheet. |
| `GlitchHex` | 111 | Self-contained canvas + RAF. |
| `ShieldLogo` | 62 | Pure SVG mark. |
| `HudChip` | 66 | Exports `CHIP_CLIP`. |
| `HudChamferLine` | 57 | Paints the diagonal edge where the two-layer trick would bleed. |
| `AuthShell` | 80 | **Fork, don't import** — it hardcodes `max-w-md`, a `◉` glyph and a `status` state machine we don't need. But it is the skeleton. |
| Token block | — | `index.css:96-121` — `:root` / `.hud-light` / `.team-red`. Copy verbatim. |

### Tier B — portable with named surgery
| Component | Surgery |
|---|---|
| `SlideInHexPanel` (171) + `CalloutLine` (140) | ① Keep `framer-motion` **or** swap its two primitives for CSS (panel spring → keyframes; `pathLength` line-draw → `stroke-dasharray/dashoffset`). ② Replace `FiX` with an inline `<svg>` — don't pull `react-icons` for one glyph. ③ Import `CHAMFER` from a trimmed constants file, not the 692-line `v2Constants`. ④ Use `computeSideCalloutPlacement`, not `computeHexPanelPlacement`. ⑤ Copy `.cc-scrollbar` (`CommandCenterV2Page.jsx:5613`). |
| `HudButton` (109) | Inline `FiChevronRight`; keep `HudChamferLine`; drop the `glitch` prop (no failed API calls here). |
| `HudInput` (74) | Cut icon imports; keep `hudInput.css` (autofill/outline resets — genuinely needed). |
| `HexLoader` (143) | Only for the submit spinner. Gate the RAF behind `prefers-reduced-motion`. |

### Tier C — do not attempt
Everything `apiClient`/auth/router-bound: all `Hud*Panel` / `Hud*Card` / `Hud*Bars` domain surfaces,
`HudSearch` (react-router + searchService), `DraggablePanel` (@dnd-kit), `CardDrillContent` (839),
`HudThreatMapCard` (mapbox + gitignored token), `CommandCenterV2Page` (5,600+). And **`CoreCanvas`** —
technically self-contained but a permanent 60 fps canvas loop; a marketing page must not pin a core.

### The chamfer rule, precisely
There is **no single canonical constant** — there is a canonical *technique* (the two-layer clip) embodied
in `HudCard` / `HudChip` / `HudChamferLine`. The standing rule "never hand-roll a clip-path chamfer" means
**use those components**, not "import one variable". Values in play:

| Source | Constant | Value |
|---|---|---|
| `v2Constants.js:15` | `CHAMFER` / `HUD_CLIP` | `14` → `polygon(0 0, calc(100% - 14px) 0, 100% 14px, 100% 100%, 0 100%)` |
| `HudCard.jsx:36` | `CHAMFERS` / `clipFor(px)` | `{sm:16, md:22, lg:32}`, same top-right-only polygon |
| `HudChip.jsx:18` | `CHIP_CLIP` | `polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 6px 100%, 0 calc(100% - 6px))` |
| `HudButton.jsx:15` | `CHAMFER` / `CLIP` | `8` → top-**left** + bottom-left |

### Theming and fonts — both free
`--hud-accent: 46 219 232` (`#2EDBE8`) is a **static `:root` default** in `index.css`. The only things
that override it are two authenticated-fetch `setProperty` calls (`BrandingSection.jsx:69`,
`CommandCenterV2Page.jsx:1648`). **A static landing page inherits the cyan with zero network calls** —
just ship the `:root` block. The `hudCanvasTheme` bus (`onHudThemeChange`) exists for canvas chrome that
must redraw on a theme flip; the landing page has no theme flip, so **skip it**.

Fonts are **free too**: there are no webfont files in the repo and no CDN links. `index.css:490` sets
`html { font-family: ui-monospace, 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Poppins', system-ui, sans-serif }`
— a system-first monospace stack. The terminal typography Henry wants **is already our type stack, at
zero bytes and zero FOIT.** If we later want visual consistency across machines, one self-hosted
JetBrains Mono woff2 (~35–60 KB/weight) is a deliberate addition, not a port.

### Background
Three stacked absolute layers, no WebGL, no RAF (`CommandCenterV2Page.jsx:3312`):
```
radial-gradient(ellipse at 50% 45%, #0a1628 0%, #050814 50%, #020309 100%)
+ 50px grid: linear-gradient(rgba(46,219,232,0.01) 1px, transparent 1px) ×2
+ <StarField count={140} />
```
Cost: two CSS gradients (free) + 140 SVG circles with compositor-only opacity animations. Cheap. **There
is no scanline layer anywhere in the codebase** — confirming §4's instruction not to invent one.

---

## 6. Tech & hosting

### 6.1 Repo: a new `auto-sec-landing`

**Rejected — a route in `auto-sec-frontend`.** The app is CRA 5 + CRACO, **single entry, single 1.05 MB
JS bundle, no code-splitting, no lazy routes**. There is no `pages/` convention and no multi-instance
`HtmlWebpackPlugin`; adding a second entry means ejecting CRACO's webpack config. Worse,
`.claude/rules/single-screen-hud.md` explicitly restricts routes to pre-auth gates. A marketing visitor
would download the entire HUD to read nine words.

**Rejected — a `landing/` folder inside the frontend repo.** Slightly better, but it puts a public,
unauthenticated, separately-deployed artifact behind the app repo's CI, review cadence and (heavier)
dependency tree, and invites accidental imports across the boundary. The two things have different
deploy targets, different release cadence, and different risk profiles.

**Rejected — hand-rolled HTML/CSS, no framework.** Genuinely tempting, and truest to "very very minimum".
But it fails on one specific point: **we would have to re-implement the chamfer and the lunar callout by
hand**, which the standing rule forbids and which is exactly where the aesthetic lives. The callout's
elbow-routing + line-draw is ~300 lines of considered geometry we already own. Re-typing it in vanilla JS
to save ~40 KB is the wrong trade.

**✅ Chosen — a new repo `wanjala-dev/auto-sec-landing`, Vite + React.**
- Precedent exists: `wanjala-dev/octopus` is a separate repo for the sibling product's landing page.
  (We diverge from its *stack* — see §1 — but the repo boundary was right.)
- Vite gives a genuinely small bundle. Budget: **< 100 KB gzipped total, < 50 KB JS.** Achievable —
  React 18 + ReactDOM is ~45 KB gz, and the vendored kit is a few KB. If we drop `framer-motion` for CSS
  keyframes (§5 Tier B ①), there are **zero third-party runtime deps** beyond React.
  - *Consider Preact via alias* to halve the runtime; only if the kit ports cleanly. Not a blocker.
- **How it consumes the HUD look without the app bundle:** a vendored `src/hud/` folder — the ~10 Tier-A/B
  files, the `:root` token block, the extracted keyframes (`cc-twinkle`, `.cc-scrollbar`), and ~25 lines
  lifted from `v2Constants` (`CHAMFER`, `HUD_CLIP`, `clipFor`, `CHIP_CLIP`, `computeSideCalloutPlacement`).
  Leave the other 660 lines of demo data behind.
- **On vendoring vs. sharing:** vendoring is a deliberate, accepted duplication. A shared npm package for
  five presentational components would add publish/version machinery to two repos for no real benefit,
  and these files change rarely. Mitigate with a header comment in `src/hud/README.md` naming the upstream
  path and commit SHA, so drift is visible and re-syncable.
- Tailwind v3 with the `withVar()` opacity-callback colour form copied from `tailwind.config.js:111`, or
  the v3-native `rgb(var(--hud-accent) / <alpha-value>)` syntax in a fresh config. Do **not** carry
  `tailwindFormsCompat` or the legacy `.btn-red` plugin.

### 6.2 Hosting: `workloads/marketing`

Already the named plan — auto-sec-infra `terraform/README.md` follow-up #3: *"`workloads/marketing` — the
auto-sec.ai apex landing site: `modules/s3-bucket` + `modules/cloudfront-s3-private`, own state key; the
frontend workload's cert already covers the apex."* And `modules/cloudfront-s3-private` was made a module
*precisely* because the marketing site is its named second consumer (`terraform/CLAUDE.md:38`).

So: **instantiate the two existing modules. Write no new module.** Mirror `workloads/frontend/main.tf`.

Three wiring details the build must not miss:

1. **The ACM cert is owned by `workloads/frontend`** (`dns.tf:28` — `domain_name = var.domain`,
   `subject_alternative_names = ["*.${var.domain}"]`). `workloads/marketing` must **data-source** it, not
   redeclare it:
   ```hcl
   data "aws_acm_certificate" "main" {
     provider = aws.us_east_1
     domain   = var.domain          # auto-sec.ai
     statuses = ["ISSUED"]
   }
   ```
   Two `aws_acm_certificate` resources for the same domain in two states would fight.
2. **Apply order** becomes api → frontend → marketing (marketing depends on the cert and on the api
   workload's data bucket for access logs).
3. **Apex A/AAAA alias records** to the CloudFront distribution — these are the records the frontend
   workload deliberately did *not* create. `no_cache_paths = ["/index.html"]`; no SPA error mapping
   needed (single page, no client routing).
4. **Deploys stay explicit**, matching the frontend's deliberate rule (no CD-through-Terraform):
   `aws s3 sync dist/ s3://autosec-prod-marketing/ --delete` + a CloudFront invalidation.

**Note the divergence from octopus:** that landing page deploys to Vercel. Ours should not — the apex,
the cert, the modules and the state layout are already decided for S3+CloudFront in our own Terraform,
and adding a second hosting provider for one static page would fragment the substrate for no gain.

---

## 7. Email capture

> ⚠️ **THIS SECTION IS SUPERSEDED — see `docs/adr/0027-waitlist-capture-standalone-not-through-the-api.md`.**
>
> The decision below (a `waitlist` surface in `components/shared_platform`, POSTed to
> `api.auto-sec.ai`) is no longer the plan. It made a PRE-launch page depend on LAUNCHING:
> §12 of this very document notes the page "cannot go live before the api + frontend
> workloads do". Capture is now CloudFront → Lambda Function URL (OAC) → DynamoDB, with no
> product dependency at all.
>
> Read on only for the abuse-control thinking (§7.6 honeypot) and the user-experience
> states (§7.7), which ADR 0027 keeps. Everything about WHERE the endpoint lives is stale.


**Decision (REVISED 2026-08-12, ADR 0027): CloudFront → Lambda Function URL (OAC) → DynamoDB,
PK = email. Standalone — no dependency on the API, the cluster, or `api.auto-sec.ai`. Do not
re-mount the inherited newsletter machinery. Do not add a third-party form service.**

~~*Superseded decision:* a new, tiny `waitlist` surface in `components/shared_platform`, POSTed
cross-origin to `api.auto-sec.ai`. Do not add the stack's first Lambda.~~ — the API dependency made
a pre-launch page wait on launching (§12). See §7.2 for why the anti-Lambda reasoning failed.

### 7.1 Why not the inherited newsletter machinery

The fork *does* carry `components/content` with a full `Subscriber` model and public
subscribe/confirm/unsubscribe controllers — and CLAUDE.md's "removed" list is **wrong**, `content` is
mounted at `api/urls.py:75`. But the machinery is the wrong tool, for five concrete reasons:

1. **The public endpoints are not routed.** `components/content/api/public_subscriber_controller.py`
   defines five `AllowAny` views; **none appear in `components/content/api/urls.py`**, whose docstring says
   the newsletter/subscriber surface is a nonprofit surface deliberately not mounted.
   `/content/public/<workspace_id>/subscribe/` **404s today.** It is live-looking dead code.
2. **It is workspace-coupled at the API layer.** The URL carries `<workspace_id>`; the use case and
   repository both require one. A pre-launch waitlist has no workspace. (The *schema* would allow
   `workspace=NULL` — there is a partial unique constraint for exactly that — but no wired path produces
   such a row.) Riding it would mean inventing a fake singleton "marketing workspace", which is precisely
   the `no-shortcuts.md` failure mode.
3. **Its confirm token is the unsubscribe token** — one persistent `uuid4` column serving both purposes,
   with **no expiry, no signing, no HMAC**. Identity's magic-link does this properly with a
   `TimestampSigner`. Replicating the weaker design is the `improve-dont-replicate.md` trap.
4. **Zero test coverage** — `components/content/` has no `tests/` directory at all in this fork.
5. **Re-mounting re-exposes more than we want**: newsletters, blog, and the SES open-pixel surface that
   was deliberately trimmed. A landing page must not drag the nonprofit surface back online.

Reusing the `Subscriber` table with `workspace=NULL` is the tempting middle path and should also be
rejected: it puts prospect PII in a table that workspace-admin surfaces read, and inherits the
`BigAutoField` PK, the weak token, and an M2M to `Newsletter`.

### 7.2 Why not a third-party form service — and why a Lambda IS the answer

> **REVISED 2026-08-12 (ADR 0027).** The original version of this section argued against a
> Lambda. That argument is kept below, struck through, because the reasoning was reasonable
> and the conclusion was still wrong — it is worth seeing why.

- **Third-party (Loops / Buttondown / ConvertKit / Formspree):** it would be the only third-party
  dependency on the page, it hands prospect PII to a processor we haven't diligenced, and it conflicts
  with §9's no-third-party-scripts rule (and its cookie-banner consequence). We are a security product;
  our prospect list living in someone else's tenant is an avoidable story.
- **Serverless handler — THIS IS NOW THE DECISION (ADR 0027).** CloudFront → Lambda Function URL
  (OAC) → DynamoDB, PK = email.

  ~~*Original argument:* there is no Lambda, no API Gateway, no CloudFront Function and no WAF anywhere
  in auto-sec-infra — the stack is 100% k3s-on-EC2 + S3/CloudFront. A form Lambda would be the first of
  all of those, introducing a new compute model, a new packaging/deploy path, and a new persistence store
  at once, and it would blur the "Terraform provisions the substrate, Kustomize deploys the workloads"
  split.~~

  **Why that was wrong.** It weighed the cost of a *new pattern* and never weighed the cost of the
  *coupling it chose instead*. Routing capture through `api.auto-sec.ai` makes a PRE-launch page depend
  on LAUNCHING — §12 of this document states exactly that: the page "cannot go live before the api +
  frontend workloads do". To collect one email we would first stand up k3s, deploy the API, delegate DNS
  from GoDaddy, and expose an API subdomain. A new-pattern objection cannot outweigh a dependency that
  blocks the artifact entirely.

  Three of the four premises were also weaker than they read:
  - *"API Gateway too"* — not needed. A **Lambda Function URL is a CloudFront origin** with OAC. That
    was historically true and no longer is.
  - *"a new persistence store"* — DynamoDB with PK = email is not incidental, it is the RIGHT shape: a
    conditional write gives idempotent dedupe with no code.
  - *"blurs the substrate/workload split"* — it does not. The landing page is not a workload on the
    cluster; it is a static site plus one function, provisioned entirely by Terraform. Nothing about it
    touches Kustomize.

  The one premise that held — *"no WAF"* — survives as a deliberate deferral (ADR 0027 D4), not as an
  argument against the design.

### 7.3 Where it lives — `shared_platform`

Not a new `components/waitlist/` context. The honest cost comparison:

| Option | Cost |
|---|---|
| New bounded context | ~20–25 files. The smallest existing context (`tagging`) is 45 `.py` files, and `tests/architecture/test_explicit_architecture_layout.py` *requires* any context with a `controller.py` to have non-empty `api/requests/` **and** `api/resources/`. Plus a new persistence app + migration + `INSTALLED_APPS`. |
| **`shared_platform`** ✅ | ~8–10 files. |

`shared_platform` is right on the merits, not just the cost:
- It is already the home for cross-cutting platform concerns **with no tenant owner** — feature flags,
  broadcast banners, uploads, domains, the honeypot.
- It is **explicitly exempt** from the requests/resources scaffolding rule
  (`test_explicit_architecture_layout.py:51` — `EXEMPT_CONTEXTS = {"shared_kernel", "shared_platform"}`).
- Its `api/urls.py` already exports separately-named lists (`broadcast_urlpatterns`, `core_urlpatterns`,
  `honeypot_urlpatterns`, …) mounted individually — `waitlist_urlpatterns` is exactly that shape.
- It already owns `EmailSendingPort`, so the confirmation email is a port call, not new plumbing.
- `broadcast` (`BroadCast_Email`, `Banner`) is direct precedent for a near-trivial surface living here.

**The counterargument, stated honestly:** if the waitlist grows into marketing/CRM (campaigns, sequences,
segments, lead scoring), it deserves its own context and starting here is a migration we'll pay for. For
pre-launch email capture that is speculative, and a 1-model/1-endpoint context fails the "is this a
bounded context or just a table?" test.

### 7.4 What to reuse

- **`EmailSendingPort`** (`components/shared_platform/application/ports/email_sending_port.py`) +
  `DjangoEmailAdapter` + its provider. **Gotcha:** the adapter calls `msg.send(fail_silently=True)` and
  returns a bool — it will not raise. Check the return value and retry; don't assume delivery.
- **The `MagicLinkRequestView` shape** (`components/identity/api/controller.py:1921`) as the canonical
  routed public-POST pattern: `authentication_classes = ()`, `permission_classes = (AllowAny,)`, a
  dedicated named throttle returned from `get_throttles()`, and a **uniform response regardless of whether
  the address is already known** (anti-enumeration).
- **The existing SES transport.** Prod is SES-over-SMTP (`api/settings/prod.py:83`), `DEFAULT_FROM_EMAIL =
  "Auto-Sec <no-reply@auto-sec.ai>"`, and SES production access is already granted account-wide. The
  `auto-sec.ai` identity, DKIM, MAIL FROM/SPF and DMARC (`p=quarantine`) are all defined in
  `auto-sec-infra/terraform/workloads/api/ses.tf` — **but none of it is applied yet**, and the domain's
  public NS is still GoDaddy. Email cannot work before that delegation lands.

### 7.5 The endpoint

```
POST https://api.auto-sec.ai/platform/waitlist/
{ "email": "you@company.com", "hp": "", "t": 1754... }
→ 202 always (400 only on a structurally invalid email)
```

- **Always 202**, whether the address is new, duplicate, or suppressed. Never reveal list membership.
- **Store:** `email` (citext/lower-cased, globally unique), `created_at`, `confirmed_at`,
  `source` (`apex`), `ip_hash` (salted — not raw IP), `user_agent`, `unsubscribed_at`, and a **separate,
  signed, expiring confirm token** (`TimestampSigner`, 7-day max age) — explicitly *not* the unsubscribe
  token.
- **Throttle:** a new `waitlist_subscribe_anon` scope. Existing anon scopes live in
  `api/settings/base.py:437`; `newsletter_subscribe_anon 5/min` is the precedent rate. Recommend
  **5/min keyed email-then-IP**, mirroring `_ScopedIdentityThrottle`.
- ⚠️ **`NUM_PROXIES` is not set anywhere in this repo.** With it unset, DRF's `get_ident()` returns the
  whole `X-Forwarded-For` header, so a client varying a spoofed header walks around any IP-keyed throttle
  unless the k3s ingress overwrites it. **Verify the ingress behaviour or set `NUM_PROXIES` before
  relying on this rate limit.** This is a real finding, not a hypothetical.

### 7.6 Abuse controls

We have **less than you'd hope** and should not pretend otherwise:
- The `honeypot` app is a **decoy Django admin login page** at `/admin/` (real admin is at `/octopus/`).
  It is a `FormView`, not middleware and not a form-field trap — **unusable for a JSON API.** A honeypot
  field here is new code.
- **No captcha/Turnstile anywhere** (grep returns nothing) and **no WAF** at the edge.

Proportionate set for v1, in order:
1. **Hidden honeypot field** (`hp`) — bots fill it, humans can't see it. `aria-hidden`, `tabindex="-1"`,
   off-screen (not `display:none`, which some bots detect). Free, catches most naive spam.
2. **Timing check** — reject submissions faster than ~2s after page load (`t` timestamp, server-verified).
3. **The throttle above**, once `NUM_PROXIES` is resolved.
4. **Syntactic validation + disposable-domain blocklist.** No MX lookup in the request path (slow,
   flaky); do it async if at all.
5. **Turnstile only if 1–4 prove insufficient.** Cloudflare Turnstile is invisible for most users and
   privacy-preserving, but it is a third-party script — so it is a deliberate escalation, not a default.

### 7.7 Opt-in, and what the user experiences

**Recommend double opt-in.** Reasoning: the entire value of this list is one high-stakes email at launch;
if that email lands in spam because the list is full of typos and bot addresses, the list was pointless.
Double opt-in protects deliverability of the only send that matters, and it produces a timestamped
consent record. The cost is a confirm click, which this audience understands.

- **Form disclosure** (one dim line, always visible, not a checkbox):
  `we'll email once, when it's ready. no marketing, no sharing.` — this doubles as the §2 reassurance
  line and as the consent notice.
- **Confirmation email:** plain text, from `no-reply@auto-sec.ai`, subject `Confirm your Auto-Sec waitlist
  spot`. One sentence, one link. Include a physical postal address and an unsubscribe path (CAN-SPAM
  hygiene — cheap to include, awkward to retrofit).
- **Failure state matters.** Because the endpoint runs on the single k3s node, a node restart means a lost
  signup. Mitigate honestly: on network/5xx failure the card shows
  `couldn't reach the server — mail us at hello@auto-sec.ai` with the address selectable. No lead lost, no
  fake success.

### 7.8 Config changes required regardless of approach

- **CORS.** `api/settings/prod.py:61` sets `CORS_ALLOWED_ORIGINS` (default `https://app.auto-sec.ai`) and
  `CORS_ALLOW_CREDENTIALS = True` — which forbids a wildcard. **A POST from `https://auto-sec.ai` is
  blocked today.** Fix is config, not code: add `https://auto-sec.ai` to the comma-separated env var in
  the k8s overlay secret. CSRF is not a concern for a DRF `AllowAny` view with
  `authentication_classes = ()`.
- **Note:** `modules/cloudfront-s3-private` sets `allowed_methods = ["GET","HEAD","OPTIONS"]` on both
  behaviours, so **you cannot POST through the marketing distribution.** The cross-origin POST straight to
  `api.auto-sec.ai` sidesteps this; do not plan a same-origin `/api/waitlist` proxy without changing the
  module.
- Also worth a boy-scout fix while nearby: `requirements/base.txt` pins `boto3>=1.34.0` — an unpinned
  floor, contrary to `pin-versions.md`.

---

## 8. Accessibility & the no-scroll constraint

This section exists because **"no scroll" and "accessible" are in genuine tension**, and the honest
resolution is not the obvious one.

### 8.1 The rule: aim for one viewport, never *lock* the viewport

**`height: 100vh; overflow: hidden` on the body is not an option.** It fails two WCAG success criteria
outright:

- **1.4.4 Resize Text (AA)** — text must scale to 200% without loss of content or functionality. At 200%
  our content will exceed the viewport; if the body can't scroll, the bottom of the page (which is where
  the email field is) becomes **unreachable**. That is a straightforward failure.
- **1.4.10 Reflow (AA)** — content must reflow to a 320 CSS px viewport without requiring two-dimensional
  scrolling. Reflow doesn't forbid a page that *happens* to fit one screen; it forbids one that **clips**.

So the correct construction is:

```css
.landing {
  min-height: 100svh;   /* not height, not 100vh */
  display: grid;
  place-items: center;
}
/* body scrolls normally whenever content exceeds the viewport */
```

`min-height` + `svh` gives "one viewport on every normal screen" while degrading gracefully to a scroll
when zoom, large text, a small phone, or a landscape phone makes that impossible. **The no-scroll promise
is a design target for the common case, not a lock.** Henry's instruction is satisfied: on any ordinary
screen nothing is above or below the fold.

### 8.2 `svh` vs `dvh` vs `vh`

| Unit | Meaning | Verdict |
|---|---|---|
| `vh` | Legacy. On iOS Safari it equals the **largest** viewport (toolbars retracted), so `100vh` is *taller* than what you can see — content gets cut off under the toolbar on load. | ❌ |
| `lvh` | Largest viewport, explicitly. Same problem, named honestly. | ❌ |
| `dvh` | Dynamic — tracks the toolbar as it shows/hides. Its value **changes during scroll**, so a `100dvh` layout visibly resizes/jitters mid-gesture. | ❌ for the shell |
| **`svh`** | **Smallest** viewport (toolbars visible). Stable, and guarantees the content fits *at the worst case*. | ✅ **use this** |

`svh`/`lvh`/`dvh` are universally available in 2026 (Safari 15.4+, Chrome 108+, Firefox 101+). No fallback
needed, but `min-height: 100vh; min-height: 100svh` costs one line and is free insurance.

### 8.3 The mobile keyboard — the failure mode this page is most exposed to

Our page centres a form field in a full-viewport layout. That is precisely the combination that breaks
when the on-screen keyboard opens: the keyboard covers the bottom ~40% of the screen, and depending on
the browser either the visual viewport shrinks (the field can end up hidden behind the keyboard) or the
layout viewport does (the whole centred layout jumps).

Mitigations, in order:
1. **Do not `autofocus` at all.** *(Corrected during review — an earlier draft of this doc said
   "autofocus on desktop only". That was wrong.)* Two independent reasons:
   - **Screen readers "teleport" to the focused control without warning** (MDN). The visitor hears the
     field label and **nothing that preceded it** — our entire pitch is skipped. On a page whose whole
     job is one argument, autofocus deletes the argument for those users.
   - On touch it summons the keyboard on load, so the first frame of a single-viewport page is half
     keyboard.

   Autofocus optimises for the one visitor who had already decided, at the cost of everyone still
   deciding. Tab reaches the only input in one keystroke. **If we want the "cursor is waiting" feel**,
   render a decorative prompt caret in the input's visual position and focus the real input on first
   keypress or click — the look without the theft.
2. **`<meta name="viewport" content="width=device-width, initial-scale=1, interactive-widget=resizes-content">`**
   — makes the layout viewport shrink with the keyboard, which keeps a focused field in view. Supported in
   Chrome/Android; Safari ignores it (harmless).
3. **Do not vertically centre with `position: fixed`.** Grid `place-items: center` on a `min-height`
   container reflows correctly; a fixed overlay does not.
4. **`scroll-margin-block: 1rem`** on the input so any browser-initiated scroll-into-view leaves breathing
   room.
5. **Test on real devices** — iOS Safari and Android Chrome, keyboard open, portrait *and* landscape.
   Simulators do not reproduce this faithfully.

> ⚠️ Note this conflicts with `AuthShell`'s `fixed inset-0 … overflow-hidden`. That is exactly why §5 says
> **fork `AuthShell`, don't import it** — the landing page needs `min-height: 100svh` + normal document
> flow, not a fixed clipped overlay.

### 8.4 Small screens: a different, taller layout — say so plainly

At roughly **< 600 px of usable height** (a landscape phone, or a portrait phone at large text settings),
one viewport is not honestly achievable without shrinking type below readable size. Shrinking type to
preserve a design constraint is the wrong trade.

**The answer is a second, taller mobile layout that scrolls** — the wordmark and headline stack, the proof
block collapses to a single line, and the email field sits directly below. It will be roughly 1.3
viewports tall and that is fine. Do not try to force one screen there.

```css
@media (max-height: 600px) { /* release the single-viewport target */ }
```

The desktop and normal-portrait-phone cases — which is nearly all real traffic — remain exactly one
viewport.

### 8.5 Contrast — a real problem with our own tokens

I computed the HUD tokens against the landing backdrop `#050814`:

| Token | Hex | Ratio vs `#050814` | Verdict |
|---|---|---|---|
| `--hud-text` | `#e5e7eb` | **16.1 : 1** | ✅ excellent |
| `--hud-accent` | `#2EDBE8` | **11.8 : 1** | ✅ excellent |
| `--hud-dim` | `#6b7280` | **≈ 4.1 : 1** | ⚠️ **fails AA (4.5:1) for normal-size body text** |

**`--hud-dim` must not carry body copy on this page.** It passes the 3:1 large-text threshold (≥ 24 px, or
≥ 18.66 px bold) and the 3:1 non-text threshold (1.4.11) for borders and UI boundaries, so it is fine for
the letter-spaced uppercase labels the HUD uses it for. But the reassurance line
(`we'll email once, when it's ready.`) is small body text — render it in a lightened dim (target
`#8b93a1` or lighter, ≈ 6:1) rather than the raw token.

This is worth flagging upstream too: the HUD uses `--hud-dim` for small secondary text throughout, which
means the same AA gap likely exists in the app. Out of scope here; worth a ticket.

Also: the faint grid uses `rgba(46,219,232,0.01)`. That is decorative and below any contrast threshold by
design — correct, as long as it never carries information.

### 8.6 Motion, and the rest

- **`prefers-reduced-motion: reduce`** must disable: the `GlitchHex` RAF loop (don't just hide it — stop
  the loop), the starfield `cc-twinkle` animation, the lunar callout's spring entrance, and the
  `CalloutLine` line-draw. The callout must still *open*, instantly. Note `index.css` already guards
  `.cc-skeleton` this way — follow that precedent.
- **Keyboard:** the page must be fully operable with Tab / Enter / Esc. Focus order: input → submit →
  `what is this?`. Enter-to-submit comes free from a real `<form>` with a real `<button type="submit">`
  — do not hand-roll a keydown handler (it breaks IME composition and native validation).
- **Focus appearance is where a one-hue-on-near-black palette is genuinely at risk.** WCAG 2.2
  **SC 2.4.11 Focus Appearance (AA)** requires the indicator to be at least a 2 px perimeter and to have
  ≥3:1 contrast between focused and unfocused states. `hudInput.css` resets outlines, so this must be
  restored deliberately. Use Sara Soueidan's **"Oreo focus"** — a light ring sandwiched against dark —
  which is exactly the right technique for our palette:
  ```css
  :focus-visible {
    outline: 2px solid #050814;                       /* inner, against the surface */
    box-shadow: 0 0 0 4px rgb(var(--hud-accent));     /* outer ring, 11.8:1 */
    outline-offset: 2px;
  }
  @media (forced-colors: active) { :focus-visible { outline-color: Highlight; } }
  ```
  `:focus-visible`, never `:focus`. The `forced-colors` block matters because `box-shadow` is forced to
  `none` there, leaving the outline to carry the indicator alone.
- **Screen readers:** the ASCII/box-drawing decoration and the starfield SVG get `aria-hidden="true"`.
  The proof block is real text, not an image — keep it that way. Submission result must be announced via
  `role="status"` / `aria-live="polite"`, otherwise a non-sighted user gets no feedback that the form
  worked.
- **The form is a real `<form>`** with a real `<label>` (visually hidden is fine) — not a bare styled
  `<input>` with a click handler. Enter-to-submit then comes free.
- **No keyboard-shortcut cleverness** — and this is now a compliance point, not a taste one.
  **WCAG 2.1.4 Character Key Shortcuts (Level A)** requires any single-character shortcut to be
  disableable, remappable, or focus-scoped. The Understanding doc's worked example: a speech-input user
  with focus in the page has a coworker say *"Hey Kim"* — and `k`, `i`, `m` all fire. It states plainly
  that single-key shortcuts are *"disastrous for speech users."* A page-level `/` binding also collides
  with screen readers' own browse-mode single-letter navigation (`h` headings, `b` buttons, `f` fields).
  Note that GitHub — which popularised `/` — ships a setting to turn it off.

  A `⌘K` palette is outside 2.1.4's scope (modifier combos are exempt) but is friction dressed as
  delight on a page with one action. **The defensible version of the TUI signal is a *static,
  non-interactive* status line** — `[TAB] focus · [ENTER] submit` — which carries the idiom and **binds
  no keys at all**. Gate it on `@media (hover: hover) and (pointer: fine)` so touch users don't see dead
  weight. This is the same footer-keybinding idiom §4.0 identified as worth stealing.

---

## 9. Explicitly out of scope for v1

Naming these prevents scope creep from re-litigating them:

- **Pricing.** Not settled (`docs/product/PRICING_PACKAGING_RECOMMENDATION_2026-08-08.md` is a
  recommendation, not a decision) and pre-launch pricing invites anchoring we can't honour.
- **Feature lists, screenshots, demo video, architecture diagrams.** All require scroll. The lunar
  callout is the *entire* depth budget.
- **Logos / social proof / testimonials / "backed by".** We have none. Fabricating or padding this is
  exactly the credibility failure this audience detects instantly — and there are two cautionary
  precedents in the sample: **Escape** shipped lorem-ipsum testimonials attributed to *"Afred Smith, CTO,
  Banking App"* (typo theirs) three times over, and **Terra Security** shipped Webflow's unedited default
  share widgets, so their tweet button pointed at `webflow.com` and their footer socials at
  `facebook.com/webflowapp`. Use the §2.2b receipt instead, or nothing.
- **A signup counter, queue position, or referral mechanic.** Now evidence-backed rather than taste:
  **zero of ~20 archived dev/security pre-launch pages used one.** The only real referral loop in the
  sample (Warp) ran on Discord invite codes, not on-page. Serious tools substitute plain scarcity framing
  — *"Currently in private beta"* — for gamification, and a technical audience reads a counter as
  growth-hacking. Our `▪ PRE-LAUNCH` status line is that framing.
- **Docs, blog, changelog, careers, about.** No secondary pages. The apex is one file.
- **Light mode.** The HUD has `.hud-light`, but the landing page commits to dark. One less thing.
- **Analytics beyond CloudFront access logs** (already enabled on the frontend distribution and
  write-only into the api workload's data bucket). No GA, no Segment, no session recording — a security
  product's landing page loading third-party trackers is an own-goal, and it would also force a cookie
  banner, which would break the one-viewport rule.
- **A login link.** `app.auto-sec.ai` is where customers go; they bookmark it. A "Log in" affordance on a
  pre-launch page implies a product you can log into today. Revisit at GA.
- **i18n.**

---

## 10. Implementation checklist (for when Henry says go)

**Phase 0 — decide**
- [ ] Henry signs off on direction (B), the headline, and the CTA wording.

**Phase 1 — repo**
- [ ] Create `wanjala-dev/auto-sec-landing` (private until launch).
- [ ] Vite + React 18 + Tailwind v3. No router. No UI library.
- [ ] `src/hud/` — vendor Tier-A files + Tier-B with the named surgery (§5). Add `src/hud/README.md`
      recording upstream path + commit SHA.
- [ ] Copy the `:root` token block, `cc-twinkle`, `.cc-scrollbar`, `hudInput.css`.
- [ ] `CLAUDE.md` for the repo: the one-viewport rule, the no-scanlines rule, the bundle budget.

**Phase 2 — build**
- [ ] `LandingShell` forked from `AuthShell` (not imported).
- [ ] Card: proof block + email form + inline success state.
- [ ] Lunar callout wired to `what is this?` with `computeSideCalloutPlacement`.
- [ ] `prefers-reduced-motion`: disables GlitchHex RAF, callout spring, line-draw, starfield twinkle.
- [ ] Mobile: taller scrollable layout below the height threshold (§8).

**Phase 3 — capture** *(depends on §7)*
- [ ] Endpoint + throttle + honeypot + CORS origin.
- [ ] Confirmation email copy + double opt-in flow.
- [ ] Success / duplicate / invalid / error states all designed, not just the happy path.

**Phase 4 — infra**
- [ ] `terraform/workloads/marketing/` — two module instantiations, own state key, cert data-source,
      apex A + AAAA, access logs.
- [ ] `terraform plan` reviewed before apply. Apply after api + frontend.
- [ ] Deploy script (explicit sync + invalidation, no CD-through-Terraform).

**Phase 5 — verify**
- [ ] **Proofread gate — treat as blocking.** Two precedents in §11: Escape shipped lorem-ipsum
      testimonials, Terra shipped Webflow's default share links pointing at `webflow.com`. For a security
      vendor an unproofread detail is disproportionately damaging. Check every link target, every
      placeholder, every default string, and the page `<title>`.
- [ ] Bundle budget met (< 100 KB gz total).
- [ ] Lighthouse a11y 100; manual check at 200% zoom and 320 px width.
- [ ] Real iOS Safari + Android Chrome pass with keyboard open on the email field.
- [ ] Submit a real address end-to-end; confirm the email arrives and the confirm link works.
- [ ] Verify the endpoint rejects: no honeypot, burst rate, malformed, duplicate.

---

## 11. Sources

- `docs/product/STATE_AND_VISION.md` §1.1 (judgment-enforcement thesis, the moat sentence), §2.1 (Tom's
  positioning reframe), §2.3 / §6 (ICP + wedge).
- `auto-sec-frontend/src/components/V2/` — `AuthShell.jsx`, `SlideInHexPanel.jsx`, `CalloutLine.jsx`,
  `HudCard.jsx`, `HudText.jsx`, `StarField.jsx`, `GlitchHex.jsx`, `v2Constants.js`, `hudCanvasTheme.js`.
- `auto-sec-frontend/src/index.css:96-121` (tokens), `:478-493` (font stack).
- `auto-sec-frontend/craco.config.js`, `package.json`, `build/` (bundle sizes).
- `auto-sec-infra/terraform/README.md` (apex reserved; `workloads/marketing` follow-up #3),
  `terraform/CLAUDE.md:38`, `workloads/frontend/{main,dns}.tf`.
- `wanjala-dev/octopus` (sibling landing page — separate repo precedent, template stack counter-example).
- Backend: `api/urls.py:75`, `components/content/api/{urls,public_subscriber_controller}.py`,
  `infrastructure/persistence/content/models.py:47`,
  `components/shared_platform/application/ports/email_sending_port.py`,
  `components/identity/api/controller.py:1921` (`MagicLinkRequestView`),
  `api/settings/{base.py:428-468, prod.py:61-106}`, `infrastructure/api/throttles.py`,
  `tests/architecture/test_explicit_architecture_layout.py:37-80`.
- Infra: `auto-sec-infra/terraform/modules/cloudfront-s3-private/main.tf`,
  `workloads/api/ses.tf`, `workloads/frontend/dns.tf:14-40`, `backend.tf.example:6`.
- [rothgar/awesome-tuis](https://github.com/rothgar/awesome-tuis) and [terminal-apps.dev](https://terminal-apps.dev/) — Henry's two references, studied in §4.0.
- WCAG 2.2 success criteria **1.4.3** (Contrast Minimum), **1.4.4** (Resize Text), **1.4.10** (Reflow),
  **1.4.11** (Non-text Contrast), **2.1.4** (Character Key Shortcuts), **2.3.1** (Three Flashes),
  **2.4.11** (Focus Appearance). Contrast ratios in §8.5 computed directly from our own tokens against
  `#050814`.
- W3C Technique **H86** (ASCII art / `role="img"` + `aria-label`) — the entire authoritative corpus on
  ASCII-art accessibility. If we ever ship an ASCII wordmark: `<pre>` with explicit `white-space: pre`,
  `aria-hidden` when it duplicates visible text, and 2–3 width variants rather than scaling.
- Sara Soueidan, *A Guide to Designing Accessible, WCAG-Conformant Focus Indicators* (the "Oreo focus"
  technique used in §8.6) — cited by the W3C Understanding doc for 2.4.11.
- Adrian Roselli, *Custom Carets and Users* (2025) — why a CSS-animated caret can't be overridden by the
  OS "prefer non-blinking cursor" setting. Relevant only if we ever add a decorative cursor.
- MDN on `autofocus` (screen-reader "teleport") — the basis for the §8.3 correction.
- Oskar Wickström, *How I Built The Monospace Web* — `max-width: calc(min(80ch, round(down, 100%, 1ch)))`
  if we ever want true character-cell alignment.
- **Pre-launch page teardowns** (live Wayback snapshots, ~20 pages): Antithesis (2023, the clickable
  upstream-bug receipt), Prophet Security (named-CISO endorsement wall), Linear (2019, founder
  one-liners + `> enter your work email`), Resend (2023, one viewport, `Press A`, physical address in
  footer), Zed (manifesto homepage + 4-question waitlist + "an email every one to three months"), Warp,
  Modal, Chainguard, Wiz (2020, anonymised-but-titled quotes), RunSybil, Sourcegraph Cody
  (*"often frustratingly wrong"*), Terra Security and Escape (both cautionary).
- **Terminal-aesthetic exemplars measured live:** Dreadnode (~25% mono; the one security-adjacent
  exemplar), Ghostty (189 DOM elements, ratio 1.00, zero img/canvas/video), terminal.shop (93 elements;
  shell-comment voice + a real published host key), e2b, SST, OpenCode, pico.sh, Axiom (simulated query
  console), and Charm (the counter-example: builds TUI libraries, sells with a purple sans site).
- Evil Martians, *We studied 100 devtool landing pages* — two hero CTAs with a visually subordinate
  secondary; hand-curated testimonials. **Note: it publishes no percentages**; any numeric stat
  attributed to it elsewhere is invented.

---

## 12. Open items / decisions for Henry

- [ ] **Sign-off on Direction B**, the headline, and `NOTIFY ME` as the CTA (§2, §4).
- [ ] **Double opt-in: yes or no?** §7.7 recommends yes; it adds a confirm click. Henry's call.
- [ ] **The receipt (§2.2b) — ship it, and if so which PR?** This is the highest-leverage single line on
      the page. It means pointing prospects at a specific agent-opened draft PR in our own public repo,
      so it needs a deliberate pick (clear finding, clean patch, a good one-sentence *why* in the body).
      If Henry says no, the page falls back to no credibility signal at all — which is what Modal and
      Terra did, and they survived, but we'd be leaving our strongest card unplayed.
- [ ] **Wordmark** — reuse `ShieldLogo` + `GlitchHex` as on the login page (recommended for v1), or
      commission a dedicated apex mark?
- [ ] **`hello@auto-sec.ai`** (or similar) needs to exist for the §7.7 failure fallback.
- [ ] **Blocked on infra:** none of the Terraform is applied yet and the domain's public NS is still
      GoDaddy. **No email can send and no cert can validate until that delegation lands** — the landing
      page cannot go live before the api + frontend workloads do.
### Evidence gaps — stated honestly

So a future reader knows which claims here are sourced and which are constructed:

- **There is no conversion data for the monospace/brutalist trend.** The design commentary that
  describes it explicitly reports no conversion or usability numbers either way. Direction B is argued
  on fit, honesty and cost — not on measured lift.
- **No published critique exists of CRT effects or ASCII art on marketing pages.** The safety half of
  the no-scanlines argument (§4 Recommendation) is sourced; the aesthetic half is constructed.
- **No authoritative ruling** on whether a decorative blinking cursor triggers WCAG 2.2.2. Moot for us —
  we ship no cursor.
- The px↔cycles-per-degree mapping in the scanline discussion is arithmetic from the clinical 3 cpd
  figure, not a directly published table.
- **`--hud-dim` ≈4.1:1 and the WCAG ratios in §8.5 are computed, not measured in situ** — re-verify with
  a checker against the real rendered page, since backdrop-blur and the gradient backdrop shift the
  effective background.

- [ ] **Follow-up ticket (not this page):** `--hud-dim` at ~4.1:1 is below AA for small body text
      across the HUD generally (§8.5), and `NUM_PROXIES` being unset undermines every IP-keyed anon
      throttle in the API (§7.5). Both found while writing this doc; both are real.
