from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import (
    Announcement,
    AnnouncementRead,
    Channel,
    ChannelMembership,
    Meeting,
    MeetingChatMessage,
    MeetingEvent,
    MeetingParticipant,
    Message,
    MessageReaction,
    MessageRead,
    Notification,
)
from .media import MediaProviderError, MediaWebhookError, media_provider
from .notifications import notification_service
from governance.services import organization_for
from governance.services import has_permission, record_audit


def _organization_or_404(user):
    return organization_for(user)


@login_required
def dashboard(request):
    if not request.user.organization_id:
        if request.user.can_manage_workplace:
            return render(request, "communications/setup_required.html")
        raise Http404("This account is not assigned to an organization.")
    organization = _organization_or_404(request.user)
    channels = Channel.objects.filter(organization=organization, archived_at__isnull=True).filter(
        models_q_public_or_member(request.user)
    ).distinct()
    announcements = _visible_announcements(request.user, organization)
    upcoming_meetings = Meeting.objects.filter(
        organization=organization,
        status__in=[
            Meeting.Status.SCHEDULED,
            Meeting.Status.WAITING,
            Meeting.Status.ACTIVE,
        ],
    )
    if not request.user.can_manage_workplace:
        upcoming_meetings = upcoming_meetings.filter(
            Q(host=request.user) | Q(participant_records__user=request.user)
        )
    upcoming_meetings = upcoming_meetings.distinct().order_by("starts_at")[:4]
    context = {
        "channels": channels[:6],
        "announcements": announcements[:4],
        "upcoming_meetings": upcoming_meetings,
        "unread_messages": Message.objects.filter(
            channel__in=channels
        ).exclude(author=request.user).exclude(read_receipts__user=request.user).count(),
    }
    return render(request, "communications/dashboard.html", context)


def models_q_public_or_member(user):
    from django.db.models import Q
    return Q(kind=Channel.Kind.PUBLIC) | Q(members=user)


def models_q_announcement_branch(branch_id):
    from django.db.models import Q
    return Q(branch__isnull=True) | Q(branch_id=branch_id)


def _accessible_channel(user, channel_id):
    organization = _organization_or_404(user)
    channel = get_object_or_404(Channel, pk=channel_id, organization=organization)
    if channel.kind != Channel.Kind.PUBLIC and not channel.members.filter(pk=user.pk).exists():
        raise Http404
    return channel


def _reply_preview(message):
    if not message.reply_to_id:
        return None
    reply = message.reply_to
    return {
        "id": reply.pk,
        "author": reply.author.get_full_name() or reply.author.employee_id,
        "body": "This message was deleted." if reply.deleted_at else reply.body,
    }


@login_required
def channel_list(request):
    organization = _organization_or_404(request.user)
    channels = Channel.objects.filter(organization=organization, archived_at__isnull=True).filter(
        models_q_public_or_member(request.user)
    ).distinct()
    return render(request, "communications/channel_list.html", {"channels": channels})


@login_required
def channel_detail(request, channel_id):
    channel = _accessible_channel(request.user, channel_id)
    if request.method == "POST":
        if channel.archived_at:
            messages.error(request, "This channel is archived and read-only.")
            return redirect("channel_detail", channel_id=channel.id)
        if not has_permission(request.user, "MESSAGE_SEND"):
            return HttpResponseForbidden("You cannot send messages.")
        body = request.POST.get("body", "").strip()
        if body:
            if len(body) > 4000:
                messages.error(request, "Messages must be 4,000 characters or fewer.")
                return redirect("channel_detail", channel_id=channel.id)
            reply_to_id = request.POST.get("reply_to", "").strip()
            reply_to = None
            if reply_to_id:
                try:
                    reply_to = channel.messages.select_related("author").get(
                        pk=int(reply_to_id), deleted_at__isnull=True
                    )
                except (ValueError, Message.DoesNotExist):
                    messages.error(request, "Choose a message in this channel to reply to.")
                    return redirect("channel_detail", channel_id=channel.id)
            Message.objects.create(
                channel=channel, author=request.user, body=body, reply_to=reply_to
            )
        return redirect("channel_detail", channel_id=channel.id)
    messages_page = list(
        channel.messages.select_related("author", "reply_to", "reply_to__author")
        .order_by("-created_at")[:100]
    )
    own_message_ids = [message.pk for message in messages_page if message.author_id == request.user.pk]
    seen_counts = dict(
        MessageRead.objects.filter(message_id__in=own_message_ids)
        .values("message_id")
        .annotate(count=Count("pk"))
        .values_list("message_id", "count")
    )
    for message in messages_page:
        message.seen_count = seen_counts.get(message.pk, 0)
    channel_title = channel.name
    if channel.kind == Channel.Kind.DIRECT:
        other = channel.members.exclude(pk=request.user.pk).first()
        channel_title = other.get_full_name() or other.employee_id if other else "Direct message"
    return render(
        request,
        "communications/channel_detail.html",
        {
            "channel": channel,
            "channel_title": channel_title,
            "chat_messages": reversed(messages_page),
            "read_endpoint": reverse("channel_read", args=[channel.pk]),
        },
    )


