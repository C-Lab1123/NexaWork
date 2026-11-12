from django.contrib import admin
from django.urls import include, path

from accounts import views as account_views
from governance import views as governance_views

admin.site.site_header = "NexaWork administration"
admin.site.site_title = "NexaWork Admin"
admin.site.index_title = "Workplace management"

urlpatterns = [
    path("", account_views.home, name="home"),
    path("login/", account_views.employee_login, name="employee_login"),
    path("employer/login/", account_views.employer_login, name="employer_login"),
    path("profile/", account_views.profile, name="profile"),
    path("profile/password/", account_views.change_password, name="change_password"),
    path("profile/<int:user_id>/photo/", account_views.profile_photo, name="profile_photo"),
    path(
        "account/setup/<int:user_id>/<str:token>/",
        governance_views.account_setup,
        name="account_setup",
    ),
    path("logout/", account_views.logout_view, name="logout"),
    path("health/", governance_views.health, name="health"),
    path("ready/", governance_views.readiness, name="readiness"),
    path("search/", governance_views.global_search, name="global_search"),
    path("manage/", include("governance.urls")),
    path("admin/", admin.site.urls),
    path("", include("communications.urls")),
    path("files/", include("documents.urls")),
    path("assistant/", include("assistant.urls")),
]
