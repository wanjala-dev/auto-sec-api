"""Seed the system (global) security report templates.

Idempotent: upserts by (name, is_seeded=True, workspace=None). These are the
report skeletons a SOC / pentest team starts from — pentest report, root-cause
analysis, incident report, corrective-action plan, threat brief — surfaced in the
Template Kernel gallery as the ``security_report_template`` kind.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from infrastructure.persistence.security_templates.models import SecurityReportTemplate

SYSTEM_TEMPLATES = [
    {
        "name": "Penetration Test Report",
        "category": "Pentest",
        "description": "Full VAPT engagement report — scope, methodology, findings with CVSS, and remediation.",
        "body_html": (
            "<h1>Penetration Test Report</h1>"
            "<h2>1. Executive Summary</h2><p>Business-level summary of risk and posture.</p>"
            "<h2>2. Scope &amp; Rules of Engagement</h2><p>Targets, timeframe, exclusions, authorization.</p>"
            "<h2>3. Methodology</h2><p>Approach, tooling, and standards followed (e.g. PTES, OWASP).</p>"
            "<h2>4. Findings</h2><p>Per finding: title, severity (CVSS), affected assets, evidence, impact, reproduction.</p>"
            "<h2>5. Remediation</h2><p>Prioritized, actionable fixes with owners and timelines.</p>"
            "<h2>6. Appendix</h2><p>Raw output, tool versions, out-of-scope observations.</p>"
        ),
    },
    {
        "name": "Root Cause Analysis (RCA)",
        "category": "RCA",
        "description": "Post-incident RCA — timeline, 5-whys, contributing factors, and corrective actions.",
        "body_html": (
            "<h1>Root Cause Analysis</h1>"
            "<h2>1. Summary</h2><p>What happened, when, and the impact.</p>"
            "<h2>2. Timeline</h2><p>Chronological sequence from detection to resolution (UTC).</p>"
            "<h2>3. Root Cause</h2><p>The 5-whys chain to the underlying cause.</p>"
            "<h2>4. Contributing Factors</h2><p>Conditions that made the incident possible or worse.</p>"
            "<h2>5. Corrective Actions</h2><p>Preventive measures with owners and due dates.</p>"
            "<h2>6. Lessons Learned</h2><p>What worked, what didn't, what changes.</p>"
        ),
    },
    {
        "name": "Incident Report",
        "category": "Incident",
        "description": "IR lifecycle report — detection, containment, eradication, recovery, lessons.",
        "body_html": (
            "<h1>Incident Report</h1>"
            "<h2>1. Overview</h2><p>Incident ID, severity, classification, affected systems.</p>"
            "<h2>2. Detection</h2><p>How and when it was detected; initial indicators.</p>"
            "<h2>3. Containment</h2><p>Actions taken to limit spread and blast radius.</p>"
            "<h2>4. Eradication</h2><p>Removing the threat and closing the entry vector.</p>"
            "<h2>5. Recovery</h2><p>Restoring service and validating integrity.</p>"
            "<h2>6. Post-Incident</h2><p>Lessons, follow-ups, and links to the RCA.</p>"
        ),
    },
    {
        "name": "Corrective Action Plan",
        "category": "Corrective Action",
        "description": "Remediation tracker — findings mapped to owners, actions, and verification.",
        "body_html": (
            "<h1>Corrective Action Plan</h1>"
            "<h2>1. Context</h2><p>Source finding(s) this plan addresses.</p>"
            "<h2>2. Actions</h2><p>Per action: description, owner, priority, due date, status.</p>"
            "<h2>3. Verification</h2><p>How each fix is validated as effective.</p>"
            "<h2>4. Residual Risk</h2><p>What remains after remediation and its acceptance.</p>"
        ),
    },
    {
        "name": "Threat Brief",
        "category": "Threat Brief",
        "description": "Concise threat-intel brief — actor, TTPs, IOCs, and recommended defenses.",
        "body_html": (
            "<h1>Threat Brief</h1>"
            "<h2>1. Summary</h2><p>The threat in two sentences and why it matters to us.</p>"
            "<h2>2. Threat Actor</h2><p>Attribution, motivation, and targeting.</p>"
            "<h2>3. TTPs</h2><p>Tactics, techniques, and procedures (MITRE ATT&amp;CK mapping).</p>"
            "<h2>4. Indicators of Compromise</h2><p>Hashes, domains, IPs, and detection logic.</p>"
            "<h2>5. Recommendations</h2><p>Detections, mitigations, and hardening steps.</p>"
        ),
    },
]


class Command(BaseCommand):
    help = "Seed the system security report templates (idempotent)."

    def handle(self, *args, **options):
        created, updated = 0, 0
        for spec in SYSTEM_TEMPLATES:
            obj, was_created = SecurityReportTemplate.objects.update_or_create(
                name=spec["name"],
                is_seeded=True,
                workspace=None,
                defaults={
                    "category": spec["category"],
                    "description": spec["description"],
                    "body_html": spec["body_html"],
                    "is_deleted": False,
                },
            )
            created += int(was_created)
            updated += int(not was_created)
        self.stdout.write(
            self.style.SUCCESS(f"Security report templates seeded: {created} created, {updated} updated.")
        )
