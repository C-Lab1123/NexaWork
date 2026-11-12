from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import AuditEvent


PERMISSIONS = (
    ("USER_VIEW", "View employees", "employees"),
    ("USER_CREATE", "Create employees", "employees"),
    ("USER_UPDATE", "Update employees", "employees"),
    ("USER_DELETE", "Deactivate employees", "employees"),
    ("BRANCH_VIEW", "View branches", "organization"),
    ("BRANCH_CREATE", "Create branches", "organization"),
    ("BRANCH_UPDATE", "Update branches", "organization"),
    ("BRANCH_DELETE", "Deactivate branches", "organization"),
    ("DEPARTMENT_VIEW", "View departments", "organization"),
    ("DEPARTMENT_CREATE", "Create departments", "organization"),
    ("DEPARTMENT_UPDATE", "Update departments", "organization"),
    ("DEPARTMENT_DELETE", "Deactivate departments", "organization"),
    ("MEETING_CREATE", "Create meetings", "meetings"),
    ("MEETING_START", "Start meetings", "meetings"),
    ("MEETING_END", "End meetings", "meetings"),
    ("MEETING_REMOVE_PARTICIPANT", "Remove meeting participants", "meetings"),
    ("MESSAGE_SEND", "Send messages", "messaging"),
    ("MESSAGE_MODERATE", "Moderate messages", "messaging"),
    ("CHANNEL_CREATE", "Create channels", "channels"),
    ("CHANNEL_UPDATE", "Update channels", "channels"),
    ("CHANNEL_DELETE", "Delete channels", "channels"),
    ("FILE_UPLOAD", "Upload files", "files"),
    ("FILE_VIEW", "View files", "files"),
    ("FILE_DELETE", "Delete files", "files"),
    ("ANNOUNCEMENT_CREATE", "Publish announcements", "announcements"),
    ("REPORT_VIEW", "View reports", "reports"),
    ("AUDIT_LOG_VIEW", "View audit logs", "governance"),
    ("ROLE_MANAGE", "Manage roles and permissions", "governance"),
    ("AI_ASSISTANT_USE", "Use the workplace assistant", "assistant"),
    ("ORGANIZATION_MANAGE", "Manage organization settings", "organization"),
)


def has_permission(user, code):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    if not user.organization_id:
        return False
    if not user.organization.is_active:
        return False
    assigned = user.role_assignments.filter(role__organization=user.organization).exists()
    if not assigned:
        if user.can_manage_workplace:
            return True
        return code in {"MESSAGE_SEND", "FILE_VIEW", "AI_ASSISTANT_USE"}
    return user.role_assignments.filter(
        role__organization=user.organization,
        role__role_permissions__permission__code=code,
    ).exists()


def require_permission(user, code):
    if not has_permission(user, code):
        raise PermissionDenied(f"Permission required: {code}")


def organization_for(user):
    if not user.organization_id:
        raise Http404("This account is not assigned to an organization.")
    if not user.organization.is_active:
        raise PermissionDenied("This organization is currently suspended.")
    return user.organization


def record_audit(request, action, resource=None, result=AuditEvent.Result.SUCCESS, metadata=None):
    user = request.user if request.user.is_authenticated else None
    resource_type = resource.__class__.__name__ if resource is not None else ""
    resource_id = str(resource.pk) if resource is not None and resource.pk else ""
    return AuditEvent.objects.create(
        organization=getattr(user, "organization", None),
        actor=user,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        metadata=metadata or {},
        ip_address=request.META.get("REMOTE_ADDR"),
    )


def permission_required(code):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            require_permission(request.user, code)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
