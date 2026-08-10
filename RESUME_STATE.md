# RESUME STATE — fix/throttle-ip-trust

**Worktree:** `/Users/henrywanjala/Desktop/auto-sec/worktrees/throttle-ip-trust`
**Branch:** `fix/throttle-ip-trust` (off `origin/main` @ `ea95f14`) — pushed.
**Lane:** settings/throttling/identity-security + tests. Do NOT touch the scanning
spine or project/board code (other agents active there).
**DO NOT MERGE** — Henry authorizes merges.

Hermetic test command (unique container name, never the shared `autosec-api:local` tag):

```bash
docker run --rm --name autosec-ipTrust-$$ \
  -v /Users/henrywanjala/Desktop/auto-sec/worktrees/throttle-ip-trust:/app -w /app \
  --entrypoint python auto-sec-backend:dev -m pytest <paths> -p no:cacheprovider --no-header -q
```

---

## 1. The defect — REPRODUCED, then FIXED

`rest_framework/throttling.py::BaseThrottle.get_ident()`:

```python
num_proxies = api_settings.NUM_PROXIES
if num_proxies is not None:
    if num_proxies == 0 or xff is None:
        return remote_addr
    addrs = xff.split(',')
    return addrs[-min(num_proxies, len(addrs))].strip()
return ''.join(xff.split()) if xff else remote_addr   # <-- NUM_PROXIES unset
```

Unset → the **entire `X-Forwarded-For` header** is the throttle bucket key. Its
left-hand entries are caller-written, so rotating one mints a new bucket per
request.

**Evidence (before the fix):**

```
AssertionError: Throttle bypassed: rotating the client-supplied X-Forwarded-For
prefix produced 11 accepted requests against a 10/hour per-IP cap.
The throttle key is attacker-controlled.
assert 429 in [202, 202, 202, 202, 202, 202, ...]
```

Note `test_baseline_throttle_engages_for_an_honest_client` PASSED at the same
time — honest clients are throttled, spoofers are not. That contrast is the
whole finding.

### Test models the real deployment honestly

One proxy (NGF) sits in front and **appends**, so Django sees
`<attacker-supplied>, <real peer>`. Helper `_through_proxy(peer=, spoofed=)` in
`components/identity/tests/integration/test_throttle_ip_trust.py` builds exactly
that. Trusted hop = **rightmost**. Do not "simplify" this to a bare single-entry
XFF — that would make the test pass for the wrong reason.

---

## 2. NUM_PROXIES per environment — DERIVED, not guessed

Grounded in `auto-sec-infra` (prod overlay merged today) + its terraform.

| Environment | Value | Why |
|---|---|---|
| local k8s (Docker Desktop) | **1** | Browser → NGF data plane → ClusterIP Service → gunicorn. kube-proxy is L3/L4 (no headers). No nginx sidecar in the image — WhiteNoise serves static (`docker/scripts/prod/start-web.sh`). One appending hop. |
| prod (k3s on EC2) | **1** | `api.auto-sec.ai` → Elastic IP → k3s host → ServiceLB → the **same** NGF data plane (TLS terminates there, cert-manager) → gunicorn. **No ALB/NLB anywhere** (`grep aws_lb terraform/` = 0 hits). API is **not** behind CloudFront — only the HUD at `app.auto-sec.ai` is. |
| bare `runserver` / pytest | **1** stays correct | No XFF present → DRF falls back to `REMOTE_ADDR` on its own. Set `NUM_PROXIES=0` explicitly if gunicorn is ever exposed with no proxy. |

It is env-driven (`int(os.environ.get("NUM_PROXIES", "1"))`) in
`api/settings/base.py`, fed into `REST_FRAMEWORK["NUM_PROXIES"]`. All settings
modules `from .base import *`, so one definition covers every environment.

**Asymmetric failure directions (documented in the settings comment):**
- too **high** → DRF reads a forgeable hop → bypassable → security defect;
- too **low** → distinct clients collapse into one bucket → blunt, never bypassable.

So when in doubt, go **low**. Raising it must happen in lockstep with adding a
real proxy hop, or the new proxy's appended entry becomes forgeable padding.

### ⚠ OPEN, prod-only, must verify before go-live

k3s ServiceLB (**klipper-lb**) does DNAT **+ MASQUERADE**. Unless
`externalTrafficPolicy: Local` is set on the NGF data-plane Service (it is **not**
set anywhere in the infra repo — NGF provisions that Service itself), nginx's
`$remote_addr` will be a **node/cluster-internal address, not the real client
IP**. If so, `NUM_PROXIES=1` is still numerically correct but yields one constant
IP for every client on earth → every anon throttle collapses into a single global
bucket. Fail-safe, not exploitable, but operationally bad.

Cannot be verified from the repo, and **cannot be verified live yet**: the
GoDaddy → Route53 NS delegation is still pending, so nothing under the zone
resolves. Verify with either a `Host:`-header override against the EIP or after
delegation:

```bash
kubectl -n <ngf-ns> exec deploy/autosec-nginx -- cat /etc/nginx/conf.d/http.conf | grep -i forwarded
# then hit the API and log HTTP_X_FORWARDED_FOR / REMOTE_ADDR as seen by Django
```

