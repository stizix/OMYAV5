#!/usr/bin/env python3
"""
OMYA Pipeline (single file)
- Audio → transcript (chunked) → summaries (map-reduce) → course (MD) → QCM → exercises
- NEW: Direct TEXT mode (skip audio/transcription)
- Robust chunking, retries, and clean CLI

Requirements:
  pip install openai python-dotenv pydub tiktoken (optional)
  ffmpeg installed for pydub
Env:
  OPENAI_API_KEY=...

Cleanup:
  OMYA_DELETE_ORIGINAL_AUDIO=1 (default) to also delete original uploaded audio after processing
"""

import os
import re
import sys
import math
import json
import time
import glob
import argparse
from typing import List, Dict, Optional
from dataclasses import dataclass
from pathlib import Path  # <<< NEW

from dotenv import load_dotenv
from pydub import AudioSegment

try:
    import tiktoken  # optional; used if available
except Exception:
    tiktoken = None

from openai import OpenAI
from celery import shared_task  # (import présent si tu l'utilises ailleurs)

load_dotenv()
client = OpenAI()

# =====================
# Config & Helpers
# =====================
COURSE_MODEL = os.getenv("OMYA_COURSE_MODEL", "gpt-4o")
SUMMARY_MODEL = os.getenv("OMYA_SUMMARY_MODEL", "gpt-4o-mini")
QCM_MODEL = os.getenv("OMYA_QCM_MODEL", "gpt-4o")
EXO_MODEL = os.getenv("OMYA_EXO_MODEL", "gpt-4o")
TRANSCRIBE_MODEL = os.getenv("OMYA_TRANSCRIBE_MODEL", "whisper-1")  # or gpt-4o-transcribe

MAX_AUDIO_MB = int(os.getenv("OMYA_MAX_AUDIO_MB", "24"))
SENTENCES_PER_CHUNK = int(os.getenv("OMYA_SENTENCES_PER_CHUNK", "12"))
TARGET_TOKENS_PER_CHUNK = int(os.getenv("OMYA_TOKENS_PER_CHUNK", "900"))  # used if tiktoken available

MAX_RETRIES = 4
RETRY_BACKOFF = 2.0

# Cleanup behavior (delete original file too?)
DELETE_ORIGINAL_AUDIO = os.getenv("OMYA_DELETE_ORIGINAL_AUDIO", "1") == "1"


@dataclass
class PipelineOutputs:
    transcript: str
    chunks_preview: List[str]
    summaries_preview: List[str]
    course: str
    qcm: str
    exercises: str


