# GitHub App registration — dev runbook (ADR 0010 D6 / Phase B)

The one-time operator action that turns the app-mode VCS integration on: register the
**Auto-Sec GitHub App** under the `wanjala-dev` org from the manifest in this directory,
then land the returned credentials in the deployment env. Everything else (install flow,
short-lived installation tokens, webhook revocation sync) is already in the codebase behind
`feature.vcs_github_app`.

> **Prod registration WAITS for a public API URL.** The manifest needs a publicly reachable
> `setup_url` + webhook `url`; `autosec.local` is not reachable from GitHub. Register the
> DEV app now (webhook deliveries will simply fail to reach a local cluster — the install +
> token path still works because it is outbound), and register a separate PROD app once the
> API has its public base URL. One app per environment is GitHub's own recommendation —
> webhook URL and secret are per-app.

## What the manifest asks for (and why)

`github-app-manifest.json`, fields that matter:

| Field | Value | Why |
|---|---|---|
| `default_permissions.contents` | `write` | create branches + commit the one-file fix |
| `default_permissions.pull_requests` | `write` | open the draft PR |
| `default_permissions.metadata` | `read` | mandatory baseline for any repo access |
| `default_events` | `pull_request` | closed+merged PRs accelerate the remediation reconciler |
| `hook_attributes.url` | `<api-base>/integrations/vcs/github-app/webhook/` | the receiver (HMAC-gated, not flag-gated) |
| `setup_url` + `setup_on_update` | `<api-base>/integrations/vcs/github-app/setup/` | GitHub sends the installing browser here with `installation_id` + our signed `state` |
| `redirect_url` | a localhost placeholder | only used ONCE, during this registration, to hand you the `?code=` (step 3) |

`installation` and `installation_repositories` events are **not** in `default_events` on
purpose: GitHub always delivers app-lifecycle events to an app's webhook — they cannot and
need not be subscribed.

Before step 2, replace `REPLACE-WITH-API-BASE` in the manifest with the API base URL for the
environment you are registering (dev can keep a placeholder — the webhook/setup URLs can be
edited later in the app's settings page).

## The click-path (all three steps within ONE HOUR)

1. **Open the manifest-create form.** GitHub takes the manifest as a POSTed form field, so
   save this as `/tmp/autosec-app-manifest.html`, paste the JSON from
   `github-app-manifest.json` between the textarea tags, open the file in a browser, and
   click the button:

   ```html
   <form action="https://github.com/organizations/wanjala-dev/settings/apps/new" method="post">
     <textarea name="manifest" rows="20" cols="80">PASTE github-app-manifest.json HERE</textarea>
     <br><button type="submit">Create Auto-Sec GitHub App</button>
   </form>
   ```

2. **Click "Create GitHub App"** on the GitHub confirmation page (you can rename it there;
   the slug is derived from the name).

3. **Copy the `?code=` from the redirect.** GitHub bounces the browser to the manifest's
   `redirect_url` (`http://localhost:8765/...` — the page will fail to load; that is fine).
   Copy the `code` query parameter out of the address bar. It is single-use and expires
   with the 1-hour window.

4. **Convert the code into credentials** (one curl, no auth needed):

   ```bash
   curl -X POST -H "Accept: application/vnd.github+json" \
     https://api.github.com/app-manifests/<code>/conversions
   ```

   The response is the app's one-time credential dump — treat it like a secret and do not
   paste it into anything that persists:

   | Response field | Lands in | Notes |
   |---|---|---|
   | `id` | `GITHUB_APP_ID` | numeric app id (`client_id` also works as the JWT issuer) |
   | `slug` | `GITHUB_APP_SLUG` | builds the install URL; not a secret |
   | `pem` | `GITHUB_APP_PRIVATE_KEY` | the WHOLE PEM. As a k8s single-line value, `\n`-escaped is fine — the auth adapter normalizes |
   | `webhook_secret` | `GITHUB_APP_WEBHOOK_SECRET` | HMAC key for `X-Hub-Signature-256` |
   | `client_id` / `client_secret` | not needed yet | only for user-access-token attribution (explicit follow-on, not built) |

5. **Land the values in the deployment.** These are env vars read by
   `api/settings/base.py` (api + celery-worker deployments). In the local cluster they
   belong in the `auto-sec-infra` overlay's secret env (the same file that carries
   `TENANT_DATABASE_URLS` etc.), never in a committed manifest:

   ```
   GITHUB_APP_ID=…
   GITHUB_APP_SLUG=…
   GITHUB_APP_PRIVATE_KEY=…      # \n-escaped single line is OK
   GITHUB_APP_WEBHOOK_SECRET=…
   ```

   Then re-apply + `kubectl -n autosec rollout restart deploy/api deploy/celery-worker`.

6. **Turn the feature on** for the workspace(s) that should see the install button —
   `feature.vcs_github_app` is seeded OFF:

   ```bash
   kubectl exec -n autosec deploy/api -- python manage.py shell -c "
   from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
   flag = FeatureFlag.objects.get(key='feature.vcs_github_app')
   FeatureFlagRule.objects.update_or_create(flag=flag, scope=FeatureFlagRule.Scope.GLOBAL, defaults={'enabled': True, 'note': 'dev enable'})
   from components.shared_platform.infrastructure.services.feature_flags import bump_feature_flags_version; bump_feature_flags_version()"
   ```

## Smoke check

```bash
# 1. Install URL (as a workspace owner, flag on):
POST /integrations/workspaces/<ws>/vcs/github-app/install/  ->  {"data": {"install_url": "https://github.com/apps/<slug>/installations/new?state=..."}}
# 2. Open it, install on a repo, land back on /integrations/vcs/github-app/setup/ -> redirected to the HUD.
# 3. The workspace now has a VcsConnection with auth_mode=github_app + installation_id; add repos to its
#    repo_allowlist (the consent boundary is still the allowlist), verify, and open a draft PR — authored by <slug>[bot].
```
