#!/usr/bin/env python3
"""
Toggl Track CLI — measured time entries for SR&ED (and general) work.

This is the *measured* companion to `sred_hours.py`: that tool re-derives a DRAFT hours
log from git commit timestamps (an estimate); this one logs ACTUAL start/stop time to
Toggl Track as you work. Real measured hours are the stronger contemporaneous record for
a founder-salary SR&ED basis (CRA wants true hours, not inferred ones).

SR&ED rule of thumb baked in here:
  • Pass a SEE-<n> ticket  → entry lands in a Toggl project named after the ticket and is
    tagged `sred` + `repo:<backend|frontend>`. Only these count toward the R&D salary basis.
  • Omit the ticket        → entry lands in the general project (TOGGL_GENERAL_PROJECT,
    default "Ops / General"), NO `sred` tag. Routine work stays OUT of the claim — by design.
  • You start/stop manually, so every logged hour is a real founder hour with no day-job
    overlap. (We deliberately do NOT auto-log agent wall-clock — that isn't your time.)

Auth: HTTP Basic with `<API_TOKEN>:api_token` (Toggl v9). Token + workspace come from env:
  export TOGGL_API_TOKEN=...                # required (Profile → API token in Toggl)
  export TOGGL_WORKSPACE_ID=...             # optional; auto-detected from /me if unset
  export TOGGL_GENERAL_PROJECT="Ops / General"   # optional; project for non-SEE work

Usage:
  toggl whoami                               # verify auth, print account + workspace
  toggl start SEE-169 grounded retrieval     # start a running R&D timer for SEE-169
  toggl start grounded retrieval             # ticket auto-detected from the git branch (feat/SEE-169-…)
  toggl start fix the deploy script          # general timer (non-SR&ED) on a non-SEE branch
  toggl status                               # show the currently-running entry (if any)
  toggl stop                                 # stop the running entry, print elapsed
  toggl report --since 2026-01-01 --until 2026-12-31 --rate 75   # measured hours by SEE ticket + git cross-check
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

SEE_RE = re.compile(r"SEE-\d+", re.I)

API = "https://api.track.toggl.com/api/v9"
REPORTS = "https://api.track.toggl.com/reports/api/v3"
LINEAR_API = "https://api.linear.app/graphql"
LINEAR_MARKER = "<!-- toggl-sync -->"  # identifies our self-updating comment so re-runs update, not duplicate
CREATED_WITH = "sred-toggl-cli"


def _die(msg: str, code: int = 1):
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _token() -> str:
    tok = os.environ.get("TOGGL_API_TOKEN")
    if not tok:
        _die("TOGGL_API_TOKEN is not set. Add `export TOGGL_API_TOKEN=...` to your shell "
             "(Toggl → Profile → API token), then re-run.")
    return tok


def _auth_header() -> str:
    raw = f"{_token()}:api_token".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _request_full(method: str, path: str, body: dict | None = None):
    url = path if path.startswith("http") else f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", _auth_header())
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read().decode().strip()
            return (json.loads(payload) if payload else None), resp.headers
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace").strip()
        if e.code == 403:
            _die("auth failed (403) — check TOGGL_API_TOKEN is correct.")
        _die(f"Toggl API {method} {url} → {e.code}: {detail}")
    except urllib.error.URLError as e:
        _die(f"network error reaching Toggl: {e.reason}")


def _request(method: str, path: str, body: dict | None = None):
    return _request_full(method, path, body)[0]


def _workspace_id(me: dict | None = None) -> int:
    env_ws = os.environ.get("TOGGL_WORKSPACE_ID")
    if env_ws:
        return int(env_ws)
    me = me or _request("GET", "/me")
    ws = me.get("default_workspace_id")
    if not ws:
        _die("could not determine workspace; set TOGGL_WORKSPACE_ID.")
    return int(ws)


def _repo_tag() -> str | None:
    cwd = os.getcwd()
    if "literacyseed" in cwd:
        return "repo:frontend"
    if "api-v2.0" in cwd or "wanjala-api" in cwd:
        return "repo:backend"
    return None


def _current_branch() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, cwd=os.getcwd())
    except (FileNotFoundError, OSError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _branch_ticket() -> str | None:
    """SEE-<n> parsed from the current git branch (e.g. feat/SEE-169-grounded-content)."""
    m = SEE_RE.search(_current_branch())
    return m.group(0).upper() if m else None


def _slug_desc(branch: str, ticket: str) -> str:
    """Human description from a branch slug: 'feat/SEE-169-grounded-content' → 'grounded content'.
    Empty when the branch doesn't belong to this ticket, so we never mislabel an entry."""
    if not branch or ticket.lower() not in branch.lower():
        return ""
    slug = branch.split("/", 1)[1] if "/" in branch else branch
    slug = re.sub(re.escape(ticket), "", slug, flags=re.I)
    return " ".join(w for w in slug.replace("-", " ").replace("_", " ").split() if w)


