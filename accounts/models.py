from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import FileExtensionValidator
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, employee_id, password, **extra_fields):
        if not employee_id:
            raise ValueError("An employee ID is required.")
        user = self.model(employee_id=employee_id.strip().upper(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, employee_id, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(employee_id, password, **extra_fields)

    def create_superuser(self, employee_id, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.EMPLOYER)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superusers must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superusers must have is_superuser=True.")
        return self._create_user(employee_id, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        EMPLOYEE = "employee", "Employee"
        MANAGER = "manager", "Manager"
        EMPLOYER = "employer", "Employer / administrator"

    class Presence(models.TextChoices):
        AVAILABLE = "available", "Available"
        BUSY = "busy", "Busy"
        AWAY = "away", "Away"
        OFFLINE = "offline", "Offline"

    username = None
    employee_id = models.CharField(max_length=32, unique=True)
    email = models.EmailField(blank=True)
    organization = models.ForeignKey(
        "organization.Organization", on_delete=models.PROTECT, null=True, blank=True, related_name="employees"
    )
    branch = models.ForeignKey(
        "organization.Branch", on_delete=models.SET_NULL, null=True, blank=True, related_name="employees"
    )
    department = models.ForeignKey(
        "organization.Department", on_delete=models.SET_NULL, null=True, blank=True, related_name="employees"
    )
    team = models.ForeignKey("organization.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="employees")
    job_role = models.ForeignKey(
        "organization.JobRole", on_delete=models.SET_NULL, null=True, blank=True, related_name="employees"
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.EMPLOYEE)
    phone = models.CharField(max_length=32, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    profile_picture = models.FileField(
        upload_to="profiles/",
        blank=True,
        validators=[FileExtensionValidator(["png", "jpg", "jpeg", "webp"])],
    )
    presence = models.CharField(max_length=12, choices=Presence.choices, default=Presence.AVAILABLE)
    is_suspended = models.BooleanField(default=False)
    notification_preferences = models.JSONField(default=dict, blank=True)
    joined_at = models.DateField(null=True, blank=True)

    USERNAME_FIELD = "employee_id"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta:
        ordering = ["last_name", "first_name", "employee_id"]

    def __str__(self):
        return self.get_full_name() or self.employee_id

    def save(self, *args, **kwargs):
        self.employee_id = self.employee_id.strip().upper()
        return super().save(*args, **kwargs)

    @property
    def can_manage_workplace(self):
        return self.is_staff or self.role == self.Role.EMPLOYER
