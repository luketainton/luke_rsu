from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ledger", "0015_sell_to_cover")]

    operations = [
        migrations.AlterField(
            model_name="vest",
            name="withholding_treatment",
            field=models.CharField(
                blank=True,
                choices=[
                    ("net", "Net shares acquired (legacy/default)"),
                    ("gross_sell_to_cover", "Gross shares acquired; withheld shares sold to cover"),
                ],
                default="net",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="vest",
            name="sell_to_cover_fees_gbp",
            field=models.DecimalField(blank=True, decimal_places=2, default=0, max_digits=16),
        ),
        migrations.AlterField(
            model_name="vest",
            name="sell_to_cover_proceeds_gbp",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Net GBP proceeds for the withheld-share sell-to-cover disposal, if evidenced.",
                max_digits=16,
                null=True,
            ),
        ),
    ]
