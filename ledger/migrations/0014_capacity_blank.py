from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ledger", "0013_pool_identity_and_adjustment")]

    operations = [
        migrations.AlterField(
            model_name="grant",
            name="capacity",
            field=models.CharField(blank=True, default="personal", max_length=40),
        ),
        migrations.AlterField(
            model_name="vest",
            name="capacity",
            field=models.CharField(blank=True, default="personal", max_length=40),
        ),
        migrations.AlterField(
            model_name="sale",
            name="capacity",
            field=models.CharField(blank=True, default="personal", max_length=40),
        ),
        migrations.AlterField(
            model_name="purchase",
            name="capacity",
            field=models.CharField(blank=True, default="personal", max_length=40),
        ),
    ]
