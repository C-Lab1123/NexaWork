from django import forms
from django.contrib.auth import get_user_model

from communications.models import Announcement, Channel, Meeting
from organization.models import Branch, Department, Organization

from .models import Role

User = get_user_model()


class CompanySetupForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ("name", "slug")


class EmployeeCreateForm(forms.ModelForm):
    email = forms.EmailField(
        required=True,
        help_text="We'll send a secure account setup link to this address.",
    )

    class Meta:
        model = User
        fields = (
            "employee_id",
            "first_name",
            "last_name",
            "email",
            "job_title",
            "branch",
            "department",
            "role",
        )

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.fields["branch"].queryset = Branch.objects.filter(organization=organization, is_active=True)
        self.fields["department"].queryset = Department.objects.filter(organization=organization, is_active=True)

    def save(self, commit=True):
        employee = super().save(commit=False)
        employee.organization = self.organization
        employee.set_unusable_password()
        if commit:
            employee.save()
        return employee


class EmployeeEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = (
            "employee_id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "job_title",
            "branch",
            "department",
            "team",
            "job_role",
            "role",
            "is_active",
            "is_suspended",
        )

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.filter(organization=organization)
        self.fields["department"].queryset = Department.objects.filter(organization=organization)
        self.fields["team"].queryset = organization.teams.all()
        self.fields["job_role"].queryset = organization.job_roles.all()


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ["name", "city", "region"]

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.fields["region"].queryset = organization.regions.all()


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name"]


class ChannelForm(forms.ModelForm):
    class Meta:
        model = Channel
        fields = ["name", "description", "kind", "members"]
        widgets = {"members": forms.SelectMultiple(attrs={"size": 6})}

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["members"].queryset = User.objects.filter(organization=organization, is_active=True)


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = [
            "title",
            "body",
            "priority",
            "branch",
            "region",
            "department",
            "team",
            "publish_at",
            "expires_at",
        ]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 5}),
            "publish_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
        help_texts = {
            "publish_at": "Enter time in your device's local timezone.",
            "expires_at": "Enter time in your device's local timezone.",
        }

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = organization.branches.all()
        self.fields["region"].queryset = organization.regions.all()
        self.fields["department"].queryset = organization.departments.all()
        self.fields["team"].queryset = organization.teams.all()


class MeetingForm(forms.ModelForm):
    invitees = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"size": 6}),
        help_text="Leave blank to invite all active employees in your organization.",
    )

    class Meta:
        model = Meeting
        fields = ["title", "description", "starts_at", "meeting_type", "provider_url"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invitees"].queryset = User.objects.filter(organization=organization, is_active=True)


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ["name", "description"]