def _find_or_create_project(ws: int, name: str) -> int:
    projects = _request("GET", f"/workspaces/{ws}/projects") or []
    for p in projects:
        if p.get("name") == name:
            return int(p["id"])
    created = _request("POST", f"/workspaces/{ws}/projects",
                       {"name": name, "active": True, "is_private": True})
    print(f"  + created Toggl project {name!r}")
    return int(created["id"])


def _fmt_elapsed(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_whoami(_args):
    me = _request("GET", "/me")
    ws = _workspace_id(me)
    print(f"authenticated as {me.get('fullname') or me.get('email')} <{me.get('email')}>")
    print(f"workspace_id={ws}  timezone={me.get('timezone')}")


def cmd_start(args):
    words = list(args.rest)
    ticket = None
    from_branch = False
    if words and words[0].upper().startswith("SEE-") and words[0][4:].isdigit():
        ticket = words.pop(0).upper()
    description = " ".join(words).strip()
    if not description:
        _die('a description is required, e.g. `toggl start SEE-169 grounded retrieval`')

    if not ticket:
        ticket = _branch_ticket()
        from_branch = ticket is not None

    ws = _workspace_id()

    existing = _request("GET", "/me/time_entries/current")
    if existing:
        _die(f"a timer is already running ({existing.get('description')!r}); "
             f"run `toggl stop` first.")

    tags: list[str] = []
    if ticket:
        project = ticket
        tags.append("sred")
    else:
        project = os.environ.get("TOGGL_GENERAL_PROJECT", "Ops / General")
    repo = _repo_tag()
    if repo:
        tags.append(repo)
    if os.environ.get("TOGGL_AUTO") == "1":
        tags.append("auto")  # hook-started — session wall-clock, review/trim before claiming
        if ticket:
            tags.append(ticket)  # lets auto-start detect which ticket a running timer is for

    project_id = _find_or_create_project(ws, project)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    entry = _request("POST", f"/workspaces/{ws}/time_entries", {
        "created_with": CREATED_WITH,
        "description": description,
        "project_id": project_id,
        "tags": tags,
        "start": now.isoformat().replace("+00:00", "Z"),
        "duration": -1,  # negative ⇒ running
        "workspace_id": ws,
    })
    sred = "  [SR&ED]" if ticket else ""
    origin = "  (ticket from branch)" if from_branch else ""
    print(f"  ▶ running… project={project} "
          f"tags={','.join(tags) or '—'}  id={entry['id']}{sred}{origin}")


def cmd_status(_args):
    entry = _request("GET", "/me/time_entries/current")
    if not entry:
        print("  ⏸ no timer running")
        return
    start = datetime.fromisoformat(entry["start"].replace("Z", "+00:00"))
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    tags = ",".join(entry.get("tags") or []) or "—"
    print(f"  ▶ {entry.get('description')!r}  ({_fmt_elapsed(elapsed)} so far)")
    print(f"    tags={tags}  since {start.astimezone():%Y-%m-%d %H:%M}")


def cmd_stop(_args):
    entry = _request("GET", "/me/time_entries/current")
    if not entry:
        _die("no timer is running.")
    ws = entry.get("workspace_id") or _workspace_id()
    stopped = _request("PATCH", f"/workspaces/{ws}/time_entries/{entry['id']}/stop")
    dur = stopped.get("duration", 0) if stopped else 0
    print(f"  ⏹ {_fmt_elapsed(dur)} logged to Toggl — {entry.get('description')!r}")


MAX_AUTO_HOURS = 6.0  # a running `auto` timer older than this is a dangling one — cap it, don't compound


def _log_breadcrumb(msg: str):
    """Best-effort note so a silently-skipped auto-track isn't invisible. See `toggl doctor`."""
    try:
        with open(os.path.expanduser("~/.toggl_auto.log"), "a") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M} {msg}\n")
    except OSError:
        pass


