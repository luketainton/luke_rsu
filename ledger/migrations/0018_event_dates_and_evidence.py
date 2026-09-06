from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ledger", "0017_section104_snapshot")]

    operations = []
    for model_name in ("grant", "vest", "sale", "purchase"):
        operations.extend(
            [
                migrations.AddField(
                    model_name=model_name,
                    name="contract_date",
                    field=models.DateField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name=model_name,
                    name="evidence_url",
                    field=models.URLField(blank=True),
                ),
            ]
        )
