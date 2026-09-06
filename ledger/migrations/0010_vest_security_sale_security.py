import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ledger", "0009_link_stock_prices_to_security")]

    operations = [
        migrations.AddField(
            model_name="vest",
            name="security",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="ledger.security",
            ),
        ),
        migrations.AddField(
            model_name="sale",
            name="security",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="ledger.security",
            ),
        ),
    ]
