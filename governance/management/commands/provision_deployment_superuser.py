import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create a deployment superuser from temporary environment variables."

    def handle(self, *args, **options):
        employee_id = os.getenv("NEXAWORK_BOOTSTRAP_SUPERUSER_EMPLOYEE_ID", "").strip()
        password = os.getenv("NEXAWORK_BOOTSTRAP_SUPERUSER_PASSWORD", "")
        if not employee_id and not password:
            self.stdout.write("No deployment superuser credentials configured; skipping.")
            return
        if not employee_id or not password:
            raise CommandError("Both deployment superuser environment variables must be set.")

        user_model = get_user_model()
        existing_user = user_model.objects.filter(employee_id=employee_id).first()
        if existing_user:
            if not existing_user.is_superuser:
                raise CommandError(f"Employee ID {employee_id} already belongs to a non-superuser.")
            self.stdout.write(f"Superuser {employee_id} already exists; leaving it unchanged.")
            return

        user = user_model(employee_id=employee_id)
        validate_password(password, user=user)
        user_model.objects.create_superuser(employee_id=employee_id, password=password)
        self.stdout.write(self.style.SUCCESS(f"Created deployment superuser {employee_id}."))
