"""Hand-authored evaluation datasets for the prompt-eval harness.

Each dataset is a JSON file with one test case per entry. Test cases
are seed data — small enough to hand-author, big enough to reveal
prompt-quality regressions. Generated cases (Claude-authored from a
spec) are deferred to a later wave so we keep tight signal-to-noise
ratio early on.
"""
