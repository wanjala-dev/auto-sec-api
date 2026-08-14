# ADR 0027 — Waitlist capture is standalone (CloudFront → Lambda → DynamoDB), not through the API

Status: accepted
Date: 2026-08-12
**Supersedes `docs/product/LANDING_PAGE_DESIGN.md` §0 decision 6 and §7.**

## Context

The pre-launch page at `auto-sec.ai` has one job: turn a technical visitor into a known
email address. `LANDING_PAGE_DESIGN.md` (2026-08-09) decided how to capture it:

> **§0 decision 6** — *"A new ~10-file `waitlist` surface in `components/shared_platform`,
> POSTed cross-origin to `api.auto-sec.ai`. **Not** the inherited newsletter machinery,
> not a third-party form service, **not a Lambda**."*

That decision was defensible when written — it reuses our throttles, our validation, our
email layer. But the same document names its own consequence three sections later:

> **§12** — *"**Blocked on infra:** none of the Terraform is applied yet and the domain's
> public NS is still GoDaddy… **the landing page cannot go live before the api + frontend
> workloads do.**"*

So the capture mechanism makes a page whose entire purpose is *pre*-launch depend on
*launching*. To collect an email we would first have to stand up k3s, deploy the API,
delegate DNS, and expose `api.auto-sec.ai`.

## Decision

**Capture the waitlist standalone**, with no dependency on the product at all:

```
CloudFront (one distribution, two origins)
  ├─ default   /*             → S3 origin (OAC)              → index.html
  └─ POST      /api/waitlist  → Lambda Function URL (OAC, IAM)
                                   └─ DynamoDB PutItem
```

### D1 — CloudFront calls the Lambda directly. No API Gateway.

A **Lambda Function URL is a CloudFront custom origin**, secured with **OAC for Lambda**
so the function URL is not publicly callable. API Gateway used to be mandatory for this
and no longer is; including it would add a service, a cost line, and a config surface for
nothing.

### D2 — DynamoDB, partition key = email.

The cheapest option is also the correct shape: a **conditional write on the PK gives
idempotent dedupe for free**, so "already signed up" needs no code. At realistic volume
(hundreds to low thousands) this is inside the permanent free tiers — Lambda's 1M
invocations/month and DynamoDB on-demand at ~$1.25 per million writes. **Effective cost:
$0.** The only standing line items are the Route53 hosted zone (~$0.50/mo) and the domain,
both already paid for.

### D3 — Reuse the existing CloudFront/S3 module; extend it with a second origin.

`cloudfront-s3-private` exists in both `octopus-infra/demo-infra/modules/` and
`auto-sec-infra`, already does OAC + `ordered_cache_behavior`, and is the pattern used for
the literacyseed/octopus front ends. Add a Lambda origin to it rather than writing a second
distribution module. No reusable Lambda or DynamoDB module exists in any of our infra repos
(only tutorial code and the Terraform state-lock table), so those are new — roughly 80 lines
of Terraform and 40 of Lambda.

### D4 — Abuse control: honeypot + conditional write now. WAF deferred, deliberately.

This is a public, unauthenticated POST on a security vendor's domain, so it needs *some*
control. v1 ships the honeypot field already specified in the landing doc §7.6 plus the
DynamoDB conditional write (which makes replay a no-op).

**AWS WAF with a rate-based rule is deliberately NOT in v1** — Henry's call, 2026-08-12.
It is ~$5/month, which is more than the entire rest of this stack, to defend a form whose
worst case is junk rows in a table nobody has yet. Recorded as a deferral, not an oversight:
**add WAF before the page is publicly announced**, because the risk changes the moment the
URL is shared. The Lambda must also cap request-body size and validate the email shape
itself — never rely on an absent edge control.

## Consequences

**Good.** The page ships today, standalone. No k3s, no API deploy, no `api.auto-sec.ai`, no
NS delegation blocking the capture path. Marketing signups stay out of the product database,
where they do not belong — a waitlist entry is not a user, and coupling the two would mean a
product migration could break a marketing form.

**Cost.** One more thing to own: a Lambda and a table outside the k8s stack. Accepted, because
the alternative costs a full product deployment before the first email can be captured.

**Migration.** When the product launches and waitlist entries become real signups, the table is
a flat list of emails and timestamps — a one-off import, not an integration.

**The design doc is now WRONG on this point** and must not be followed on capture. §0 decision 6
and §7 are superseded by this ADR. Everything else in that document — the copy, the layout, the
HUD porting rules, the accessibility constraints — still stands.

## References

- `docs/product/LANDING_PAGE_DESIGN.md` §0 decision 6, §7, §12 (the blocker that motivated this)
- `octopus-infra/demo-infra/modules/cloudfront-s3-private` — the S3+OAC pattern being reused
- Task #146 and the 2026-08-12 session: the standing lesson that a decided document goes stale
  and must be superseded explicitly, never silently contradicted by code.
