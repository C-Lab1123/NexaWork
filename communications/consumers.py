from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.urls import reverse
from django.utils import timezone

from governance.services import has_permission
from accounts.models import User
from .models import Channel, Meeting, MeetingChatMessage, MeetingParticipant, Message
from .notifications import notification_service


class ChannelConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.channel_id = self.scope["url_route"]["kwargs"]["channel_id"]
        access = await self.authorize_channel()
        if not access:
            await self.close(code=4403)
            return
        self.organization_id = access
        self.channel_group = f"nexawork.channel.{self.channel_id}"
        self.presence_group = f"nexawork.presence.{self.organization_id}"
        await self.channel_layer.group_add(self.channel_group, self.channel_name)
        await self.channel_layer.group_add(self.presence_group, self.channel_name)
        await self.accept()
        await self.channel_layer.group_send(
            self.presence_group,
            {
                "type": "presence.event",
                "event": {
                    "type": "user.online",
                    "user_id": self.user.pk,
                    "name": self.user.get_full_name() or self.user.employee_id,
                },
            },
        )

    async def disconnect(self, close_code):
        if getattr(self, "channel_group", None):
            await self.channel_layer.group_discard(self.channel_group, self.channel_name)
            await self.channel_layer.group_discard(self.presence_group, self.channel_name)
            await self.channel_layer.group_send(
                self.presence_group,
                {
                    "type": "presence.event",
                    "event": {
                        "type": "user.offline",
                        "user_id": self.user.pk,
                        "name": self.user.get_full_name() or self.user.employee_id,
                    },
                },
            )

    async def receive_json(self, content, **kwargs):
        event_type = content.get("type")
        if event_type == "message.send":
            body = content.get("body")
            if not isinstance(body, str) or not body.strip() or len(body) > 4000:
                await self.send_json({"type": "error", "detail": "Messages must contain 1–4000 characters."})
                return
            reply_to_id = content.get("reply_to")
            if reply_to_id is not None and (
                isinstance(reply_to_id, bool) or not isinstance(reply_to_id, int)
            ):
                await self.send_json({"type": "error", "detail": "Invalid reply target."})
                return
            message = await self.create_message(body.strip(), reply_to_id)
            if message["type"] == "error":
                await self.send_json(message)
                return
            await self.channel_layer.group_send(
                self.channel_group,
                {"type": "chat.message", "message": message},
            )
        elif event_type in {"typing.started", "typing.stopped"}:
            await self.channel_layer.group_send(
                self.channel_group,
                {
                    "type": "chat.typing",
                    "user_id": self.user.pk,
                    "name": self.user.get_full_name() or self.user.employee_id,
                    "typing": event_type == "typing.started",
                },
            )
        else:
            await self.send_json({"type": "error", "detail": "Unsupported event type."})

    async def chat_message(self, event):
        await self.send_json(event["message"])

    async def chat_event(self, event):
        await self.send_json(event["event"])
        if event["event"].get("type") == "channel.archived":
            await self.close(code=4403)

    async def chat_typing(self, event):
        if event["user_id"] != self.user.pk:
            await self.send_json(
                {
                    "type": "typing",
                    "user_id": event["user_id"],
                    "name": event["name"],
                    "typing": event["typing"],
                }
            )

    async def presence_event(self, event):
        if event["event"]["user_id"] != self.user.pk:
            await self.send_json(event["event"])

    @database_sync_to_async
    def authorize_channel(self):
        if not self.user.is_authenticated or not self.user.is_active or self.user.is_suspended:
            return None
        channel = (
            Channel.objects.select_related("organization")
            .filter(pk=self.channel_id, organization__is_active=True, archived_at__isnull=True)
            .first()
        )
        if not channel or channel.organization_id != self.user.organization_id:
            return None
        if channel.kind != Channel.Kind.PUBLIC and not channel.members.filter(pk=self.user.pk).exists():
            return None
        return channel.organization_id

    @database_sync_to_async
    def create_message(self, body, reply_to_id=None):
        if not has_permission(self.user, "MESSAGE_SEND"):
            return {"type": "error", "detail": "You do not have permission to send messages."}
        if not Channel.objects.filter(pk=self.channel_id, archived_at__isnull=True).exists():
            return {"type": "error", "detail": "This channel is archived and read-only."}
        reply_to = None
        if reply_to_id is not None:
            reply_to = (
                Message.objects.select_related("author")
                .filter(
                    pk=reply_to_id,
                    channel_id=self.channel_id,
                    deleted_at__isnull=True,
                )
                .first()
            )
            if not reply_to:
                return {"type": "error", "detail": "Invalid reply target."}
        message = Message.objects.create(
            channel_id=self.channel_id, author=self.user, body=body, reply_to=reply_to
        )
        member_ids = list(
            Channel.objects.get(pk=self.channel_id)
            .members.exclude(pk=self.user.pk)
            .filter(is_active=True)
            .values_list("pk", flat=True)
        )
        notification_service.create_many(
            User.objects.filter(pk__in=member_ids),
            "New channel message",
            f"{self.user.get_full_name() or self.user.employee_id}: {body[:420]}",
            f"/channels/{self.channel_id}/",
        )
        return {
            "type": "message.created",
            "id": message.pk,
            "author": self.user.get_full_name() or self.user.employee_id,
            "profile_photo_url": (
                reverse("profile_photo", args=[self.user.pk]) if self.user.profile_picture else None
            ),
            "body": message.body,
            "reply_to": (
                {
                    "id": reply_to.pk,
                    "author": reply_to.author.get_full_name() or reply_to.author.employee_id,
                    "body": reply_to.body,
                }
                if reply_to
                else None
            ),
            "created_at": timezone.localtime(message.created_at).strftime("%H:%M"),
            "mine": True,
            "seen_count": 0,
        }


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if not await self.is_allowed():
            await self.close(code=4403)
            return
        self.notification_group = f"nexawork.notifications.{self.user.pk}"
        await self.channel_layer.group_add(self.notification_group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if getattr(self, "notification_group", None):
            await self.channel_layer.group_discard(self.notification_group, self.channel_name)

    async def notification_created(self, event):
        await self.send_json({"type": "notification.created", **event["notification"]})

    @database_sync_to_async
    def is_allowed(self):
        return bool(
            self.user.is_authenticated
            and self.user.is_active
            and not self.user.is_suspended
            and self.user.organization_id
            and self.user.organization.is_active
        )


class MeetingChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.meeting_id = self.scope["url_route"]["kwargs"]["meeting_id"]
        if not await self.is_allowed():
            await self.close(code=4403)
            return
        self.chat_group = f"nexawork.meeting_chat.{self.meeting_id}"
        await self.channel_layer.group_add(self.chat_group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if getattr(self, "chat_group", None):
            await self.channel_layer.group_discard(self.chat_group, self.channel_name)

    async def meeting_chat_message(self, event):
        await self.send_json(event["message"])

    @database_sync_to_async
    def is_allowed(self):
        return bool(
            self.user.is_authenticated
            and self.user.is_active
            and not self.user.is_suspended
            and self.user.organization_id
            and MeetingParticipant.objects.filter(
                meeting_id=self.meeting_id,
                meeting__organization_id=self.user.organization_id,
                meeting__organization__is_active=True,
                user=self.user,
                status=MeetingParticipant.Status.JOINED,
            ).exists()
        )
