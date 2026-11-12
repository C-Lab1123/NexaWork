import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

import jwt
from django.conf import settings


class MediaProviderError(Exception):
    pass


class MediaWebhookError(Exception):
    pass


class LiveKitMediaProvider:
    def __init__(self):
        self.api_key = settings.LIVEKIT_API_KEY
        self.api_secret = settings.LIVEKIT_API_SECRET
        self.public_url = settings.LIVEKIT_PUBLIC_URL
        self.server_url = settings.LIVEKIT_INTERNAL_URL.rstrip("/")

    @property
    def configured(self):
        return bool(self.api_key and self.api_secret and self.public_url and self.server_url)

    def join_configuration(self, meeting, user):
        if not self.configured:
            return None
        now = int(time.time())
        room = str(meeting.meeting_id)
        claims = {
            "iss": self.api_key,
            "sub": user.employee_id,
            "name": user.get_full_name() or user.employee_id,
            "nbf": now,
            "iat": now,
            "exp": now + 3600,
            "video": {
                "roomJoin": True,
                "room": room,
                "canPublish": True,
                "canSubscribe": True,
                "canPublishData": True,
            },
        }
        return {"url": self.public_url, "token": jwt.encode(claims, self.api_secret, algorithm="HS256")}

    def remove_participant(self, meeting, user):
        if not self.configured:
            return False
        now = int(time.time())
        claims = {
            "iss": self.api_key,
            "sub": f"nexawork-admin-{meeting.host_id}",
            "nbf": now,
            "iat": now,
            "exp": now + 60,
            "video": {"roomAdmin": True, "room": str(meeting.meeting_id)},
        }
        request = urllib.request.Request(
            f"{self.server_url.rstrip('/')}/twirp/livekit.RoomService/RemoveParticipant",
            data=json.dumps(
                {"room": str(meeting.meeting_id), "identity": user.employee_id}
            ).encode(),
            headers={
                "Authorization": f"Bearer {jwt.encode(claims, self.api_secret, algorithm='HS256')}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status >= 300:
                    raise MediaProviderError("The media provider did not accept the participant removal.")
        except (urllib.error.URLError, TimeoutError) as error:
            raise MediaProviderError("Could not remove the participant from the media room.") from error
        return True

    def end_meeting(self, meeting):
        if not self.configured:
            return False
        now = int(time.time())
        claims = {
            "iss": self.api_key,
            "sub": f"nexawork-admin-{meeting.host_id}",
            "nbf": now,
            "iat": now,
            "exp": now + 60,
            "video": {"roomAdmin": True, "room": str(meeting.meeting_id)},
        }
        request = urllib.request.Request(
            f"{self.server_url}/twirp/livekit.RoomService/DeleteRoom",
            data=json.dumps({"room": str(meeting.meeting_id)}).encode(),
            headers={
                "Authorization": f"Bearer {jwt.encode(claims, self.api_secret, algorithm='HS256')}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status >= 300:
                    raise MediaProviderError("The media provider did not accept the end-meeting request.")
        except (urllib.error.URLError, TimeoutError) as error:
            raise MediaProviderError("Could not end the media room.") from error
        return True

    def mute_participant(self, meeting, user, track_sid, muted=True):
        if not self.configured:
            return False
        if not track_sid or len(track_sid) > 128:
            raise MediaProviderError("A valid media track ID is required.")
        now = int(time.time())
        claims = {
            "iss": self.api_key,
            "sub": f"nexawork-admin-{meeting.host_id}",
            "nbf": now,
            "iat": now,
            "exp": now + 60,
            "video": {"roomAdmin": True, "room": str(meeting.meeting_id)},
        }
        request = urllib.request.Request(
            f"{self.server_url}/twirp/livekit.RoomService/MutePublishedTrack",
            data=json.dumps(
                {
                    "room": str(meeting.meeting_id),
                    "identity": user.employee_id,
                    "track_sid": track_sid,
                    "muted": muted,
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {jwt.encode(claims, self.api_secret, algorithm='HS256')}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status >= 300:
                    raise MediaProviderError("The media provider rejected the mute request.")
        except (urllib.error.URLError, TimeoutError) as error:
            raise MediaProviderError("Could not reach the media provider.") from error
        return True

    def decode_webhook(self, body, authorization):
        if not self.configured or not authorization.startswith("Bearer "):
            raise MediaWebhookError("LiveKit webhook authentication is unavailable.")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            claims = jwt.decode(
                token,
                self.api_secret,
                algorithms=["HS256"],
                issuer=self.api_key,
                options={"require": ["exp", "nbf", "iss"]},
            )
        except jwt.InvalidTokenError as error:
            raise MediaWebhookError("The LiveKit webhook signature is invalid.") from error
        expected = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode().rstrip("=")
        if not hmac.compare_digest(str(claims.get("sha256", "")), expected):
            raise MediaWebhookError("The LiveKit webhook payload signature is invalid.")
        try:
            event = json.loads(body)
        except json.JSONDecodeError as error:
            raise MediaWebhookError("The LiveKit webhook payload is invalid.") from error
        if not isinstance(event, dict):
            raise MediaWebhookError("The LiveKit webhook payload is invalid.")
        return event


media_provider = LiveKitMediaProvider()
