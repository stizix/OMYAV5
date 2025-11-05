# views.py — version clean avec fallback mutagen→pydub/ffmpeg pour la durée MP3
import uuid
import os
import math
import traceback
from pathlib import Path
from django.db import transaction
from courses.utils import text_chars  # nouvelle util
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db import transaction
from django.db.models import F

from .forms import CourseUploadForm
from .models import Course
from .tasks import process_course_task

# Tu utilises la version synchrone de ta logique ici
from .logic import (
    pipeline_from_audio,
    pipeline_from_text,
)

# =========================
# Helpers robustes
# =========================

# Compteur de tokens : on essaye tiktoken si présent, sinon fallback grossier
try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_ENC.encode(text))

except Exception:
    def _count_tokens(text: str) -> int:
        # Fallback très grossier (≈ 1 token / 4 caractères)
        return max(1, len(text) // 4)

def _text_seconds_equiv(text: str) -> int:
    """
    Approximation : ~3 tokens ≈ 1 seconde "équivalente audio".
    Sert uniquement à débiter des crédits de manière homogène texte vs audio.
    Ajuste le ratio si tu veux un pricing différent.
    """
    tokens = _count_tokens(text or "")
    return int(math.ceil(tokens / 3))

def get_audio_duration_seconds(audio_abs_path: str) -> int:
    """
    Retourne la durée en secondes d'un fichier audio (MP3 notamment).
    Stratégie à 3 étages :
      1) mutagen.mp3.MP3 (spécifique MP3)
      2) mutagen.File (générique)
      3) pydub + ffmpeg (lit le flux, très robuste si ffmpeg dispo)

    Si ffmpeg n'est pas dans le PATH, tu peux définir la variable d'env FFMPEG_BIN
    (ex: FFMPEG_BIN=C:\\ffmpeg\\bin\\ffmpeg.exe) — le code ci-dessous la prend en compte.
    """
    # Sanity checks
    if not os.path.isfile(audio_abs_path):
        raise ValueError(f"Fichier introuvable: {audio_abs_path}")
    if os.path.getsize(audio_abs_path) == 0:
        raise ValueError("Fichier audio vide")

    # 1) mutagen.mp3.MP3 (spécifique MP3, plus fiable sur certains encodages)
    try:
        from mutagen.mp3 import MP3  # type: ignore
        mp3 = MP3(audio_abs_path)
        if mp3 and mp3.info and getattr(mp3.info, "length", None):
            return int(mp3.info.length)
    except Exception:
        pass  # on tente plus loin

    # 2) mutagen.File (générique)
    try:
        from mutagen import File as MutagenFile  # type: ignore
        m = MutagenFile(audio_abs_path)
        if m and getattr(m, "info", None) and getattr(m.info, "length", None):
            return int(m.info.length)
    except Exception:
        pass

    # 3) pydub + ffmpeg (lit réellement le flux)
    try:
        from pydub import AudioSegment  # type: ignore
        ffbin = os.environ.get("FFMPEG_BIN")
        if ffbin:
            # Pydub cherche ffmpeg dans PATH; on peut le forcer via cette variable
            AudioSegment.converter = ffbin
        seg = AudioSegment.from_file(audio_abs_path)
        return int(round(len(seg) / 1000.0))
    except Exception as e:
        raise ValueError(
            "Durée audio introuvable (mutagen et pydub/ffmpeg ont échoué). "
            "Installe ffmpeg et/ou définis FFMPEG_BIN, et vérifie le fichier. "
            f"Détail: {e}"
        )
# =========================
# Vues
# =========================
from django.utils.html import escape
from django.core.exceptions import ValidationError

# Strong caps
MAX_TEXT_CHARS = 200_000            # hard cap for pasted/uploaded text
MAX_AUDIO_MB   = 100                # hard cap for audio size

# MIME check (needs python-magic: pip install python-magic)
try:
    import magic
    def _mime_of(django_file) -> str:
        head = django_file.read(4096)
        django_file.seek(0)
        return magic.from_buffer(head, mime=True)
except Exception:
    magic = None
    def _mime_of(django_file) -> str:
        # Fallback: trust extension only (less secure). Prefer installing python-magic.
        return "application/octet-stream"

def text_chars(payload: str) -> int:
    payload = (payload or "").replace("\r\n", "\n").strip()
    return len(payload)

@login_required
def upload_course(request):
    if request.method == "POST":
        form = CourseUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "Formulaire invalide.")
            return render(request, "upload_course.html", {"form": form})

        user = request.user
        try:
            user.reset_monthly_credits()
        except Exception:
            pass

        title = form.cleaned_data["title"].strip()
        description = (form.cleaned_data.get("description") or "").strip()
        language = form.cleaned_data.get("language") or "fr"
        audio_file = form.cleaned_data.get("audio_file")
        text_input = (form.cleaned_data.get("text_input") or "").strip()
        text_file = form.cleaned_data.get("text_file")

        # ---------- SECURITY: enforce XOR + size/MIME checks ----------
        chosen = sum(bool(x) for x in [audio_file, text_input, text_file])
        if chosen == 0:
            messages.error(request, "Aucune source fournie.")
            return render(request, "upload_course.html", {"form": form})
        if chosen > 1:
            messages.error(request, "Une seule source: audio OU texte.")
            return render(request, "upload_course.html", {"form": form})

        source_type = None
        payload = None
        duration_seconds = 0
        text_chars_count = 0
        orig_name = "unknown"

        if audio_file:
            source_type = "audio"

            # Size cap
            if audio_file.size > MAX_AUDIO_MB * 1024 * 1024:
                messages.error(request, f"Audio trop lourd (> {MAX_AUDIO_MB} MB).")
                return render(request, "upload_course.html", {"form": form})

            # MIME check (defense in depth)
            mime = _mime_of(audio_file)
            if not mime.startswith("audio/"):
                messages.error(request, f"Type de fichier invalide ({mime}).")
                return render(request, "upload_course.html", {"form": form})

            # Generate safe name & store
            ext = os.path.splitext(getattr(audio_file, "name", "audio"))[1].lower() or ".bin"
            safe_name = f"{uuid.uuid4().hex}{ext}"
            upload_dir = os.path.join("uploads", "audio")
            stored_rel_path = default_storage.save(os.path.join(upload_dir, safe_name), audio_file)
            audio_abs_path = os.path.join(settings.MEDIA_ROOT, stored_rel_path)

            # Derive duration
            try:
                duration_seconds = get_audio_duration_seconds(audio_abs_path)
            except Exception as e:
                # Remove bad file if unreadable
                try:
                    default_storage.delete(stored_rel_path)
                except Exception:
                    pass
                messages.error(request, f"Durée audio invalide: {e}")
                return render(request, "upload_course.html", {"form": form})

            payload = audio_abs_path
            orig_name = safe_name

        elif text_input:
            source_type = "text"
            if len(text_input) > MAX_TEXT_CHARS:
                messages.error(request, f"Texte trop long (> {MAX_TEXT_CHARS} caractères).")
                return render(request, "upload_course.html", {"form": form})
            payload = text_input
            text_chars_count = text_chars(payload)
            orig_name = f"text_input_{timezone.now().strftime('%Y%m%d_%H%M%S')}.txt"

        elif text_file:
            source_type = "text"

            # Size cap
            if text_file.size > MAX_TEXT_CHARS * 2:  # generous for CR/LF etc.
                messages.error(request, "Fichier texte trop volumineux.")
                return render(request, "upload_course.html", {"form": form})

            # MIME check
            mime = _mime_of(text_file)
            if mime not in ("text/plain", "application/octet-stream"):  # octet-stream is a common browser fallback
                messages.error(request, f"Type de fichier invalide ({mime}).")
                return render(request, "upload_course.html", {"form": form})

            raw = text_file.read()
            try:
                payload = raw.decode("utf-8")
            except UnicodeDecodeError:
                payload = raw.decode("latin-1")

            if len(payload) > MAX_TEXT_CHARS:
                messages.error(request, f"Texte trop long (> {MAX_TEXT_CHARS} caractères).")
                return render(request, "upload_course.html", {"form": form})

            text_chars_count = text_chars(payload)
            orig_name = getattr(text_file, "name", "text_file.txt")

        # ---------- Credits (unchanged) ----------
        if source_type == "audio":
            if duration_seconds <= 0:
                messages.error(request, "Durée audio invalide.")
                return render(request, "upload_course.html", {"form": form})
            if not user.has_enough_audio(duration_seconds):
                messages.error(
                    request,
                    f"Crédits audio insuffisants. Restant: {user.audio_credits_s}s, requis: {duration_seconds}s."
                )
                return redirect("account_page")
            if not user.debit_audio(duration_seconds):
                messages.error(request, "Crédits audio insuffisants (concurrence). Réessaie.")
                return redirect("account_page")
        else:
            if text_chars_count == 0:
                messages.error(request, "Texte vide.")
                return render(request, "upload_course.html", {"form": form})
            if not user.has_enough_text(text_chars_count):
                messages.error(
                    request,
                    f"Crédits texte insuffisants. Restant: {user.text_credits_ch} ch, requis: {text_chars_count} ch."
                )
                return redirect("account_page")
            if not user.debit_text(text_chars_count):
                messages.error(request, "Crédits texte insuffisants (concurrence). Réessaie.")
                return redirect("account_page")

        # ---------- Create course (escape plain text fields) ----------
        course = Course.objects.create(
            user=user,
            title=title,                                  # title is plain text field rendered in inputs (safe)
            description=escape(description),              # SECURITY: escape any description you later render
            language=language,
            course_markdown="",                           # will be filled by task
            qcm_markdown="",
            exercises_markdown="",
            transcript_text="",
            audio_duration=(duration_seconds if source_type == "audio" else 0),
            processing=True,
            source_type=source_type,
            original_filename=orig_name,
            state="QUEUED",
            progress=1,
            error=""
        )

        # ---------- Dispatch Celery (unchanged) ----------
        try:
            async_result = process_course_task.delay(
                course.id,
                source_type,
                payload,
                title,
                language or "fr"
            )
            if hasattr(course, "celery_task_id"):
                course.celery_task_id = async_result.id
                course.save(update_fields=["celery_task_id"])
        except Exception:
            # Refund on enqueue failure
            if source_type == "audio":
                user.__class__.objects.filter(pk=user.pk).update(
                    audio_credits_s=F("audio_credits_s") + duration_seconds
                )
            else:
                user.__class__.objects.filter(pk=user.pk).update(
                    text_credits_ch=F("text_credits_ch") + text_chars_count
                )
            messages.error(request, "Erreur d’envoi de tâche. Aucun crédit débité.")
            return render(request, "upload_course.html", {"form": form})

        messages.success(request, "Traitement lancé. Tu seras notifié quand c’est prêt.")
        return redirect("account_page")

    # GET
    form = CourseUploadForm()
    return render(request, "upload_course.html", {"form": form})

