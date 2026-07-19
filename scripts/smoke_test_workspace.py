#!/usr/bin/env python3
"""
Smoke test for workspace context endpoints.
Hits every endpoint under /workspaces/ and reports pass/fail.

Usage: python3 scripts/smoke_test_workspace.py
"""

import json
import subprocess
import sys

BASE = "http://localhost:8010/workspaces"
USER_ID = "d3326a5b-57b7-425b-8a97-f084a4592632"
# Placeholder workspace — we'll try to discover a real one
WORKSPACE_ID = "1"

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


def discover_workspace():
    """Try to get a real workspace ID from the list endpoint."""
    code, resp = curl("GET", f"{BASE}/")
    if code == 200:
        try:
            data = json.loads(resp)
            results = data.get("results", data) if isinstance(data, dict) else data
            if results and isinstance(results, list):
                return str(results[0].get("id", "1"))
        except json.JSONDecodeError:
            pass
    return None


def main():
    print(f"{'='*80}")
    print(f"  WORKSPACE CONTEXT SMOKE TEST")
    print(f"{'='*80}\n")

    # Discover a real workspace ID first
    global WORKSPACE_ID
    ws_id = discover_workspace()
    if ws_id:
        WORKSPACE_ID = ws_id
        print(f"  Using workspace ID: {WORKSPACE_ID}\n")
    else:
        print(f"  WARNING: Could not discover workspace, using placeholder '{WORKSPACE_ID}'\n")

    ENDPOINTS = [
        # --- Workspace Core ---
        ("GET",  "/",                                          None, "List workspaces"),
        ("POST", "/create/",                                   {"workspace_name": "SmokeTest"}, "Create workspace"),
        ("GET",  "/can-create/",                               None, "Create eligibility"),
        ("GET",  "/category/personal/",                        None, "List by category"),
        ("GET",  "/tags/",                                     None, "List tags"),
        ("GET",  "/public/ai-privacy-brief/",                  None, "AI privacy brief"),
        ("GET",  "/public/ai-privacy-brief/contract/",         None, "AI privacy brief contract"),

        # --- Categories ---
        ("GET",  "/category/",                                 None, "Category list"),
        ("POST", "/category/",                                 {"name": "SmokeCategory"}, "Category create"),
        ("GET",  "/category/detail/1/",                        None, "Category detail"),
        ("GET",  "/categories-subcategories/",                 None, "Categories & subcategories"),

        # --- Preferences ---
        ("GET",  f"/{WORKSPACE_ID}/preferences/",             None, "Preferences by workspace"),
        ("GET",  "/preferences/",                              None, "Preferences list"),
        ("GET",  f"/{WORKSPACE_ID}/setup-status/",            None, "Setup status"),

        # --- Operations ---
        ("GET",  f"/{WORKSPACE_ID}/operations/",              None, "Operations by workspace"),
        ("GET",  "/operations/",                               None, "Operations list"),

        # --- Cards ---
        ("GET",  f"/{WORKSPACE_ID}/cards/",                   None, "Cards by workspace"),
        ("GET",  "/cards/",                                    None, "Cards list"),

        # --- Actions ---
        ("GET",  "/actions/",                                  None, "Actions list"),
        ("GET",  "/actions/1/",                                None, "Action detail"),
        ("GET",  f"/{WORKSPACE_ID}/actions/",                 None, "Actions by workspace"),

        # --- Contribution Means ---
        ("GET",  "/contribution-means/",                       None, "Contribution means list"),
        ("POST", "/assign-contribution-means/",                {"workspace": WORKSPACE_ID, "means": []}, "Assign contribution means"),
        ("GET",  f"/{WORKSPACE_ID}/contribution-means/",      None, "Contribution means by workspace"),

        # --- Follow ---
        ("POST", "/follow/",                                   {"workspace": WORKSPACE_ID}, "Follow workspace"),
        ("POST", f"/{WORKSPACE_ID}/follow/",                  {}, "Follow by workspace"),

        # --- Workspace Detail (CRUD) ---
        ("GET",  f"/{WORKSPACE_ID}/",                         None, "Workspace detail"),
        ("PATCH", f"/{WORKSPACE_ID}/",                        {"workspace_name": "Updated"}, "Workspace partial update"),

        # --- Comments ---
        ("GET",  "/comment",                                   None, "Comment list"),
        ("POST", "/comment/create",                            {"workspace": WORKSPACE_ID, "comment": "test"}, "Comment create"),
        ("GET",  "/comment/1/",                                None, "Comment detail"),
        ("GET",  f"/{WORKSPACE_ID}/comment/",                 None, "Comments by workspace"),

        # --- Aggregations ---
        ("GET",  f"/aggregations/{WORKSPACE_ID}/",            None, "Aggregations"),

        # --- Cross-context: Content/News ---
        ("GET",  "/news/",                                     None, "News list"),
        ("POST", "/news/",                                     {"title": "test", "content": "test"}, "News create"),
        ("GET",  "/news/categories/",                          None, "News categories"),

        # --- Cross-context: Payments ---
        ("GET",  "/payments/providers/",                       None, "Payment providers"),
        ("GET",  f"/payments/{WORKSPACE_ID}/methods/",        None, "Payment methods"),

        # --- Cross-context: Billing ---
        ("GET",  f"/billing/plans/",                           None, "Billing plans"),
        ("GET",  f"/billing/{WORKSPACE_ID}/overview/",        None, "Billing overview"),
        ("GET",  f"/billing/{WORKSPACE_ID}/history/",         None, "Billing history"),

        # --- Cross-context: Workflows ---
        ("GET",  f"/workflows/{WORKSPACE_ID}/workflows/",     None, "Workflow list"),
        ("GET",  f"/workflows/{WORKSPACE_ID}/workflow-templates/", None, "Workflow templates"),
    ]

    results = []
    for method, path, body, desc in ENDPOINTS:
        url = f"{BASE}{path}"
        code, resp = curl(method, url, body)

        if code == 0:
            status = "FAIL (connection error)"
        elif code >= 500:
            status = f"FAIL ({code})"
        elif code in (401, 403):
            status = f"OK   ({code} auth required)"
        elif code == 404:
            status = f"WARN ({code} not found)"
        elif code == 405:
            status = f"OK   ({code} method not allowed)"
        elif code == 429:
            status = f"OK   ({code} throttled)"
        else:
            status = f"OK   ({code})"

        is_fail = code == 0 or code >= 500
        marker = "X" if is_fail else "."
        print(f"  [{marker}] {method:6s} {path:55s} {status}")
        if is_fail:
            # Extract error from HTML response
            if '<pre class="exception_value">' in resp:
                val = resp.split('<pre class="exception_value">')[1].split('</pre>')[0]
                print(f"       >>> {val[:150]}")
            elif '<title>' in resp:
                title = resp.split('<title>')[1].split('</title>')[0].strip()
                print(f"       >>> {title}")
        results.append((method, path, desc, code, is_fail, resp))

    # Summary
    total = len(results)
    failures = [r for r in results if r[4]]
    warnings = [r for r in results if r[3] == 404]

    print(f"\n{'='*80}")
    print(f"  RESULTS: {total - len(failures)}/{total} passed, {len(failures)} failures, {len(warnings)} warnings")
    print(f"{'='*80}")

    if failures:
        print(f"\n  FAILURES:")
        for method, path, desc, code, _, resp in failures:
            print(f"    {method} {path} — {desc}")
            if '<pre class="exception_value">' in resp:
                val = resp.split('<pre class="exception_value">')[1].split('</pre>')[0]
                print(f"      Error: {val[:200]}")
            elif '<title>' in resp:
                title = resp.split('<title>')[1].split('</title>')[0].strip()
                print(f"      Error: {title}")

    if warnings:
        print(f"\n  WARNINGS (404):")
        for method, path, desc, code, _, resp in warnings:
            print(f"    {method} {path} — {desc}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
