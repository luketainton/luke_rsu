import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("ledger", "0011_vest_capital_cost_gbp_sale_proceeds_gbp_and_opening_balance")]

    operations = [
        migrations.CreateModel(
            name="Purchase",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("grant_id", models.CharField(blank=True, max_length=120)),
                ("date", models.DateField()),
                ("units", models.DecimalField(decimal_places=4, max_digits=16)),
                (
                    "usd_price",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=16, null=True),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "source_key",
                    models.CharField(blank=True, editable=False, max_length=64, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "capital_cost_gbp",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=16, null=True),
                ),
                ("fees_gbp", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                (
                    "broker",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="ledger.broker",
                    ),
                ),
                (
                    "security",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="ledger.security",
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
        migrations.AddConstraint(
            model_name="purchase",
            constraint=models.UniqueConstraint(
                condition=Q(("source_key__isnull", False)),
                fields=("workspace", "source_key"),
                name="unique_imported_purchase",
            ),
        ),
    ]
