#!/usr/bin/env python3
"""
Smoke test for ALL bounded contexts.
Hits every endpoint and reports pass/fail by context.

Usage: python3 scripts/smoke_test_all.py
"""

import json
import subprocess
import sys

BASE = "http://localhost:8010"
USER_ID = "d3326a5b-57b7-425b-8a97-f084a4592632"
FAKE_UUID = "00000000-0000-0000-0000-000000000001"

def curl(method, url, body=None):
    cmd = ["curl", "-s", "-o", "/tmp/smoke_resp.txt", "-w", "%{http_code}",
           "-X", method, url,
           "-H", "Content-Type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        status_code = int(result.stdout.strip())
        with open("/tmp/smoke_resp.txt") as f:
            resp = f.read()[:500]
        return status_code, resp
    except Exception as e:
        return 0, str(e)


def extract_error(resp):
    if '<pre class="exception_value">' in resp:
        val = resp.split('<pre class="exception_value">')[1].split('</pre>')[0]
        return val[:200].replace("&#x27;", "'").replace("&quot;", '"')
    if '<title>' in resp:
        return resp.split('<title>')[1].split('</title>')[0].strip()
    return resp[:150]


CONTEXTS = {
    # ── TEAM ──
    "team": [
        ("GET",  "/team/",                                      None, "Create team (GET form)"),
        ("POST", "/team/",                                      {"workspace": FAKE_UUID, "team_name": "smoke"}, "Create team"),
        ("POST", "/team/activate/",                              {}, "Activate"),
        ("GET",  "/team/1/team",                                 None, "Team by ID"),
        ("GET",  f"/team/{FAKE_UUID}/",                          None, "Team by UUID"),
        ("GET",  f"/team/workspaces/{FAKE_UUID}/teams/",         None, "Teams by workspace"),
        ("POST", "/team/stripe/webhook/",                        {}, "Stripe webhook"),
    ],

    # ── MEMBERSHIP ──
    "membership": [
        ("GET",  "/membership/members/",                         None, "Team members"),
        ("GET",  "/membership/invitations/pending/",             None, "Pending invitations"),
        ("POST", "/membership/invitations/",                     {"email": "t@t.com"}, "Invite"),
        ("POST", "/membership/invitations/accept/",              {"token": "fake"}, "Accept invite"),
    ],

    # ── BUDGETING ──
    "budgeting": [
        ("GET",  "/budget/",                                     None, "Budget list"),
        ("POST", "/budget/add/",                                 {"name": "test"}, "Budget create"),
        ("GET",  f"/budget/{FAKE_UUID}",                         None, "Budget by workspace"),
        ("GET",  "/budget/detail/1",                             None, "Budget detail"),
        ("GET",  f"/budget/dashboard/{FAKE_UUID}/",              None, "Dashboard"),
        ("GET",  f"/budget/history/{FAKE_UUID}/",                None, "History"),
        ("GET",  "/budget/imports/",                              None, "Imports list"),
        ("GET",  "/budget/imports/1/",                            None, "Import detail"),
        ("GET",  "/budget/imports/1/rows/",                       None, "Import rows"),
        ("GET",  "/budget/1/standard-budget/",                    None, "Standard budget list"),
        ("GET",  "/budget/1/beneficiaries/",                      None, "Beneficiary summary"),
        ("PATCH", "/budget/1/status/",                            {"status": "active"}, "Status update"),
        ("GET",  f"/budget/summary/{FAKE_UUID}/",                None, "Summary"),
        ("GET",  f"/budget/estimate/{FAKE_UUID}/",               None, "Estimate list"),
        ("GET",  f"/budget/category/{FAKE_UUID}",                None, "Category list"),
        ("GET",  "/budget/category/detail/1/",                    None, "Category detail"),
        ("GET",  "/budget/category/chart_data/",                  None, "Chart data"),
        ("GET",  f"/budget/transaction/{FAKE_UUID}",             None, "Transaction list"),
        ("GET",  "/budget/transaction/1/",                        None, "Transaction detail"),
        ("GET",  f"/budget/transaction/income/{FAKE_UUID}",      None, "Income transactions"),
        ("GET",  f"/budget/transaction/expense/{FAKE_UUID}",     None, "Expense transactions"),
    ],

    # ── SPONSORSHIP ──
    "sponsorship": [
        ("GET",  f"/sponsorship/communications/teams/{FAKE_UUID}/channels/", None, "Comm channels"),
        ("POST", "/sponsorship/donations/payments/ingest/",       {}, "Payment ingest"),
        ("POST", "/sponsorship/donations/donate/",                {}, "Donate"),
        ("GET",  f"/sponsorship/donations/{FAKE_UUID}/",         None, "Donations by workspace"),
        ("POST", "/sponsorship/sponsor/",                         {}, "Sponsor checkout"),
        ("GET",  f"/sponsorship/ledger/recipients/{FAKE_UUID}/{FAKE_UUID}/balance/", None, "Ledger balance"),
        ("GET",  "/sponsorship/recipients/",                      None, "Recipients list"),
        ("GET",  "/sponsorship/recipients/update/",               None, "Recipient updates"),
        ("GET",  "/sponsorship/recipients/update/tags/",          None, "Recipient update tags"),
        ("GET",  f"/sponsorship/recipients/{FAKE_UUID}/",        None, "Recipients by workspace"),
        ("GET",  f"/sponsorship/recipients/{FAKE_UUID}/categories/", None, "Recipient categories"),
    ],

    # ── GRANTS ──
    "grants": [
        ("GET",  f"/grants/workspaces/{FAKE_UUID}/",             None, "Grants list"),
        ("POST", f"/grants/workspaces/{FAKE_UUID}/",             {"title": "smoke"}, "Grant create"),
        ("GET",  f"/grants/{FAKE_UUID}/",                        None, "Grant detail"),
    ],

    # ── CAMPAIGNS ──
    "campaigns": [
        ("GET",  "/campaigns/",                                   None, "Campaign list"),
        ("POST", "/campaigns/",                                   {"name": "test"}, "Campaign create"),
        ("GET",  f"/campaigns/meta/{FAKE_UUID}/",                None, "Campaign meta"),
        ("GET",  f"/campaigns/{FAKE_UUID}/",                     None, "Campaign detail"),
        ("POST", "/campaigns/checkout/",                          {}, "Campaign checkout"),
    ],

    # ── EVENTS ──
    "events": [
        ("GET",  f"/events/workspaces/{FAKE_UUID}/",             None, "Events list"),
        ("GET",  f"/events/{FAKE_UUID}/",                        None, "Event detail"),
    ],

    # ── PROJECT ──
    "project": [
        ("GET",  "/project/",                                     None, "Projects list"),
        ("POST", "/project/",                                     {"name": "smoke"}, "Project create"),
        ("GET",  "/project/updates/",                              None, "Project updates"),
        ("GET",  "/project/milestones/",                           None, "Milestones"),
        ("GET",  "/project/columns/",                              None, "Columns"),
        ("GET",  f"/project/workspaces/{FAKE_UUID}/",             None, "Projects by workspace"),
        ("GET",  f"/project/user/{USER_ID}/",                     None, "Projects by user"),
        ("POST", "/project/tasks/timer/start_timer/",              {}, "Start timer"),
        ("POST", "/project/tasks/timer/stop_timer/",               {}, "Stop timer"),
        ("POST", "/project/tasks/timer/discard_timer/",            {}, "Discard timer"),
        ("GET",  "/project/tasks/1/comments/",                     None, "Task comments"),
    ],

    # ── SOCIAL ──
    "social": [
        ("GET",  "/social/",                                      None, "Social list"),
        ("POST", "/social/",                                      {"content": "test"}, "Social create"),
        ("GET",  "/social/comment/",                               None, "Comments list"),
        ("POST", "/social/comment/",                               {"content": "test"}, "Comment create"),
        ("GET",  "/social/tag/",                                   None, "Tags list"),
        ("POST", "/social/tag/",                                   {"name": "test"}, "Tag create"),
        ("GET",  "/social/message/",                               None, "Messages list"),
        ("GET",  "/social/thread/",                                None, "Threads list"),
    ],

    # ── NOTIFICATIONS ──
    "notifications": [
        ("GET",  "/notifications/",                                None, "Notifications list"),
        ("POST", "/notifications/mark-all-read/",                  {}, "Mark all read"),
        ("GET",  "/notifications/unread-count/",                   None, "Unread count"),
        ("GET",  "/notifications/preferences/workspaces/",         None, "Workspace prefs"),
        ("GET",  "/notifications/preferences/ai/",                 None, "AI prefs"),
    ],

    # ── REPORTS ──
    "reports": [
        ("GET",  "/reports/financial-reports/",                    None, "Financial reports"),
        ("GET",  "/reports/financial-report-requests/",            None, "Report requests"),
        ("GET",  "/reports/dispatches/",                           None, "Dispatches"),
    ],

    # ── SEARCH ──
    "search": [
        ("GET",  "/search/suggest/",                               None, "Suggest"),
        ("GET",  "/search/news/",                                  None, "News search"),
        ("GET",  "/search/user/",                                  None, "User search"),
        ("GET",  "/search/category/",                              None, "Category search"),
        ("GET",  "/search/aggregate/",                             None, "Aggregate search"),
        ("POST", "/search/advanced/",                              {"query": "test"}, "Advanced search"),
    ],

    # ── LANDING / SHARED PLATFORM ──
    "landing": [
        ("GET",  "/landing/",                                      None, "Landing list"),
        ("GET",  "/landing/newsletters/",                          None, "Newsletters"),
        ("GET",  "/landing/subscribers/",                          None, "Subscribers"),
        ("GET",  "/landing/testimonial/",                          None, "Testimonials"),
        ("GET",  "/landing/contact/sendemail/",                    None, "Contact emails"),
        ("GET",  "/landing/theme/",                                None, "Theme"),
    ],

    # ── COMMERCE ──
    "commerce": [
        ("GET",  "/shop/",                                         None, "Shop list"),
        ("GET",  "/cart/",                                         None, "Cart"),
        ("POST", "/payment/checkout/",                             {}, "Payment checkout"),
    ],

    # ── AI / AGENTS ──
    "agents": [
        ("GET",  "/ai/health/health/",                             None, "AI health"),
        ("GET",  "/ai/health/status/",                             None, "AI status"),
        ("GET",  "/ai/health/test/",                               None, "AI test"),
        ("GET",  "/ai/llms/providers/",                            None, "LLM providers"),
        ("GET",  "/ai/llms/available-models/",                     None, "Available models"),
        ("GET",  "/ai/embeddings/providers/",                      None, "Embedding providers"),
        ("GET",  "/ai/actions/",                                   None, "AI actions"),
    ],

    # ── KNOWLEDGE ──
    "knowledge": [
        ("GET",  "/ai/knowledge/vector-stores/providers/",         None, "Vector store providers"),
    ],

    # ── FEATURE FLAGS / CORE ──
    "core": [
        ("GET",  "/feature-flags/",                                None, "Feature flags list"),
        ("GET",  f"/feature-flags/{FAKE_UUID}/",                  None, "Feature flag detail"),
    ],

    # ── COUNTRIES / SECTORS ──
    "shared": [
        ("GET",  "/countries/",                                    None, "Countries list"),
        ("GET",  "/sectors/",                                      None, "Sectors list"),
    ],

    # ── UPLOADS ──
    "uploads": [
        ("GET",  "/upload/",                                       None, "Upload list"),
    ],

    # ── ANNOUNCEMENTS ──
    "announcements": [
        ("GET",  "/announcements/banners/",                        None, "Banners list"),
    ],
}


def main():
    print(f"{'='*90}")
    print(f"  FULL API SMOKE TEST — ALL CONTEXTS")
    print(f"{'='*90}\n")

    all_results = []
    context_summaries = []

    for context_name, endpoints in CONTEXTS.items():
        print(f"\n  ── {context_name.upper()} {'─' * (70 - len(context_name))}")
        ctx_failures = 0
        ctx_total = len(endpoints)

        for method, path, body, desc in endpoints:
            url = f"{BASE}{path}"
            code, resp = curl(method, url, body)

            if code == 0:
                stat = "FAIL (connection error)"
            elif code >= 500:
                stat = f"FAIL ({code})"
            elif code in (401, 403):
                stat = f"OK   ({code} auth)"
            elif code == 404:
                stat = f"OK   ({code} not found)"
            elif code == 405:
                stat = f"OK   ({code} method)"
            elif code == 429:
                stat = f"OK   ({code} throttle)"
            else:
                stat = f"OK   ({code})"

            is_fail = code == 0 or code >= 500
            marker = "X" if is_fail else "."
            print(f"    [{marker}] {method:6s} {path:60s} {stat}")
            if is_fail:
                ctx_failures += 1
                err = extract_error(resp)
                print(f"         >>> {err}")

            all_results.append((context_name, method, path, desc, code, is_fail, resp))

        passed = ctx_total - ctx_failures
        context_summaries.append((context_name, passed, ctx_total, ctx_failures))

    # Final summary
    total = len(all_results)
    total_failures = sum(1 for r in all_results if r[5])

    print(f"\n{'='*90}")
    print(f"  SUMMARY BY CONTEXT")
    print(f"{'='*90}")
    for name, passed, tot, fails in context_summaries:
        status = "PASS" if fails == 0 else "FAIL"
        print(f"    [{status:4s}] {name:20s} {passed}/{tot}")

    print(f"\n{'='*90}")
    print(f"  TOTAL: {total - total_failures}/{total} passed, {total_failures} failures")
    print(f"{'='*90}")

    if total_failures:
        print(f"\n  ALL FAILURES:")
        for ctx, method, path, desc, code, is_fail, resp in all_results:
            if is_fail:
                err = extract_error(resp)
                print(f"    [{ctx}] {method} {path}")
                print(f"      {err}")

    return 1 if total_failures else 0


if __name__ == "__main__":
    sys.exit(main())
