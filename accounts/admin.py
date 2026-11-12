from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .forms import NexaWorkUserChangeForm, NexaWorkUserCreationForm
from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = NexaWorkUserChangeForm
    add_form = NexaWorkUserCreationForm
    ordering = ("employee_id",)
    list_display = ("employee_id", "first_name", "last_name", "organization", "role", "is_active")
    list_filter = ("organization", "role", "is_active", "is_staff")
    search_fields = ("employee_id", "first_name", "last_name", "email")
    fieldsets = (
        (None, {"fields": ("employee_id", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email", "phone")}),
        ("Workplace", {"fields": ("organization", "branch", "department", "team", "job_role", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("employee_id", "password1", "password2", "first_name", "last_name", "email", "organization", "role", "is_staff"),
            },
        ),
    )
    filter_horizontal = ("groups", "user_permissions")