@login_required
def direct_message(request, user_id):
    organization = _organization_or_404(request.user)
    colleague = get_object_or_404(
        request.user.__class__,
        pk=user_id,
        organization=organization,
        is_active=True,
        is_suspended=False,
    )
    if colleague.pk == request.user.pk:
        raise Http404
    first_id, second_id = sorted((request.user.pk, colleague.pk))
    name = f"dm-{first_id}-{second_id}"
    channel, _ = Channel.objects.get_or_create(
        organization=organization,
        name=name,
        defaults={
            "description": "Private direct conversation",
            "kind": Channel.Kind.DIRECT,
            "created_by": request.user,
        },
    )
    ChannelMembership.objects.get_or_create(channel=channel, user=request.user)
    ChannelMembership.objects.get_or_create(channel=channel, user=colleague)
    return redirect("channel_detail", channel_id=channel.pk)


@login_required
@never_cache
def channel_messages(request, channel_id):
    channel = _accessible_channel(request.user, channel_id)
    if request.method == "POST":
        if channel.archived_at:
            return JsonResponse({"error": "This channel is archived and read-only."}, status=409)
        if not has_permission(request.user, "MESSAGE_SEND"):
            return JsonResponse({"error": "You do not have permission to send messages."}, status=403)
        body = request.POST.get("body", "").strip()
        if not body or len(body) > 4000:
            return JsonResponse({"error": "Messages must contain 1–4000 characters."}, status=400)
        reply_to_id = request.POST.get("reply_to", "").strip()
        reply_to = None
        if reply_to_id:
            try:
                reply_to = channel.messages.select_related("author").get(
                    pk=int(reply_to_id), deleted_at__isnull=True
                )
            except (ValueError, Message.DoesNotExist):
                return JsonResponse(
                    {"error": "Choose a message in this channel to reply to."}, status=400
                )
        message = Message.objects.create(
            channel=channel, author=request.user, body=body, reply_to=reply_to
        )
        message_data = {
            "type": "message.created",
            "id": message.pk,
            "author": request.user.get_full_name() or request.user.employee_id,
            "profile_photo_url": (
                reverse("profile_photo", args=[request.user.pk]) if request.user.profile_picture else None
            ),
            "body": message.body,
            "reply_to": _reply_preview(message),
            "created_at": timezone.localtime(message.created_at).strftime("%H:%M"),
            "mine": True,
            "seen_count": 0,
        }
        _broadcast_channel_event(channel.pk, message_data)
        member_ids = channel.members.exclude(pk=request.user.pk).filter(is_active=True)
        notification_service.create_many(
            member_ids,
            "New channel message",
            f"{message_data['author']}: {body[:420]}",
            f"/channels/{channel.pk}/",
        )
        return JsonResponse(message_data, status=201)
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    try:
        after = int(request.GET.get("after", "0"))
    except ValueError:
        return JsonResponse({"error": "Invalid message cursor."}, status=400)
    items = (
        channel.messages.filter(pk__gt=after)
        .select_related("author", "reply_to", "reply_to__author")
        .annotate(read_receipt_count=Count("read_receipts"))
        .order_by("created_at")[:100]
    )
    seen_counts = dict(
        channel.messages.filter(author=request.user)
        .annotate(read_count=Count("read_receipts"))
        .order_by("-created_at")
        .values_list("pk", "read_count")[:100]
    )
    return JsonResponse(
        {
            "messages": [
                {
                    "id": item.pk,
                    "author": item.author.get_full_name() or item.author.employee_id,
                    "profile_photo_url": (
                        reverse("profile_photo", args=[item.author_id])
                        if item.author.profile_picture
                        else None
                    ),
                    "body": item.body if not item.deleted_at else "This message was deleted.",
                    "deleted": bool(item.deleted_at),
                    "reply_to": _reply_preview(item),
                    "created_at": timezone.localtime(item.created_at).strftime("%H:%M"),
                    "mine": item.author_id == request.user.pk,
                    "seen_count": (
                        item.read_receipt_count if item.author_id == request.user.pk else 0
                    ),
                }
                for item in items
            ],
            "seen_counts": seen_counts,
        }
    )


