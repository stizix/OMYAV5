
from django.urls import path
from .views import upload_course
from . import views
urlpatterns = [

    path("upload_course/", upload_course, name="upload_course"),
    path("course/<int:course_id>/", views.course_detail, name="course_detail"),
    path("course/<int:course_id>/delete/", views.delete_course, name="delete_course"),
    path("course/<int:course_id>/rename/", views.rename_course, name="rename_course"),
]