from django.db import migrations, models
from django.db.models import F, Q
from django.utils import timezone


def mark_existing_announcements_as_notified(apps, schema_editor):
    Announcement = apps.get_model("communications", "Announcement")
    now = timezone.now()
    Announcement.objects.exclude(
        Q(publish_at__gt=now)
        & (Q(expires_at__isnull=True) | Q(expires_at__gt=F("publish_at")))
    ).update(notifications_sent_at=F("created_at"))


class Migration(migrations.Migration):

    dependencies = [
        ("communications", "0004_meetingparticipant_reminder_sent_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="announcement",
            name="notifications_sent_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(
            mark_existing_announcements_as_notified,
            migrations.RunPython.noop,
        ),
    ]
