"""Seed system workflow templates.

Usage:
    python manage.py seed_workflow_templates          # upsert all
    python manage.py seed_workflow_templates --dry-run # preview without writing

Every template in ``SYSTEM_TEMPLATES`` is authored to be **publish-ready and
autonomous**: its ``default_graph`` passes ``validate_graph`` (the publish gate)
with zero errors AND runs end-to-end with no human-in-the-loop step *unless* a
human decision is genuinely required (grant approve/decline, document review).

The autonomous-engine rules (see the ``workflow`` skill + ``.claude/rules``):

- Every ``message`` node carries ``channel`` + a real ``body`` so it publishes
  and actually sends. (An empty-body message fails ``message_missing_payload``.)
- Branch points are ``wait_until`` (wait for a domain event up to a timeout, then
  branch Yes=event-arrived / No=timed-out) or ``condition`` (evaluate a predicate
  against the run context and branch with no human). Both need ≥2 *labelled*
  outgoing edges — we label them ``yes``/``no`` so ``WorkflowGraph.branch_target``
  resolves deterministically (not just positionally).
- The legacy manual ``decision`` node is used ONLY where a person must judge
  (grant approve/decline, import review approve/reject) — those steps are meant
  to pause for an operator's ``complete_step`` call.
- ``task`` / ``assign`` nodes no-op gracefully in a *system* template (they need a
  workspace-specific ``column_id``/``user_id`` the author supplies after cloning);
  they never fail publish.

``WorkflowTemplate.default_graph`` is validated by ``WorkflowTemplateSerializer``
on create/update with the same ``validate_graph`` — and
``components/workflow/tests/unit/test_seeded_templates_publish.py`` asserts every
template here passes. Edit a graph below and that test is the regression lock.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

# Workspace-default tip: bodies are sent as-is (no placeholder resolution on the
# raw ``body`` path), so keep copy generic — a literal ``{{first_name}}`` would
# render unresolved. To personalise, set ``template_id`` to a content
# WritingTemplate instead (rendered by ``_render_template_body``).

SYSTEM_TEMPLATES = [
    # ── Sponsor Welcome ───────────────────────────────────────
    {
        "id": "sponsor",
        "label": "Sponsor Welcome",
        "category": "sponsorship",
        "version": "3",
        "description": "Welcome a new sponsor, tag them, then wait for their first gift and follow up either way.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "New sponsor added", "subtitle": "Contact enters the workflow", "config": {"triggerType": "contact_added"}},
                {"id": "welcome", "type": "message", "label": "Welcome message", "subtitle": "Send a warm welcome email", "config": {"channel": "email", "subject": "Welcome to our community", "body": "Thank you for joining us. Your support helps us reach the children and families who need it most. We'll keep you close to the impact you make."}},
                {"id": "tag", "type": "add_tag", "label": "Tag as Sponsor", "subtitle": "Add the Sponsor tag", "config": {"tag": "Sponsor"}},
                {"id": "wait_gift", "type": "wait_until", "label": "Wait for first gift", "subtitle": "Wait up to 30 days for a donation", "config": {"event": "donation_received", "timeout_seconds": 2592000}},
                {"id": "thanks", "type": "message", "label": "Thank-you for first gift", "subtitle": "Acknowledge the first donation", "config": {"channel": "email", "subject": "Thank you for your first gift", "body": "Your first gift just arrived and it means the world to us. Here's exactly where it goes and the difference it makes."}},
                {"id": "nudge", "type": "message", "label": "Gentle reminder", "subtitle": "Invite them to make a first gift", "config": {"channel": "email", "subject": "Ready to make your first gift?", "body": "Whenever you're ready, your first gift goes directly to the program you care about. Here's how to give in under a minute."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Exit workflow", "config": {}},
            ],
            "edges": [
                {"id": "sponsor-0", "from": "start", "to": "welcome"},
                {"id": "sponsor-1", "from": "welcome", "to": "tag"},
                {"id": "sponsor-2", "from": "tag", "to": "wait_gift"},
                {"id": "sponsor-3", "from": "wait_gift", "to": "thanks", "label": "yes"},
                {"id": "sponsor-4", "from": "wait_gift", "to": "nudge", "label": "no"},
                {"id": "sponsor-5", "from": "thanks", "to": "end"},
                {"id": "sponsor-6", "from": "nudge", "to": "end"},
            ],
        },
    },
    # ── Event Invite ──────────────────────────────────────────
    {
        "id": "event",
        "label": "Event Invite",
        "category": "event",
        "version": "3",
        "description": "Invite a contact to an event, wait for their RSVP, and confirm or remind automatically.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Contact added", "subtitle": "Contact enters the workflow", "config": {"triggerType": "contact_added"}},
                {"id": "invite", "type": "message", "label": "Send invite", "subtitle": "Event invitation", "config": {"channel": "email", "subject": "You're invited", "body": "We'd love for you to join us. Tap below to see the details and RSVP — we hope to see you there."}},
                {"id": "wait_rsvp", "type": "wait_until", "label": "Wait for RSVP", "subtitle": "Wait up to 7 days for an RSVP", "config": {"event": "event_rsvp_yes", "timeout_seconds": 604800}},
                {"id": "confirm", "type": "message", "label": "Confirm attendance", "subtitle": "RSVP received", "config": {"channel": "email", "subject": "You're on the list", "body": "Thanks for confirming. Here's everything you need to know before the event — date, time, and directions."}},
                {"id": "remind", "type": "message", "label": "RSVP reminder", "subtitle": "No RSVP yet", "config": {"channel": "email", "subject": "Last chance to RSVP", "body": "We haven't heard back yet and didn't want you to miss out. There's still room — let us know if you can make it."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Exit event flow", "config": {}},
            ],
            "edges": [
                {"id": "event-0", "from": "start", "to": "invite"},
                {"id": "event-1", "from": "invite", "to": "wait_rsvp"},
                {"id": "event-2", "from": "wait_rsvp", "to": "confirm", "label": "yes"},
                {"id": "event-3", "from": "wait_rsvp", "to": "remind", "label": "no"},
                {"id": "event-4", "from": "confirm", "to": "end"},
                {"id": "event-5", "from": "remind", "to": "end"},
            ],
        },
    },
    # ── Donor Nurture ─────────────────────────────────────────
    {
        "id": "nurture",
        "label": "Donor Nurture",
        "category": "campaign",
        "version": "3",
        "description": "Share an impact story, then wait for a gift — thank givers, gently follow up with everyone else.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Contact added", "subtitle": "New donor enters the flow", "config": {"triggerType": "contact_added"}},
                {"id": "impact", "type": "message", "label": "Share impact", "subtitle": "Send an impact story", "config": {"channel": "email", "subject": "See the impact you make possible", "body": "Here's a story from the field about a life your support helps change. This is what generosity looks like up close."}},
                {"id": "wait_gift", "type": "wait_until", "label": "Wait for a gift", "subtitle": "Wait up to 14 days for a donation", "config": {"event": "donation_received", "timeout_seconds": 1209600}},
                {"id": "thanks", "type": "message", "label": "Thank-you note", "subtitle": "Acknowledge the gift", "config": {"channel": "email", "subject": "Thank you", "body": "Your generosity just made a real difference. Thank you for standing with the people we serve."}},
                {"id": "checkin", "type": "message", "label": "Check-in note", "subtitle": "Friendly follow-up", "config": {"channel": "email", "subject": "Staying in touch", "body": "Just checking in to share what's next and to thank you for being part of our community."}},
                {"id": "reminder", "type": "task", "label": "Follow-up task", "subtitle": "Create a follow-up to-do", "config": {"title": "Personal follow-up with donor", "description": "Reach out personally to continue the relationship."}},
                {"id": "exit", "type": "end", "label": "End", "subtitle": "Exit nurture flow", "config": {}},
            ],
            "edges": [
                {"id": "nurture-0", "from": "start", "to": "impact"},
                {"id": "nurture-1", "from": "impact", "to": "wait_gift"},
                {"id": "nurture-2", "from": "wait_gift", "to": "thanks", "label": "yes"},
                {"id": "nurture-3", "from": "wait_gift", "to": "checkin", "label": "no"},
                {"id": "nurture-4", "from": "thanks", "to": "exit"},
                {"id": "nurture-5", "from": "checkin", "to": "reminder"},
                {"id": "nurture-6", "from": "reminder", "to": "exit"},
            ],
        },
    },
    # ── New Contact Automation ────────────────────────────────
    {
        "id": "automation",
        "label": "New Contact Automation",
        "category": "campaign",
        "version": "3",
        "description": "Welcome a new contact, wait for them to engage with a link, then convert or assign manual follow-up.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "New contact added", "subtitle": "Contact enters the workflow", "config": {"triggerType": "contact_added"}},
                {"id": "welcome", "type": "message", "label": "Welcome email", "subtitle": "Send a welcome", "config": {"channel": "email", "subject": "Welcome", "body": "Glad to have you with us. Here's a quick look at who we are and how you can get involved."}},
                {"id": "settle", "type": "wait", "label": "Wait 1 day", "subtitle": "Pause before measuring engagement", "config": {"delay_seconds": 86400}},
                {"id": "wait_click", "type": "wait_until", "label": "Wait for a click", "subtitle": "Wait up to 7 days for a link click", "config": {"event": "campaign_clicked", "timeout_seconds": 604800}},
                {"id": "followup", "type": "message", "label": "Follow-up email", "subtitle": "They engaged — keep momentum", "config": {"channel": "email", "subject": "Here's what's next", "body": "Thanks for taking a look. Here's an easy next step to go deeper with our work."}},
                {"id": "task", "type": "task", "label": "Manual follow-up", "subtitle": "No engagement — assign a to-do", "config": {"title": "Follow up with new contact", "description": "Contact hasn't engaged yet — reach out personally."}},
                {"id": "exit", "type": "end", "label": "End", "subtitle": "Exit automation", "config": {}},
            ],
            "edges": [
                {"id": "auto-0", "from": "start", "to": "welcome"},
                {"id": "auto-1", "from": "welcome", "to": "settle"},
                {"id": "auto-2", "from": "settle", "to": "wait_click"},
                {"id": "auto-3", "from": "wait_click", "to": "followup", "label": "yes"},
                {"id": "auto-4", "from": "wait_click", "to": "task", "label": "no"},
                {"id": "auto-5", "from": "followup", "to": "exit"},
                {"id": "auto-6", "from": "task", "to": "exit"},
            ],
        },
    },
    # ── Grant Approval (human-in-the-loop is intentional) ─────
    {
        "id": "grants",
        "label": "Grant Approval",
        "category": "campaign",
        "version": "3",
        "description": "Route a grant application through AI document prep and a reviewer task to a human approve/decline decision.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Grant submitted", "subtitle": "Application enters review", "config": {"triggerType": "grant_submitted"}},
                {"id": "documents", "type": "ai", "label": "Organize documents", "subtitle": "AI summarizes the proposal & attachments", "config": {"prompt": "Summarize this grant application and list the supporting documents and any gaps a reviewer should know about."}},
                {"id": "notify", "type": "message", "label": "Notify the team", "subtitle": "Alert reviewers", "config": {"channel": "in_app", "body": "A new grant application is ready for review."}},
                {"id": "review", "type": "task", "label": "Assign reviewer", "subtitle": "Create a review to-do", "config": {"title": "Review grant application", "description": "Read the AI summary and the proposal, then make a decision."}},
                {"id": "decision", "type": "decision", "label": "Approve or decline", "subtitle": "Human reviewer decides", "config": {}},
                {"id": "approved", "type": "message", "label": "Notify approved", "subtitle": "Tell the applicant", "config": {"channel": "email", "subject": "Your grant has been approved", "body": "Congratulations — your application has been approved. Here are the next steps to receive your funds."}},
                {"id": "declined", "type": "message", "label": "Notify declined", "subtitle": "Tell the applicant", "config": {"channel": "email", "subject": "An update on your grant application", "body": "Thank you for applying. We're not able to fund this application, but we'd welcome a future submission."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Close grant review", "config": {}},
            ],
            "edges": [
                {"id": "grant-0", "from": "start", "to": "documents"},
                {"id": "grant-1", "from": "documents", "to": "notify"},
                {"id": "grant-2", "from": "notify", "to": "review"},
                {"id": "grant-3", "from": "review", "to": "decision"},
                {"id": "grant-4", "from": "decision", "to": "approved", "label": "Approve"},
                {"id": "grant-5", "from": "decision", "to": "declined", "label": "Decline"},
                {"id": "grant-6", "from": "approved", "to": "end"},
                {"id": "grant-7", "from": "declined", "to": "end"},
            ],
        },
    },
    # ── Donation Thank You (autonomous amount-based branch) ───
    {
        "id": "donation-thanks",
        "label": "Donation Thank You",
        "category": "sponsorship",
        "version": "2",
        "description": "Thank a donor, share impact, then branch on gift size — steward major gifts, invite others to give monthly.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Donation received", "subtitle": "A gift arrives", "config": {"triggerType": "donation_received"}},
                {"id": "thank", "type": "message", "label": "Thank-you email", "subtitle": "Immediate acknowledgement", "config": {"channel": "email", "subject": "Thank you for your generous gift", "body": "Your gift just arrived and we're so grateful. Thank you for investing in the people we serve."}},
                {"id": "wait", "type": "wait", "label": "Wait 3 days", "subtitle": "Pause before the impact update", "config": {"delay_seconds": 259200}},
                {"id": "impact", "type": "message", "label": "Impact update", "subtitle": "Show where the gift went", "config": {"channel": "email", "subject": "Here's what your gift made possible", "body": "A few days on, here's the concrete difference your gift is already making."}},
                {"id": "major", "type": "condition", "label": "Major gift?", "subtitle": "Branch on gift size (>= 250)", "config": {"predicate": {"match": "all", "conditions": [{"field": "amount", "op": "gte", "value": 250}]}}},
                {"id": "steward", "type": "message", "label": "Major-donor outreach", "subtitle": "Invite a deeper conversation", "config": {"channel": "email", "subject": "We'd love to talk", "body": "Your generosity puts you among our most committed supporters. We'd love to share more about the work and explore a deeper partnership."}},
                {"id": "recurring", "type": "message", "label": "Recurring invite", "subtitle": "Invite monthly giving", "config": {"channel": "email", "subject": "Make your impact monthly", "body": "Becoming a monthly giver turns a single gift into steady, year-round impact. Here's how to set it up in a minute."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Exit flow", "config": {}},
            ],
            "edges": [
                {"id": "dt-0", "from": "start", "to": "thank"},
                {"id": "dt-1", "from": "thank", "to": "wait"},
                {"id": "dt-2", "from": "wait", "to": "impact"},
                {"id": "dt-3", "from": "impact", "to": "major"},
                {"id": "dt-4", "from": "major", "to": "steward", "label": "yes"},
                {"id": "dt-5", "from": "major", "to": "recurring", "label": "no"},
                {"id": "dt-6", "from": "steward", "to": "end"},
                {"id": "dt-7", "from": "recurring", "to": "end"},
            ],
        },
    },
    # ── Event Follow-Up ───────────────────────────────────────
    {
        "id": "event-followup",
        "label": "Event Follow-Up",
        "category": "event",
        "version": "2",
        "description": "After an event, send a recap and wait for a gift — thank givers, send everyone else a feedback ask.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Attendee checked in", "subtitle": "Attendee enters the flow", "config": {"triggerType": "event_checkin"}},
                {"id": "wait1", "type": "wait", "label": "Wait 1 day", "subtitle": "Pause before following up", "config": {"delay_seconds": 86400}},
                {"id": "recap", "type": "message", "label": "Event recap", "subtitle": "Send a recap & photos", "config": {"channel": "email", "subject": "Thanks for joining us", "body": "What a day. Here's a recap, a few photos, and the impact we made together — plus an easy way to keep it going."}},
                {"id": "wait_gift", "type": "wait_until", "label": "Wait for a gift", "subtitle": "Wait up to 7 days for a donation", "config": {"event": "donation_received", "timeout_seconds": 604800}},
                {"id": "thanks", "type": "message", "label": "Thank-you for gift", "subtitle": "Acknowledge the donation", "config": {"channel": "email", "subject": "Thank you", "body": "Your post-event gift means so much. Thank you for turning a great evening into lasting impact."}},
                {"id": "survey", "type": "message", "label": "Feedback ask", "subtitle": "Invite feedback", "config": {"channel": "email", "subject": "How did we do?", "body": "We'd love your quick take on the event — it helps us make the next one even better."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Exit flow", "config": {}},
            ],
            "edges": [
                {"id": "ef-0", "from": "start", "to": "wait1"},
                {"id": "ef-1", "from": "wait1", "to": "recap"},
                {"id": "ef-2", "from": "recap", "to": "wait_gift"},
                {"id": "ef-3", "from": "wait_gift", "to": "thanks", "label": "yes"},
                {"id": "ef-4", "from": "wait_gift", "to": "survey", "label": "no"},
                {"id": "ef-5", "from": "thanks", "to": "end"},
                {"id": "ef-6", "from": "survey", "to": "end"},
            ],
        },
    },
    # ── Sponsorship Onboarding ────────────────────────────────
    {
        "id": "sponsor-onboard",
        "label": "Sponsorship Onboarding",
        "category": "sponsorship",
        "version": "2",
        "description": "Onboard a new sponsor over a week, then wait for their first gift and personalize the next step.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Sponsorship started", "subtitle": "New sponsor begins", "config": {"triggerType": "sponsorship_started"}},
                {"id": "welcome", "type": "message", "label": "Welcome & mission", "subtitle": "Introduce the mission", "config": {"channel": "email", "subject": "Welcome — here's our mission", "body": "Welcome aboard. Here's the heart of what we do and the difference your sponsorship will make."}},
                {"id": "wait1", "type": "wait", "label": "Wait 2 days", "subtitle": "Pause", "config": {"delay_seconds": 172800}},
                {"id": "profile", "type": "message", "label": "Recipient profile", "subtitle": "Introduce their recipient", "config": {"channel": "email", "subject": "Meet who you're supporting", "body": "Here's a little about the person your sponsorship supports — their story, their hopes, and how you fit in."}},
                {"id": "wait2", "type": "wait", "label": "Wait 5 days", "subtitle": "Pause", "config": {"delay_seconds": 432000}},
                {"id": "updates", "type": "message", "label": "Update schedule", "subtitle": "Explain what to expect", "config": {"channel": "email", "subject": "How we'll keep you in the loop", "body": "Here's how often you'll hear from us and the kinds of updates and milestones you can expect along the way."}},
                {"id": "wait_gift", "type": "wait_until", "label": "Wait for first gift", "subtitle": "Wait up to 30 days for a donation", "config": {"event": "donation_received", "timeout_seconds": 2592000}},
                {"id": "ai", "type": "ai", "label": "Personalized next step", "subtitle": "AI suggests a tailored follow-up", "config": {"prompt": "This sponsor has just made their first gift. Suggest a warm, specific next step to deepen the relationship."}},
                {"id": "task", "type": "task", "label": "Steward follow-up", "subtitle": "No gift yet — assign a steward", "config": {"title": "Donor steward follow-up", "description": "Sponsor hasn't made a first gift — reach out personally."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Onboarding complete", "config": {}},
            ],
            "edges": [
                {"id": "so-0", "from": "start", "to": "welcome"},
                {"id": "so-1", "from": "welcome", "to": "wait1"},
                {"id": "so-2", "from": "wait1", "to": "profile"},
                {"id": "so-3", "from": "profile", "to": "wait2"},
                {"id": "so-4", "from": "wait2", "to": "updates"},
                {"id": "so-5", "from": "updates", "to": "wait_gift"},
                {"id": "so-6", "from": "wait_gift", "to": "ai", "label": "yes"},
                {"id": "so-7", "from": "wait_gift", "to": "task", "label": "no"},
                {"id": "so-8", "from": "ai", "to": "end"},
                {"id": "so-9", "from": "task", "to": "end"},
            ],
        },
    },
    # ── Grant Deadline Reminder (human readiness check) ──────
    {
        "id": "grant-deadline",
        "label": "Grant Deadline Reminder",
        "category": "campaign",
        "version": "2",
        "description": "Notify the team of a new grant, remind as the deadline nears, then confirm readiness via a human check.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Grant submitted", "subtitle": "A grant enters the pipeline", "config": {"triggerType": "grant_submitted"}},
                {"id": "notify", "type": "message", "label": "Notify team", "subtitle": "Alert the team in-app", "config": {"channel": "in_app", "body": "A new grant is in progress — let's get the documents ready before the deadline."}},
                {"id": "wait", "type": "wait", "label": "Wait 7 days", "subtitle": "Pause until closer to the deadline", "config": {"delay_seconds": 604800}},
                {"id": "reminder", "type": "message", "label": "Deadline reminder", "subtitle": "Remind the team", "config": {"channel": "email", "subject": "Grant deadline approaching", "body": "The deadline is getting close. Please confirm the documents are ready or flag anything still outstanding."}},
                {"id": "ready", "type": "decision", "label": "Documents ready?", "subtitle": "Human confirms readiness", "config": {}},
                {"id": "confirm", "type": "message", "label": "Confirm ready", "subtitle": "All set to submit", "config": {"channel": "email", "subject": "Ready to submit", "body": "Everything's in place — we're ready to submit ahead of the deadline."}},
                {"id": "task", "type": "task", "label": "Urgent prep", "subtitle": "Not ready — create urgent to-do", "config": {"title": "Urgent grant prep needed", "description": "Documents aren't ready and the deadline is near — prioritize this."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Deadline flow complete", "config": {}},
            ],
            "edges": [
                {"id": "gd-0", "from": "start", "to": "notify"},
                {"id": "gd-1", "from": "notify", "to": "wait"},
                {"id": "gd-2", "from": "wait", "to": "reminder"},
                {"id": "gd-3", "from": "reminder", "to": "ready"},
                {"id": "gd-4", "from": "ready", "to": "confirm", "label": "Ready"},
                {"id": "gd-5", "from": "ready", "to": "task", "label": "Not ready"},
                {"id": "gd-6", "from": "confirm", "to": "end"},
                {"id": "gd-7", "from": "task", "to": "end"},
            ],
        },
    },
    # ── Campaign Re-engagement ────────────────────────────────
    {
        "id": "campaign-reengage",
        "label": "Campaign Re-engagement",
        "category": "campaign",
        "version": "2",
        "description": "Re-engage a contact with an AI-personalized follow-up, wait for a click, then convert or hand off — and notify your CRM.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Campaign opened", "subtitle": "Opened but no action yet", "config": {"triggerType": "campaign_opened"}},
                {"id": "wait", "type": "wait", "label": "Wait 2 days", "subtitle": "Pause before re-engaging", "config": {"delay_seconds": 172800}},
                {"id": "ai", "type": "ai", "label": "AI personalize", "subtitle": "Draft a tailored follow-up", "config": {"prompt": "This contact opened our campaign but didn't act. Write a short, warm, personalized nudge that invites a single clear next step."}},
                {"id": "followup", "type": "message", "label": "Personalized follow-up", "subtitle": "Send the nudge", "config": {"channel": "email", "subject": "A quick follow-up, just for you", "body": "We noticed you took a look — here's a simple next step if you'd like to get involved."}},
                {"id": "wait_click", "type": "wait_until", "label": "Wait for a click", "subtitle": "Wait up to 7 days for a click", "config": {"event": "campaign_clicked", "timeout_seconds": 604800}},
                {"id": "convert", "type": "message", "label": "Conversion offer", "subtitle": "They clicked — make the ask", "config": {"channel": "email", "subject": "Ready to take the next step?", "body": "Thanks for clicking through. Here's how to turn your interest into real impact today."}},
                {"id": "task", "type": "task", "label": "Manual outreach", "subtitle": "No click — assign a to-do", "config": {"title": "Manual outreach for re-engagement", "description": "Contact didn't re-engage — try a personal touch."}},
                {"id": "webhook", "type": "webhook", "label": "Notify CRM", "subtitle": "Send the outcome to an external CRM", "config": {"url": "", "method": "POST"}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Exit re-engagement", "config": {}},
            ],
            "edges": [
                {"id": "cr-0", "from": "start", "to": "wait"},
                {"id": "cr-1", "from": "wait", "to": "ai"},
                {"id": "cr-2", "from": "ai", "to": "followup"},
                {"id": "cr-3", "from": "followup", "to": "wait_click"},
                {"id": "cr-4", "from": "wait_click", "to": "convert", "label": "yes"},
                {"id": "cr-5", "from": "wait_click", "to": "task", "label": "no"},
                {"id": "cr-6", "from": "convert", "to": "webhook"},
                {"id": "cr-7", "from": "task", "to": "webhook"},
                {"id": "cr-8", "from": "webhook", "to": "end"},
            ],
        },
    },
    # ── Document Import (human review is intentional) ─────────
    {
        "id": "document-import",
        "label": "Document Import",
        "category": "campaign",
        "version": "4",
        "description": "When a document is uploaded: AI extracts & classifies it, a reviewer approves, then records are applied and categorized.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Document uploaded", "subtitle": "File enters the pipeline", "config": {"triggerType": "document_uploaded"}},
                {"id": "ai-extract", "type": "ai", "label": "AI extraction", "subtitle": "Extract rows via RAG", "config": {"prompt": "Extract the structured rows (date, description, amount) from this uploaded document and flag anything unreadable."}},
                {"id": "classify", "type": "ai", "label": "Classify type", "subtitle": "Expense, income, or budget?", "config": {"prompt": "Classify each extracted row as expense, income, or budget and note your confidence."}},
                {"id": "validate", "type": "decision", "label": "Valid data?", "subtitle": "Reviewer checks row quality", "config": {}},
                {"id": "notify-reviewer", "type": "message", "label": "Notify reviewer", "subtitle": "Rows ready for review", "config": {"channel": "in_app", "body": "Extracted rows are ready for your review."}},
                {"id": "notify-uploader", "type": "message", "label": "Notify uploader", "subtitle": "Extraction had issues", "config": {"channel": "email", "subject": "We hit a snag with your upload", "body": "We couldn't cleanly read part of your document. Please re-upload a clearer copy when you can."}},
                {"id": "wait-review", "type": "data_request", "label": "Wait for review", "subtitle": "Human reviews the rows", "config": {}},
                {"id": "decide", "type": "decision", "label": "Approve?", "subtitle": "Reviewer approves or rejects", "config": {}},
                {"id": "apply", "type": "webhook", "label": "Apply records", "subtitle": "Create transactions", "config": {"url": "", "method": "POST"}},
                {"id": "categorize", "type": "ai", "label": "Auto categorize", "subtitle": "AI assigns categories", "config": {"prompt": "Assign the most likely budget category to each applied transaction."}},
                {"id": "notify-applied", "type": "message", "label": "Confirm applied", "subtitle": "Success notification", "config": {"channel": "in_app", "body": "The imported records were applied successfully."}},
                {"id": "reject-task", "type": "task", "label": "Manual entry", "subtitle": "Rejected — create a to-do", "config": {"title": "Manual entry needed for rejected import", "description": "Reviewer rejected the import — enter the records manually."}},
                {"id": "retry-extract", "type": "ai", "label": "Retry extraction", "subtitle": "Try a different strategy", "config": {"prompt": "The first extraction failed. Retry with a more tolerant strategy and report what you recovered."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Complete", "config": {}},
            ],
            "edges": [
                {"id": "di-0", "from": "start", "to": "ai-extract"},
                {"id": "di-1", "from": "ai-extract", "to": "classify"},
                {"id": "di-2", "from": "classify", "to": "validate"},
                {"id": "di-3", "from": "validate", "to": "notify-reviewer", "label": "Valid"},
                {"id": "di-4", "from": "validate", "to": "notify-uploader", "label": "Issues"},
                {"id": "di-5", "from": "validate", "to": "retry-extract", "label": "Unreadable"},
                {"id": "di-6", "from": "notify-reviewer", "to": "wait-review"},
                {"id": "di-7", "from": "wait-review", "to": "decide"},
                {"id": "di-8", "from": "decide", "to": "apply", "label": "Approve"},
                {"id": "di-9", "from": "decide", "to": "reject-task", "label": "Reject"},
                {"id": "di-10", "from": "apply", "to": "categorize"},
                {"id": "di-11", "from": "categorize", "to": "notify-applied"},
                {"id": "di-12", "from": "notify-applied", "to": "end"},
                {"id": "di-13", "from": "reject-task", "to": "end"},
                {"id": "di-14", "from": "notify-uploader", "to": "end"},
                # retry-extract is terminal (-> end), NOT a loop back to classify.
                # A cycle in a *published* workflow risks the engine re-walking the
                # loop indefinitely, and a back-edge also has to be special-cased by
                # the canvas layout. "Try a different strategy" runs one more AI
                # extraction pass, then the run completes; an author can wire a loop
                # themselves if they accept the re-run risk.
                {"id": "di-15", "from": "retry-extract", "to": "end"},
            ],
        },
    },
    # ── Phase 4 of the Agents-as-Teammates migration ──────────────────
    # Fires whenever a task with ``source_type LIKE 'ai.%'`` moves into
    # the ``Accepted`` column on the workspace's AI agent team board.
    # The ``publish_event`` node short-circuits non-AI tasks via its
    # ``task_source_type_prefix`` filter and publishes a
    # ``TaskAcceptedFromBoard`` shared-kernel event so downstream
    # specialist agents can react. (Already publish-valid — unchanged.)
    {
        "id": "ai-findings-accepted",
        "label": "AI Findings Accepted",
        "category": "agents",
        "version": "1",
        "description": (
            "When an AI-finding task moves into the Accepted column on "
            "the agent team board, publish a TaskAcceptedFromBoard "
            "event so downstream specialist agents can react."
        ),
        "default_graph": {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "label": "Task moves between columns",
                    "subtitle": "Triggered by Kanban drag-drop or PATCH",
                    "config": {"triggerType": "task_moved_column"},
                },
                {
                    "id": "publish",
                    "type": "publish_event",
                    "label": "Publish TaskAcceptedFromBoard",
                    "subtitle": (
                        "Fan out to specialist handlers — gates on "
                        "source_type ai.* + new column 'Accepted'"
                    ),
                    "config": {
                        "event_type": "task_accepted_from_board",
                        "filters": {
                            "task_source_type_prefix": "ai.",
                            "new_column_title": "Accepted",
                        },
                    },
                },
                {
                    "id": "end",
                    "type": "end",
                    "label": "Done",
                    "subtitle": "Workflow complete",
                    "config": {},
                },
            ],
            "edges": [
                {"id": "ai-findings-0", "from": "start", "to": "publish"},
                {"id": "ai-findings-1", "from": "publish", "to": "end"},
            ],
        },
    },
    # ── Receipt Accountability ────────────────────────────────
    # When an expense is recorded, wait for a receipt to be attached; if none
    # arrives within the window, email the owner a reminder. Correlation key =
    # the transaction id (the run targets the transaction, not a contact), so the
    # ``wait_until`` resolves Yes the moment the matching receipt_attached event
    # fires, and the reminder email resolves its recipient from the trigger
    # payload's owner_email (see node_actions ``_send_email_message`` fallback).
    {
        "id": "receipt-accountability",
        "label": "Receipt Accountability",
        "category": "budget",
        "version": "1",
        "description": "When an expense is recorded, wait for a receipt; if none arrives in 7 days, remind the owner to attach one.",
        "default_graph": {
            "nodes": [
                {"id": "start", "type": "start", "label": "Expense recorded", "subtitle": "An expense line item is committed", "config": {"triggerType": "transaction_recorded"}},
                {"id": "wait_receipt", "type": "wait_until", "label": "Wait for receipt", "subtitle": "Wait up to 7 days for a receipt", "config": {"event": "receipt_attached", "timeout_seconds": 604800}},
                {"id": "remind", "type": "message", "label": "Receipt reminder", "subtitle": "Email the owner to attach a receipt", "config": {"channel": "email", "subject": "Please attach a receipt for your expense", "body": "An expense you recorded is still missing its receipt. Please attach the receipt so the books stay audit-ready and every dollar is accounted for."}},
                {"id": "end", "type": "end", "label": "End", "subtitle": "Exit workflow", "config": {}},
            ],
            "edges": [
                {"id": "receipt-acct-0", "from": "start", "to": "wait_receipt"},
                {"id": "receipt-acct-1", "from": "wait_receipt", "to": "end", "label": "yes"},
                {"id": "receipt-acct-2", "from": "wait_receipt", "to": "remind", "label": "no"},
                {"id": "receipt-acct-3", "from": "remind", "to": "end"},
            ],
        },
    },
]

# System templates that were seeded by an earlier version of this command and are
# now retired. The seeder DELETES these rows so a stale, non-publishable, or
# off-ICP template can't linger in the library.
#
# ``product-launch`` was a generic SaaS product-launch demo (dev/design/marketing
# teams) — off the nonprofit ICP (see ``.claude/rules/gtm-scope-freeze.md``) and
# its wide parallel fan-out never actually ran (the engine advances one edge from
# a node, so 4 of the 5 "parallel" branches were dead). Removed rather than
# shipped as a misleading visual.
DEPRECATED_TEMPLATE_IDS = ["product-launch"]


class Command(BaseCommand):
    help = "Seed system workflow templates (idempotent upsert + retire deprecated)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        from infrastructure.persistence.workspaces.workflows.models import WorkflowTemplate

        created_count = 0
        updated_count = 0
        unchanged_count = 0

        for tmpl in SYSTEM_TEMPLATES:
            template_id = tmpl["id"]
            defaults = {
                "label": tmpl["label"],
                "description": tmpl["description"],
                "category": tmpl["category"],
                "version": tmpl["version"],
                "is_system": True,
                "default_graph": tmpl["default_graph"],
                "workspace": None,
                "created_by": None,
            }

            try:
                existing = WorkflowTemplate.objects.get(id=template_id)
                # Only update if version changed
                if existing.version != tmpl["version"]:
                    if not dry_run:
                        for field, value in defaults.items():
                            setattr(existing, field, value)
                        existing.save()
                    updated_count += 1
                    self.stdout.write(f"  Updated: {template_id} (v{existing.version} -> v{tmpl['version']})")
                else:
                    unchanged_count += 1
                    self.stdout.write(f"  Unchanged: {template_id} (v{tmpl['version']})")
            except WorkflowTemplate.DoesNotExist:
                if not dry_run:
                    WorkflowTemplate.objects.create(id=template_id, **defaults)
                created_count += 1
                self.stdout.write(f"  Created: {template_id} (v{tmpl['version']})")

        deleted_count = 0
        for dead_id in DEPRECATED_TEMPLATE_IDS:
            qs = WorkflowTemplate.objects.filter(id=dead_id, is_system=True)
            if qs.exists():
                if not dry_run:
                    qs.delete()
                deleted_count += 1
                self.stdout.write(f"  Retired: {dead_id}")

        prefix = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{prefix}Done. Created: {created_count}, Updated: {updated_count}, "
                f"Unchanged: {unchanged_count}, Retired: {deleted_count}"
            )
        )
