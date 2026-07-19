"""Seed the default security domains a workspace can operate across."""

from django.db import migrations

DEFAULT_DOMAINS = [
    ("cloud", "Cloud", "Cloud infrastructure & workloads (AWS, GCP, Azure).", "☁", 10),
    ("endpoint", "Endpoint", "Workstations, servers, and device security.", "▦", 20),
    ("network", "Network", "Network traffic, perimeter, and segmentation.", "⇄", 30),
    ("identity", "Identity", "Identity, access, and privilege management.", "◉", 40),
    ("application", "Application", "Application & API security (AppSec).", "◈", 50),
    ("data", "Data", "Data protection, DLP, and exfiltration.", "▤", 60),
    ("email", "Email", "Email security, phishing, and messaging.", "✉", 70),
]


def seed(apps, schema_editor):
    Domain = apps.get_model("domains", "Domain")
    for slug, name, description, icon, sort_order in DEFAULT_DOMAINS:
        Domain.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "description": description,
                "icon": icon,
                "sort_order": sort_order,
            },
        )


def unseed(apps, schema_editor):
    Domain = apps.get_model("domains", "Domain")
    Domain.objects.filter(slug__in=[d[0] for d in DEFAULT_DOMAINS]).delete()


class Migration(migrations.Migration):
    dependencies = [("domains", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
