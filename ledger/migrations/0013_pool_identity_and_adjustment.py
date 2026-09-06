import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ledger", "0012_purchase")]

    operations = [
        migrations.AddField(
            model_name="grant",
            name="beneficial_owner",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="grant",
            name="capacity",
            field=models.CharField(default="personal", max_length=40),
        ),
        migrations.AddField(
            model_name="grant",
            name="account_reference",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="vest",
            name="beneficial_owner",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="vest",
            name="capacity",
            field=models.CharField(default="personal", max_length=40),
        ),
        migrations.AddField(
            model_name="vest",
            name="account_reference",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="sale",
            name="beneficial_owner",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="sale",
            name="capacity",
            field=models.CharField(default="personal", max_length=40),
        ),
        migrations.AddField(
            model_name="sale",
            name="account_reference",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="purchase",
            name="beneficial_owner",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="purchase",
            name="capacity",
            field=models.CharField(default="personal", max_length=40),
        ),
        migrations.AddField(
            model_name="purchase",
            name="account_reference",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.CreateModel(
            name="PoolAdjustment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("effective_on", models.DateField()),
                ("units_delta", models.DecimalField(decimal_places=4, default=0, max_digits=16)),
                ("cost_delta_gbp", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("reason", models.CharField(max_length=160)),
                ("source_url", models.URLField(blank=True)),
                ("notes", models.TextField(blank=True)),
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
