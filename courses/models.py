from django.db import models

# Create your models here.
# 🔹 Cours lié à un utilisateur
# models.py (exemple minimal)
from django.conf import settings
from django.utils import timezone

from django.utils import timezone


class Course(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    course_markdown = models.TextField(blank=True)
    qcm_markdown = models.TextField(blank=True)
    exercises_markdown = models.TextField(blank=True)
    audio_duration = models.IntegerField(default=0)  # utilisé comme “coût”
    processing = models.BooleanField(default=False)

    # Optionnels (conseillés)
    source_type = models.CharField(max_length=10, blank=True, default="")  # "audio" | "text"
    original_filename = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    state = models.CharField(max_length=32, default="PENDING")   # PENDING/STARTED/PROGRESS/SUCCESS/FAILURE
    progress = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(null=True, blank=True)
    transcript_text = models.TextField(null=True, blank=True)               # transcript complet
    language = models.CharField(max_length=5, default="fr")   