@login_required
@require_POST
def channel_read(request, channel_id):
    channel = _accessible_channel(request.user, channel_id)
    raw_ids = request.POST.getlist("message_ids")
    if not raw_ids or len(raw_ids) > 100:
        return JsonResponse({"error": "Select between 1 and 100 messages to mark as seen."}, status=400)
    try:
        message_ids = {int(value) for value in raw_ids}
    except ValueError:
        return JsonResponse({"error": "Invalid message IDs."}, status=400)
    if any(message_id <= 0 for message_id in message_ids):
        return JsonResponse({"error": "Invalid message IDs."}, status=400)
    eligible_ids = set(
        channel.messages.filter(pk__in=message_ids)
        .exclude(author=request.user)
        .values_list("pk", flat=True)
    )
    new_ids = []
    for message_id in eligible_ids:
        _, created = MessageRead.objects.get_or_create(message_id=message_id, user=request.user)
        if created:
            new_ids.append(message_id)
    if new_ids:
        _broadcast_channel_event(
            channel.pk,
            {
                "type": "messages.seen",
                "message_ids": new_ids,
                "reader_id": request.user.pk,
                "reader": request.user.get_full_name() or request.user.employee_id,
            },
        )
    return JsonResponse({"seen_message_ids": new_ids})


@login_required
@require_POST
def message_edit(request, message_id):
    organization = _organization_or_404(request.user)
    message = get_object_or_404(
        Message.objects.select_related("channel"),
        pk=message_id,
        channel__organization=organization,
        deleted_at__isnull=True,
    )
    if message.author_id != request.user.pk and not has_permission(request.user, "MESSAGE_MODERATE"):
        raise PermissionDenied
    channel = _accessible_channel(request.user, message.channel_id)
    if channel.archived_at:
        return JsonResponse({"error": "Messages in archived channels cannot be edited."}, status=409)
    body = request.POST.get("body", "").strip()
    if not body or len(body) > 4000:
        return JsonResponse({"error": "Messages must contain 1–4000 characters."}, status=400)
    message.body = body
    message.edited_at = timezone.now()
    message.save(update_fields=["body", "edited_at"])
    _broadcast_channel_event(
        message.channel_id,
        {
            "type": "message.updated",
            "id": message.pk,
            "body": body,
            "edited_at": timezone.localtime(message.edited_at).strftime("%H:%M"),
        },
    )
    return JsonResponse({"status": "updated"})


@login_required
@require_POST
def message_delete(request, message_id):
    organization = _organization_or_404(request.user)
    message = get_object_or_404(
        Message.objects.select_related("channel"),
        pk=message_id,
        channel__organization=organization,
        deleted_at__isnull=True,
    )
    if message.author_id != request.user.pk and not has_permission(request.user, "MESSAGE_MODERATE"):
        raise PermissionDenied
    channel = _accessible_channel(request.user, message.channel_id)
    if channel.archived_at:
        return JsonResponse({"error": "Messages in archived channels cannot be deleted."}, status=409)
    message.body = ""
    message.deleted_at = timezone.now()
    message.save(update_fields=["body", "deleted_at"])
    if message.author_id != request.user.pk:
        record_audit(request, "message.moderated", message, metadata={"moderator_action": "delete"})
    _broadcast_channel_event(
        message.channel_id,
        {"type": "message.deleted", "id": message.pk},
    )
    return JsonResponse({"status": "deleted"})