If the client IP is being eaten, the lever is NGF's `NginxProxy` CRD
(`rewriteClientIP`) + PROXY protocol, or patching the NGF Service to
`externalTrafficPolicy: Local`. **Neither exists in the repo today — that is a
new infra decision, not a code change.** This is the main reason no infra PR has
been opened yet.

---

## 3. IP-derived consumers — full sweep

| Consumer | Location | Verdict |
|---|---|---|
| DRF throttles (all anon/IP-keyed) | `rest_framework.throttling` via `NUM_PROXIES` | **WAS EXPLOITABLE → FIXED** |
| Identity audit / session / login-activity IP | `components/identity/api/request_context.py::extract_client_ip` | **WAS EXPLOITABLE → FIXED.** Took `XFF.split(",")[0]` — the FIRST, caller-written hop. Any user could stamp a chosen IP onto their own session rows, login-activity entries and auth audit events. In a security product that trail is evidence; letting its subject author it makes it worthless. |
| Honeypot attempt attribution | `components/shared_platform/api/controller.py::HoneypotLoginView._client_ip` | **WAS EXPLOITABLE → FIXED.** Same first-hop bug — the scanner being fingerprinted could dictate the IP recorded about it. |
| **Account lockout** | `login_use_case.py` → `CacheLockoutAdapter` | **NOT IP-keyed — keyed by `email`** (`scope="login", identifier=email`). Not spoofable via XFF. Threshold 10, warn at 7, 30-min window (`domain/enums.py`). |
| Magic-link `request_ip` | `verify_magic_link_use_case.py` | Flows from `context.ip_address` → now fixed at the source. |
| `SECURE_PROXY_SSL_HEADER` | `api/settings/prod.py:385` | Safe — nginx **sets** (overwrites) `X-Forwarded-Proto`, unlike XFF which it appends. Still worth confirming in the same NGF config dump as the ⚠ above. |

### FINDING A — honeypot 500s on every POST (pre-existing on `main`, FIXED here)

`HoneypotLoginView._record_attempt` calls `messages.error(...)` but
`django.contrib.messages` was **never imported** → `NameError` escapes the view.
Its own test `test_post_records_attempt` is **already RED on `origin/main`** —
verified by stashing this branch's changes and re-running:

```
E  NameError: name 'messages' is not defined
1 failed, 1 passed
```

Impact: a real Django admin returns **200** with a login-failed message; ours
returned **500**, instantly fingerprinting the decoy to any scanner — the exact
opposite of a honeypot's job, on a surface about to go internet-facing. Attempts
*were* still captured (the row is written before the raise); only the response
broke. Fixed with the missing import.

### FINDING B — login has NO per-IP ceiling (NOT yet fixed — decided, not built)

`LoginThrottle` extends `_ScopedIdentityThrottle`, whose `_identity()` returns
`email:<x>` whenever an email is in the body and only falls back to `ip:` when
there is none. And `LoginAPIView` sets `throttle_classes = [LoginThrottle]`,
which **replaces** `DEFAULT_THROTTLE_CLASSES` entirely — so the global
`AnonRateThrottle` (200/min) does not apply either.

Net: **password spraying / credential stuffing is unthrottled** — rotate the
email each request and every attempt lands in its own bucket, from one host.

The repo already ships the correct remedy one endpoint over:
`/identity/resend-verification/` stacks `ResendVerificationEmailThrottle` **and**
`ResendVerificationIPThrottle`. Login should mirror it.

Planned fix (per `dry-reuse.md` "when adding the Nth, re-examine the 1st"):
extract a `_ScopedIPThrottle` base and have **both** `ResendVerificationIPThrottle`
and a new `LoginIPThrottle` use it, rather than copy-pasting `get_cache_key`.
Proposed rate `30/min` per IP — generous enough for a 30-person office behind one
NAT, caps spray at 30/min/IP instead of unlimited.

### FINDING C — hardcoded `rate` makes `DEFAULT_THROTTLE_RATES` dead config

Every class in `components/identity/api/throttles.py` sets **both** `scope` and a
hardcoded `rate` (e.g. `LoginThrottle.rate = "10/min"`).
`SimpleRateThrottle.__init__` does `if not getattr(self, 'rate', None): self.rate = self.get_rate()`
— so the class attribute **wins** and the settings lookup never runs.

Consequences:
1. `DEFAULT_THROTTLE_RATES["auth_login"]`, `auth_password_reset_*`,
   `auth_email_verify` in `base.py` are **dead config** — they look authoritative
   and change nothing.
2. `local.py`'s dev-relief block (`auth_login: 1000/min`, etc.) carries a comment
   explaining it relaxes those caps for the QA E2E suite. **It does nothing.**

Not exploitable — the class rates in force are the *tighter* ones. Reported, not
fixed, because it is a separate concern (rate-configuration plumbing, not IP
trust) and the honest fix touches every identity throttle: drop the hardcoded
`rate`s and add the missing scopes (`auth_resend_verification`,
`auth_resend_verification_ip`, `auth_magic_link_*`, `otp_verify`,
`otp_static_verify`) to `DEFAULT_THROTTLE_RATES`, or `get_rate()` raises
`ImproperlyConfigured`.

