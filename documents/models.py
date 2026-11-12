from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models


class WorkplaceFile(models.Model):
    organization = models.ForeignKey("organization.Organization", on_delete=models.CASCADE, related_name="files")
    branch = models.ForeignKey(
        "organization.Branch", on_delete=models.CASCADE, null=True, blank=True, related_name="files"
    )
    title = models.CharField(max_length=180)
    description = models.CharField(max_length=500, blank=True)
    file = models.FileField(
        upload_to="private_documents/%Y/%m/",
        validators=[FileExtensionValidator(["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "png", "jpg", "jpeg"])],
    )
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="uploaded_files")
    restricted_to = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="accessible_workplace_files")
    is_restricted = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.title


class DocumentVersion(models.Model):
    workplace_file = models.ForeignKey(WorkplaceFile, on_delete=models.CASCADE, related_name="versions")
    file = models.FileField(upload_to="private_documents/versions/%Y/%m/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_file_versions",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
