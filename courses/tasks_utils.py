"""
Task utilities for OMYA course processing.
Provides a unified interface for both async (Celery) and sync processing.
"""

from django.conf import settings
from django.db import transaction
from .models import Course
from .logic import pipeline_from_audio, pipeline_from_text


def enqueue_course(course_id: int, mode: str, payload_path: str = None, payload_text: str = None, title_hint: str = None):
    """
    Enqueue course processing either asynchronously (Celery) or synchronously based on USE_ASYNC setting.
    
    Args:
        course_id: ID of the Course object to process
        mode: Processing mode ("audio" or "text")
        payload_path: Path to audio file (for audio mode)
        payload_text: Text content (for text mode)
        title_hint: Optional title hint for the course
    
    Returns:
        If async: Celery task result
        If sync: None (processing completed synchronously)
    """
    if settings.USE_ASYNC:
        # Use Celery for async processing
        from .tasks import process_course_async
        return process_course_async.delay(course_id, mode, payload_path, payload_text, title_hint)
    else:
        # Process synchronously
        return _process_course_sync(course_id, mode, payload_path, payload_text, title_hint)


def _process_course_sync(course_id: int, mode: str, payload_path: str = None, payload_text: str = None, title_hint: str = None):
    """
    Process course synchronously without Celery.
    This function replicates the logic from process_course_async but runs synchronously.
    """
    course = Course.objects.get(id=course_id)
    try:
        if mode == "audio":
            out = pipeline_from_audio(payload_path, title_hint=title_hint)
        elif mode == "text":
            out = pipeline_from_text(payload_text, title_hint=title_hint)
        else:
            raise ValueError(f"Mode inconnu: {mode}")

        with transaction.atomic():
            course.course_markdown = out.course
            course.qcm_markdown = out.qcm
            course.exercises_markdown = out.exercises
            course.processing = False
            course.save()
            
    except Exception as e:
        # En prod, loggue l'erreur et éventuellement un champ error_message
        course.processing = False
        course.description = (course.description or "") + f"\n\n[ERREUR TRAITEMENT] {e}"
        course.save()
        raise