@login_required
@require_POST
def message_reaction(request, message_id):
    organization = _organization_or_404(request.user)
    message = get_object_or_404(
        Message.objects.select_related("channel"),
        pk=message_id,
        channel__organization=organization,
        deleted_at__isnull=True,
    )
    channel = _accessible_channel(request.user, message.channel_id)
    if channel.archived_at:
        return JsonResponse({"error": "Reactions in archived channels cannot be changed."}, status=409)
    emoji = request.POST.get("emoji", "")
    if emoji not in {"👍", "❤️", "😂", "🎉", "👀"}:
        return JsonResponse({"error": "That reaction is not supported."}, status=400)
    reaction, created = MessageReaction.objects.get_or_create(
        message=message, user=request.user, emoji=emoji
    )
    if not created:
        reaction.delete()
    return JsonResponse({"status": "added" if created else "removed", "emoji": emoji})


def _broadcast_channel_event(channel_id, event):
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(
            f"nexawork.channel.{channel_id}",
            {"type": "chat.event", "event": event},
        )


@login_required
def announcements(request):
    organization = _organization_or_404(request.user)
    items = _visible_announcements(request.user, organization)
    AnnouncementRead.objects.bulk_create(
        [
            AnnouncementRead(announcement_id=announcement_id, user=request.user)
            for announcement_id in items.exclude(read_receipts__user=request.user).values_list("pk", flat=True)
        ],
        ignore_conflicts=True,
    )
    return render(request, "communications/announcements.html", {"announcements": items})


