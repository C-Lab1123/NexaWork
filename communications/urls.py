from django.urls import path

from . import views

urlpatterns = [
    path("integrations/livekit/webhook/", views.livekit_webhook, name="livekit_webhook"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("channels/", views.channel_list, name="channel_list"),
    path("channels/<int:channel_id>/", views.channel_detail, name="channel_detail"),
    path("channels/<int:channel_id>/messages/", views.channel_messages, name="channel_messages"),
    path("channels/<int:channel_id>/read/", views.channel_read, name="channel_read"),
    path("messages/direct/<int:user_id>/", views.direct_message, name="direct_message"),
    path("messages/<int:message_id>/edit/", views.message_edit, name="message_edit"),
    path("messages/<int:message_id>/delete/", views.message_delete, name="message_delete"),
    path("messages/<int:message_id>/reactions/", views.message_reaction, name="message_reaction"),
    path("announcements/", views.announcements, name="announcements"),
    path("meetings/", views.meeting_list, name="meeting_list"),
    path("meetings/updates/", views.meeting_updates, name="meeting_updates"),
    path("meetings/<int:meeting_id>/", views.meeting_detail, name="meeting_detail"),
    path("meetings/<int:meeting_id>/chat/", views.meeting_chat_api, name="meeting_chat_api"),
    path("meetings/<int:meeting_id>/end/", views.meeting_end, name="meeting_end"),
    path("meetings/<int:meeting_id>/leave/", views.meeting_leave, name="meeting_leave"),
    path("meetings/<int:meeting_id>/lock/", views.meeting_lock, name="meeting_lock"),
    path(
        "meetings/<int:meeting_id>/participants/<int:user_id>/promote/",
        views.meeting_promote,
        name="meeting_promote",
    ),
    path(
        "meetings/<int:meeting_id>/participants/<int:user_id>/mute/",
        views.meeting_mute_participant,
        name="meeting_mute_participant",
    ),
    path(
        "meetings/<int:meeting_id>/participants/<int:user_id>/remove/",
        views.remove_meeting_participant,
        name="remove_meeting_participant",
    ),
    path(
        "notifications/",
        views.notification_list,
        name="notification_list",
    ),
    path(
        "notifications/updates/",
        views.notification_updates,
        name="notification_updates",
    ),
    path(
        "notifications/<int:notification_id>/read/",
        views.mark_notification_read,
        name="mark_notification_read",
    ),
]
