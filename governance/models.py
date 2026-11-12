from django.conf import settings
from django.db import models


class PermissionCode(models.Model):
    code = models.CharField(max_length=80, unique=True)
    label = models.CharField(max_length=120)
    module = models.CharField(max_length=40)

    class Meta:
        ordering = ["module", "code"]

    def __str__(self):
        return self.code


class Role(models.Model):
    organization = models.ForeignKey(
        "organization.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="access_roles",
    )
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=240, blank=True)
    is_system = models.BooleanField(default=False)
    permissions = models.ManyToManyField(PermissionCode, through="RolePermission", related_name="roles")
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="UserRole",
        through_fields=("role", "user"),
        related_name="access_roles",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_role_per_org"),
        ]

    def __str__(self):
        return self.name


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions")
    permission = models.ForeignKey(PermissionCode, on_delete=models.CASCADE, related_name="role_permissions")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="unique_permission_per_role"),
        ]


class UserRole(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assignments")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="user_assignments")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_roles",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "role"], name="unique_user_role")]


class AccountInvitation(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_invitation",
    )
    token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Account invitation for {self.user}"


class AuditEvent(models.Model):
    class Result(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"

    organization = models.ForeignKey(
        "organization.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=80, blank=True)
    resource_id = models.CharField(max_length=80, blank=True)
    result = models.CharField(max_length=8, choices=Result.choices, default=Result.SUCCESS)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} ({self.result})"