@login_required
def course_detail(request, course_id):
    """
    Page de détail d'un cours de l'utilisateur.
    Affiche les champs Course.* (markdowns, transcript, états, etc.).
    """
    course = get_object_or_404(Course, id=course_id, user=request.user)
    return render(request, "course_detail.html", {"course": course})

@login_required
def delete_course(request, course_id):
    """
    Suppression d'un cours (avec confirmation côté template).
    """
    course = get_object_or_404(Course, id=course_id, user=request.user)
    if request.method == "POST":
        course.delete()
        messages.success(request, "Le cours a bien été supprimé.")
        return redirect("account_page")
    return render(request, "delete_course_confirm.html", {"course": course})

@login_required
def rename_course(request, course_id):
    """
    Renommer un cours (titre + description).
    """
    course = get_object_or_404(Course, id=course_id, user=request.user)
    if request.method == "POST":
        new_title = request.POST.get("title", "").strip()
        new_description = request.POST.get("description", "").strip()
        if new_title:
            # SECURITY: escape description at write-time
            course.title = new_title
            course.description = escape(new_description)
            course.save(update_fields=["title", "description"])
            messages.success(request, "Le cours a bien été renommé.")
            return redirect("course_detail", course_id=course.id)
        else:
            messages.error(request, "Le titre ne peut pas être vide.")
    return render(request, "rename_course.html", {"course": course})

@login_required
def course_status(request, course_id):
    """
    Renvoie un JSON léger avec l'état du traitement.
    Utile si tu veux rafraîchir la page via JS sans la recharger.
    """
    try:
        course = Course.objects.get(id=course_id, user=request.user)
    except Course.DoesNotExist:
        raise Http404

    data = {
        "state": getattr(course, "state", "UNKNOWN"),
        "progress": getattr(course, "progress", 0),
        "processing": getattr(course, "processing", False),
        "error": getattr(course, "error", "") or "",
        "has_result": bool(course.course_markdown or course.qcm_markdown or course.exercises_markdown),
    }
    return JsonResponse(data)
