import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from organization.models import Organization

from .models import WorkplaceFile


class PrivateWorkplaceFileTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=Path(self.temp_media.name))
        self.media_override.enable()
        self.organization = Organization.objects.create(name="Nexa Labs", slug="nexa-labs")
        self.manager = User.objects.create_user(
            employee_id="NW-MGR",
            password="SecurePassword!123",
            organization=self.organization,
            role=User.Role.EMPLOYER,
            is_staff=True,
        )
        self.employee = User.objects.create_user(
            employee_id="NW-EMP", password="SecurePassword!123", organization=self.organization
        )
        self.unselected_employee = User.objects.create_user(
            employee_id="NW-UNSELECTED",
            password="SecurePassword!123",
            organization=self.organization,
        )
        self.other_employee = User.objects.create_user(
            employee_id="NW-OTHER",
            password="SecurePassword!123",
            organization=self.organization,
        )

    def tearDown(self):
        self.media_override.disable()
        self.temp_media.cleanup()

    def test_file_download_requires_login_and_company_membership(self):
        workplace_file = WorkplaceFile.objects.create(
            organization=self.organization,
            title="Team guide",
            uploaded_by=self.manager,
            file=SimpleUploadedFile("guide.pdf", b"private file"),
        )
        download_url = reverse("file_download", args=[workplace_file.pk])
        self.assertEqual(self.client.get(download_url).status_code, 302)

        self.client.force_login(self.employee)
        response = self.client.get(download_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))

        self.client.force_login(self.other_employee)
        self.assertEqual(self.client.get(download_url).status_code, 200)

    def test_restricted_file_is_visible_only_to_selected_users(self):
        workplace_file = WorkplaceFile.objects.create(
            organization=self.organization,
            title="Private brief",
            uploaded_by=self.manager,
            is_restricted=True,
            file=SimpleUploadedFile("brief.pdf", b"private"),
        )
        workplace_file.restricted_to.add(self.employee)
        self.client.force_login(self.employee)
        self.assertEqual(
            self.client.get(reverse("file_download", args=[workplace_file.pk])).status_code,
            200,
        )
        self.client.force_login(self.unselected_employee)
        self.assertEqual(
            self.client.get(reverse("file_download", args=[workplace_file.pk])).status_code,
            404,
        )

    def test_admin_can_upload_file_for_their_organization(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse("file_list"),
            {
                "title": "Welcome pack",
                "description": "First week information",
                "file": SimpleUploadedFile("welcome.pdf", b"%PDF-1.4\nwelcome"),
                "is_restricted": "",
                "restricted_to": [],
            },
        )
        self.assertRedirects(response, reverse("file_list"))
        workplace_file = WorkplaceFile.objects.get(title="Welcome pack")
        self.assertEqual(workplace_file.organization, self.organization)
        self.assertEqual(workplace_file.uploaded_by, self.manager)

    def test_uploading_new_version_preserves_and_serves_previous_file(self):
        workplace_file = WorkplaceFile.objects.create(
            organization=self.organization,
            title="Team guide",
            uploaded_by=self.manager,
            file=SimpleUploadedFile("guide.pdf", b"%PDF-1.4\noriginal"),
        )
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("file_upload_version", args=[workplace_file.pk]),
            {"file": SimpleUploadedFile("guide.pdf", b"%PDF-1.4\nupdated")},
        )

        self.assertRedirects(response, reverse("file_list"))
        workplace_file.refresh_from_db()
        version = workplace_file.versions.get()
        self.assertEqual(version.uploaded_by, self.manager)
        with version.file.open("rb") as archived_file:
            self.assertEqual(archived_file.read(), b"%PDF-1.4\noriginal")
        with workplace_file.file.open("rb") as current_file:
            self.assertEqual(current_file.read(), b"%PDF-1.4\nupdated")

        response = self.client.get(
            reverse("file_version_download", args=[workplace_file.pk, version.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4\noriginal")

    def test_employee_without_upload_permission_cannot_upload_new_version(self):
        workplace_file = WorkplaceFile.objects.create(
            organization=self.organization,
            title="Team guide",
            uploaded_by=self.manager,
            file=SimpleUploadedFile("guide.pdf", b"%PDF-1.4\noriginal"),
        )
        self.client.force_login(self.employee)

        response = self.client.post(
            reverse("file_upload_version", args=[workplace_file.pk]),
            {"file": SimpleUploadedFile("guide.pdf", b"%PDF-1.4\nupdated")},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(workplace_file.versions.exists())