def _retry(fn, *args, **kwargs):
    """Exponential backoff retry wrapper for API calls."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise
            sleep_s = RETRY_BACKOFF ** attempt
            print(f"⚠️ API error: {e}. Retry {attempt}/{MAX_RETRIES-1} in {sleep_s:.1f}s...", file=sys.stderr)
            time.sleep(sleep_s)


# =====================
# Cross-OS path helper (Windows → WSL)
# =====================

def to_wsl_path(p: Optional[str]) -> Optional[str]:
    """
    Convertit un chemin absolu Windows (ex: C:\\Users\\...) en chemin WSL (/mnt/c/Users/...)
    Laisse inchangé si déjà POSIX ou si None.
    """
    if p is None:
        return None
    # déjà POSIX ?
    if p.startswith("/"):
        return p
    # Windows absolu ?
    if re.match(r"^[A-Za-z]:\\", p):
        drive = p[0].lower()
        p2 = p.replace("\\", "/")
        return f"/mnt/{drive}/{p2[3:]}"
    return p


# =====================
# Cleanup helpers
# =====================

def _safe_rm(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

def cleanup_audio_files(original_path: Optional[str], part_paths: Optional[List[str]] = None):
    """Delete chunk files and (optionally) original upload."""
    # delete explicit part files if provided
    if part_paths:
        for p in part_paths:
            _safe_rm(p)
    # also sweep any stray *_part*.mp3 next to original (extra safety)
    if original_path:
        for p in glob.glob(f"{original_path}_part*.mp3"):
            _safe_rm(p)
        if DELETE_ORIGINAL_AUDIO:
            _safe_rm(original_path)


# =====================
# 1) Audio splitting by size
# =====================

def split_audio_by_size(file_path: str, max_mb: int = MAX_AUDIO_MB) -> List[str]:
    # Normalize path for WSL if coming from Windows
    file_path = to_wsl_path(file_path)  # <<< NEW
    file_path = str(Path(file_path))    # normalize
    if not Path(file_path).exists():    # guard with explicit error
        raise FileNotFoundError(file_path)

    file_size_bytes = os.path.getsize(file_path)
    max_bytes = max_mb * 1024 * 1024
    audio = AudioSegment.from_file(file_path)

    if file_size_bytes <= max_bytes:
        out = f"{file_path}_part0.mp3"
        audio.export(out, format="mp3")
        print("✅ Audio en 1 partie (pas de découpage)")
        return [out]

    num_parts = math.ceil(file_size_bytes / max_bytes)
    print(f"⚙️ Fichier {round(file_size_bytes / (1024*1024), 2)} Mo → découpe en {num_parts} parties…")
    part_duration_ms = len(audio) // num_parts

    chunks = []
    start = 0
    while start < len(audio):
        end = min(start + part_duration_ms, len(audio))
        chunk = audio[start:end]
        chunks.append(chunk)
        start = end

    # Merge tiny tail if < 10 seconds into previous chunk
    if len(chunks) > 1 and len(chunks[-1]) < 10_000:
        print("⏩ Dernière partie fusionnée (trop courte)")
        chunks[-2] = chunks[-2] + chunks[-1]
        chunks = chunks[:-1]

    out_paths = []
    for i, ch in enumerate(chunks):
        out = f"{file_path}_part{i}.mp3"
        ch.export(out, format="mp3")
        out_paths.append(out)
    return out_paths


# =====================
# 2) Transcription
# =====================

def transcribe_audio(file_path: str, model: str = TRANSCRIBE_MODEL) -> str:
    file_path = to_wsl_path(file_path)  # <<< NEW (safety)
    with open(file_path, "rb") as f:
        tr = _retry(
            client.audio.transcriptions.create,
            model=model,
            file=f,
            response_format="text",
        )
    return tr


# =====================
# 3) Chunking utilities (sentences / tokens)
# =====================

def sentence_split(text: str) -> List[str]:
    # Naive but effective sentence split (keeps punctuation)
    chunks = re.split(r"(?<=[.!?])\s+", text.strip())
    return [c for c in chunks if c]


def estimate_tokens(text: str) -> int:
    if tiktoken is None:
        # rough estimate: 1 token ≈ 4 chars in English; FR similar order
        return max(1, len(text) // 4)
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def chunk_text(text: str,
               sentences_per_chunk: int = SENTENCES_PER_CHUNK,
               target_tokens: int = TARGET_TOKENS_PER_CHUNK) -> List[str]:
    sents = sentence_split(text)
    chunks: List[str] = []
    buf: List[str] = []
    buf_tokens = 0

    for s in sents:
        candidate = (" ".join(buf + [s])).strip()
        toks = estimate_tokens(candidate)
        if buf and (toks > target_tokens or len(buf) >= sentences_per_chunk):
            chunks.append(" ".join(buf).strip())
            buf = [s]
            buf_tokens = estimate_tokens(s)
        else:
            buf.append(s)
            buf_tokens = toks

    if buf:
        chunks.append(" ".join(buf).strip())
    return chunks


# =====================
# 4) LLM helpers
# =====================

def _lang_label(language: str) -> str:
    mapping = {
        "fr": "French",
        "en": "English",
        "es": "Spanish",
        "de": "German",
        "it": "Italian",
    }
    return mapping.get(language, "French")


def summarize_chunk(chunk: str, language: str = "fr") -> str:
    resp = _retry(
        client.chat.completions.create,
        model=SUMMARY_MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": f"You are a precise academic summarizer. Output bullet points only. Always respond in {_lang_label(language)}."},
            {"role": "user", "content": f"Summarize the following in 5-10 concise bullet points. Respond in {_lang_label(language)}.\n\n{chunk}"},
        ],
    )
    return resp.choices[0].message.content.strip()


def reduce_summaries(summaries: List[str], language: str = "fr") -> str:
    joined = "\n".join(summaries)
    resp = _retry(
        client.chat.completions.create,
        model=SUMMARY_MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": f"You merge overlapping bullets into a coherent high-level outline. Always respond in {_lang_label(language)}."},
            {"role": "user", "content": f"Merge and deduplicate these bullet summaries into a crisp outline with sections and sub-bullets. Respond in {_lang_label(language)}.\n\n{joined}"},
        ],
    )
    return resp.choices[0].message.content.strip()


def generate_course_from_outline(outline_md: str, title_hint: Optional[str] = None, language: str = "fr") -> str:
    title_line = f"# {title_hint}" if title_hint else ""
    resp = _retry(
        client.chat.completions.create,
        model=COURSE_MODEL,
        temperature=0.4,
        messages=[
            {"role": "system", "content": f"You are a university-level course writer. Output Markdown only. Always respond in {_lang_label(language)}."},
            {"role": "user", "content": f"""
