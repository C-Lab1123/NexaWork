from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from governance.services import record_audit

from .forms import ProfileForm
from .models import User


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "landing.html", {"public_page": True})


def _login(request, employer=False):
    if request.user.is_authenticated:
        return redirect("dashboard")
    error = ""
    if request.method == "POST":
        employee_id = request.POST.get("employee_id", "").strip().upper()
        password = request.POST.get("password", "")
        user = authenticate(request, employee_id=employee_id, password=password)
        allowed = (
            user
            and user.is_active
            and not user.is_suspended
            and (not user.organization_id or user.organization.is_active)
            and (user.can_manage_workplace if employer else not user.can_manage_workplace)
        )
        if allowed:
            from governance.models import AuditEvent

            login(request, user)
            AuditEvent.objects.create(
                organization=user.organization,
                actor=user,
                action="auth.login",
                resource_type="User",
                resource_id=str(user.pk),
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            target = request.POST.get("next", "")
            if target and url_has_allowed_host_and_scheme(target, {request.get_host()}):
                return redirect(target)
            return redirect("dashboard")
        from governance.models import AuditEvent

        known_user = User.objects.filter(employee_id=employee_id).only("pk", "organization_id").first()
        AuditEvent.objects.create(
            organization=known_user.organization if known_user else None,
            actor=None,
            action="auth.login_failed",
            resource_type="User" if known_user else "",
            resource_id=str(known_user.pk) if known_user else "",
            result=AuditEvent.Result.FAILURE,
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        error = "The employee ID or password is incorrect, or this account cannot use this sign-in."
    return render(
        request,
        "accounts/login.html",
        {"employer_login": employer, "error": error, "next": request.GET.get("next", "")},
    )


def employee_login(request):
    return _login(request)


def employer_login(request):
    return _login(request, employer=True)


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        record_audit(request, "auth.logout", request.user)
    logout(request)
    messages.info(request, "You have signed out of NexaWork.")
    return redirect(reverse("employee_login"))


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        record_audit(request, "profile.updated", request.user)
        messages.success(request, "Your NexaWork profile was updated.")
        return redirect("profile")
    return render(request, "accounts/profile.html", {"form": form})


@login_required
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        record_audit(request, "auth.password_changed", user)
        messages.success(request, "Your password was changed.")
        return redirect("profile")
    return render(request, "accounts/change_password.html", {"form": form})


@login_required
def profile_photo(request, user_id):
    organization = request.user.organization
    if not organization or not organization.is_active:
        from django.http import Http404
        raise Http404
    user = get_object_or_404(User, pk=user_id, organization=organization, is_active=True)
    if not user.profile_picture:
        from django.http import Http404
        raise Http404
    from django.http import FileResponse
    import mimetypes

    try:
        photo = user.profile_picture.open("rb")
    except OSError as error:
        from django.http import Http404
        raise Http404("Profile photo unavailable.") from error
    response = FileResponse(
        photo,
        content_type=mimetypes.guess_type(user.profile_picture.name)[0] or "application/octet-stream",
    )
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response
