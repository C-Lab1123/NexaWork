import re
import tempfile
from datetime import timedelta
from unittest import skip

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test import override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from accounts.models import User
from communications.models import Announcement, Channel, Meeting, MeetingParticipant, Message, Notification
from communications.tasks import deliver_scheduled_announcements
from organization.models import Organization

from .models import AccountInvitation, AuditEvent, PermissionCode, Role, RolePermission, UserRole


class OrganizationManagementTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Nexa Labs", slug="nexa-labs")
        self.admin = User.objects.create_user(
            employee_id="NW-ADMIN",
            password="SecurePassword!123",
            organization=self.organization,
            role=User.Role.EMPLOYER,
            is_staff=True,
        )
        self.employee = User.objects.create_user(
            employee_id="NW-EMP",
            password="SecurePassword!123",
            organization=self.organization,
        )
        self.other_employee = User.objects.create_user(
            employee_id="OTHER-EMP",
            password="SecurePassword!123",
            organization=self.organization,
        )

    def test_admin_dashboard_and_employee_search_are_company_scoped(self):
        AuditEvent.objects.create(
            organization=self.organization,
            actor=None,
            action="system.event",
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("manage_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["employee_count"], 3)
        self.assertContains(response, "System")

        response = self.client.get(reverse("manage_employee_list"), {"q": "EMP"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.employee.employee_id)
        self.assertContains(response, self.other_employee.employee_id)

    def test_global_search_returns_visible_announcements(self):
        Announcement.objects.create(
            organization=self.organization,
            title="Channel updates",
            body="A workspace update.",
            created_by=self.admin,
        )
        self.client.force_login(self.employee)

        response = self.client.get(reverse("global_search"), {"q": "channel"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Channel updates")

    def test_global_search_renders_message_results_instead_of_model_objects(self):
        channel = Channel.objects.create(organization=self.organization, name="team-chat")
        Message.objects.create(
            channel=channel,
            author=self.employee,
            body="The schedule is ready.",
        )
        self.client.force_login(self.employee)

        response = self.client.get(reverse("global_search"), {"q": "schedule"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The schedule is ready.")
        self.assertNotContains(response, "Message object")

    def test_unassigned_superuser_is_redirected_to_company_setup(self):
        platform_admin = User.objects.create_superuser(
            employee_id="NW-ROOT", password="StrongPassword!789"
        )
        self.client.force_login(platform_admin)

        response = self.client.get(reverse("manage_dashboard"))

        self.assertRedirects(response, reverse("company_setup"))

    def test_platform_administration_route_is_removed(self):
        with self.assertRaises(NoReverseMatch):
            reverse("platform_dashboard")

    def test_channel_creator_is_added_to_private_channel_members(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("manage_channel_list"),
            {
                "name": "admin-employee-private",
                "description": "Private discussion",
                "kind": Channel.Kind.PRIVATE,
                "members": [self.employee.pk],
            },
        )

        self.assertRedirects(response, reverse("manage_channel_list"))
        channel = Channel.objects.get(name="admin-employee-private")
        self.assertQuerySetEqual(
            channel.members.order_by("pk"),
            sorted([self.admin, self.employee], key=lambda user: user.pk),
            transform=lambda user: user,
        )
        self.client.force_login(self.admin)
        channel_list = self.client.get(reverse("channel_list"))
        self.assertContains(channel_list, "admin-employee-private")

    def test_admin_can_archive_and_restore_channel_without_deleting_history(self):
        channel = Channel.objects.create(
            organization=self.organization,
            name="project-history",
        )
        self.client.force_login(self.admin)

        archived = self.client.post(
            reverse("manage_channel_archive", args=[channel.pk])
        )
        channel.refresh_from_db()
        self.assertRedirects(archived, reverse("manage_channel_list"))
        self.assertIsNotNone(channel.archived_at)

        restored = self.client.post(
            reverse("manage_channel_archive", args=[channel.pk])
        )
        channel.refresh_from_db()
        self.assertRedirects(restored, reverse("manage_channel_list"))
        self.assertIsNone(channel.archived_at)

    def test_company_setup_assigns_superuser_to_existing_company(self):
        setup_admin = User.objects.create_superuser(
            employee_id="NW-ROOT",
            password="SecurePassword!789",
        )
        self.client.force_login(setup_admin)

        response = self.client.post(reverse("company_setup"))

        self.assertRedirects(response, reverse("manage_dashboard"))
        setup_admin.refresh_from_db()
        self.assertEqual(setup_admin.organization, self.organization)
        self.assertEqual(setup_admin.role, User.Role.EMPLOYER)
        self.assertTrue(setup_admin.is_staff)

    def test_audit_log_displays_events_without_an_actor(self):
        AuditEvent.objects.create(
            organization=self.organization,
            actor=None,
            action="system.event",
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("manage_audit_log"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "System")

    def test_standard_employee_cannot_open_management_dashboard(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("manage_employee_list"))
        self.assertEqual(response.status_code, 403)

    def test_custom_rbac_role_grants_only_its_configured_permission(self):
        view_permission = PermissionCode.objects.create(
            code="USER_VIEW", label="View employees", module="employees"
        )
        report_permission = PermissionCode.objects.create(
            code="REPORT_VIEW", label="View reports", module="reports"
        )
        role = Role.objects.create(organization=self.organization, name="Directory viewer")
        RolePermission.objects.create(role=role, permission=view_permission)
        UserRole.objects.create(user=self.employee, role=role)
        self.assertTrue(self.employee.has_perm("governance.USER_VIEW"))

        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse("manage_employee_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("manage_audit_log")).status_code, 403)
        self.assertFalse(role.permissions.filter(pk=report_permission.pk).exists())

    def test_branch_creation_is_tenant_scoped_and_audited(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("manage_branch_list"), {"name": "Lagos", "city": "Lagos"})
        self.assertRedirects(response, reverse("manage_branch_list"))
        branch = self.organization.branches.get(name="Lagos")
        self.assertEqual(branch.organization_id, self.organization.pk)
        self.assertTrue(AuditEvent.objects.filter(action="branch.created", resource_id=str(branch.pk)).exists())

    def test_suspended_organization_blocks_existing_authenticated_sessions(self):
        self.organization.is_active = False
        self.organization.save(update_fields=["is_active"])
        self.client.force_login(self.admin)
        response = self.client.get(reverse("manage_dashboard"))
        self.assertEqual(response.status_code, 403)

    @skip("Multi-organization provisioning was replaced by one-company setup.")
    def test_platform_admin_creates_tenant_with_initial_employer(self):
        platform_admin = User.objects.create_superuser(
            employee_id="NW-ROOT", password="AnotherSecurePassword!123"
        )
        self.client.force_login(platform_admin)
        response = self.client.post(
            reverse("platform_organization_create"),
            {
                "name": "Nexa Engineering Ltd",
                "slug": "nexa-engineering",
                "admin_employee_id": "NX-OWNER",
                "admin_first_name": "Ari",
                "admin_last_name": "Owner",
                "admin_password": "DistinctSecretPhrase!984",
            },
        )
        self.assertRedirects(response, reverse("platform_dashboard"))
        organization = Organization.objects.get(slug="nexa-engineering")
        employer = User.objects.get(employee_id="NX-OWNER")
        self.assertEqual(employer.organization_id, organization.pk)
        self.assertTrue(employer.is_staff)
        self.assertTrue(AuditEvent.objects.filter(action="organization.created", organization=organization).exists())

    def test_database_rejects_a_second_company(self):
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Organization.objects.create(name="Second company", slug="second-company")

    def test_publishing_announcement_notifies_active_employees(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("manage_announcement_create"),
            {
                "title": "Office update",
                "body": "The office opens at nine.",
                "priority": "normal",
            },
        )

        self.assertRedirects(response, reverse("announcements"))
        notification = Notification.objects.get(user=self.employee)
        self.assertEqual(notification.title, "Announcement: Office update")
        self.assertEqual(notification.body, "The office opens at nine.")

    def test_scheduled_announcement_notifies_employees_when_due_once(self):
        self.client.force_login(self.admin)
        publish_at = timezone.localtime(timezone.now() + timedelta(minutes=5))

        response = self.client.post(
            reverse("manage_announcement_create"),
            {
                "title": "Upcoming office update",
                "body": "The office opens later.",
                "priority": "normal",
                "publish_at": publish_at.strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertRedirects(response, reverse("announcements"))
        announcement = Announcement.objects.get(title="Upcoming office update")
        self.assertFalse(Notification.objects.filter(title__contains=announcement.title).exists())
        self.assertIsNone(announcement.notifications_sent_at)

        announcement.publish_at = timezone.now() - timedelta(seconds=1)
        announcement.save(update_fields=["publish_at"])

        self.assertEqual(deliver_scheduled_announcements.run(), 1)
        self.assertTrue(
            Notification.objects.filter(
                user=self.employee,
                title="Announcement: Upcoming office update",
            ).exists()
        )
        announcement.refresh_from_db()
        self.assertIsNotNone(announcement.notifications_sent_at)
        self.assertEqual(deliver_scheduled_announcements.run(), 0)

    def test_scheduling_meeting_notifies_selected_employee(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("manage_meeting_create"),
            {
                "title": "Planning meeting",
                "starts_at": timezone.localtime(timezone.now() + timedelta(hours=1)).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "meeting_type": "video",
                "invitees": [self.employee.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        notification = Notification.objects.get(user=self.employee)
        self.assertEqual(notification.title, "Meeting invitation: Planning meeting")

    def test_scheduling_meeting_without_invitees_invites_all_active_employees(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("manage_meeting_create"),
            {
                "title": "Company voice meeting",
                "starts_at": timezone.localtime(timezone.now() + timedelta(hours=1)).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
                "meeting_type": "audio",
            },
        )

        self.assertEqual(response.status_code, 302)
        meeting = Meeting.objects.get(title="Company voice meeting")
        self.assertEqual(meeting.status, Meeting.Status.SCHEDULED)
        self.assertSetEqual(
            set(meeting.participant_records.values_list("user_id", flat=True)),
            {self.admin.pk, self.employee.pk, self.other_employee.pk},
        )
        self.assertSetEqual(
            set(
                Notification.objects.filter(title="Meeting invitation: Company voice meeting")
                .values_list("user_id", flat=True)
            ),
            {self.employee.pk, self.other_employee.pk},
        )

        self.client.force_login(self.employee)
        meeting_list = self.client.get(reverse("meeting_list"))
        self.assertEqual(meeting_list.status_code, 200)
        self.assertContains(meeting_list, "Company voice meeting")
        meeting_detail = self.client.get(reverse("meeting_detail", args=[meeting.pk]))
        self.assertEqual(meeting_detail.status_code, 200)
        self.assertContains(meeting_detail, "Join when ready")
        self.assertContains(meeting_detail, 'data-meeting-type="audio"')
        meeting.refresh_from_db()
        self.assertEqual(meeting.status, Meeting.Status.SCHEDULED)
        self.assertFalse(
            meeting.participant_records.filter(
                user=self.admin,
                status=MeetingParticipant.Status.JOINED,
            ).exists()
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_new_employer_is_not_assigned_the_default_employee_permission_role(self):
        employee_role = Role.objects.create(organization=self.organization, name="Employee")
        view_permission = PermissionCode.objects.create(
            code="USER_VIEW", label="View employees", module="employees"
        )
        RolePermission.objects.create(role=employee_role, permission=view_permission)
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("manage_employee_create"),
            {
                "employee_id": "NW-EMPLOYER",
                "first_name": "Company",
                "last_name": "Administrator",
                "email": "employer@example.com",
                "role": User.Role.EMPLOYER,
            },
        )

        self.assertRedirects(response, reverse("manage_employee_list"))
        employer = User.objects.get(employee_id="NW-EMPLOYER")
        self.assertFalse(employer.role_assignments.exists())
        self.assertTrue(employer.has_perm("governance.USER_CREATE"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_employee_invitation_sets_password_once(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("manage_employee_create"),
            {
                "employee_id": "NW-NEW",
                "first_name": "New",
                "last_name": "Colleague",
                "email": "new.colleague@example.com",
                "job_title": "Analyst",
                "branch": "",
                "department": "",
                "role": User.Role.EMPLOYEE,
            },
        )

        self.assertRedirects(response, reverse("manage_employee_list"))
        employee = User.objects.get(employee_id="NW-NEW")
        self.assertFalse(employee.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(employee.employee_id, mail.outbox[0].body)
        match = re.search(r"https?://testserver/account/setup/(\d+)/([A-Za-z0-9_-]+)", mail.outbox[0].body)
        self.assertIsNotNone(match)
        user_id, token = match.groups()

        setup_url = reverse("account_setup", args=[user_id, token])
        self.assertEqual(self.client.get(setup_url).status_code, 200)
        self.client.force_login(self.admin)
        authenticated_response = self.client.get(setup_url)
        self.assertEqual(authenticated_response.status_code, 200)
        self.assertContains(authenticated_response, "Create your password")
        self.assertContains(authenticated_response, 'name="new_password1"')
        self.assertEqual(authenticated_response.content.count(b"data-password-toggle"), 2)
        self.assertContains(authenticated_response, 'aria-controls="id_new_password1"')
        self.assertContains(authenticated_response, 'aria-controls="id_new_password2"')
        self.assertContains(authenticated_response, 'name="profile_picture"')
        self.client.logout()
        temp_media = tempfile.TemporaryDirectory()
        self.addCleanup(temp_media.cleanup)
        with override_settings(MEDIA_ROOT=temp_media.name):
            invalid_response = self.client.post(
                setup_url,
                {
                    "new_password1": "DistinctPassword!984",
                    "new_password2": "DistinctPassword!984",
                    "profile_picture": SimpleUploadedFile("not-an-image.png", b"not an image"),
                },
            )
            self.assertEqual(invalid_response.status_code, 200)
            self.assertContains(invalid_response, "Upload a valid PNG, JPEG, or WebP image.")

            response = self.client.post(
                setup_url,
                {
                    "new_password1": "DistinctPassword!984",
                    "new_password2": "DistinctPassword!984",
                    "profile_picture": SimpleUploadedFile(
                        "employee.png", b"\x89PNG\r\n\x1a\nprofile image"
                    ),
                },
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], reverse("employee_login"))
            employee.refresh_from_db()
            self.assertTrue(employee.check_password("DistinctPassword!984"))
            self.assertTrue(employee.profile_picture.name.startswith("profiles/"))
            with employee.profile_picture.open("rb") as picture:
                self.assertEqual(picture.read(), b"\x89PNG\r\n\x1a\nprofile image")
            invitation = AccountInvitation.objects.get(user=employee)
            self.assertIsNotNone(invitation.used_at)
            self.assertEqual(self.client.get(setup_url).status_code, 400)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_resending_invitation_invalidates_previous_link(self):
        employee = User.objects.create_user(
            employee_id="NW-PENDING",
            password=None,
            email="pending@example.com",
            organization=self.organization,
        )
        self.client.force_login(self.admin)

        self.client.post(reverse("manage_employee_invitation_resend", args=[employee.pk]))
        first_link = re.search(
            r"https?://testserver/account/setup/(\d+)/([A-Za-z0-9_-]+)",
            mail.outbox[-1].body,
        )
        self.assertIsNotNone(first_link)
        self.client.post(reverse("manage_employee_invitation_resend", args=[employee.pk]))
        second_link = re.search(
            r"https?://testserver/account/setup/(\d+)/([A-Za-z0-9_-]+)",
            mail.outbox[-1].body,
        )
        self.assertIsNotNone(second_link)
        self.assertNotEqual(first_link.group(2), second_link.group(2))
        self.assertEqual(self.client.get(reverse("account_setup", args=first_link.groups())).status_code, 400)
        self.assertEqual(self.client.get(reverse("account_setup", args=second_link.groups())).status_code, 200)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_invitation_must_be_unexpired_and_established_accounts_cannot_be_invited(self):
        employee = User.objects.create_user(
            employee_id="NW-EXPIRED",
            password=None,
            email="expired@example.com",
            organization=self.organization,
        )
        self.client.force_login(self.admin)
        self.client.post(reverse("manage_employee_invitation_resend", args=[employee.pk]))
        match = re.search(
            r"https?://testserver/account/setup/(\d+)/([A-Za-z0-9_-]+)",
            mail.outbox[-1].body,
        )
        invitation = AccountInvitation.objects.get(user=employee)
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
        invitation.save(update_fields=["expires_at"])
        self.assertEqual(self.client.get(reverse("account_setup", args=match.groups())).status_code, 400)

        mail.outbox.clear()
        self.client.post(reverse("manage_employee_invitation_resend", args=[self.employee.pk]))
        self.assertEqual(mail.outbox, [])


class FirstCompanySetupTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            employee_id="NW-ROOT",
            password="SecurePassword!789",
        )
        self.client.force_login(self.admin)

    def test_superuser_can_create_the_installations_only_company(self):
        response = self.client.post(
            reverse("company_setup"),
            {"name": "Nexa Labs", "slug": "nexa-labs"},
        )

        self.assertRedirects(response, reverse("manage_dashboard"))
        organization = Organization.objects.get()
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.organization, organization)
        self.assertEqual(self.admin.role, User.Role.EMPLOYER)
        self.assertTrue(self.admin.is_staff)
        self.assertTrue(AuditEvent.objects.filter(action="organization.created", organization=organization).exists())