def _visible_announcements(user, organization):
    now = timezone.now()
    items = Announcement.objects.filter(organization=organization).filter(
        Q(publish_at__isnull=True) | Q(publish_at__lte=now)
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    if user.branch_id:
        items = items.filter(Q(branch__isnull=True) | Q(branch_id=user.branch_id))
    else:
        items = items.filter(branch__isnull=True)
    if user.branch and user.branch.region_id:
        items = items.filter(Q(region__isnull=True) | Q(region_id=user.branch.region_id))
    else:
        items = items.filter(region__isnull=True)
    if user.department_id:
        items = items.filter(Q(department__isnull=True) | Q(department_id=user.department_id))
    else:
        items = items.filter(department__isnull=True)
    if user.team_id:
        items = items.filter(Q(team__isnull=True) | Q(team_id=user.team_id))
    else:
        items = items.filter(team__isnull=True)
    return items.distinct()


@login_required
def meeting_list(request):
    organization = _organization_or_404(request.user)
    meetings = Meeting.objects.filter(
        organization=organization,
        status__in=[
            Meeting.Status.SCHEDULED,
            Meeting.Status.WAITING,
            Meeting.Status.ACTIVE,
        ],
    )
    if not request.user.can_manage_workplace:
        meetings = meetings.filter(Q(host=request.user) | Q(participant_records__user=request.user))
    meetings = meetings.distinct()
    return render(request, "communications/meeting_list.html", {"meetings": meetings})


@login_required
@require_GET
def meeting_updates(request):
    organization = _organization_or_404(request.user)
    meetings = Meeting.objects.filter(
        organization=organization,
        status__in=[
            Meeting.Status.SCHEDULED,
            Meeting.Status.WAITING,
            Meeting.Status.ACTIVE,
        ],
    ).select_related("host")
    if not request.user.can_manage_workplace:
        meetings = meetings.filter(Q(host=request.user) | Q(participant_records__user=request.user))
    meetings = meetings.distinct().order_by("starts_at", "pk")[:100]
    return JsonResponse(
        {
            "meetings": [
                {
                    "id": meeting.pk,
                    "title": meeting.title,
                    "description": meeting.description,
                    "starts_at": meeting.starts_at.isoformat(),
                    "meeting_type": meeting.meeting_type,
                    "status": meeting.status,
                    "host": meeting.host.get_full_name() or meeting.host.employee_id,
                    "url": reverse("meeting_detail", args=[meeting.pk]),
                }
                for meeting in meetings
            ]
        }
    )


@login_required
def meeting_detail(request, meeting_id):
    organization = _organization_or_404(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, organization=organization)
    participant = meeting.participant_records.filter(user=request.user).first()
    is_cohost = bool(participant and participant.role == MeetingParticipant.Role.COHOST)
    can_manage = (
        request.user == meeting.host
        or is_cohost
        or has_permission(request.user, "MEETING_END")
        or has_permission(request.user, "MEETING_REMOVE_PARTICIPANT")
    )
    can_end = request.user == meeting.host or has_permission(request.user, "MEETING_END")
    can_manage_roles = request.user == meeting.host or has_permission(request.user, "MEETING_END")
    if participant is None and not can_manage:
        raise Http404
    now = timezone.now()
    if participant and participant.removed_until and participant.removed_until > now:
        messages.error(request, f"You cannot rejoin this meeting until {timezone.localtime(participant.removed_until):%H:%M}.")
        return redirect("meeting_list")
    if request.method == "POST" and request.POST.get("action") == "join":
        if meeting.status in {Meeting.Status.COMPLETED, Meeting.Status.CANCELLED}:
            messages.error(request, "This meeting is no longer available.")
            return redirect("meeting_list")
        if meeting.is_locked and not can_manage:
            return HttpResponseForbidden("This meeting is locked.")
        if participant is None:
            participant = MeetingParticipant.objects.create(
                meeting=meeting,
                user=request.user,
                joined_at=now,
                status=MeetingParticipant.Status.JOINED,
                role=(
                    MeetingParticipant.Role.HOST
                    if request.user == meeting.host
                    else MeetingParticipant.Role.PARTICIPANT
                ),
            )
        else:
            participant.removed_until = None
            participant.status = MeetingParticipant.Status.JOINED
            participant.joined_at = now
            participant.save(update_fields=["removed_until", "status", "joined_at"])
        MeetingEvent.objects.create(meeting=meeting, actor=request.user, event_type="participant_joined")
        if request.user == meeting.host and meeting.status in {Meeting.Status.SCHEDULED, Meeting.Status.WAITING}:
            meeting.status = Meeting.Status.ACTIVE
            meeting.started_at = now
            meeting.save(update_fields=["status", "started_at"])
            MeetingEvent.objects.create(meeting=meeting, actor=request.user, event_type="started")
        return redirect("meeting_detail", meeting_id=meeting.id)

    participant_rows = meeting.participant_records.select_related("user").all()
    chat_messages = meeting.chat_messages.select_related("author").order_by("-created_at")[:50]
    livekit = None
    if (
        participant
        and participant.status == MeetingParticipant.Status.JOINED
        and not (participant.removed_until and participant.removed_until > now)
    ):
        from .media import media_provider
        livekit = media_provider.join_configuration(meeting, request.user)
    return render(
        request,
        "communications/meeting_detail.html",
        {
            "meeting": meeting,
            "participant": participant,
            "participant_rows": participant_rows,
            "can_manage": can_manage,
            "can_end": can_end,
            "can_manage_roles": can_manage_roles,
            "livekit": livekit,
            "now": now,
            "meeting_chat_messages": reversed(chat_messages),
        },
    )


@login_required
def meeting_chat_api(request, meeting_id):
    organization = _organization_or_404(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, organization=organization)
    if not meeting.participant_records.filter(user=request.user).exists():
        return JsonResponse({"error": "You are not invited to this meeting."}, status=403)
    if request.method == "GET":
        after = request.GET.get("after", "0")
        try:
            after_id = int(after)
        except ValueError:
            return JsonResponse({"error": "Invalid message cursor."}, status=400)
        items = meeting.chat_messages.filter(pk__gt=after_id).select_related("author")[:100]
        return JsonResponse(
            {
                "messages": [
                    {
                        "id": item.pk,
                        "author": item.author.get_full_name() or item.author.employee_id,
                        "body": item.body,
                        "created_at": timezone.localtime(item.created_at).strftime("%H:%M"),
                    }
                    for item in items
                ]
            }
        )
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    if not request.user.meeting_records.filter(
        meeting=meeting, status=MeetingParticipant.Status.JOINED
    ).exists():
        return JsonResponse({"error": "Join the meeting before using meeting chat."}, status=403)
    body = request.POST.get("body", "").strip()
    if not body or len(body) > 2000:
        return JsonResponse({"error": "Meeting messages must contain 1–2000 characters."}, status=400)
    item = MeetingChatMessage.objects.create(meeting=meeting, author=request.user, body=body)
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(
            f"nexawork.meeting_chat.{meeting.pk}",
            {
                "type": "meeting.chat.message",
                "message": {
                    "type": "message.created",
                    "id": item.pk,
                    "author": request.user.get_full_name() or request.user.employee_id,
                    "body": item.body,
                    "created_at": timezone.localtime(item.created_at).strftime("%H:%M"),
                },
            },
        )
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        messages.success(request, "Meeting message sent.")
        return redirect("meeting_detail", meeting_id=meeting.pk)
    return JsonResponse(
        {
            "id": item.pk,
            "author": request.user.get_full_name() or request.user.employee_id,
            "body": item.body,
            "created_at": timezone.localtime(item.created_at).strftime("%H:%M"),
        },
        status=201,
    )


@login_required
@require_POST
def remove_meeting_participant(request, meeting_id, user_id):
    organization = _organization_or_404(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, organization=organization)
    participant_record = meeting.participant_records.filter(user=request.user).first()
    if (
        request.user != meeting.host
        and not (participant_record and participant_record.role == MeetingParticipant.Role.COHOST)
        and not has_permission(request.user, "MEETING_REMOVE_PARTICIPANT")
        and not has_permission(request.user, "MEETING_END")
    ):
        return HttpResponseForbidden("You are not allowed to manage this meeting.")
    if user_id == meeting.host_id:
        messages.error(request, "The meeting host cannot be removed.")
        return redirect("meeting_detail", meeting_id=meeting.id)
    participant = get_object_or_404(MeetingParticipant, meeting=meeting, user_id=user_id)
    participant.removed_until = timezone.now() + timedelta(minutes=10)
    participant.status = MeetingParticipant.Status.REMOVED
    participant.left_at = timezone.now()
    participant.save(update_fields=["removed_until", "status", "left_at"])
    try:
        media_provider.remove_participant(meeting, participant.user)
    except MediaProviderError as error:
        MeetingEvent.objects.create(
            meeting=meeting,
            actor=request.user,
            target_user=participant.user,
            event_type="participant_removal_provider_failed",
            metadata={"reason": str(error)},
        )
        record_audit(
            request,
            "meeting.participant_removal_failed",
            meeting,
            result="failure",
            metadata={"participant_id": participant.user_id},
        )
        return JsonResponse(
            {
                "error": "The participant is blocked from rejoining NexaWork, but the media provider could not be contacted. Retry removal or end the room."
            },
            status=502,
        )
    MeetingEvent.objects.create(
        meeting=meeting,
        actor=request.user,
        target_user=participant.user,
        event_type="participant_removed",
        metadata={"blocked_until": participant.removed_until.isoformat()},
    )
    notification_service.create(
        participant.user,
        f"Removed from {meeting.title}",
        "The host removed you from this meeting. You may rejoin after 10 minutes.",
        f"/meetings/{meeting.pk}/",
    )
    messages.success(request, "Participant removed. They can rejoin after 10 minutes.")
    return redirect("meeting_detail", meeting_id=meeting.id)


@login_required
@require_POST
def meeting_end(request, meeting_id):
    organization = _organization_or_404(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, organization=organization)
    if request.user != meeting.host and not has_permission(request.user, "MEETING_END"):
        return HttpResponseForbidden("You are not allowed to end this meeting.")
    if meeting.status in {Meeting.Status.COMPLETED, Meeting.Status.CANCELLED}:
        return redirect("meeting_detail", meeting_id=meeting.pk)
    try:
        media_provider.end_meeting(meeting)
    except MediaProviderError as error:
        messages.error(request, str(error))
        return redirect("meeting_detail", meeting_id=meeting.pk)
    was_active = meeting.status == Meeting.Status.ACTIVE
    meeting.status = Meeting.Status.COMPLETED
    meeting.ended_at = timezone.now()
    if was_active and meeting.started_at:
        meeting.actual_duration_seconds = int((meeting.ended_at - meeting.started_at).total_seconds())
    meeting.save(update_fields=["status", "started_at", "ended_at", "actual_duration_seconds"])
    MeetingParticipant.objects.filter(meeting=meeting, status=MeetingParticipant.Status.JOINED).update(
        status=MeetingParticipant.Status.LEFT, left_at=meeting.ended_at
    )
    MeetingEvent.objects.create(meeting=meeting, actor=request.user, event_type="ended")
    record_audit(request, "meeting.ended", meeting)
    messages.success(request, "Meeting ended.")
    return redirect("meeting_list")


@login_required
@require_POST
def meeting_leave(request, meeting_id):
    organization = _organization_or_404(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, organization=organization)
    participant = get_object_or_404(MeetingParticipant, meeting=meeting, user=request.user)
    participant.status = MeetingParticipant.Status.LEFT
    participant.left_at = timezone.now()
    participant.save(update_fields=["status", "left_at"])
    MeetingEvent.objects.create(meeting=meeting, actor=request.user, event_type="participant_left")
    return redirect("meeting_list")


@login_required
@require_POST
def meeting_lock(request, meeting_id):
    organization = _organization_or_404(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, organization=organization)
    if request.user != meeting.host and not has_permission(request.user, "MEETING_END"):
        return HttpResponseForbidden("You are not allowed to change meeting access.")
    meeting.is_locked = not meeting.is_locked
    meeting.save(update_fields=["is_locked"])
    MeetingEvent.objects.create(
        meeting=meeting,
        actor=request.user,
        event_type="locked" if meeting.is_locked else "unlocked",
    )
    record_audit(request, "meeting.lock_changed", meeting, metadata={"is_locked": meeting.is_locked})
    return redirect("meeting_detail", meeting_id=meeting.pk)


@login_required
@require_POST
def meeting_promote(request, meeting_id, user_id):
    organization = _organization_or_404(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, organization=organization)
    if request.user != meeting.host and not has_permission(request.user, "MEETING_END"):
        return HttpResponseForbidden("You are not allowed to manage meeting roles.")
    if user_id == meeting.host_id:
        return redirect("meeting_detail", meeting_id=meeting.pk)
    participant = get_object_or_404(MeetingParticipant, meeting=meeting, user_id=user_id)
    if participant.status != MeetingParticipant.Status.JOINED:
        return JsonResponse({"error": "Only joined participants can be promoted."}, status=409)
    target_role = (
        MeetingParticipant.Role.PARTICIPANT
        if participant.role == MeetingParticipant.Role.COHOST
        else MeetingParticipant.Role.COHOST
    )
    participant.role = target_role
    participant.save(update_fields=["role"])
    MeetingEvent.objects.create(
        meeting=meeting,
        actor=request.user,
        target_user=participant.user,
        event_type="participant_role_changed",
        metadata={"role": target_role},
    )
    record_audit(
        request,
        "meeting.participant_role_changed",
        meeting,
        metadata={"user_id": user_id, "role": target_role},
    )
    return redirect("meeting_detail", meeting_id=meeting.pk)


@login_required
@require_POST
def meeting_mute_participant(request, meeting_id, user_id):
    organization = _organization_or_404(request.user)
    meeting = get_object_or_404(Meeting, pk=meeting_id, organization=organization)
    actor = meeting.participant_records.filter(user=request.user).first()
    if (
        request.user != meeting.host
        and not (actor and actor.role == MeetingParticipant.Role.COHOST)
        and not has_permission(request.user, "MEETING_END")
    ):
        return HttpResponseForbidden("You are not allowed to mute meeting participants.")
    participant = get_object_or_404(
        MeetingParticipant.objects.select_related("user"), meeting=meeting, user_id=user_id
    )
    if participant.status != MeetingParticipant.Status.JOINED:
        return JsonResponse({"error": "Only joined participants can be muted."}, status=409)
    try:
        muted = request.POST.get("muted", "true").lower() == "true"
        provider_result = media_provider.mute_participant(
            meeting,
            participant.user,
            request.POST.get("track_sid", ""),
            muted=muted,
        )
        if not provider_result:
            return JsonResponse({"error": "The meeting media provider is not configured."}, status=503)
    except MediaProviderError as error:
        return JsonResponse({"error": str(error)}, status=502)
    MeetingEvent.objects.create(
        meeting=meeting,
        actor=request.user,
        target_user=participant.user,
        event_type="participant_muted" if muted else "participant_unmuted",
        metadata={"track_sid": request.POST.get("track_sid", "")},
    )
    return JsonResponse({"status": "ok", "muted": muted})


@csrf_exempt
@require_POST
def livekit_webhook(request):
    try:
        event = media_provider.decode_webhook(
            request.body, request.headers.get("Authorization", "")
        )
    except MediaWebhookError:
        return JsonResponse({"error": "Invalid provider webhook."}, status=401)

    room_name = (event.get("room") or {}).get("name", "")
    meeting = Meeting.objects.filter(meeting_id=room_name).first()
    if not meeting:
        return JsonResponse({"status": "ignored"})
    event_type = event.get("event")
    participant_identity = (event.get("participant") or {}).get("identity", "")
    participant = meeting.participant_records.filter(user__employee_id=participant_identity).select_related("user").first()

    if event_type == "participant_joined" and participant and participant.removed_until:
        if participant.removed_until > timezone.now():
            try:
                media_provider.remove_participant(meeting, participant.user)
            except MediaProviderError:
                return JsonResponse({"error": "Could not enforce the meeting removal."}, status=503)
            MeetingEvent.objects.create(
                meeting=meeting,
                target_user=participant.user,
                event_type="participant_reentry_blocked",
                metadata={"blocked_until": participant.removed_until.isoformat()},
            )
            return JsonResponse({"status": "participant_removed"})
        participant.removed_until = None
        participant.save(update_fields=["removed_until"])

    if event_type == "participant_left" and participant and participant.status == MeetingParticipant.Status.JOINED:
        participant.status = MeetingParticipant.Status.LEFT
        participant.left_at = timezone.now()
        participant.save(update_fields=["status", "left_at"])
    elif event_type == "room_finished" and meeting.status not in {
        Meeting.Status.COMPLETED,
        Meeting.Status.CANCELLED,
    }:
        meeting.status = Meeting.Status.COMPLETED
        meeting.ended_at = timezone.now()
        if meeting.started_at:
            meeting.actual_duration_seconds = int((meeting.ended_at - meeting.started_at).total_seconds())
        meeting.save(update_fields=["status", "ended_at", "actual_duration_seconds"])
    return JsonResponse({"status": "accepted"})


@login_required
def notification_list(request):
    return render(
        request,
        "communications/notification_list.html",
        {"notifications": Notification.objects.filter(user=request.user)[:50]},
    )


@login_required
@require_GET
def notification_updates(request):
    try:
        after = int(request.GET.get("after", "0"))
    except ValueError:
        return JsonResponse({"error": "The notification cursor must be an integer."}, status=400)
    if after < 0:
        return JsonResponse({"error": "The notification cursor cannot be negative."}, status=400)

    notifications = Notification.objects.filter(user=request.user, pk__gt=after).order_by("pk")[:50]
    return JsonResponse(
        {
            "notifications": [
                {
                    "id": notification.pk,
                    "title": notification.title,
                    "body": notification.body,
                    "url": notification.url,
                    "created_at": timezone.localtime(notification.created_at).strftime("%H:%M"),
                }
                for notification in notifications
            ]
        }
    )


@login_required
@require_POST
def mark_notification_read(request, notification_id):
    notification = get_object_or_404(Notification, pk=notification_id, user=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    if notification.url and url_has_allowed_host_and_scheme(
        notification.url, allowed_hosts={request.get_host()}
    ):
        return redirect(notification.url)
    return redirect("notification_list")
