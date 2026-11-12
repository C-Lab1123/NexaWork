import hashlib
import secrets
from datetime import timedelta
import hmac

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from .models import AccountInvitation


class EmailDeliveryError(Exception):
    pass


def invitation_token_matches(invitation, token):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(invitation.token_hash, token_hash)


def invitation_is_valid(invitation, token, now=None):
    now = now or timezone.now()
    user = invitation.user
    return (
        invitation.used_at is None
        and invitation.expires_at > now
        and not user.has_usable_password()
        and user.is_active
        and not user.is_suspended
        and user.organization_id is not None
        and user.organization.is_active
        and invitation_token_matches(invitation, token)
    )


def send_account_invitation(request, user):
    token = secrets.token_urlsafe(32)
    now = timezone.now()
    invitation, _ = AccountInvitation.objects.update_or_create(
        user=user,
        defaults={
            "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "expires_at": now + timedelta(seconds=settings.ACCOUNT_INVITATION_TIMEOUT),
            "used_at": None,
        },
    )
    setup_url = request.build_absolute_uri(
        reverse("account_setup", kwargs={"user_id": user.pk, "token": token})
    )
    full_name = user.get_full_name() or user.employee_id
    expiry_hours = max(1, settings.ACCOUNT_INVITATION_TIMEOUT // 3600)
    message = (
        f"Hello {full_name},\n\n"
        f"An account has been created for you at {user.organization.name} in NexaWork.\n"
        f"Your employee ID is {user.employee_id}.\n\n"
        f"Set your password using this one-time link:\n{setup_url}\n\n"
        f"This link expires in {expiry_hours} hours. If you did not expect this invitation, contact your workplace administrator."
    )
    sent_count = send_mail(
        subject="Set up your NexaWork account",
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
    if sent_count != 1:
        raise EmailDeliveryError("The invitation email was not accepted by the configured email backend.")
    return invitation