Note for whoever builds Finding B: give `LoginIPThrottle` a `scope` and a
settings entry and do **not** hardcode `rate` — cargo-culting the broken sibling
would deepen Finding C (`improve-dont-replicate.md`).

---

## 4. What is DONE (committed + pushed)

- `api/settings/base.py` — `NUM_PROXIES` env-driven, default 1, with the
  per-environment derivation and asymmetric-failure rationale in comments.
- `infrastructure/api/client_ip.py` (**new**) — canonical `trusted_client_ip()`.
  Mirrors DRF's rule; treats unset `NUM_PROXIES` as `0` so misconfiguration
  degrades to blunt-but-honest, never attacker-chosen.
- `components/identity/api/request_context.py` — delegates to it.
- `components/shared_platform/api/controller.py` — honeypot `_client_ip`
  delegates to it, **plus** the missing `from django.contrib import messages`
  (Finding A).
- `components/identity/tests/integration/test_throttle_ip_trust.py` (**new**) —
  5 tests: `NUM_PROXIES` is configured; baseline throttle engages; rotating
  spoofed XFF does not evade; long forged hop chain does not evade; distinct real
  peers keep separate buckets (guards against over-correcting into one global
  bucket).
- `components/identity/tests/integration/test_user_sessions.py` — the XFF
  assertion was **updated, not bent**: it explicitly asserted the FIRST hop, i.e.
  it encoded the vulnerable behaviour. Now asserts the trusted rightmost hop plus
  an explicit `!= forged` assertion. Module docstring updated.

**Last verified run** (`test_throttle_ip_trust.py` + `test_honeypot_views.py` +
`test_user_sessions.py` + `test_session_enrichment.py`): all throttle tests green
after the fix. The 2 failures in that run were the honeypot `NameError`
(Finding A) and the old first-hop session assertion — **both since fixed**, but
the confirming re-run had not been executed when the session ended.

---

## 5. NEXT STEPS, in order

1. **Re-run the suite** and confirm green (nothing has been run since the
   honeypot import + session-test edits):
   ```
   components/identity/tests/integration/test_throttle_ip_trust.py
   components/identity/tests/integration/test_honeypot_views.py
   components/identity/tests/integration/test_user_sessions.py
   components/identity/tests/integration/test_session_enrichment.py
   components/identity/tests/integration/test_resend_verification.py
   tests/architecture/
   ```
   `tests/architecture/` matters: `components/shared_platform/api/controller.py`
   gained an `infrastructure.api.*` import. There is precedent —
   `components/content/api/public_subscriber_controller.py` already imports
   `infrastructure.api.throttles` — but confirm, don't assume.
2. **Control-proving tests still owed** (standing task #123, scoped to this lane):
   - **Throttles:** anon covered; still need a **per-user** (`UserRateThrottle`)
     test, and one asserting two different authenticated users get separate
     buckets.
   - **Account lockout:** unit tests of the pure policy exist
     (`tests/unit/test_auth_lockout_policy.py`) but **nothing proves the login
     endpoint enforces it**. Add an integration test: 10 bad passwords → locked,
     correct password still refused, warn fires at 7, success clears the counter.
     Note it is email-keyed, so an attacker can lock a known account (DoS
     trade-off) — assert current behaviour and call it out.
   - **OTP policy:** `test_otp_verification.py` only covers token claims; add
     wrong-code rejection, the `OTPVerifyThrottle` (10/min) and
     `StaticVerifyThrottle` (5/min) caps, and single-use static recovery codes.
   - **Honeypot:** add a spoof-resistance case (forged XFF prefix must not become
     the recorded `ip_address`) and assert the response is a **200 decoy**, not a
     500 — the regression guard for Finding A.
3. **Decide Finding B** — build `_ScopedIPThrottle` + `LoginIPThrottle`, or defer.
4. **Prod env contract / infra PR** — add `NUM_PROXIES` to the prod ConfigMap and
   document the klipper-lb verification step. Exact files:
   - `auto-sec-infra/k8s/bases/api/configmap.yaml` (style: `KEY: "value"`)
   - `auto-sec-infra/k8s/overlays/prod/kustomization.yaml` `configMapGenerator`
     `behavior: merge` literals (style: `KEY=value`)
   - **Not** `secrets/env.prod.example` — `NUM_PROXIES` is non-secret.
   Because the code default is already the correct `1` for both environments,
   this is documentation-of-contract, not a functional change — which is why it
   can be a follow-up rather than a blocker.
5. **Open the API PR** (`gh pr create --base main`) leading with the reproduction
   evidence and Findings A/B/C. **DO NOT MERGE.**

## Conventions in play

- No `Co-Authored-By` on autosec commits.
- Formatter trap: add usages **first**, imports **last**, then grep-verify.
- Never build/run the shared `autosec-api:local` tag; unique `--name` per
  throwaway container.
