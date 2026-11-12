from django.urls import path

from .consumers import ChannelConsumer, MeetingChatConsumer, NotificationConsumer

websocket_urlpatterns = [
    path("ws/channels/<int:channel_id>/", ChannelConsumer.as_asgi()),
    path("ws/meetings/<int:meeting_id>/chat/", MeetingChatConsumer.as_asgi()),
    path("ws/notifications/", NotificationConsumer.as_asgi()),
]
