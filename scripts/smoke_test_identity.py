#!/usr/bin/env python3
"""
Smoke test for identity context endpoints.
Hits every endpoint under /identity/ and reports pass/fail.

A "pass" means the server responded (no 500/connection error).
Expected 401/403 for auth-required endpoints is fine — it means the view resolved.
A 500 or connection error means something is broken.

Usage: python3 scripts/smoke_test_identity.py
"""

import json
import subprocess
import sys

BASE = "http://localhost:8010/identity"
USER_ID = "d3326a5b-57b7-425b-8a97-f084a4592632"

# (method, path, body_or_none, description)
ENDPOINTS = [
    # --- UserViewSet (router) ---
    ("GET",  "/users/",                           None, "List users"),
    ("GET",  f"/users/{USER_ID}/",                 None, "Retrieve user"),

    # --- Auth ---
    ("POST", "/register/",                         {"username": "smoketest", "email": "smoke@test.com", "password": "Test1234!", "password2": "Test1234!"}, "Register"),
    ("POST", "/login/",                            {"email": "henry@wanjala.art", "password": "wrong"}, "Login"),
    ("POST", "/logout/",                           {"refresh": "fake-token"}, "Logout"),
    ("POST", "/token/refresh/",                    {"refresh": "fake-token"}, "Token refresh"),
    ("POST", "/google/",                           {"auth_token": "fake"}, "Google social auth"),

    # --- User detail / edit ---
    ("GET",  f"/detail/{USER_ID}/",                None, "User detail"),
    ("GET",  "/me/summary/",                       None, "User summary"),
    ("PATCH", f"/edit/{USER_ID}/",                 {"first_name": "Smoke"}, "User patch edit"),
    ("PATCH", f"/profile/{USER_ID}/",              {"title": "tester"}, "Profile edit"),

    # --- Password ---
    ("POST", "/request-reset-email/",              {"email": "henry@wanjala.art"}, "Request password reset"),
    ("PATCH", "/password-reset-complete",          {"password": "x", "token": "x", "uidb64": "x"}, "Password reset complete"),
    ("PUT",  "/changepassword/",                   {"old_password": "x", "new_password": "y"}, "Change password"),

    # --- Email verification ---
    ("GET",  "/email-verify/?token=fake",          None, "Email verify"),

    # --- OTP ---
    ("GET",  "/otp/create/",                       None, "OTP create (GET)"),
    ("POST", "/otp/verify/",                       {"token": "000000"}, "OTP verify"),
    ("POST", "/otp/verify/000000/",                None, "OTP verify legacy"),
    ("POST", "/otp/delete/",                       {}, "OTP delete"),
    ("POST", "/otp/static/create/",                {}, "OTP static create"),
    ("POST", "/otp/static/verify/",                {"token": "000000"}, "OTP static verify"),
    ("POST", "/otp/static/verify/000000/",         None, "OTP static verify legacy"),

    # --- Invitations ---
    ("POST", "/invitations/",                      {"email": "test@test.com"}, "Invitations"),

    # --- Search ---
    ("POST", "/search/",                           {"query": "wanjala"}, "User search"),
    ("GET",  "/search/wanjala/",                   None, "User search by query"),

    # --- Social (mounted under identity) ---
    ("GET",  f"/workspaces/{USER_ID}/",            None, "List workspaces"),
    ("GET",  f"/posts/{USER_ID}/",                 None, "List posts"),
    ("GET",  f"/profile/{USER_ID}/followers/",     None, "List followers"),

    # --- Inbox ---
    ("GET",  "/inbox/",                            None, "List threads (inbox)"),
    ("POST", "/inbox/thread/",                     {"participants": []}, "Create thread"),

    # --- Signup API ---
    ("POST", "/signupapi/",                        {"username": "smoke2", "email": "s2@t.com", "password": "Test1234!"}, "Signup API"),
]


def curl(method, url, body=None):
    """Run curl and return (status_code, response_body_snippet)."""
    cmd = ["curl", "-s", "-o", "/tmp/smoke_resp.txt", "-w", "%{http_code}",
           "-X", method, url,
           "-H", "Content-Type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        status_code = int(result.stdout.strip())
        with open("/tmp/smoke_resp.txt") as f:
            resp = f.read()[:300]
        return status_code, resp
    except Exception as e:
        return 0, str(e)


def main():
    print(f"{'='*80}")
    print(f"  IDENTITY CONTEXT SMOKE TEST")
    print(f"{'='*80}\n")

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
        print(f"  [{marker}] {method:6s} {path:45s} {status}")
        if is_fail:
            # Print error snippet for failures
            print(f"       >>> {resp[:200]}")
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
            # Try to extract error message
            try:
                data = json.loads(resp)
                if "exception_value" in str(data):
                    print(f"      Error: {data}")
                else:
                    print(f"      Response: {json.dumps(data)[:200]}")
            except json.JSONDecodeError:
                # HTML error page - extract title
                if "<title>" in resp:
                    title = resp.split("<title>")[1].split("</title>")[0]
                    print(f"      Error: {title}")
                else:
                    print(f"      Response: {resp[:200]}")

    if warnings:
        print(f"\n  WARNINGS (404):")
        for method, path, desc, code, _, resp in warnings:
            print(f"    {method} {path} — {desc}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
