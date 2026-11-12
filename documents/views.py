from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from .forms import WorkplaceFileForm, WorkplaceFileVersionForm
from .models import DocumentVersion, WorkplaceFile
from governance.services import has_permission, record_audit


def _visible_files(user):
    if not user.organization_id:
        return WorkplaceFile.objects.none()
    files = WorkplaceFile.objects.filter(organization_id=user.organization_id)
    if user.branch_id:
        files = files.filter(Q(branch__isnull=True) | Q(branch_id=user.branch_id))
    else:
        files = files.filter(branch__isnull=True)
    return files.filter(Q(is_restricted=False) | Q(restricted_to=user) | Q(uploaded_by=user)).distinct()


@login_required
def file_list(request):
    if not request.user.organization_id:
        raise Http404("This account is not assigned to an organization.")
    form = WorkplaceFileForm(user=request.user)
    if request.method == "POST":
        if not has_permission(request.user, "FILE_UPLOAD"):
            raise Http404
        form = WorkplaceFileForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            workplace_file = form.save(commit=False)
            workplace_file.organization = request.user.organization
            workplace_file.uploaded_by = request.user
            if workplace_file.branch and workplace_file.branch.organization_id != request.user.organization_id:
                form.add_error("branch", "Choose a branch in your organization.")
            if not form.errors:
                workplace_file.save()
                form.save_m2m()
                record_audit(request, "file.uploaded", workplace_file)
                messages.success(request, "File uploaded securely.")
                return redirect("file_list")
    return render(
        request,
        "documents/file_list.html",
        {
            "files": _visible_files(request.user).prefetch_related("versions__uploaded_by"),
            "form": form,
            "can_upload_files": has_permission(request.user, "FILE_UPLOAD"),
        },
    )


@login_required
@require_GET
def file_download(request, file_id):
    workplace_file = get_object_or_404(_visible_files(request.user), pk=file_id)
    try:
        file_handle = workplace_file.file.open("rb")
    except OSError as error:
        raise Http404("The requested file is unavailable.") from error
    record_audit(request, "file.downloaded", workplace_file)
    return FileResponse(file_handle, as_attachment=True, filename=workplace_file.file.name.rsplit("/", 1)[-1])


@login_required
@require_GET
def file_version_download(request, file_id, version_id):
    workplace_file = get_object_or_404(_visible_files(request.user), pk=file_id)
    version = get_object_or_404(DocumentVersion, workplace_file=workplace_file, pk=version_id)
    try:
        file_handle = version.file.open("rb")
    except OSError as error:
        raise Http404("The requested file version is unavailable.") from error
    record_audit(request, "file.version_downloaded", workplace_file, metadata={"version_id": version.pk})
    return FileResponse(file_handle, as_attachment=True, filename=version.file.name.rsplit("/", 1)[-1])


@login_required
@require_POST
def file_upload_version(request, file_id):
    if not has_permission(request.user, "FILE_UPLOAD"):
        raise Http404
    workplace_file = get_object_or_404(_visible_files(request.user), pk=file_id)
    form = WorkplaceFileVersionForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, form.errors.as_text())
        return redirect("file_list")

    previous_file = workplace_file.file
    version = DocumentVersion(workplace_file=workplace_file, uploaded_by=request.user)
    with previous_file.open("rb") as previous_content:
        version.file.save(previous_file.name.rsplit("/", 1)[-1], ContentFile(previous_content.read()), save=False)
    version.save()

    workplace_file.file = form.cleaned_data["file"]
    workplace_file.save(update_fields=["file"])
    previous_file.delete(save=False)
    record_audit(request, "file.version_uploaded", workplace_file, metadata={"version_id": version.pk})
    messages.success(request, "New file version uploaded. The previous version is available in its history.")
    return redirect("file_list")


@login_required
@require_POST
def file_delete(request, file_id):
    workplace_file = get_object_or_404(_visible_files(request.user), pk=file_id)
    if not has_permission(request.user, "FILE_DELETE"):
        raise Http404
    record_audit(request, "file.deleted", workplace_file)
    for version in workplace_file.versions.all():
        version.file.delete(save=False)
    workplace_file.file.delete(save=False)
    workplace_file.delete()
    messages.success(request, "File deleted.")
    return redirect("file_list")