Write a complete, well-structured Markdown course using this outline. Requirements:
1) Start with a single H1 title.
2) Use bolded section headings (**Title**) followed by clear explanations.
3) Include short examples, formulas, or mini-cases when relevant.
4) Keep it rigorous but readable for first-year CS students.

{title_line}

Outline:

{outline_md}
"""},
        ],
    )
    return resp.choices[0].message.content.strip()


def generate_qcm(course_md: str, num_questions: int = 20, language: str = "fr") -> str:
    resp = _retry(
        client.chat.completions.create,
        model=QCM_MODEL,
        temperature=0.3,
        messages=[
            {"role": "system", "content": f"You are a rigorous examiner. Output Markdown only. Always respond in {_lang_label(language)}."},
            {"role": "user", "content": f"""

Generate a multiple-choice quiz with {num_questions} questions.
STRICT FORMAT — exactly 6 lines per question, no extra text, no code fences:

1. **Question:** <text>
- A) <text>
- B) <text>
- C) <text>
- D) <text>
- Answer: <A/B/C/D>

Rules:
- Use exactly "1. **Question:**", "2. **Question:**", etc. (number + dot + space)
- Choices must start with "- A) ", "- B) ", "- C) ", "- D) "
- The answer line must be "- Answer: X" (no bold, no explanation)
- No blank lines between the 6 lines of a question
- One blank line between questions
- even in other languages you use "Answer" in English for the answer line and Question in English for the question line.
- Base ONLY on this course:

{course_md}
"""},
        ],
    )
    return resp.choices[0].message.content.strip()


def generate_exercises(course_md: str, count: int = 3, language: str = "fr") -> str:
    resp = _retry(
        client.chat.completions.create,
        model=EXO_MODEL,
        temperature=0.4,
        messages=[
            {"role": "system", "content": f"You are a university professor. Output Markdown only. Always respond in {_lang_label(language)}."},
            {"role": "user", "content": f"""
Write {count} open-ended, challenging exercises that require analysis, application, or synthesis (no rote recall). Give clear statements and expected directions, but no full solutions.
Format:
- **Exercise 1:** ...
- **Exercise 2:** ...
- **Exercise 3:** ...

Base it ONLY on this course:

