# DRY — Don't Repeat Yourself, Reuse Before You Build (HARD RULE)

Stay DRY. Before writing a new model, service, adapter, util, tool, or component,
check whether one already exists that you can reuse or extend. If a suitable one
exists, reuse it. Only build new when nothing reusable fits — and say what you
checked and why it didn't.

This is the sibling of `no-shortcuts.md`: shortcuts are shallow fixes; duplication
is a shortcut against your future self. Copy-pasted logic drifts — one copy gets a
fix the others don't, and the divergence surfaces as a bug months later. Solve it
once, in one place.

## The rules

1. **Grep before you build.** Search for the model name, the port, the service, the
   component. Reinventing something that exists is a defect, not a style choice.

2. **Extract shared choreography into ONE place.** When two code paths do the same
   multi-step dance with small differences, factor the dance into a helper and pass
   the differences in (callbacks / params) — don't fork the whole sequence.
   - Worked example: the triage agent and the optimization agent both fetch a
     pending finding, run an advisor, then — under a row lock, re-checking status —
     comment, move the card, stamp handled, and append a provenance event. That
     choreography lives ONCE in
     `components/agents/infrastructure/adapters/langchain/tools/_finding_processing.py::process_pending_finding`.
     Each agent supplies only the advisor, the comment text, and which payload
     fields the suggestion fills. Copy-pasting the concurrency guard per agent would
     have rotted the moment one copy got a lock fix the other missed.
   - Worked example: the error scan and the temporal pattern aggregator both need to
     assume the customer's AWS role and read an S3 window. The credential + read
     primitive lives ONCE in `log_ingest_service.py::_assume_role_s3_client` /
     `iter_window_records`; both callers consume it.

3. **Extend an existing seam instead of forking it.** A new finding KIND is a new
   `action_type` + a new specialist + ONE entry in the router's
   `ROUTABLE_SOURCE_TYPES` — not a parallel routing path. If adding a feature means
   copying an existing pipeline and tweaking it, stop: make the existing pipeline
   take the new case.

4. **One canonical thing per concern.** One ledger, one uploader, one email layer,
   one finding-persistence path (`persist_finding_as_task`), one board-mutation
   helper. A second parallel implementation of a concern is the defect.

5. **Reuse the frontend component catalog.** Never hand-roll a Button / Card / Table
   / Modal / EmptyState that already exists. Compose the existing HUD primitives.

6. **If unsure whether a reusable thing exists, ask or grep — don't assume it
   doesn't.** The only acceptable reason to build new is that nothing reusable fits,
   and you can name what you checked.

## Cross-references

- `no-shortcuts.md` — the deep-fix-not-bandaid rule this pairs with
- `architecture-manifesto.md` — ports/adapters keep reuse honest (swap the adapter,
  not the caller)
- `bounded-context-structure.md` — where shared things live so they're findable
