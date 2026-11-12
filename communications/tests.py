import tempfile
from datetime import timedelta
from unittest.mock import patch

import jwt
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from organization.models import Organization

from .media import LiveKitMediaProvider
from .models import (
    Channel,
    ChannelMembership,
    Announcement,
    Meeting,
    MeetingChatMessage,
    MeetingEvent,
    MeetingParticipant,
    Message,
    MessageRead,
    Notification,
)
from .routing import websocket_urlpatterns
from .notifications import notification_service


class CommunicationAccessTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Nexa Labs", slug="nexa-labs")
        self.other_organization = self.organization
        self.employee = User.objects.create_user(
            employee_id="NW-1", password="SecurePassword!123", organization=self.organization
        )
        self.colleague = User.objects.create_user(
            employee_id="NW-2", password="SecurePassword!123", organization=self.organization
        )
        self.other_employee = User.objects.create_user(
            employee_id="NW-3", password="SecurePassword!123", organization=self.other_organization
        )
        self.public_channel = Channel.objects.create(
            organization=self.organization, name="announcements", kind=Channel.Kind.PUBLIC
        )
        self.private_channel = Channel.objects.create(
            organization=self.organization, name="leadership", kind=Channel.Kind.PRIVATE
        )

    def test_public_channel_messages_post_and_poll(self):
        self.client.force_login(self.employee)
        response = self.client.post(
            reverse("channel_detail", args=[self.public_channel.pk]),
            {"body": "Hello, team"},
        )
        self.assertRedirects(response, reverse("channel_detail", args=[self.public_channel.pk]))
        message = Message.objects.get(channel=self.public_channel)
        self.assertEqual(message.author, self.employee)

        response = self.client.get(
            reverse("channel_messages", args=[self.public_channel.pk]), {"after": 0}
        )
        self.assertEqual(response.json()["messages"][0]["body"], "Hello, team")

    def test_channel_message_api_post_persists_and_broadcasts_message(self):
        self.client.force_login(self.employee)

        with patch("communications.views._broadcast_channel_event") as broadcast:
            response = self.client.post(
                reverse("channel_messages", args=[self.public_channel.pk]),
                {"body": "Posted over HTTP"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["type"], "message.created")
        self.assertEqual(response.json()["body"], "Posted over HTTP")
        self.assertTrue(response.json()["mine"])
        message = Message.objects.get(channel=self.public_channel)
        self.assertEqual(message.author, self.employee)
        broadcast.assert_called_once()
        self.assertEqual(broadcast.call_args.args[0], self.public_channel.pk)
        self.assertEqual(broadcast.call_args.args[1]["id"], message.pk)

    def test_channel_messages_support_quoted_replies_and_reject_other_channel_targets(self):
        original = Message.objects.create(
            channel=self.public_channel,
            author=self.colleague,
            body="The launch is at noon.",
        )
        other_channel = Channel.objects.create(organization=self.organization, name="other")
        other_message = Message.objects.create(
            channel=other_channel,
            author=self.colleague,
            body="Not in this conversation.",
        )
        self.client.force_login(self.employee)

        with patch("communications.views._broadcast_channel_event") as broadcast:
            response = self.client.post(
                reverse("channel_messages", args=[self.public_channel.pk]),
                {"body": "I will be there.", "reply_to": str(original.pk)},
            )
        reply = Message.objects.get(body="I will be there.")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(reply.reply_to, original)
        self.assertEqual(
            response.json()["reply_to"],
            {
                "id": original.pk,
                "author": self.colleague.get_full_name() or self.colleague.employee_id,
                "body": "The launch is at noon.",
            },
        )
        self.assertEqual(broadcast.call_args.args[1]["reply_to"], response.json()["reply_to"])

        invalid = self.client.post(
            reverse("channel_messages", args=[self.public_channel.pk]),
            {"body": "Cross-channel reply", "reply_to": str(other_message.pk)},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(Message.objects.filter(body="Cross-channel reply").exists())

        page = self.client.get(reverse("channel_detail", args=[self.public_channel.pk]))
        self.assertContains(page, "The launch is at noon.")
        self.assertContains(page, "I will be there.")
        self.assertContains(page, "Reply")

    def test_channel_read_receipts_are_created_once_and_counted_for_message_authors(self):
        own_message = Message.objects.create(
            channel=self.public_channel,
            author=self.employee,
            body="Please review this.",
        )
        incoming_message = Message.objects.create(
            channel=self.public_channel,
            author=self.colleague,
            body="I will review it.",
        )
        self.client.force_login(self.employee)
        endpoint = reverse("channel_read", args=[self.public_channel.pk])

        page = self.client.get(reverse("channel_detail", args=[self.public_channel.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "list.querySelectorAll(\"[data-message-id]\").forEach(observeMessage)")
        self.assertFalse(MessageRead.objects.filter(message=incoming_message).exists())

        with patch("communications.views._broadcast_channel_event") as broadcast:
            response = self.client.post(
                endpoint,
                {"message_ids": [str(own_message.pk), str(incoming_message.pk)]},
            )
            duplicate = self.client.post(
                endpoint,
                {"message_ids": [str(incoming_message.pk)]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["seen_message_ids"], [incoming_message.pk])
        self.assertEqual(duplicate.json()["seen_message_ids"], [])
        self.assertFalse(MessageRead.objects.filter(message=own_message).exists())
        self.assertTrue(
            MessageRead.objects.filter(message=incoming_message, user=self.employee).exists()
        )
        broadcast.assert_called_once()
        self.assertEqual(broadcast.call_args.args[1]["type"], "messages.seen")

        self.client.force_login(self.colleague)
        self.client.post(endpoint, {"message_ids": [str(own_message.pk)]})
        self.client.force_login(self.employee)
        page = self.client.get(reverse("channel_detail", args=[self.public_channel.pk]))
        self.assertContains(page, "Seen by 1")
        sync = self.client.get(
            reverse("channel_messages", args=[self.public_channel.pk]), {"after": 0}
        )
        self.assertEqual(sync.json()["seen_counts"][str(own_message.pk)], 1)

    def test_channel_message_api_rejects_invalid_body_and_cursor(self):
        self.client.force_login(self.employee)

        invalid_body = self.client.post(
            reverse("channel_messages", args=[self.public_channel.pk]),
            {"body": "   "},
        )
        invalid_cursor = self.client.get(
            reverse("channel_messages", args=[self.public_channel.pk]), {"after": "invalid"}
        )

        self.assertEqual(invalid_body.status_code, 400)
        self.assertIn("error", invalid_body.json())
        self.assertEqual(invalid_cursor.status_code, 400)
        self.assertIn("error", invalid_cursor.json())
        self.assertFalse(Message.objects.filter(channel=self.public_channel).exists())

    def test_channel_detail_uses_reconnecting_chat_client(self):
        self.client.force_login(self.employee)

        response = self.client.get(reverse("channel_detail", args=[self.public_channel.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reconnecting; syncing messages")
        self.assertContains(response, "Message sync failed")
        self.assertContains(response, "Message not sent:")

    def test_channel_message_avatars_use_profile_photos_in_history_polling_and_live_events(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.employee.profile_picture.save(
                "employee.png",
                SimpleUploadedFile("employee.png", b"\x89PNG\r\n\x1a\nprofile image"),
            )
            message = Message.objects.create(
                channel=self.public_channel,
                author=self.employee,
                body="Photo in conversation",
            )
            photo_url = reverse("profile_photo", args=[self.employee.pk])
            self.client.force_login(self.colleague)

            page = self.client.get(reverse("channel_detail", args=[self.public_channel.pk]))
            self.assertContains(page, f'<img src="{photo_url}" alt="">', html=True)

            history = self.client.get(
                reverse("channel_messages", args=[self.public_channel.pk]), {"after": 0}
            )
            self.assertEqual(history.status_code, 200)
            self.assertEqual(history.json()["messages"][0]["profile_photo_url"], photo_url)

            self.client.force_login(self.employee)
            with patch("communications.views._broadcast_channel_event") as broadcast:
                live = self.client.post(
                    reverse("channel_messages", args=[self.public_channel.pk]),
                    {"body": "Live photo"},
                )

            self.assertEqual(live.status_code, 201)
            self.assertEqual(live.json()["profile_photo_url"], photo_url)
            self.assertEqual(broadcast.call_args.args[1]["profile_photo_url"], photo_url)
            self.assertTrue(Message.objects.filter(pk=message.pk).exists())

    def test_archived_channel_is_hidden_but_history_is_read_only(self):
        self.public_channel.archived_at = timezone.now()
        self.public_channel.save(update_fields=["archived_at"])
        message = Message.objects.create(
            channel=self.public_channel,
            author=self.employee,
            body="Preserved history",
        )
        self.client.force_login(self.employee)

        channel_list = self.client.get(reverse("channel_list"))
        detail = self.client.get(reverse("channel_detail", args=[self.public_channel.pk]))
        send = self.client.post(
            reverse("channel_messages", args=[self.public_channel.pk]),
            {"body": "Should not be saved"},
        )
        edit = self.client.post(
            reverse("message_edit", args=[message.pk]),
            {"body": "Should not edit"},
        )
        delete = self.client.post(reverse("message_delete", args=[message.pk]))
        react = self.client.post(
            reverse("message_reaction", args=[message.pk]),
            {"emoji": "👍"},
        )

        self.assertNotContains(
            channel_list,
            reverse("channel_detail", args=[self.public_channel.pk]),
        )
        self.assertContains(detail, "Archived · read only")
        self.assertContains(detail, "Preserved history")
        self.assertNotContains(detail, "chat-compose")
        self.assertEqual(send.status_code, 409)
        self.assertEqual(edit.status_code, 409)
        self.assertEqual(delete.status_code, 409)
        self.assertEqual(react.status_code, 409)
        message.refresh_from_db()
        self.assertEqual(message.body, "Preserved history")
        self.assertIsNone(message.deleted_at)
        self.assertFalse(message.reactions.exists())

    def test_private_channel_requires_membership(self):
        self.client.force_login(self.employee)
        self.assertEqual(
            self.client.get(reverse("channel_detail", args=[self.private_channel.pk])).status_code,
            404,
        )
        ChannelMembership.objects.create(channel=self.private_channel, user=self.employee)
        self.assertEqual(
            self.client.get(reverse("channel_detail", args=[self.private_channel.pk])).status_code,
            200,
        )

    def test_user_cannot_access_a_missing_channel(self):
        self.client.force_login(self.employee)
        self.assertEqual(
            self.client.get(reverse("channel_detail", args=[999999])).status_code,
            404,
        )

    def test_host_can_remove_a_participant_and_rejoin_is_delayed(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Planning",
            starts_at=timezone.now() + timedelta(hours=1),
            host=self.employee,
        )
        participant = MeetingParticipant.objects.create(meeting=meeting, user=self.colleague)
        self.client.force_login(self.employee)
        with patch("communications.media.media_provider.remove_participant"):
            response = self.client.post(
                reverse("remove_meeting_participant", args=[meeting.pk, self.colleague.pk])
            )
        self.assertRedirects(response, reverse("meeting_detail", args=[meeting.pk]))
        participant.refresh_from_db()
        self.assertGreater(participant.removed_until, timezone.now())
        self.client.force_login(self.colleague)
        response = self.client.post(
            reverse("meeting_detail", args=[meeting.pk]), {"action": "join"}
        )
        self.assertRedirects(response, reverse("meeting_list"))
        participant.refresh_from_db()
        self.assertGreater(participant.removed_until, timezone.now())

    def test_meeting_detail_page_renders_for_an_employee(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Planning",
            starts_at=timezone.now() + timedelta(hours=1),
            host=self.employee,
        )
        self.client.force_login(self.employee)
        response = self.client.get(reverse("meeting_detail", args=[meeting.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Join when ready")
        response = self.client.post(
            reverse("meeting_detail", args=[meeting.pk]), {"action": "join"}
        )
        self.assertRedirects(response, reverse("meeting_detail", args=[meeting.pk]))
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, Meeting.Status.ACTIVE)
        self.assertTrue(meeting.participant_records.filter(user=self.employee).exists())

    def test_audio_meeting_has_audio_recovery_control_without_camera(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Audio check-in",
            starts_at=timezone.now(),
            host=self.employee,
            meeting_type="audio",
        )
        self.client.force_login(self.employee)
        self.client.post(
            reverse("meeting_detail", args=[meeting.pk]), {"action": "join"}
        )

        with patch(
            "communications.media.media_provider.join_configuration",
            return_value={"url": "wss://example.test", "token": "test-token"},
        ):
            response = self.client.get(reverse("meeting_detail", args=[meeting.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="enable-audio"')
        self.assertContains(response, "Enable audio")
        self.assertContains(response, "Use headphones")
        self.assertNotContains(response, 'id="toggle-camera"')
        self.assertContains(response, "Waiting for live call connection")
        self.assertContains(response, "/static/js/meeting-room.js?v=4")

    @override_settings(
        LIVEKIT_API_KEY="test-api-key",
        LIVEKIT_API_SECRET="test-livekit-secret-at-least-32-bytes-long",
        LIVEKIT_PUBLIC_URL="wss://meetings.example.test",
        LIVEKIT_INTERNAL_URL="https://meetings.example.test",
    )
    def test_livekit_join_token_allows_two_way_participant_media(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="LiveKit test",
            starts_at=timezone.now(),
            host=self.employee,
        )
        configuration = LiveKitMediaProvider().join_configuration(meeting, self.employee)
        claims = jwt.decode(
            configuration["token"],
            "test-livekit-secret-at-least-32-bytes-long",
            algorithms=["HS256"],
            issuer="test-api-key",
        )

        self.assertEqual(configuration["url"], "wss://meetings.example.test")
        self.assertEqual(claims["video"]["room"], str(meeting.meeting_id))
        self.assertTrue(claims["video"]["roomJoin"])
        self.assertTrue(claims["video"]["canPublish"])
        self.assertTrue(claims["video"]["canSubscribe"])

    def test_meeting_chat_returns_only_messages_after_cursor(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Chat check-in",
            starts_at=timezone.now(),
            host=self.employee,
            status=Meeting.Status.ACTIVE,
        )
        MeetingParticipant.objects.create(
            meeting=meeting,
            user=self.employee,
            status=MeetingParticipant.Status.JOINED,
        )
        first_message = MeetingChatMessage.objects.create(
            meeting=meeting,
            author=self.colleague,
            body="Can everyone hear me?",
        )
        MeetingChatMessage.objects.create(
            meeting=meeting,
            author=self.employee,
            body="Yes, loud and clear.",
        )
        self.client.force_login(self.employee)

        response = self.client.get(
            reverse("meeting_chat_api", args=[meeting.pk]), {"after": first_message.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["messages"]), 1)
        self.assertEqual(response.json()["messages"][0]["body"], "Yes, loud and clear.")

        page = self.client.get(reverse("meeting_detail", args=[meeting.pk]))

        self.assertContains(page, f'data-message-id="{first_message.pk}"')
        self.assertContains(page, "Live updates connecting")
        self.assertContains(page, f"/ws/meetings/{meeting.pk}/chat/")
        self.assertContains(page, "new WebSocket")
        self.assertContains(page, '<button type="submit" class="button button-primary">Send</button>')
        self.assertContains(page, f'action="{reverse("meeting_chat_api", args=[meeting.pk])}"')

    def test_employee_can_send_meeting_chat_without_javascript(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Employee chat",
            starts_at=timezone.now(),
            host=self.colleague,
            status=Meeting.Status.ACTIVE,
        )
        MeetingParticipant.objects.create(
            meeting=meeting,
            user=self.employee,
            status=MeetingParticipant.Status.JOINED,
        )
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("meeting_chat_api", args=[meeting.pk]),
            {"body": "Sent by a regular employee."},
        )

        self.assertRedirects(response, reverse("meeting_detail", args=[meeting.pk]))
        message = MeetingChatMessage.objects.get(meeting=meeting)
        self.assertEqual(message.author, self.employee)
        self.assertEqual(message.body, "Sent by a regular employee.")

    def test_employee_meeting_list_includes_active_meeting_after_start_time(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Ongoing audio meeting",
            starts_at=timezone.now() - timedelta(minutes=5),
            host=self.colleague,
            meeting_type="audio",
            status=Meeting.Status.ACTIVE,
        )
        MeetingParticipant.objects.create(meeting=meeting, user=self.employee)
        self.client.force_login(self.employee)

        response = self.client.get(reverse("meeting_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ongoing audio meeting")

    def test_employee_meeting_list_includes_scheduled_meeting_past_start_until_started(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Late start audio meeting",
            starts_at=timezone.now() - timedelta(minutes=5),
            host=self.colleague,
            meeting_type="audio",
        )
        MeetingParticipant.objects.create(meeting=meeting, user=self.employee)
        self.client.force_login(self.employee)

        response = self.client.get(reverse("meeting_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Late start audio meeting")
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, Meeting.Status.SCHEDULED)

    def test_employee_can_poll_new_meetings_without_admin_starting_them(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Live audio meeting",
            starts_at=timezone.now() + timedelta(minutes=5),
            host=self.colleague,
            meeting_type="audio",
        )
        MeetingParticipant.objects.create(meeting=meeting, user=self.employee)
        self.client.force_login(self.employee)

        response = self.client.get(reverse("meeting_updates"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["meetings"][0]["id"], meeting.pk)
        self.assertEqual(response.json()["meetings"][0]["meeting_type"], "audio")
        self.assertEqual(meeting.status, Meeting.Status.SCHEDULED)

    def test_scheduled_meeting_is_visible_on_open_dashboard_and_poll_endpoint(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Live scheduled voice meeting",
            starts_at=timezone.now() - timedelta(minutes=5),
            host=self.colleague,
            meeting_type="audio",
        )
        MeetingParticipant.objects.create(meeting=meeting, user=self.employee)
        self.client.force_login(self.employee)

        dashboard = self.client.get(reverse("dashboard"))
        updates = self.client.get(reverse("meeting_updates"))

        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, "Live scheduled voice meeting")
        self.assertEqual(updates.status_code, 200)
        self.assertEqual(
            [item["id"] for item in updates.json()["meetings"]],
            [meeting.pk],
        )
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, Meeting.Status.SCHEDULED)

    def test_host_can_lock_and_unlock_meeting(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Planning",
            starts_at=timezone.now() + timedelta(hours=1),
            host=self.employee,
        )
        self.client.force_login(self.employee)

        response = self.client.post(reverse("meeting_lock", args=[meeting.pk]))

        self.assertRedirects(response, reverse("meeting_detail", args=[meeting.pk]))
        meeting.refresh_from_db()
        self.assertTrue(meeting.is_locked)
        self.assertTrue(MeetingEvent.objects.filter(meeting=meeting, event_type="locked").exists())

        self.client.post(reverse("meeting_lock", args=[meeting.pk]))
        meeting.refresh_from_db()
        self.assertFalse(meeting.is_locked)

    def test_host_can_promote_a_joined_meeting_participant(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Planning",
            starts_at=timezone.now() + timedelta(hours=1),
            host=self.employee,
        )
        participant = MeetingParticipant.objects.create(
            meeting=meeting,
            user=self.colleague,
            status=MeetingParticipant.Status.JOINED,
        )
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("meeting_promote", args=[meeting.pk, self.colleague.pk])
        )

        self.assertRedirects(response, reverse("meeting_detail", args=[meeting.pk]))
        participant.refresh_from_db()
        self.assertEqual(participant.role, MeetingParticipant.Role.COHOST)
        self.assertTrue(
            MeetingEvent.objects.filter(meeting=meeting, event_type="participant_role_changed").exists()
        )

    @patch("communications.views.media_provider.mute_participant", return_value=True)
    def test_host_can_mute_a_joined_participant(self, mute_participant):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Planning",
            starts_at=timezone.now() + timedelta(hours=1),
            host=self.employee,
        )
        MeetingParticipant.objects.create(
            meeting=meeting,
            user=self.colleague,
            status=MeetingParticipant.Status.JOINED,
        )
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("meeting_mute_participant", args=[meeting.pk, self.colleague.pk]),
            {"track_sid": "TR_audio", "muted": "true"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "muted": True})
        mute_participant.assert_called_once()
        self.assertTrue(
            MeetingEvent.objects.filter(meeting=meeting, event_type="participant_muted").exists()
        )

    @patch("communications.views.media_provider.mute_participant", return_value=False)
    def test_mute_does_not_report_success_without_a_media_provider(self, mute_participant):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Planning",
            starts_at=timezone.now() + timedelta(hours=1),
            host=self.employee,
        )
        MeetingParticipant.objects.create(
            meeting=meeting,
            user=self.colleague,
            status=MeetingParticipant.Status.JOINED,
        )
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("meeting_mute_participant", args=[meeting.pk, self.colleague.pk]),
            {"track_sid": "TR_audio", "muted": "true"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertFalse(MeetingEvent.objects.filter(meeting=meeting, event_type="participant_muted").exists())
        mute_participant.assert_called_once()

    def test_assistant_page_accepts_a_workplace_question(self):
        self.client.force_login(self.employee)
        response = self.client.post(
            reverse("assistant_home"), {"question": "Where can I find files?"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open Files")

    def test_employee_cannot_remove_a_meeting_participant(self):
        meeting = Meeting.objects.create(
            organization=self.organization,
            title="Planning",
            starts_at=timezone.now() + timedelta(hours=1),
            host=self.colleague,
        )
        MeetingParticipant.objects.create(meeting=meeting, user=self.other_employee)
        self.client.force_login(self.employee)
        response = self.client.post(
            reverse("remove_meeting_participant", args=[meeting.pk, self.other_employee.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_notifications_are_private_and_can_be_marked_read(self):
        notification = Notification.objects.create(user=self.employee, title="Update", body="Read this.")
        self.client.force_login(self.colleague)
        self.assertEqual(
            self.client.post(reverse("mark_notification_read", args=[notification.pk])).status_code,
            404,
        )
        self.client.force_login(self.employee)
        self.assertEqual(
            self.client.post(reverse("mark_notification_read", args=[notification.pk])).status_code,
            302,
        )
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_notification_updates_returns_only_new_notifications_for_signed_in_user(self):
        own = Notification.objects.create(user=self.employee, title="New update", body="For employee.")
        Notification.objects.create(user=self.colleague, title="Private update", body="For colleague.")
        self.client.force_login(self.employee)

        response = self.client.get(reverse("notification_updates"), {"after": 0})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["notifications"],
            [
                {
                    "id": own.pk,
                    "title": "New update",
                    "body": "For employee.",
                    "url": "",
                    "created_at": timezone.localtime(own.created_at).strftime("%H:%M"),
                }
            ],
        )

    def test_published_announcement_notification_is_available_to_live_polling(self):
        announcement = Announcement.objects.create(
            organization=self.organization,
            title="Urgent update",
            body="Please check the new schedule.",
            created_by=self.employee,
        )
        notification_service.deliver_announcement(announcement, [self.employee])
        self.client.force_login(self.employee)

        response = self.client.get(reverse("notification_updates"), {"after": 0})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["notifications"][0]["title"],
            "Announcement: Urgent update",
        )

    def test_notification_updates_rejects_invalid_cursor(self):
        self.client.force_login(self.employee)

        self.assertEqual(
            self.client.get(reverse("notification_updates"), {"after": "invalid"}).status_code,
            400,
        )

    def test_announcement_list_supports_live_announcement_updates(self):
        self.client.force_login(self.employee)

        response = self.client.get(reverse("announcements"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-live-announcements="card"')


class ChannelWebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.organization = Organization.objects.create(name="Realtime Org", slug="realtime-org")
        self.user = User.objects.create_user(
            employee_id="RT-EMP", password="SecurePassword!123", organization=self.organization
        )
        self.other = User.objects.create_user(
            employee_id="RT-OTHER", password="SecurePassword!123", organization=self.organization
        )
        self.admin = User.objects.create_user(
            employee_id="ANN-ADMIN",
            password="AdminPassword!234",
            organization=self.organization,
            role=User.Role.EMPLOYER,
            is_staff=True,
        )
        self.channel = Channel.objects.create(organization=self.organization, name="live")
        self.private_channel = Channel.objects.create(
            organization=self.organization, name="private", kind=Channel.Kind.PRIVATE
        )

    def test_authenticated_member_can_send_a_real_time_message(self):
        async_to_sync(self._send_message)()
        self.assertTrue(Message.objects.filter(channel=self.channel, author=self.user, body="Live from Django Channels").exists())

    def test_authenticated_member_can_reply_over_websocket(self):
        original = Message.objects.create(
            channel=self.channel,
            author=self.other,
            body="A message to quote.",
        )

        event = async_to_sync(self._send_message)(original.pk)

        self.assertEqual(Message.objects.get(pk=event["id"]).reply_to, original)
        self.assertEqual(event["reply_to"]["body"], "A message to quote.")

    def test_live_message_includes_authors_profile_photo_url(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.user.profile_picture.save(
                "employee.png",
                SimpleUploadedFile("employee.png", b"\x89PNG\r\n\x1a\nprofile image"),
            )

            event = async_to_sync(self._send_message)()

            self.assertEqual(
                event["profile_photo_url"],
                reverse("profile_photo", args=[self.user.pk]),
            )

    async def _send_message(self, reply_to_id=None):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), f"/ws/channels/{self.channel.pk}/"
        )
        communicator.scope["user"] = self.user
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        payload = {"type": "message.send", "body": "Live from Django Channels"}
        if reply_to_id is not None:
            payload["reply_to"] = reply_to_id
        await communicator.send_json_to(payload)
        event = await communicator.receive_json_from(timeout=3)
        self.assertEqual(event["type"], "message.created")
        self.assertEqual(event["body"], "Live from Django Channels")
        await communicator.disconnect()
        return event

    def test_nonmember_cannot_connect_to_private_channel_websocket(self):
        async_to_sync(self._reject_private_channel)()

    async def _reject_private_channel(self):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), f"/ws/channels/{self.private_channel.pk}/"
        )
        communicator.scope["user"] = self.user
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4403)

    def test_member_cannot_connect_to_archived_channel_websocket(self):
        self.channel.archived_at = timezone.now()
        self.channel.save(update_fields=["archived_at"])
        async_to_sync(self._reject_archived_channel)()

    async def _reject_archived_channel(self):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), f"/ws/channels/{self.channel.pk}/"
        )
        communicator.scope["user"] = self.user
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4403)


class MeetingChatWebSocketTests(TransactionTestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Meeting Chat Org", slug="meeting-chat-org")
        self.user = User.objects.create_user(
            employee_id="CHAT-EMP", password="chat-test-password", organization=self.organization
        )
        self.other = User.objects.create_user(
            employee_id="CHAT-OTHER",
            password="chat-test-password",
            organization=self.organization,
            role=User.Role.EMPLOYER,
            is_staff=True,
        )
        self.meeting = Meeting.objects.create(
            organization=self.organization,
            title="Live chat",
            starts_at=timezone.now(),
            host=self.other,
            status=Meeting.Status.ACTIVE,
        )
        MeetingParticipant.objects.create(
            meeting=self.meeting,
            user=self.user,
            status=MeetingParticipant.Status.JOINED,
        )
        MeetingParticipant.objects.create(
            meeting=self.meeting,
            user=self.other,
            status=MeetingParticipant.Status.JOINED,
        )

    def test_api_message_is_delivered_to_connected_meeting_participants(self):
        async_to_sync(self._receive_api_message)()

    async def _receive_api_message(self):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/meetings/{self.meeting.pk}/chat/",
        )
        communicator.scope["user"] = self.other
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await database_sync_to_async(self.client.force_login)(self.user)
        response = await database_sync_to_async(self.client.post)(
            reverse("meeting_chat_api", args=[self.meeting.pk]),
            {"body": "The employee chat is live."},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 201)

        event = await communicator.receive_json_from(timeout=3)
        self.assertEqual(event["type"], "message.created")
        self.assertEqual(event["body"], "The employee chat is live.")
        self.assertEqual(event["author"], self.user.get_full_name() or self.user.employee_id)
        await communicator.disconnect()

    def test_non_joined_invitee_cannot_connect_to_meeting_chat(self):
        MeetingParticipant.objects.create(
            meeting=self.meeting,
            user=User.objects.create_user(
                employee_id="CHAT-INVITED",
                password="chat-test-password",
                organization=self.organization,
            ),
            status=MeetingParticipant.Status.INVITED,
        )
        invited = MeetingParticipant.objects.get(
            meeting=self.meeting, status=MeetingParticipant.Status.INVITED
        ).user
        async_to_sync(self._reject_invitee)(invited)

    async def _reject_invitee(self, invited):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/meetings/{self.meeting.pk}/chat/",
        )
        communicator.scope["user"] = invited
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4403)


class RealtimeNotificationWebSocketTests(TransactionTestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Announcements Org", slug="announcements-org")
        self.user = User.objects.create_user(
            employee_id="ANN-EMP", password="test-password", organization=self.organization
        )
        self.channel = Channel.objects.create(organization=self.organization, name="live")
        self.announcement = Announcement.objects.create(
            organization=self.organization,
            title="Team update",
            body="The announcement is live.",
            created_by=self.user,
        )
        self.admin = User.objects.create_user(
            employee_id="ANN-ADMIN",
            password="AdminPassword!234",
            organization=self.organization,
            role=User.Role.EMPLOYER,
            is_staff=True,
        )

    def test_published_announcement_is_delivered_to_signed_in_employee(self):
        async_to_sync(self._receive_announcement)()

    def test_admin_published_announcement_reaches_employee_websocket(self):
        async_to_sync(self._receive_admin_announcement)()

    async def _receive_admin_announcement(self):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), "/ws/notifications/"
        )
        communicator.scope["user"] = self.user
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await database_sync_to_async(self.client.force_login)(self.admin)
        response = await database_sync_to_async(self.client.post)(
            reverse("manage_announcement_create"),
            {
                "title": "Emergency office update",
                "body": "The office is closed today.",
                "priority": "important",
            },
        )
        self.assertEqual(response.status_code, 302)

        event = await communicator.receive_json_from(timeout=3)
        self.assertEqual(event["type"], "notification.created")
        self.assertEqual(event["title"], "Announcement: Emergency office update")
        self.assertEqual(event["body"], "The office is closed today.")
        await communicator.disconnect()

    def test_admin_meeting_invitation_reaches_invited_employee_websocket(self):
        async_to_sync(self._receive_admin_meeting_invitation)()

    async def _receive_admin_meeting_invitation(self):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), "/ws/notifications/"
        )
        communicator.scope["user"] = self.user
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await database_sync_to_async(self.client.force_login)(self.admin)
        starts_at = timezone.localtime(timezone.now() + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M"
        )
        response = await database_sync_to_async(self.client.post)(
            reverse("manage_meeting_create"),
            {
                "title": "Team planning",
                "starts_at": starts_at,
                "meeting_type": "video",
                "invitees": [self.user.pk],
            },
        )
        self.assertEqual(response.status_code, 302)

        event = await communicator.receive_json_from(timeout=3)
        self.assertEqual(event["type"], "notification.created")
        self.assertEqual(event["title"], "Meeting invitation: Team planning")
        self.assertIn("You're invited", event["body"])
        await communicator.disconnect()

    async def _receive_announcement(self):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), "/ws/notifications/"
        )
        communicator.scope["user"] = self.user
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await database_sync_to_async(notification_service.deliver_announcement)(
            self.announcement, [self.user]
        )

        event = await communicator.receive_json_from(timeout=3)
        self.assertEqual(event["type"], "notification.created")
        self.assertEqual(event["title"], "Announcement: Team update")
        self.assertEqual(event["body"], "The announcement is live.")
        await communicator.disconnect()

    def test_suspended_user_cannot_connect_to_channel_websocket(self):
        other_org = self.organization
        stranger = User.objects.create_user(
            employee_id="FOREIGN", password="SecurePassword!123", organization=other_org
        )
        stranger.is_suspended = True
        stranger.save(update_fields=["is_suspended"])
        async_to_sync(self._reject_user)(stranger)

    async def _reject_user(self, user):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), f"/ws/channels/{self.channel.pk}/"
        )
        communicator.scope["user"] = user
        connected, close_code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4403)
