# RESUME STATE — brand accent contrast guard (backend)

Branch `fix/brand-accent-contrast` in `worktrees/brand-contrast-api`.
Paired frontend worktree: `worktrees/brand-contrast-fe`, same branch name.

**Delete this file before opening the PR** — it is a session handoff, not repo content.

## The defect

Per-workspace branding injected the customer's raw brand colour straight into
`--hud-accent`. Nothing guaranteed it was legible on OUR canvas. Reproduced live
in the browser on the seeded test workspace (brand `#345700`): the label
`AGENTS` rendered at **1.87:1** on `#04263a` — an accent-tinted card fill, not
the bare canvas. Every design partner brands their workspace, so a dark brand
makes their own HUD illegible and reads as our bug.

## Seam chosen: BACKEND (the derivation), not the frontend injection

Verified against the code, not assumed:
- `components/workspace/domain/services/brand_resolution_service.py` already
  owns brand derivation and already had `WcagContrastPolicy` — but its guarantee
  is "what text can sit ON the brand fill" (`primary` + `primary-foreground`).
  The unguarded question was the inverse: "can the brand read as text on our
  canvas?" That is the same *kind* of policy, so it belongs beside it.
- `ColorSpacePort` + `WcagContrastPolicy` are the one canonical colour-maths
  home. Deriving in the frontend would fork it.
- Every consumer of `BrandResolutionPort` inherits the safe value; the API can
  no longer emit an unusable accent.

## What is DONE and green

Backend is complete. `302 passed, 3 xfailed` — `components/workspace/tests/`
plus `tests/architecture/`, run hermetically:

```
docker run --rm --name autosec-brandcontrast-$$ -v "$PWD:/app" -w /app \
  -e DJANGO_SETTINGS_MODULE=api.settings.test --entrypoint python \
  autosec-api:local -m pytest components/workspace/tests/ tests/architecture/ -q
```

Files:
- `domain/value_objects/ui_surface_palette.py` (new) — the real HUD surfaces per
  theme, mirroring `src/index.css`, plus the accent-tint alpha.
- `domain/services/ui_accent_derivation_service.py` (new) — the guard.
- `domain/policies/wcag_contrast_policy.py` — added `worst_contrast()`.
- `application/ports/color_space_port.py` + `infrastructure/adapters/
  pure_python_color_space_adapter.py` — added `blend()` and `lightness()`.
- `application/use_cases/resolve_workspace_brand_use_case.py` — emits the
  additive top-level `ui_accent` key (`None` when unbranded).
- `application/providers/brand_resolution_provider.py` — wiring.
- `tests/unit/test_ui_accent_derivation.py` (new, 64 cases) +
  `tests/integration/test_public_brand_endpoint.py` (contract + e2e guarantee).

### The algorithm (one paragraph)

For each theme, keep the seed's hue and saturation and move only its lightness —
up on the dark canvas, down on the light canvas — in 2% steps until the colour
clears its bar against the worst surface that theme paints it on: the canvas,
the two panel surfaces, and the accent-tinted card fill, which is recomputed at
every step because it is itself derived from the accent. Two bars, two roles:
`text` clears WCAG AA 4.5:1 (accent-coloured text and meaningful state);
`decorative` clears the 1.4.11 non-text 3:1 bar and stays much closer to the raw
brand (borders, fills, glow). A colour that already passes is returned untouched.

### Measured (backend, worst surface incl. tint)

| seed | theme | before | text after | decorative after |
|---|---|---|---|---|
| `#345700` | dark | 2.10:1 | `#5E9D00` 4.94:1 | `#467500` 3.10:1 |
| `#345700` | light | 5.99:1 | unchanged | unchanged |
| `#000000` | dark | 1.07:1 | `#878787` 4.57:1 | `#696969` 3.11:1 |
| `#FFFFFF` | light | 1.07:1 | `#5F5F5F` 4.67:1 | `#7D7D7D` 3.10:1 |
| `#808080` | light | 2.98:1 | `#5D5D5D` 4.82:1 | `#7B7B7B` 3.19:1 |
| `#39FF14` | light | 1.10:1 | `#0F6900` 4.98:1 | `#159100` 3.07:1 |
| `#1E3A8A` | dark | 1.71:1 | `#6285DC` 4.63:1 | `#3A65D2` 3.21:1 |
| `#2EDBE8` | light | 1.35:1 | `#0D6A73` 4.58:1 | `#118C97` 3.02:1 |

Sanity signal: autosec's own cyan derives to `#0D6A73` on light, within a
hair of the hand-tuned `#0b636b` fe#175 landed independently.

## What is LEFT

1. Light-theme + red-team live re-measure in the browser (dark before/after is
   done and reproduced 1.87:1 → see the FE worktree's RESUME_STATE).
2. Pathological brand colours on a **throwaway** workspace (not the demo's —
   the demo workspace's branding is `brand_seed='#345700'`, `secondary_seed=''`,
   `mode='light'`, `logo_url=''` and has NOT been modified; leave it that way).
3. Screenshots to `/Users/henrywanjala/Desktop/auto-sec/_session-artifacts-2026-08-08/`.
4. Open the PR. **DO NOT MERGE.**

## Local test rig (both worktrees)

- Throwaway API container `autosec-brand-api` on host `:8901`, this worktree
  bind-mounted, pointed at the cluster's Postgres/Redis through
  `kubectl -n autosec port-forward svc/postgres 55432:5432` and
  `svc/redis 56379:6379`. The shared `autosec-api:local` deployment is NOT
  touched — other agents are on that cluster.
- FE dev server from the FE worktree on `:3021` (Henry's review server is
  `:3015` — never touch it). Kill by path+port when done.
- Login: `test@autosec.local` / `AutoSecTest2026!`,
  ws `cc287133-b53c-43c8-9000-2873f8c8a1e3`. Real login, never a forged token.
