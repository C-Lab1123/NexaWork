from django.db import migrations, models
from django.db.models import Q


def ensure_single_company(apps, schema_editor):
    Organization = apps.get_model("organization", "Organization")
    if Organization.objects.count() > 1:
        raise RuntimeError(
            "This NexaWork installation now supports one company. "
            "Choose and retain one company before applying this migration."
        )
    Organization.objects.update(is_single_company=True)


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0002_branch_is_active_department_is_active_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="is_single_company",
            field=models.BooleanField(null=True, editable=False),
        ),
        migrations.RunPython(ensure_single_company, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="organization",
            name="is_single_company",
            field=models.BooleanField(default=True, editable=False, unique=True),
        ),
        migrations.AddConstraint(
            model_name="organization",
            constraint=models.CheckConstraint(
                check=Q(is_single_company=True),
                name="organization_is_single_company",
            ),
        ),
    ]
