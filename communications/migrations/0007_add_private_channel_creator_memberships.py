from django.db import migrations


def add_private_channel_creator_memberships(apps, schema_editor):
    Channel = apps.get_model("communications", "Channel")
    ChannelMembership = apps.get_model("communications", "ChannelMembership")
    database = schema_editor.connection.alias
    memberships = (
        ChannelMembership(channel_id=channel_id, user_id=creator_id)
        for channel_id, creator_id in (
            Channel.objects.using(database)
            .filter(kind="private", created_by__isnull=False)
            .values_list("pk", "created_by_id")
            .iterator()
        )
    )
    ChannelMembership.objects.using(database).bulk_create(
        memberships,
        batch_size=500,
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("communications", "0006_channel_archived_at"),
    ]

    operations = [
        migrations.RunPython(
            add_private_channel_creator_memberships,
            migrations.RunPython.noop,
        ),
    ]
