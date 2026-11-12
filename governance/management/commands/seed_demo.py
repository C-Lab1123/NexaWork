from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.crypto import get_random_string

from communications.models import Announcement, Channel, ChannelMembership, Meeting, MeetingParticipant, Message, Notification
from governance.models import AuditEvent, PermissionCode, Role, RolePermission, UserRole
from governance.services import PERMISSIONS
from organization.models import Branch, Department, JobRole, Organization, Region, Team

User = get_user_model()


class Command(BaseCommand):
    help = "Create demo data in the installation's single company workspace."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Shared demo password. Defaults to a randomly generated value.")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo seed data can only be created when DJANGO_DEBUG=true.")

        password = options["password"] or get_random_string(24)
        organization = Organization.objects.first()
        if organization is None:
            organization, _ = Organization.objects.get_or_create(
                slug="nexa-engineering",
                defaults={"name": "Nexa Engineering Ltd"},
            )
        regions = {
            name: Region.objects.get_or_create(organization=organization, name=name)[0]
            for name in ("South West", "North Central", "South South", "North West")
        }
        branches = {}
        for name, city, region in (
            ("Lagos", "Lagos", "South West"),
            ("Abuja", "Abuja", "North Central"),
            ("Port Harcourt", "Port Harcourt", "South South"),
            ("Kano", "Kano", "North West"),
        ):
            branches[name] = Branch.objects.get_or_create(
                organization=organization,
                name=name,
                defaults={"city": city, "region": regions[region]},
            )[0]
        departments = {
            name: Department.objects.get_or_create(organization=organization, name=name)[0]
            for name in ("Engineering", "Finance", "Human Resources", "Operations", "Administration")
        }
        titles = {
            name: JobRole.objects.get_or_create(organization=organization, name=name)[0]
            for name in ("Platform Administrator", "Branch Manager", "HR Manager", "Team Lead", "Software Engineer")
        }
        team, _ = Team.objects.get_or_create(
            organization=organization,
            name="Platform Engineering",
            defaults={"department": departments["Engineering"]},
        )

        people = {}
        definitions = (
            ("NX-ADMIN", "Amina", "Okafor", User.Role.EMPLOYER, "Lagos", "Administration", "Platform Administrator", True),
            ("NX-MGR", "Chidi", "Bello", User.Role.MANAGER, "Abuja", "Operations", "Branch Manager", False),
            ("NX-HR", "Zara", "Adeyemi", User.Role.MANAGER, "Lagos", "Human Resources", "HR Manager", False),
            ("NX-LEAD", "Emeka", "Nwosu", User.Role.MANAGER, "Lagos", "Engineering", "Team Lead", False),
            ("NX-EMP", "Tomi", "Danladi", User.Role.EMPLOYEE, "Port Harcourt", "Engineering", "Software Engineer", False),
            ("NX-EMP2", "Ife", "Abubakar", User.Role.EMPLOYEE, "Kano", "Finance", "Software Engineer", False),
        )
        for employee_id, first_name, last_name, role, branch, department, title, is_staff in definitions:
            person, created = User.objects.get_or_create(
                employee_id=employee_id,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "role": role,
                    "organization": organization,
                    "branch": branches[branch],
                    "department": departments[department],
                    "job_title": title,
                    "job_role": titles[title],
                    "team": team if department == "Engineering" else None,
                    "is_staff": is_staff,
                    "email": f"{employee_id.lower()}@example.test",
                },
            )
            if created:
                person.set_password(password)
                person.save()
            people[employee_id] = person

        platform, created = User.objects.get_or_create(
            employee_id="NX-PLATFORM",
            defaults={
                "first_name": "NexaWork",
                "last_name": "Platform Admin",
                "is_staff": True,
                "is_superuser": True,
                "role": User.Role.EMPLOYER,
            },
        )
        if created:
            platform.set_password(password)
            platform.save()

        for code, label, module in PERMISSIONS:
            PermissionCode.objects.update_or_create(code=code, defaults={"label": label, "module": module})
        all_codes = [code for code, _, _ in PERMISSIONS]
        role_permissions = {
            "Organization Administrator": set(all_codes),
            "Branch Manager": {
                "USER_VIEW", "USER_UPDATE", "BRANCH_VIEW", "DEPARTMENT_VIEW", "MEETING_CREATE",
                "MEETING_REMOVE_PARTICIPANT", "MESSAGE_SEND", "CHANNEL_CREATE", "FILE_UPLOAD",
                "FILE_VIEW", "ANNOUNCEMENT_CREATE", "AI_ASSISTANT_USE",
            },
            "HR Manager": {
                "USER_VIEW", "USER_CREATE", "USER_UPDATE", "DEPARTMENT_VIEW", "ANNOUNCEMENT_CREATE",
                "REPORT_VIEW", "AI_ASSISTANT_USE",
            },
            "Team Lead": {"USER_VIEW", "MESSAGE_SEND", "CHANNEL_CREATE", "MEETING_CREATE", "FILE_VIEW", "AI_ASSISTANT_USE"},
            "Employee": {"MESSAGE_SEND", "FILE_VIEW", "AI_ASSISTANT_USE"},
        }
        roles = {}
        for name, codes in role_permissions.items():
            role, _ = Role.objects.get_or_create(
                organization=organization,
                name=name,
                defaults={"description": f"NexaWork {name.lower()} access."},
            )
            role.permissions.set(PermissionCode.objects.filter(code__in=codes))
            roles[name] = role
        assignments = {
            "NX-ADMIN": "Organization Administrator",
            "NX-MGR": "Branch Manager",
            "NX-HR": "HR Manager",
            "NX-LEAD": "Team Lead",
            "NX-EMP": "Employee",
            "NX-EMP2": "Employee",
        }
        for employee_id, role_name in assignments.items():
            UserRole.objects.get_or_create(
                user=people[employee_id],
                role=roles[role_name],
                defaults={"assigned_by": people["NX-ADMIN"]},
            )

        general, _ = Channel.objects.get_or_create(
            organization=organization,
            name="general",
            defaults={"description": "Organization-wide updates and conversation.", "created_by": people["NX-ADMIN"]},
        )
        engineering, _ = Channel.objects.get_or_create(
            organization=organization,
            name="engineering",
            defaults={
                "description": "Engineering team collaboration.",
                "kind": Channel.Kind.PRIVATE,
                "created_by": people["NX-LEAD"],
            },
        )
        general.members.add(*people.values())
        engineering.members.add(people["NX-LEAD"], people["NX-EMP"], people["NX-EMP2"])
        Message.objects.get_or_create(
            channel=general,
            author=people["NX-ADMIN"],
            body="Welcome to NexaWork! Introduce yourself and share what you're working on.",
        )
        Message.objects.get_or_create(
            channel=engineering,
            author=people["NX-LEAD"],
            body="Engineering team: use this channel to coordinate platform work.",
        )
        Announcement.objects.get_or_create(
            organization=organization,
            title="Welcome to NexaWork",
            defaults={
                "body": "Nexa Engineering teams are now connected on NexaWork. Visit your channels and introduce yourself.",
                "created_by": people["NX-ADMIN"],
                "priority": "important",
            },
        )
        meeting, _ = Meeting.objects.get_or_create(
            organization=organization,
            title="Weekly engineering sync",
            defaults={
                "description": "Share updates and coordinate work across branches.",
                "starts_at": timezone.now() + timedelta(days=1),
                "host": people["NX-LEAD"],
                "meeting_type": "video",
            },
        )
        MeetingParticipant.objects.get_or_create(
            meeting=meeting,
            user=people["NX-LEAD"],
            defaults={"role": MeetingParticipant.Role.HOST},
        )
        for attendee in (people["NX-EMP"], people["NX-EMP2"], people["NX-MGR"]):
            MeetingParticipant.objects.get_or_create(meeting=meeting, user=attendee)
        Notification.objects.get_or_create(
            user=people["NX-EMP"],
            title="Welcome to NexaWork",
            defaults={"body": "Your NexaWork workspace is ready.", "url": "/dashboard/"},
        )
        AuditEvent.objects.get_or_create(
            organization=organization,
            action="demo.seeded",
            resource_type="Organization",
            resource_id=str(organization.pk),
            defaults={"actor": platform, "metadata": {"source": "seed_demo"}},
        )

        self.stdout.write(self.style.SUCCESS("NexaWork demo workspace is ready."))
        self.stdout.write("Employer login: NX-ADMIN")
        self.stdout.write("Employee login: NX-EMP")
        self.stdout.write("Platform super admin: NX-PLATFORM")
        self.stdout.write(f"Demo password (development only): {password}")
