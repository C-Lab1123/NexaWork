from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .models import WorkplaceFile


def validate_uploaded_file(uploaded_file):
    if uploaded_file.size > 25 * 1024 * 1024:
        raise ValidationError("Files must be 25 MB or smaller.")
    extension = uploaded_file.name.rsplit(".", 1)[-1].lower()
    uploaded_file.seek(0)
    signature = uploaded_file.read(8)
    uploaded_file.seek(0)
    signatures = {
        "pdf": signature.startswith(b"%PDF-"),
        "png": signature.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": signature.startswith(b"\xff\xd8\xff"),
        "jpeg": signature.startswith(b"\xff\xd8\xff"),
        "docx": signature.startswith(b"PK"),
        "xlsx": signature.startswith(b"PK"),
        "pptx": signature.startswith(b"PK"),
        "doc": signature.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "xls": signature.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "ppt": signature.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "txt": True,
    }
    if not signatures.get(extension, False):
        raise ValidationError("The uploaded file content does not match its file extension.")
    if extension == "txt":
        uploaded_file.seek(0)
        try:
            uploaded_file.read(4096).decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValidationError("Text files must use UTF-8 encoding.") from error
        finally:
            uploaded_file.seek(0)
    return uploaded_file


class WorkplaceFileForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and user.organization_id:
            self.fields["branch"].queryset = self.fields["branch"].queryset.filter(
                organization_id=user.organization_id
            )
            self.fields["restricted_to"].queryset = get_user_model().objects.filter(
                organization_id=user.organization_id
            )
        else:
            self.fields["branch"].queryset = self.fields["branch"].queryset.none()
            self.fields["restricted_to"].queryset = get_user_model().objects.none()

    class Meta:
        model = WorkplaceFile
        fields = ["title", "description", "branch", "file", "is_restricted", "restricted_to"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "restricted_to": forms.SelectMultiple(attrs={"size": 5}),
        }

    def clean_file(self):
        return validate_uploaded_file(self.cleaned_data["file"])


class WorkplaceFileVersionForm(forms.Form):
    file = forms.FileField()

    def clean_file(self):
        return validate_uploaded_file(self.cleaned_data["file"])
