import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Channel(models.Model):
    class Kind(models.TextChoices):
        PUBLIC = "public", "Organization"
        PRIVATE = "private", "Private"
        DIRECT = "direct", "Direct message"

    organization = models.ForeignKey("organization.Organization", on_delete=models.CASCADE, related_name="channels")
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=240, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PUBLIC)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_channels")
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, through="ChannelMembership", related_name="channels")
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_channel_name_per_org")
        ]

    def __str__(self):
        return self.name


class ChannelMembership(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="channel_memberships")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["channel", "user"], name="unique_channel_member")]


class Message(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages")
    body = models.TextField(max_length=4000)
    reply_to = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies")
    attachments = models.ManyToManyField("documents.WorkplaceFile", blank=True, related_name="messages")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]


class MessageRead(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="read_receipts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="message_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["message", "user"], name="unique_message_read")]


class MessageReaction(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="message_reactions")
    emoji = models.CharField(max_length=16)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["message", "user", "emoji"], name="unique_message_reaction")
        ]


class Announcement(models.Model):
    organization = models.ForeignKey("organization.Organization", on_delete=models.CASCADE, related_name="announcements")
    branch = models.ForeignKey(
        "organization.Branch", on_delete=models.CASCADE, null=True, blank=True, related_name="announcements"
    )
    region = models.ForeignKey(
        "organization.Region", on_delete=models.CASCADE, null=True, blank=True, related_name="announcements"
    )
    department = models.ForeignKey(
        "organization.Department", on_delete=models.CASCADE, null=True, blank=True, related_name="announcements"
    )
    team = models.ForeignKey(
        "organization.Team", on_delete=models.CASCADE, null=True, blank=True, related_name="announcements"
    )
    title = models.CharField(max_length=180)
    body = models.TextField()
    priority = models.CharField(
        max_length=10,
        choices=[("normal", "Normal"), ("important", "Important"), ("urgent", "Urgent")],
        default="normal",
    )
    publish_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    notifications_sent_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="announcements")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class AnnouncementRead(models.Model):
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="read_receipts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="announcement_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["announcement", "user"], name="unique_announcement_read")
        ]


class Meeting(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        WAITING = "waiting", "Waiting"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey("organization.Organization", on_delete=models.CASCADE, related_name="meetings")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hosted_meetings")
    provider_url = models.URLField(blank=True, help_text="Optional meeting room URL from an approved conferencing provider.")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED, db_index=True)
    meeting_type = models.CharField(
        max_length=8, choices=[("video", "Video"), ("audio", "Audio")], default="video"
    )
    meeting_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    password_hash = models.CharField(max_length=128, blank=True)
    is_locked = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    actual_duration_seconds = models.PositiveIntegerField(default=0)
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="MeetingParticipant", related_name="meetings"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at"]

    def __str__(self):
        return self.title


class MeetingParticipant(models.Model):
    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        JOINED = "joined", "Joined"
        LEFT = "left", "Left"
        REMOVED = "removed", "Removed"

    class Role(models.TextChoices):
        HOST = "host", "Host"
        COHOST = "cohost", "Co-host"
        PARTICIPANT = "participant", "Participant"

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="participant_records")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="meeting_records")
    invited_at = models.DateTimeField(default=timezone.now, editable=False)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    removed_until = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.INVITED)
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.PARTICIPANT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["meeting", "user"], name="unique_meeting_participant")]


class MeetingEvent(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="meeting_events"
    )
    event_type = models.CharField(max_length=32, db_index=True)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_target_events",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class MeetingChatMessage(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="chat_messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="meeting_chat_messages")
    reply_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies"
    )
    body = models.CharField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "pk"]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=180)
    body = models.CharField(max_length=500)
    url = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
