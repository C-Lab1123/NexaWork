from django.urls import path

from . import views

urlpatterns = [
    path("", views.file_list, name="file_list"),
    path("<int:file_id>/download/", views.file_download, name="file_download"),
    path("<int:file_id>/versions/<int:version_id>/download/", views.file_version_download, name="file_version_download"),
    path("<int:file_id>/versions/upload/", views.file_upload_version, name="file_upload_version"),
    path("<int:file_id>/delete/", views.file_delete, name="file_delete"),
]
