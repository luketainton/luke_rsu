import django.db.models.deletion
from django.db import migrations, models


def link_stock_prices_to_securities(apps, schema_editor):
    grant_model = apps.get_model("ledger", "Grant")
    stock_price_model = apps.get_model("ledger", "StockPrice")
    security_model = apps.get_model("ledger", "Security")
    for grant in grant_model.objects.filter(security__isnull=True).exclude(ticker="").iterator():
        security, _ = security_model.objects.get_or_create(
            workspace_id=grant.workspace_id,
            ticker=grant.ticker,
            share_class="",
            defaults={"name": grant.ticker},
        )
        grant.security_id = security.id
        grant.save(update_fields=["security"])
    for price in stock_price_model.objects.all().iterator():
        security, _ = security_model.objects.get_or_create(
            workspace_id=price.workspace_id,
            ticker=price.ticker,
            share_class="",
            defaults={"name": price.ticker},
        )
        price.security_id = security.id
        price.save(update_fields=["security"])


class Migration(migrations.Migration):
    # PostgreSQL cannot alter a table while FK trigger events from the
    # backfill above are still pending in the same transaction.
    atomic = False

    dependencies = [("ledger", "0008_security_grant_security_and_more")]

    operations = [
        migrations.AddField(
            model_name="stockprice",
            name="security",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="stock_prices",
                to="ledger.security",
            ),
        ),
        migrations.RunPython(link_stock_prices_to_securities, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="stockprice",
            name="unique_workspace_ticker_price_date_source",
        ),
        migrations.RemoveField(model_name="grant", name="ticker"),
        migrations.RemoveField(model_name="stockprice", name="ticker"),
        migrations.AlterField(
            model_name="stockprice",
            name="security",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="stock_prices",
                to="ledger.security",
            ),
        ),
        migrations.AlterModelOptions(
            name="stockprice",
            options={"ordering": ["security__ticker", "-price_date"]},
        ),
        migrations.AddConstraint(
            model_name="stockprice",
            constraint=models.UniqueConstraint(
                fields=("workspace", "security", "price_date", "source"),
                name="unique_workspace_security_price_date_source",
            ),
        ),
    ]
