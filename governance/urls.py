from django.urls import path

from . import views

urlpatterns = [
    path("", views.manage_dashboard, name="manage_dashboard"),
    path("employees/", views.employee_list, name="manage_employee_list"),
    path("employees/add/", views.employee_create, name="manage_employee_create"),
    path("employees/<int:user_id>/invitation/", views.employee_invitation_resend, name="manage_employee_invitation_resend"),
    path("employees/<int:user_id>/edit/", views.employee_edit, name="manage_employee_edit"),
    path("employees/<int:user_id>/status/", views.employee_toggle_status, name="manage_employee_status"),
    path("branches/", views.branch_list, name="manage_branch_list"),
    path("branches/<int:branch_id>/toggle/", views.branch_toggle, name="manage_branch_toggle"),
    path("departments/", views.department_list, name="manage_department_list"),
    path("departments/<int:department_id>/toggle/", views.department_toggle, name="manage_department_toggle"),
    path("channels/", views.channel_manage, name="manage_channel_list"),
    path("channels/<int:channel_id>/archive/", views.channel_archive, name="manage_channel_archive"),
    path("channels/<int:channel_id>/delete/", views.channel_delete, name="manage_channel_delete"),
    path("announcements/new/", views.announcement_create, name="manage_announcement_create"),
    path("meetings/new/", views.meeting_create, name="manage_meeting_create"),
    path("audit/", views.audit_log, name="manage_audit_log"),
    path("roles/", views.role_list, name="manage_role_list"),
    path("roles/<int:role_id>/users/<int:user_id>/toggle/", views.role_assign, name="manage_role_assign"),
    path("setup/", views.company_setup, name="company_setup"),
]