def _running_ticket(entry) -> str | None:
    return next((t for t in (entry.get("tags") or []) if SEE_RE.fullmatch(t)), None)


def cmd_auto_start(args):
    """Hook entrypoint: ensure a timer runs for the current/named SEE task. No-op off SEE work."""
    ticket = getattr(args, "ticket", None) or _branch_ticket()
    if not ticket:
        return  # not on / not creating a SEE branch → nothing to track
    ticket = ticket.upper()
    if not os.environ.get("TOGGL_API_TOKEN"):
        _log_breadcrumb(f"auto-start skipped for {ticket}: TOGGL_API_TOKEN not in hook env")
        return
    cur = _request("GET", "/me/time_entries/current")
    if cur:
        if "auto" not in (cur.get("tags") or []):
            return  # a manually-started timer is running — never clobber it
        start = datetime.fromisoformat(cur["start"].replace("Z", "+00:00"))
        age_h = (datetime.now(timezone.utc) - start).total_seconds() / 3600
        ws = cur.get("workspace_id") or _workspace_id()
        if age_h >= MAX_AUTO_HOURS:
            # dangling (SessionEnd never fired). DELETE it — don't fabricate hours of not-working.
            _request("DELETE", f"/workspaces/{ws}/time_entries/{cur['id']}")
            _log_breadcrumb(f"deleted dangling auto timer ({age_h:.1f}h) before starting {ticket}")
        elif _running_ticket(cur) == ticket:
            return  # already tracking this exact ticket — leave it running
        else:
            # switching tickets mid-session — stop (log) the old one, then start the new
            _request("PATCH", f"/workspaces/{ws}/time_entries/{cur['id']}/stop")
    branch = getattr(args, "branch", None) or _current_branch()
    desc = _slug_desc(branch, ticket) or "auto-tracked session"
    os.environ["TOGGL_AUTO"] = "1"
    cmd_start(argparse.Namespace(rest=[ticket, *desc.split()]))


def cmd_auto_stop(_args):
    """Hook entrypoint: stop a running `auto` timer. Leaves manually-started timers untouched."""
    if not os.environ.get("TOGGL_API_TOKEN"):
        return
    cur = _request("GET", "/me/time_entries/current")
    if not cur or "auto" not in (cur.get("tags") or []):
        return
    ws = cur.get("workspace_id") or _workspace_id()
    _request("PATCH", f"/workspaces/{ws}/time_entries/{cur['id']}/stop")


def cmd_doctor(_args):
    """Diagnose whether auto-tracking will actually work right now."""
    tok = os.environ.get("TOGGL_API_TOKEN")
    print(f"TOGGL_API_TOKEN: {'set' if tok else 'NOT SET'}")
    if not tok:
        print("  → hooks will silently no-op. Export it where you launch Claude Code, then re-check.")
        return
    me = _request("GET", "/me")
    print(f"auth: OK as {me.get('email')}  workspace_id={_workspace_id(me)}")
    bt = _branch_ticket()
    print(f"branch ticket: {bt.upper() if bt else '(none — non-SEE branch; would not auto-track)'}")
    cur = _request("GET", "/me/time_entries/current")
    print(f"running timer: {cur.get('description')!r} tags={cur.get('tags')}" if cur else "running timer: none")
    log = os.path.expanduser("~/.toggl_auto.log")
    if os.path.exists(log):
        print(f"breadcrumbs: {log} (auto-track skips / dangling-timer deletions are logged here)")


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        _die(f"bad date {s!r}; use YYYY-MM-DD.")


def _report_search(ws: int, since: date, until: date) -> list:
    """Detailed time-entry rows from the Reports API v3 — serves arbitrary history (the v9
    /me/time_entries endpoint only goes back ~3 months). Chunked ≤1yr, paginated."""
    rows, span = [], timedelta(days=366)
    cur = since
    while cur <= until:
        chunk_end = min(cur + span - timedelta(days=1), until)
        first_row = None
        while True:
            body = {"start_date": cur.isoformat(), "end_date": chunk_end.isoformat(),
                    "page_size": 1000}
            if first_row:
                body["first_row_number"] = first_row
            data, headers = _request_full(
                "POST", f"{REPORTS}/workspace/{ws}/search/time_entries", body)
            rows.extend(data or [])
            nxt = headers.get("X-Next-Row-Number")
            if not nxt:
                break
            first_row = int(nxt)
        cur = chunk_end + timedelta(days=1)
    return rows


