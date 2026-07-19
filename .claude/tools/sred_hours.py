#!/usr/bin/env python3
"""
SR&ED hours-log generator — derives a *draft* contemporaneous time log from git history.

Your commit timestamps already prove WHEN you worked (evenings/weekends). This clusters
them into work sessions, estimates hours, maps sessions to SEE-<n> Linear tickets (via the
`Linear: SEE-<n>` commit trailer or a `feat/SEE-<n>-…` branch name baked into the message),
flags evening/weekend work, and totals by ticket and fiscal year.

IMPORTANT — this is an ESTIMATE and a DRAFT, not a filed timesheet:
  • Session hours are inferred from commit spacing + a warm-up allowance; design/thinking
    time between/around commits is approximate. REVIEW and adjust to reality before any claim.
  • A salary claim must reflect ACTUAL hours at a reasonable rate, and must NOT overlap your
    day-job hours. This tool gives a defensible starting basis the consultant can work from.
  • NOT tax advice. Consultant + accountant gate the claim.

Usage:
  python3 .claude/tools/sred_hours.py                 # both repos, all history, summary
  python3 .claude/tools/sred_hours.py --since 2026-01-01 --until 2026-12-31   # a fiscal year
  python3 .claude/tools/sred_hours.py --detail        # per-session table too
  python3 .claude/tools/sred_hours.py --rate 75       # also print a $ salary basis at $/hr
"""
import argparse
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta

REPOS = {
    "backend": "/Users/henrywanjala/Desktop/wanjala-api-v2.0/api-v2.0",
    "frontend": "/Users/henrywanjala/Desktop/frontend/literacyseed",
}
# Whose commits count as the founder's R&D labour (substring match on "Name <email>").
AUTHOR_PATTERNS = ("wanjala-dev", "c0d3henry", "henry")

SESSION_GAP_MIN = 90      # gap > this starts a new work session
WARMUP_MIN = 30           # added per session for work before the first commit
MIN_SESSION_MIN = 30      # floor for a lone-commit session
SEE_RE = re.compile(r"SEE-\d+", re.I)


def git_commits(repo: str, since: str | None, until: str | None):
    fmt = "%H%x1f%an <%ae>%x1f%cI%x1f%s%x1f%b%x1e"
    cmd = ["git", "-C", repo, "log", f"--pretty=format:{fmt}", "--no-merges"]
    if since:
        cmd.append(f"--since={since}")
    if until:
        cmd.append(f"--until={until} 23:59:59")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    rows = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split("\x1f")
        if len(parts) < 4:
            continue
        sha, author, iso, subject = parts[0], parts[1], parts[2], parts[3]
        body = parts[4] if len(parts) > 4 else ""
        if not any(p.lower() in author.lower() for p in AUTHOR_PATTERNS):
            continue
        try:
            ts = datetime.fromisoformat(iso)
        except ValueError:
            continue
        tickets = sorted(set(SEE_RE.findall(subject + " " + body)))
        rows.append({"ts": ts, "subject": subject, "tickets": tickets})
    return rows


def sessionize(commits):
    commits = sorted(commits, key=lambda c: c["ts"])
    sessions, cur = [], []
    for c in commits:
        if cur and (c["ts"] - cur[-1]["ts"]) > timedelta(minutes=SESSION_GAP_MIN):
            sessions.append(cur)
            cur = []
        cur.append(c)
    if cur:
        sessions.append(cur)
    out = []
    for s in sessions:
        start, end = s[0]["ts"], s[-1]["ts"]
        span = (end - start).total_seconds() / 60
        mins = max(span + WARMUP_MIN, MIN_SESSION_MIN)
        tickets = sorted({t for c in s for t in c["tickets"]})
        weekend = start.weekday() >= 5
        evening = start.hour >= 18 or start.hour < 9
        out.append({
            "start": start, "end": end, "hours": round(mins / 60, 2),
            "commits": len(s), "tickets": tickets,
            "off_hours": weekend or evening,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--rate", type=float, help="$/hr to print an illustrative salary basis")
    args = ap.parse_args()

    all_sessions = []
    for name, path in REPOS.items():
        for s in sessionize(git_commits(path, args.since, args.until)):
            s["repo"] = name
            all_sessions.append(s)
    all_sessions.sort(key=lambda s: s["start"])

    print("# SR&ED hours log (DRAFT — derived from git; review before any claim)")
    rng = f"{args.since or 'start'} … {args.until or 'now'}"
    print(f"_Range: {rng}. Estimate from commit timestamps + {WARMUP_MIN}min warm-up; "
          f"sessions split on >{SESSION_GAP_MIN}min gaps. NOT a filed timesheet; NOT tax advice._\n")

    total = sum(s["hours"] for s in all_sessions)
    off = sum(s["hours"] for s in all_sessions if s["off_hours"])
    by_ticket = defaultdict(float)
    unmapped = 0.0
    for s in all_sessions:
        if s["tickets"]:
            for t in s["tickets"]:
                by_ticket[t.upper()] += s["hours"] / len(s["tickets"])
        else:
            unmapped += s["hours"]

    print(f"- **Total estimated R&D hours:** {total:.1f}")
    print(f"- **Evening/weekend (around-a-day-job) hours:** {off:.1f} "
          f"({(off/total*100 if total else 0):.0f}%)")
    print(f"- **Sessions:** {len(all_sessions)}")
    print(f"- **Hours mapped to SEE tickets:** {sum(by_ticket.values()):.1f}; "
          f"**unmapped (pre-convention commits):** {unmapped:.1f}")
    if args.rate:
        print(f"- **Illustrative salary basis @ ${args.rate:.0f}/hr:** "
              f"${total*args.rate:,.0f} (before reasonableness/specified-employee cap — accountant sizes)")

    if by_ticket:
        print("\n## Hours by SEE ticket (mapped)")
        for t, h in sorted(by_ticket.items(), key=lambda kv: -kv[1]):
            print(f"- {t}: {h:.1f}h")

    if args.detail:
        print("\n## Sessions")
        print("| Date | Start–End | Hrs | Repo | Off-hrs | Tickets | Commits |")
        print("|---|---|---|---|---|---|---|")
        for s in all_sessions:
            print(f"| {s['start']:%Y-%m-%d} | {s['start']:%H:%M}–{s['end']:%H:%M} | "
                  f"{s['hours']:.2f} | {s['repo']} | {'✓' if s['off_hours'] else ''} | "
                  f"{', '.join(s['tickets']) or '—'} | {s['commits']} |")


if __name__ == "__main__":
    main()
