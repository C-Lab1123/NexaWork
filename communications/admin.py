from django.contrib import admin

from .models import (
    Announcement,
    Channel,
    ChannelMembership,
    Meeting,
    MeetingParticipant,
    Message,
    Notification,
)

admin.site.register([Channel, ChannelMembership, Message, Announcement, Meeting, MeetingParticipant, Notification])
