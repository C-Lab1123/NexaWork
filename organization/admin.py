from django.contrib import admin

from .models import Branch, Department, JobRole, Organization, Region, Team


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    fields = ("name", "slug", "is_active", "settings")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register([Region, Branch, Department, Team, JobRole])
