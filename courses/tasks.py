# courses/tasks.py
from pathlib import Path
from celery import shared_task
from .logic import pipeline_from_audio, pipeline_from_text, to_wsl_path  # <<< NEW
from .models import Course


@shared_task
def process_course_task(course_id: int, source_type: str, payload: str, title: str | None, language: str = "fr"):
    """
    source_type: "audio" -> payload = absolute audio path (Windows or POSIX)
                 "text"  -> payload = raw text
    """
    course = Course.objects.get(id=course_id)

    # Guard: avoid double-processing if someone re-clicks
    if getattr(course, "state", "") == "SUCCESS":
        return "Already processed"

    # Mark started (simple, no progress dance)
    course.state = "STARTED"
    course.processing = True
    course.save(update_fields=["state", "processing"])

    try:
        if source_type == "audio":
            # Normalize Windows path to WSL if needed
            audio_path_norm = to_wsl_path(payload)  # <<< NEW
            p = Path(audio_path_norm)
            if not p.exists():
                # Log in DB for debugging
                course.error = f"Audio file not found: {audio_path_norm}"
                course.state = "FAILURE"
                course.processing = False
                course.save(update_fields=["error", "state", "processing"])
                raise FileNotFoundError(f"Missing file: {audio_path_norm}")

            outs = pipeline_from_audio(str(p), title_hint=title, language=language)

        else:
            outs = pipeline_from_text(payload, title_hint=title, language=language)

        # Single write of final results
        course.transcript_text     = outs.transcript
        course.course_markdown     = outs.course
        course.qcm_markdown        = outs.qcm
        course.exercises_markdown  = outs.exercises
        course.processing          = False
        course.state               = "SUCCESS"
        course.save(update_fields=[
            "transcript_text", "course_markdown", "qcm_markdown",
            "exercises_markdown", "processing", "state"
        ])
        return "OK"

    except Exception as e:
        course.processing = False
        course.state = "FAILURE"
        course.error = str(e)
        course.save(update_fields=["processing", "state", "error"])
        raise
