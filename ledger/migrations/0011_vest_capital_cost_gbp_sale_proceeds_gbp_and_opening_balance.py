import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ledger", "0010_vest_security_sale_security")]

    operations = [
        migrations.AddField(
            model_name="vest",
            name="capital_cost_gbp",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Total allowable CGT acquisition cost for the shares acquired, if evidenced.",
                max_digits=16,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="sale",
            name="proceeds_gbp",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Net disposal proceeds in GBP, if evidenced directly.",
                max_digits=16,
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="Section104OpeningBalance",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("effective_on", models.DateField()),
                ("units", models.DecimalField(decimal_places=4, max_digits=16)),
                ("pool_cost_gbp", models.DecimalField(decimal_places=2, max_digits=16)),
                ("source_url", models.URLField(blank=True)),
                ("notes", models.TextField(blank=True)),
                (
                    "security",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="opening_balances",
                        to="ledger.security",
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="opening_balances",
                        to="ledger.workspace",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("workspace", "security"),
                        name="unique_workspace_security_opening_balance",
                    )
                ]
            },
        ),
    ]
