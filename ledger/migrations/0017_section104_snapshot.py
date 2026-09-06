import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ledger", "0016_alter_vest_sell_to_cover_proceeds_gbp")]

    operations = [
        migrations.CreateModel(
            name="Section104Snapshot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("engine_version", models.CharField(max_length=40)),
                ("input_hash", models.CharField(max_length=64)),
                ("payload", models.JSONField()),
                (
                    "security",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="ledger.security"
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="ledger.workspace"
                    ),
                ),
            ],
        ),
    ]
