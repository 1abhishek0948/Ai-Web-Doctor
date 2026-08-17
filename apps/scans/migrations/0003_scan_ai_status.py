"""Add the machine-readable AI analysis status to scans."""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scans", "0002_scan_client_ip"),
    ]

    operations = [
        migrations.AddField(
            model_name="scan",
            name="ai_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("running", "Running"),
                    ("completed", "Completed"),
                    ("unavailable", "Unavailable"),
                    ("failed", "Failed"),
                    ("rate_limited", "Rate limited"),
                    ("skipped", "Skipped"),
                ],
                db_index=True,
                default="pending",
                max_length=16,
            ),
        ),
    ]