{course_md}
"""},
        ],
    )
    return resp.choices[0].message.content.strip()


# =====================
# 5) Pipelines
# =====================

def pipeline_from_audio(audio_path: str,
                        title_hint: Optional[str] = None,
                        language: str = "fr") -> PipelineOutputs:
    # Normalize once at the entry point
    audio_path = to_wsl_path(audio_path)                  # <<< NEW
    audio_path = str(Path(audio_path))
    if not Path(audio_path).exists():
        raise FileNotFoundError(audio_path)

    print("🔍 Vérification taille fichier…")
    parts: List[str] = []
    try:
        parts = split_audio_by_size(audio_path, MAX_AUDIO_MB)

        transcript_all = []
        for i, p in enumerate(parts):
            print(f"🎧 Transcription {i+1}/{len(parts)} : {p}")
            tr = transcribe_audio(p)
            transcript_all.append(tr)
        transcript = "\n".join(transcript_all).strip()

        print("✂️ Chunking…")
        chunks = chunk_text(transcript)

        print("🧠 Résumés (map)…")
        summaries = [summarize_chunk(c, language=language) for c in chunks]
        print("🧠 Fusion (reduce)…")
        outline = reduce_summaries(summaries, language=language)

        print("📚 Génération du cours…")
        course = generate_course_from_outline(outline, title_hint, language=language)
        print("🧪 Génération du QCM…")
        qcm = generate_qcm(course, language=language)
        print("🧠 Génération des exercices…")
        exos = generate_exercises(course, language=language)

        return PipelineOutputs(
            transcript=transcript,
            chunks_preview=chunks[:3],
            summaries_preview=summaries[:3],
            course=course,
            qcm=qcm,
            exercises=exos,
        )
    finally:
        # 🧹 Cleanup des morceaux + (optionnel) du fichier original
        try:
            cleanup_audio_files(audio_path, parts)
        except Exception:
            pass


def pipeline_from_text(raw_text: str,
                       title_hint: Optional[str] = None,
                       language: str = "fr") -> PipelineOutputs:
    """NEW: Direct text mode, skipping audio/transcription."""
    transcript = raw_text.strip()
    print("✂️ Chunking (text)…")
    chunks = chunk_text(transcript)

    print("🧠 Résumés (map)…")
    summaries = [summarize_chunk(c, language=language) for c in chunks]
    print("🧠 Fusion (reduce)…")
    outline = reduce_summaries(summaries, language=language)

    print("📚 Génération du cours…")
    course = generate_course_from_outline(outline, title_hint, language=language)
    print("🧪 Génération du QCM…")
    qcm = generate_qcm(course, language=language)
    print("🧠 Génération des exercices…")
    exos = generate_exercises(course, language=language)

    return PipelineOutputs(
        transcript=transcript,
        chunks_preview=chunks[:3],
        summaries_preview=summaries[:3],
        course=course,
        qcm=qcm,
        exercises=exos,
    )


# =====================
# 6) I/O helpers
# =====================

def save_outputs(base: str, out: PipelineOutputs) -> Dict[str, str]:
    os.makedirs(os.path.dirname(base) or ".", exist_ok=True)
    paths = {}

    paths["transcript"] = f"{base}_transcript.txt"
    with open(paths["transcript"], "w", encoding="utf-8") as f:
        f.write(out.transcript)

    paths["course"] = f"{base}_course.md"
    with open(paths["course"], "w", encoding="utf-8") as f:
        f.write(out.course)

    paths["qcm"] = f"{base}_qcm.md"
    with open(paths["qcm"], "w", encoding="utf-8") as f:
        f.write(out.qcm)

    paths["exercises"] = f"{base}_exercises.md"
    with open(paths["exercises"], "w", encoding="utf-8") as f:
        f.write(out.exercises)

    meta = {
        "chunks_preview": out.chunks_preview,
        "summaries_preview": out.summaries_preview,
        "models": {
            "course": COURSE_MODEL,
            "summary": SUMMARY_MODEL,
            "qcm": QCM_MODEL,
            "exercises": EXO_MODEL,
            "transcribe": TRANSCRIBE_MODEL,
        },
    }
    paths["meta"] = f"{base}_meta.json"
    with open(paths["meta"], "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return paths


# =====================
# 7) CLI
# =====================

def main():
    ap = argparse.ArgumentParser(description="OMYA pipeline: audio or text → course/QCM/exercises")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audio", type=str, help="Path to audio file (mp3/wav/…) to transcribe")
    mode.add_argument("--text", type=str, help="Raw text string (surround with quotes)")
    mode.add_argument("--text-file", type=str, help="Path to a UTF-8 text file to ingest")

    ap.add_argument("--title", type=str, default=None, help="Optional course title hint")
    ap.add_argument("--out-base", type=str, default="omya_output/out", help="Base path for saving outputs (no extension)")

    args = ap.parse_args()

    if args.audio:
        outputs = pipeline_from_audio(args.audio, args.title)
    else:
        if args.text_file:
            with open(args.text_file, "r", encoding="utf-8") as f:
                raw = f.read()
        else:
            raw = args.text or ""
        if not raw.strip():
            print("❌ Empty text input", file=sys.stderr)
            sys.exit(1)
        outputs = pipeline_from_text(raw, args.title)

    paths = save_outputs(args.out_base, outputs)

    # Console previews
    print("\n✅ Cours (aperçu) :\n")
    print(outputs.course[:1200] + ("…" if len(outputs.course) > 1200 else ""))
    print("\n✅ QCM (aperçu) :\n")
    print(outputs.qcm.splitlines()[0:20])
    print("\n✅ Exercices (aperçu) :\n")
    print(outputs.exercises)

    print("\n📂 Fichiers enregistrés:")
    for k, p in paths.items():
        print(f"- {k}: {p}")


if __name__ == "__main__":
    main()
