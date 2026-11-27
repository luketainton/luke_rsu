from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ledger", "0019_mcpapikey")]

    operations = [
        migrations.AddField(
            model_name="mcpapikey",
            name="allow_write",
            field=models.BooleanField(default=False),
        )
    ]
