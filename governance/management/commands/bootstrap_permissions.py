from django.core.management.base import BaseCommand

from governance.models import PermissionCode, Role, RolePermission
from governance.services import PERMISSIONS


class Command(BaseCommand):
    help = "Create NexaWork permission definitions and starter organization roles."

    def add_arguments(self, parser):
        parser.add_argument("--organization", type=int, help="Organization ID to initialize.")

    def handle(self, *args, **options):
        for code, label, module in PERMISSIONS:
            PermissionCode.objects.update_or_create(code=code, defaults={"label": label, "module": module})

        organization_id = options.get("organization")
        if not organization_id:
            self.stdout.write(self.style.SUCCESS("Permission catalog initialized. Pass --organization ID to add starter roles."))
            return

        admin_role, _ = Role.objects.get_or_create(
            organization_id=organization_id,
            name="Organization Administrator",
            defaults={"description": "Manage the organization's NexaWork workspace."},
        )
        employee_role, _ = Role.objects.get_or_create(
            organization_id=organization_id,
            name="Employee",
            defaults={"description": "Standard employee access."},
        )
        admin_codes = [code for code, _, _ in PERMISSIONS]
        employee_codes = {"MESSAGE_SEND", "FILE_VIEW", "AI_ASSISTANT_USE"}
        RolePermission.objects.bulk_create(
            [
                RolePermission(role=admin_role, permission_id=PermissionCode.objects.get(code=code).pk)
                for code in admin_codes
            ],
            ignore_conflicts=True,
        )
        RolePermission.objects.bulk_create(
            [
                RolePermission(role=employee_role, permission_id=PermissionCode.objects.get(code=code).pk)
                for code in employee_codes
            ],
            ignore_conflicts=True,
        )
        self.stdout.write(self.style.SUCCESS(f"Initialized permissions and roles for organization {organization_id}."))
