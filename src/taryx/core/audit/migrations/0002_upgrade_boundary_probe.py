"""Deliberately minimal schema-version step.

This migration exists so the deployment upgrade path is exercisable
end-to-end: applying it requires a real `migrate` run (recorded in
django_migrations, gated by `migrate --check`), while changing no
schema. Deploy tooling and evidence use it to prove that recreated
migration Jobs run pending migrations before gated workloads start.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [
        migrations.RunSQL(sql="SELECT 1", reverse_sql="SELECT 1"),
    ]
