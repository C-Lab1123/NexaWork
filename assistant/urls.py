from django.urls import path

from . import views

urlpatterns = [path("", views.assistant_home, name="assistant_home")]
