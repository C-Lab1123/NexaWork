from django import forms
from django.contrib.auth.forms import SetPasswordForm, UserChangeForm, UserCreationForm

from .models import User


def validate_profile_picture(picture):
    if not picture or not getattr(picture, "file", None):
        return picture
    if picture.size > 5 * 1024 * 1024:
        raise forms.ValidationError("Profile photos must be 5 MB or smaller.")
    picture.seek(0)
    signature = picture.read(12)
    picture.seek(0)
    extension = picture.name.rsplit(".", 1)[-1].lower()
    valid = {
        "png": signature.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": signature.startswith(b"\xff\xd8\xff"),
        "jpeg": signature.startswith(b"\xff\xd8\xff"),
        "webp": signature.startswith(b"RIFF") and signature[8:12] == b"WEBP",
    }
    if not valid.get(extension, False):
        raise forms.ValidationError("Upload a valid PNG, JPEG, or WebP image.")
    return picture


class AccountSetupForm(SetPasswordForm):
    profile_picture = forms.FileField(
        required=False,
        label="Profile photo",
        help_text="Optional. PNG, JPEG, or WebP; maximum 5 MB.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
    )

    def clean_profile_picture(self):
        return validate_profile_picture(self.cleaned_data.get("profile_picture"))

    def save(self, commit=True):
        user = super().save(commit=False)
        picture = self.cleaned_data.get("profile_picture")
        if picture:
            user.profile_picture = picture
        if commit:
            user.save()
        return user


class NexaWorkUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("employee_id", "first_name", "last_name", "email", "organization", "role", "is_staff")


class NexaWorkUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class ProfileForm(forms.ModelForm):
    email_notifications = forms.BooleanField(required=False, label="Email me workplace notifications")

    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "phone",
            "job_title",
            "presence",
            "profile_picture",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email_notifications"].initial = self.instance.notification_preferences.get("email", False)

    def clean_profile_picture(self):
        return validate_profile_picture(self.cleaned_data.get("profile_picture"))

    def save(self, commit=True):
        user = super().save(commit=False)
        user.notification_preferences = {
            **user.notification_preferences,
            "email": self.cleaned_data.get("email_notifications", False),
        }
        if commit:
            user.save()
        return user