def _git_estimate(since: date, until: date):
    """(total, by_ticket) SEE-mapped hours from sred_hours.py for the same range."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import sred_hours  # noqa: PLC0415 — sibling tool, intentional lazy import
    except ImportError:
        return None, None
    total, by_ticket = 0.0, defaultdict(float)
    for path in sred_hours.REPOS.values():
        commits = sred_hours.git_commits(path, since.isoformat(), until.isoformat())
        for s in sred_hours.sessionize(commits):
            if not s["tickets"]:
                continue
            total += s["hours"]
            for t in s["tickets"]:
                by_ticket[t.upper()] += s["hours"] / len(s["tickets"])
    return total, by_ticket


def _measured_by_ticket(ws: int, since: date, until: date):
    """(total_hours, sred_hours, {project_name: sred_hours}) from Toggl over the range."""
    projects = _request("GET", f"/workspaces/{ws}/projects?active=both") or []
    pid_name = {int(p["id"]): p["name"] for p in projects}
    tags = _request("GET", f"/workspaces/{ws}/tags") or []
    sred_tag_id = next((int(t["id"]) for t in tags if t.get("name") == "sred"), None)
    total = sred_total = 0.0
    by_ticket = defaultdict(float)
    for row in _report_search(ws, since, until):
        secs = sum(te.get("seconds", 0) for te in row.get("time_entries", []) if te.get("seconds", 0) > 0)
        hrs = secs / 3600
        total += hrs
        if sred_tag_id is not None and sred_tag_id in (row.get("tag_ids") or []):
            sred_total += hrs
            by_ticket[pid_name.get(row.get("project_id"), "(no project)")] += hrs
    return total, sred_total, by_ticket


def cmd_report(args):
    ws = _workspace_id()
    today = datetime.now().date()
    since = _parse_date(args.since) if args.since else date(today.year, 1, 1)
    until = _parse_date(args.until) if args.until else today

    total, sred_total, by_ticket = _measured_by_ticket(ws, since, until)

    print("# Toggl measured hours (SR&ED)")
    print(f"_Range {since} … {until}. MEASURED from Toggl start/stop entries. "
          f"Review before any claim; hours must not overlap day-job hours._\n")
    print(f"- **Total measured hours:** {total:.1f}")
    print(f"- **SR&ED (sred-tagged) hours:** {sred_total:.1f}")
    print(f"- **Non-SR&ED (routine) hours:** {total - sred_total:.1f}")
    if args.rate:
        print(f"- **Illustrative SR&ED salary basis @ ${args.rate:.0f}/hr:** ${sred_total * args.rate:,.0f} "
              f"(before reasonableness / specified-employee cap — accountant sizes)")

    if by_ticket:
        print("\n## SR&ED hours by SEE ticket (measured)")
        for t, h in sorted(by_ticket.items(), key=lambda kv: -kv[1]):
            print(f"- {t}: {h:.1f}h")

    est_total, est_by_ticket = _git_estimate(since, until)
    if est_total is not None:
        print("\n## Cross-check vs git estimate (sred_hours.py)")
        print(f"- Measured SR&ED: **{sred_total:.1f}h**  ·  git-estimate (SEE-mapped): **{est_total:.1f}h**")
        diff = sred_total - est_total
        verdict = "aligned" if abs(diff) < 0.5 else ("measured higher" if diff > 0 else "estimate higher")
        print(f"- Drift: **{diff:+.1f}h** ({verdict})")
        gaps = sorted(set(est_by_ticket) - set(by_ticket))
        if gaps:
            print(f"- Tickets with git commits but **no measured time** (likely un-timed): {', '.join(gaps)}")


def _linear_request(query: str, variables: dict) -> dict:
    key = os.environ.get("LINEAR_API_KEY")
    if not key:
        _die("LINEAR_API_KEY not set — create a personal API key at linear.app/settings/api and export it.")
    data = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(LINEAR_API, data=data, method="POST")
    req.add_header("Authorization", key)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        _die(f"Linear API {e.code}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        _die(f"network error reaching Linear: {e.reason}")
    if payload.get("errors"):
        _die(f"Linear GraphQL error: {payload['errors']}")
    return payload["data"]


def cmd_sync_linear(args):
    """Upsert a 'Toggl measured time' comment onto each SEE ticket. Dry-run unless --commit."""
    ws = _workspace_id()
    today = datetime.now().date()
    since = _parse_date(args.since) if args.since else date(today.year, 1, 1)
    until = _parse_date(args.until) if args.until else today
    _, _, by_ticket = _measured_by_ticket(ws, since, until)
    tickets = {k: v for k, v in by_ticket.items() if SEE_RE.fullmatch(k)}
    if not tickets:
        print("no SEE-ticketed measured hours in range — nothing to sync.")
        return

    q_find = ("query($num:Float!){issues(filter:{number:{eq:$num},team:{key:{eq:\"SEE\"}}})"
              "{nodes{id identifier comments{nodes{id body}}}}}")
    m_create = "mutation($i:String!,$b:String!){commentCreate(input:{issueId:$i,body:$b}){success}}"
    m_update = "mutation($id:String!,$b:String!){commentUpdate(id:$id,input:{body:$b}){success}}"

    print("# Toggl → Linear hours sync " + ("(COMMIT)" if args.commit else "(DRY-RUN — nothing posted)"))
    print(f"_Range {since} … {until}. Posts measured `sred` hours per ticket; review/trim before any claim._\n")
    synced = 0
    for ticket, hrs in sorted(tickets.items(), key=lambda kv: -kv[1]):
        line = f"- {ticket}: {hrs:.1f}h"
        if not args.commit:
            print(f"{line}  (dry-run)")
            continue
        num = float(ticket.split("-")[1])
        nodes = _linear_request(q_find, {"num": num})["issues"]["nodes"]
        if not nodes:
            print(f"{line}  — ticket not found, skipped")
            continue
        issue = nodes[0]
        body = (f"**⏱ Toggl measured time** (auto-synced)\n\n"
                f"- Measured R&D hours: **{hrs:.1f}h** (as of {today})\n"
                f"- Source: Toggl Track `sred`-tagged entries — a DRAFT; review/trim before any SR&ED claim.\n\n"
                f"{LINEAR_MARKER}")
        existing = next((c for c in issue["comments"]["nodes"] if LINEAR_MARKER in (c.get("body") or "")), None)
        if existing:
            _linear_request(m_update, {"id": existing["id"], "b": body})
            print(f"{line}  — updated")
        else:
            _linear_request(m_create, {"i": issue["id"], "b": body})
            print(f"{line}  — created")
        synced += 1

    print(f"\n✅ synced {synced} ticket(s) to Linear." if args.commit
          else "\nRun with `--commit` to post these to Linear (needs LINEAR_API_KEY).")


MAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sred_pr_ticket_map.json")


def _repo_paths() -> dict:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import sred_hours
        return dict(sred_hours.REPOS)
    except ImportError:
        return {}


def _pr_commit_time(repo_path: str, pr: str):
    """Real merge-commit timestamp for a squash-merged PR (subject contains '(#<pr>)')."""
    try:
        out = subprocess.run(
            ["git", "-C", repo_path, "log", "-1", "-F", f"--grep=(#{pr})", "--pretty=%cI"],
            capture_output=True, text=True)
    except (FileNotFoundError, OSError):
        return None
    line = out.stdout.strip()
    if out.returncode != 0 or not line:
        return None
    try:
        return datetime.fromisoformat(line)
    except ValueError:
        return None


def _cluster_hours(items, gap_min=90, warmup_min=30, floor_min=30):
    """Assign each item an 'hours' share: cluster by ≤gap into sessions, split session time."""
    items = sorted(items, key=lambda x: x["ts"])
    sessions, cur = [], []
    for it in items:
        if cur and (it["ts"] - cur[-1]["ts"]) > timedelta(minutes=gap_min):
            sessions.append(cur)
            cur = []
        cur.append(it)
    if cur:
        sessions.append(cur)
    for s in sessions:
        span = (s[-1]["ts"] - s[0]["ts"]).total_seconds() / 60
        per = max(span + warmup_min, floor_min) / len(s)
        for it in s:
            it["hours"] = round(per / 60, 2)
    return items


DEFAULT_SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sred_backfill_sheet.csv")
SHEET_COLS = ["date", "ticket", "pr", "repo", "eligibility", "milestone", "title", "floor_hint_h", "hours"]


def _resolve_items():
    """Each non-excluded PR → real merge timestamp + a clustering floor hint. Sorted by date."""
    if not os.path.exists(MAP_FILE):
        _die(f"map not found: {MAP_FILE} — (re)generate it from Linear first.")
    pr_map = json.load(open(MAP_FILE))
    repos = _repo_paths()
    if not repos:
        _die("could not resolve repo paths (sred_hours.py REPOS).")
    by_repo = defaultdict(list)
    skipped_excluded = no_commit = 0
    for pr, meta in pr_map.items():
        if meta.get("eligibility") == "excluded":
            skipped_excluded += 1
            continue
        ts = _pr_commit_time(repos.get(meta.get("repo", "backend"), ""), pr)
        if ts is None:
            no_commit += 1
            continue
        by_repo[meta.get("repo", "backend")].append({"ts": ts, "pr": pr, **meta})
    items = []
    for lst in by_repo.values():
        items.extend(_cluster_hours(lst))  # only for the floor_hint column
    items.sort(key=lambda x: x["ts"])
    return items, skipped_excluded, no_commit


def cmd_backfill(args):
    import csv
    if args.write_sheet is not None:
        path = args.write_sheet or DEFAULT_SHEET
        items, exc, nc = _resolve_items()
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(SHEET_COLS)
            for it in items:
                w.writerow([f"{it['ts']:%Y-%m-%d}", it["ticket"], f"#{it['pr']}", it["repo"],
                            it["eligibility"], it.get("milestone", ""), it.get("title", ""),
                            f"{it['hours']:.2f}", ""])
        print(f"wrote {len(items)} rows → {path}")
        print(f"(skipped {exc} excluded as non-R&D, {nc} with no matching git commit)")
        print("\nFill the **hours** column with your REAL hours (floor_hint_h is just a lower-bound "
              "reference from commit spacing — your real time is higher). Leave a row's hours blank to "
              "skip it. Then:\n  toggl backfill --from-sheet              # dry-run preview\n"
              "  toggl backfill --from-sheet --commit     # write to Toggl")
        return

    if args.from_sheet is None:
        _die("use --write-sheet to generate the review sheet, or --from-sheet to load your filled one.")

    path = args.from_sheet or DEFAULT_SHEET
    if not os.path.exists(path):
        _die(f"sheet not found: {path} — run `toggl backfill --write-sheet` first.")
    pr_map = json.load(open(MAP_FILE))
    repos = _repo_paths()
    rows = list(csv.DictReader(open(path)))

    entries, blank = [], 0
    for r in rows:
        hv = (r.get("hours") or "").strip()
        if not hv:
            blank += 1
            continue
        try:
            hrs = float(hv)
        except ValueError:
            _die(f"bad hours {hv!r} for {r.get('pr')} — must be a number.")
        if hrs <= 0:
            continue
        pr = (r.get("pr") or "").lstrip("#")
        repo = r.get("repo") or pr_map.get(pr, {}).get("repo", "backend")
        ts = _pr_commit_time(repos.get(repo, ""), pr)
        if ts is None:  # fall back to merge date @ 20:00 local (evening — clean of day job)
            ts = datetime.strptime(r["date"], "%Y-%m-%d").replace(hour=20, tzinfo=timezone.utc)
        entries.append({"ts": ts, "pr": pr, "repo": repo, "hours": hrs,
                        "ticket": r.get("ticket", ""), "title": r.get("title", ""),
                        "eligibility": r.get("eligibility", "")})
    if not entries:
        _die(f"no rows with hours filled in {path} ({blank} blank). Fill the hours column first.")
    entries.sort(key=lambda e: e["ts"])

    ws = _workspace_id()
    existing_prs = set()
    if args.commit:
        for row in _report_search(ws, entries[0]["ts"].date(), entries[-1]["ts"].date()):
            d = row.get("description") or ""
            if d.startswith("#"):
                existing_prs.add(d.split()[0])

    print("# Toggl SR&ED backfill " + ("(COMMIT)" if args.commit else "(DRY-RUN — nothing written)"))
    print("_Dates = real PR merge timestamps. Hours = YOUR reviewed numbers from the sheet. "
          "Tagged `backfilled`. Consultant + accountant gate any claim._\n")
    print("| Date | Ticket | PR | Hrs | Elig | Title |")
    print("|---|---|---|---|---|---|")
    total, written, skipped_dup = 0.0, 0, 0
    for e in entries:
        marker = f"#{e['pr']}"
        if args.commit and marker in existing_prs:
            skipped_dup += 1
            continue
        total += e["hours"]
        print(f"| {e['ts']:%Y-%m-%d} | {e['ticket']} | {marker} | {e['hours']:.2f} | "
              f"{e['eligibility']} | {(e['title'] or '')[:48]} |")
        if args.commit:
            pid = _find_or_create_project(ws, e["ticket"] or "SR&ED (unmapped)")
            _request("POST", f"/workspaces/{ws}/time_entries", {
                "created_with": CREATED_WITH,
                "description": f"{marker} {e['title']}".strip(),
                "project_id": pid,
                "tags": ["sred", "backfilled", f"repo:{e['repo']}"],
                "start": e["ts"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "duration": int(round(e["hours"] * 3600)),
                "workspace_id": ws,
            })
            written += 1

    print(f"\n- **Entries:** {len(entries)}  ·  **total hours:** {total:.1f}  ·  **blank rows skipped:** {blank}")
    if args.commit and skipped_dup:
        print(f"- **Already in Toggl (skipped):** {skipped_dup}")
    if args.rate:
        print(f"- **Illustrative basis @ ${args.rate:.0f}/hr:** ${total * args.rate:,.0f} "
              f"(consultant + accountant gate)")
    if args.commit:
        print(f"\n✅ wrote {written} entries to Toggl (tagged `backfilled`).")
    else:
        print("\nRun with `--commit` to write these to Toggl.")


def main():
    ap = argparse.ArgumentParser(prog="toggl", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("whoami", help="verify auth + print account/workspace")
    p_start = sub.add_parser("start", help="start a running timer")
    p_start.add_argument("rest", nargs=argparse.REMAINDER,
                         help="[SEE-<n>] <description words…>")
    sub.add_parser("status", help="show the running timer, if any")
    sub.add_parser("stop", help="stop the running timer")
    p_report = sub.add_parser("report", help="measured hours by SEE ticket + git cross-check")
    p_report.add_argument("--since", help="YYYY-MM-DD (default: Jan 1 this year)")
    p_report.add_argument("--until", help="YYYY-MM-DD (default: today)")
    p_report.add_argument("--rate", type=float, help="$/hr for an illustrative salary basis")
    p_backfill = sub.add_parser("backfill",
                                help="past work → Toggl via a review sheet (you fill real hours)")
    p_backfill.add_argument("--write-sheet", nargs="?", const="", default=None,
                            metavar="PATH", help="generate the review CSV (default path if PATH omitted)")
    p_backfill.add_argument("--from-sheet", nargs="?", const="", default=None,
                            metavar="PATH", help="load your filled CSV → Toggl")
    p_backfill.add_argument("--commit", action="store_true", help="actually write entries (default: dry-run)")
    p_backfill.add_argument("--rate", type=float, help="$/hr for an illustrative basis")
    p_auto = sub.add_parser("auto-start", help="hook: start a timer for the current/named SEE task")
    p_auto.add_argument("--ticket", help="SEE-<n> (else derived from the git branch)")
    p_auto.add_argument("--branch", help="branch name for the description (when not the current branch)")
    sub.add_parser("auto-stop", help="hook: stop a running auto timer (no-op otherwise)")
    sub.add_parser("doctor", help="check whether auto-tracking will work (token, auth, branch)")
    p_sync = sub.add_parser("sync-linear", help="post measured hours per SEE ticket as a Linear comment")
    p_sync.add_argument("--since", help="YYYY-MM-DD (default: Jan 1 this year)")
    p_sync.add_argument("--until", help="YYYY-MM-DD (default: today)")
    p_sync.add_argument("--commit", action="store_true", help="actually post (default: dry-run)")

    args = ap.parse_args()
    {"whoami": cmd_whoami, "start": cmd_start, "status": cmd_status, "stop": cmd_stop,
     "report": cmd_report, "backfill": cmd_backfill, "doctor": cmd_doctor, "sync-linear": cmd_sync_linear,
     "auto-start": cmd_auto_start, "auto-stop": cmd_auto_stop}[args.command](args)


if __name__ == "__main__":
    main()
