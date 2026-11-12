from django.contrib import admin

from .models import DocumentVersion, WorkplaceFile


@admin.register(WorkplaceFile)
class WorkplaceFileAdmin(admin.ModelAdmin):
    list_display = ("title", "organization", "branch", "uploaded_by", "is_restricted", "uploaded_at")
    list_filter = ("organization", "branch", "is_restricted")
    search_fields = ("title", "description")
    filter_horizontal = ("restricted_to",)


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("workplace_file", "uploaded_by", "uploaded_at")
    list_filter = ("uploaded_at",)
    search_fields = ("workplace_file__title", "uploaded_by__employee_id")
    readonly_fields = ("workplace_file", "file", "uploaded_by", "uploaded_at")
