#!/usr/bin/env python3
"""CLI for Tongji Look (look.tongji.edu.cn): setup, list, transcribe.

This script is designed to be used by a Codex skill:
- Credentials are stored in the skill root `.env` (ignored by `.gitignore`).
- Auth cache is stored in `<skill>/state/`.
- Artifacts are written to `./tongji-output/` under the current working directory.
"""

from __future__ import annotations

import argparse
import array
import builtins
import concurrent.futures
import functools
import getpass
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from tongji_backend.auth import TongjiAuth
from tongji_backend.client import TongjiClient
from tongji_backend.transcriber import NoAudioStreamError, Transcriber, TranscriptionError, _ffmpeg_bin


print = functools.partial(builtins.print, flush=True)


def _hidden_subprocess_kwargs(*, new_process_group: bool = False) -> dict[str, Any]:
    if os.name != "nt":
        return {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if new_process_group:
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    kwargs: dict[str, Any] = {"startupinfo": startupinfo}
    if creationflags:
        kwargs["creationflags"] = creationflags
    return kwargs


DEFAULT_TRANSLATION_MODEL = "gpt-4.1-mini"
LANGUAGE_NAMES = {
    "ru": "Russian",
    "russian": "Russian",
    "en": "English",
    "english": "English",
    "ja": "Japanese",
    "japanese": "Japanese",
    "ko": "Korean",
    "korean": "Korean",
    "fr": "French",
    "french": "French",
    "de": "German",
    "german": "German",
    "es": "Spanish",
    "spanish": "Spanish",
}


@dataclass
class SrtCue:
    index: int
    start: str
    end: str
    text: str


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _env_path() -> Path:
    return _skill_root() / ".env"


def _state_dir() -> Path:
    return _skill_root() / "state"


def _auth_session_file() -> Path:
    return _state_dir() / "auth_session.json"


def _last_course_file() -> Path:
    return _state_dir() / "last_course.json"


def _output_dir(output_dir: str | None) -> Path:
    return (Path(output_dir).expanduser().resolve() if output_dir else (Path.cwd() / "tongji-output"))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _print_err(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def _format_hms(total_seconds: int) -> str:
    sec = max(0, int(total_seconds))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}-{m:02d}-{s:02d}"


def _safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._-") or "item"


def _safe_output_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "item"
    text = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", text)
    text = re.sub(r"\s+", " ", text)
    text = text.rstrip(" .")
    return text or "item"


def _today_output_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _normalize_output_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return _today_output_date()
    match = re.search(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", text)
    if match:
        year, month, day = [int(part) for part in match.groups()]
        return f"{year:04d}-{month:02d}-{day:02d}"
    return _today_output_date()


def _direct_output_base_name(output_dir: str | None) -> str:
    out_dir = _output_dir(output_dir)
    today = _today_output_date()
    numbers = list(range(1, 1001))
    random.shuffle(numbers)
    suffixes = (".mp4", ".srt", ".zh.srt", ".txt", ".json", ".video.json")
    for number in numbers:
        base = f"{today}-{number}"
        if not any((out_dir / f"{base}{suffix}").exists() for suffix in suffixes):
            return base
    return f"{today}-{random.randint(1, 1000)}"


def _replay_output_base_name(
    *,
    client: TongjiClient,
    course_id: str,
    sub_id: str,
    title_hint: str = "",
    date_hint: str = "",
) -> str:
    title = str(title_hint or "").strip()
    lecture_date = str(date_hint or "").strip()
    try:
        detail = client.get_course_detail(course_id)
    except Exception:
        detail = {}
    if not title:
        title = str(detail.get("title") or "").strip()
    lectures = detail.get("lectures") or []
    if isinstance(lectures, list):
        for lecture in lectures:
            if str(lecture.get("sub_id") or "").strip() != str(sub_id or "").strip():
                continue
            if not lecture_date:
                lecture_date = str(lecture.get("date") or "").strip()
            if not title:
                title = str(lecture.get("title") or lecture.get("sub_title") or "").strip()
            break
    title_part = _safe_output_name(title or course_id or "course")
    date_part = _normalize_output_date(lecture_date)
    return _safe_output_name(f"{date_part}-{title_part}")


def _guess_ext_from_url(url: str) -> str:
    path = urlparse(url).path or ""
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return suffix
    return ".jpg"


def _direct_media_url_from_lecture_url(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return ""
    suffix = Path(parsed.path or "").suffix.lower()
    if suffix in {".mp4", ".m3u8", ".mp3", ".m4a", ".wav", ".aac", ".webm", ".mov", ".mkv"}:
        return text
    return ""


def _direct_media_base_name(url: str) -> str:
    parsed = urlparse(url)
    stem = _safe_filename_part(Path(parsed.path or "").stem)
    if stem:
        return stem
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return f"look_media_{digest}"


def _language_name(value: str) -> str:
    lang = (value or "").strip()
    if not lang:
        return "Russian"
    return LANGUAGE_NAMES.get(lang.lower(), lang)


def _language_suffix(value: str) -> str:
    lang = (value or "").strip().lower()
    reverse = {
        "russian": "ru",
        "english": "en",
        "japanese": "ja",
        "korean": "ko",
        "french": "fr",
        "german": "de",
        "spanish": "es",
    }
    return reverse.get(lang, re.sub(r"[^a-z0-9]+", "-", lang).strip("-") or "ru")


def _normalize_date_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Date is required")
    parts = re.split(r"[-./]", text)
    if len(parts) != 3:
        raise ValueError(f"Invalid date: {value}")
    try:
        year, month, day = [int(part) for part in parts]
    except Exception as exc:
        raise ValueError(f"Invalid date: {value}") from exc
    return f"{year:04d}-{month:02d}-{day:02d}"


def _parse_weekday_filter(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    aliases = {
        "1": 1,
        "mon": 1,
        "monday": 1,
        "2": 2,
        "tue": 2,
        "tues": 2,
        "tuesday": 2,
        "3": 3,
        "wed": 3,
        "weds": 3,
        "wednesday": 3,
        "4": 4,
        "thu": 4,
        "thur": 4,
        "thurs": 4,
        "thursday": 4,
        "5": 5,
        "fri": 5,
        "friday": 5,
        "6": 6,
        "sat": 6,
        "saturday": 6,
        "7": 7,
        "sun": 7,
        "sunday": 7,
    }
    lowered = text.lower()
    if lowered in aliases:
        return aliases[lowered]
    raise ValueError("Invalid weekday. Use 1-7 or mon/tue/wed/... (1=Monday, 3=Wednesday).")


def _iter_date_strings(start_date: str, end_date: str, weekday: int | None = None) -> list[str]:
    start = datetime.strptime(_normalize_date_text(start_date), "%Y-%m-%d").date()
    end = datetime.strptime(_normalize_date_text(end_date), "%Y-%m-%d").date()
    if start > end:
        raise ValueError("start-date cannot be later than end-date")

    dates: list[str] = []
    current = start
    while current <= end:
        if weekday is None or current.isoweekday() == weekday:
            dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def _contains_keyword(text: str, keyword: str) -> bool:
    needle = (keyword or "").strip().lower()
    if not needle:
        return True
    return needle in (text or "").strip().lower()


def _replay_item_matches(
    item: dict[str, Any],
    *,
    teacher_keyword: str,
    title_keyword: str,
    replay_only: bool,
) -> bool:
    teacher_text = " ".join(
        part for part in [
            str(item.get("teacher") or "").strip(),
            str(item.get("lecturer_name") or "").strip(),
            str(item.get("teacher_search") or "").strip(),
        ]
        if part
    )
    title_text = " ".join(
        part for part in [
            str(item.get("title") or "").strip(),
            str(item.get("sub_title") or "").strip(),
        ]
        if part
    )
    if replay_only and not bool(item.get("has_playback")):
        return False
    if not _contains_keyword(teacher_text, teacher_keyword):
        return False
    if not _contains_keyword(title_text, title_keyword):
        return False
    return True


def _search_slug(
    *,
    teacher_keyword: str,
    title_keyword: str,
    start_date: str,
    end_date: str,
    weekday: int | None,
) -> str:
    parts = [
        teacher_keyword.strip() or "all-teachers",
        title_keyword.strip() or "all-courses",
        start_date,
        end_date,
    ]
    if weekday is not None:
        parts.append(f"weekday-{weekday}")
    return _safe_filename_part("_".join(parts))


def _load_replay_items_json(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("items") or raw.get("results") or raw.get("list") or []
    else:
        raise ValueError("Replay JSON must be a list or an object with items/results/list")
    if not isinstance(items, list):
        raise ValueError("Replay JSON does not contain a valid item list")
    return [item for item in items if isinstance(item, dict)]


def _search_replay_range(
    client: TongjiClient,
    *,
    teacher_keyword: str,
    title_keyword: str,
    start_date: str,
    end_date: str,
    weekday: int | None,
    quantum_id: int,
    replay_only: bool,
    max_results: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    dates = _iter_date_strings(start_date, end_date, weekday=weekday)
    hits: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for index, date_text in enumerate(dates, start=1):
        print(f"[SearchReplay] Progress: {index}/{len(dates)}")
        print(f"[SearchReplay] Scanning {date_text}")
        try:
            day_items = client.search_live_courses(date_text, quantum_id=quantum_id, dedupe=True)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            failures.append({"date": date_text, "error": error})
            print(f"[SearchReplay] WARN {date_text}: {error}")
            continue

        for item in day_items:
            if not _replay_item_matches(
                item,
                teacher_keyword=teacher_keyword,
                title_keyword=title_keyword,
                replay_only=replay_only,
            ):
                continue
            key = (
                str(item.get("course_id") or "").strip(),
                str(item.get("sub_id") or "").strip(),
            )
            if key in seen:
                continue
            seen.add(key)
            hits.append(item)
            if max_results and len(hits) >= max_results:
                return hits, failures

    hits.sort(
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("bucket_id") or ""),
            str(item.get("course_begin") or ""),
            str(item.get("title") or ""),
        )
    )
    return hits, failures


def _search_owned_replay_range(
    client: TongjiClient,
    *,
    teacher_keyword: str,
    title_keyword: str,
    start_date: str,
    end_date: str,
    weekday: int | None,
    replay_only: bool,
    max_results: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    target_dates = set(_iter_date_strings(start_date, end_date, weekday=weekday))
    hits: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    try:
        courses = client.get_all_courses()
    except Exception as e:
        raise RuntimeError(f"get_all_courses failed: {type(e).__name__}: {e}") from e

    candidate_courses = list(courses)
    print(f"[SearchReplay] Owned courses: {len(candidate_courses)}")

    for index, course in enumerate(candidate_courses, start=1):
        course_id = str(course.get("course_id") or "").strip()
        if not course_id:
            continue
        print(f"[SearchReplay] Progress: {index}/{len(candidate_courses)}")
        print(f"[SearchReplay] Checking course {course_id}")
        try:
            detail = client.get_course_detail(course_id)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            failures.append({"course_id": course_id, "error": error})
            print(f"[SearchReplay] WARN course_id={course_id}: {error}")
            continue

        course_title = str(detail.get("title") or course.get("title") or "").strip()
        course_teacher = str(detail.get("teacher") or course.get("teacher") or "").strip()
        lectures = detail.get("lectures") or []
        if not isinstance(lectures, list):
            continue

        for lecture in lectures:
            if not isinstance(lecture, dict):
                continue
            sub_id = str(lecture.get("sub_id") or "").strip()
            if not sub_id:
                continue
            try:
                lecture_date = _normalize_date_text(str(lecture.get("date") or "").strip())
            except Exception:
                continue
            if lecture_date not in target_dates:
                continue

            has_playback = bool(lecture.get("has_playback"))
            if replay_only and not has_playback:
                continue

            item = {
                "date": lecture_date,
                "search_date": lecture_date,
                "title": course_title,
                "course_name": course_title,
                "sub_title": str(lecture.get("sub_title") or "").strip(),
                "teacher": course_teacher,
                "lecturer_name": str(lecture.get("lecturer_name") or course_teacher).strip(),
                "course_id": course_id,
                "sub_id": sub_id,
                "status_label": "回放" if has_playback else "",
                "has_playback": has_playback,
                "bucket_id": "",
                "bucket_name": "owned-course",
            }
            if not _replay_item_matches(
                item,
                teacher_keyword=teacher_keyword,
                title_keyword=title_keyword,
                replay_only=replay_only,
            ):
                continue

            key = (course_id, sub_id)
            if key in seen:
                continue
            seen.add(key)
            hits.append(item)
            if max_results and len(hits) >= max_results:
                return hits, failures

    hits.sort(
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("course_id") or ""),
            str(item.get("sub_id") or ""),
            str(item.get("title") or ""),
        )
    )
    return hits, failures


def _pil_resample_lanczos():
    from PIL import Image

    resampling = getattr(Image, "Resampling", None)
    if resampling is not None:
        return resampling.LANCZOS
    return Image.LANCZOS


def _center_crop_image(img, fraction: float = 0.65):
    width, height = img.size
    crop_w = max(1, int(width * fraction))
    crop_h = max(1, int(height * fraction))
    left = max(0, (width - crop_w) // 2)
    top = max(0, (height - crop_h) // 2)
    return img.crop((left, top, left + crop_w, top + crop_h))


def _slide_perceptual_hash(path: Path, size: int = 16, low_freq_size: int = 8) -> list[int]:
    from PIL import Image, ImageOps

    if low_freq_size > size:
        raise ValueError("low_freq_size must be <= size")

    with Image.open(path) as img:
        crop = _center_crop_image(img).convert("L")
        crop = ImageOps.fit(crop, (size, size), method=_pil_resample_lanczos())
        pixels = list(crop.getdata())

    rows = [pixels[idx * size:(idx + 1) * size] for idx in range(size)]
    coeffs: list[float] = []
    for u in range(low_freq_size):
        cu = 1 / math.sqrt(2) if u == 0 else 1.0
        for v in range(low_freq_size):
            cv = 1 / math.sqrt(2) if v == 0 else 1.0
            total = 0.0
            for i in range(size):
                for j in range(size):
                    total += rows[i][j] * math.cos((2 * i + 1) * u * math.pi / (2 * size)) * math.cos(
                        (2 * j + 1) * v * math.pi / (2 * size)
                    )
            coeffs.append(0.25 * cu * cv * total)

    median_source = sorted(coeffs[1:]) or [0.0]
    median = median_source[len(median_source) // 2]
    return [1 if value > median else 0 for value in coeffs]


def _slide_clarity_score(path: Path) -> tuple[float, tuple[int, int], int]:
    from PIL import Image, ImageFilter, ImageStat

    with Image.open(path) as img:
        crop = _center_crop_image(img).convert("L")
        width, height = crop.size
        edge_img = crop.filter(ImageFilter.FIND_EDGES)
        variance = float(ImageStat.Stat(edge_img).var[0])
    pixels = width * height
    return variance * pixels, (width, height), pixels


def _hash_hamming_distance(left: list[int], right: list[int]) -> int:
    return sum(1 for l_bit, r_bit in zip(left, right) if l_bit != r_bit)


def _load_slide_items_from_dir(slide_dir: Path) -> list[dict[str, Any]]:
    index_path = slide_dir / "index.json"
    if index_path.is_file():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8-sig"))
            items = data.get("items", [])
            if isinstance(items, list):
                loaded: list[dict[str, Any]] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    copied = dict(item)
                    filename = str(copied.get("filename") or "").strip()
                    if filename and not copied.get("filepath"):
                        copied["filepath"] = str((slide_dir / filename).resolve())
                    loaded.append(copied)
                if loaded:
                    return loaded
        except Exception:
            pass

    items = []
    for path in sorted(slide_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            continue
        stamp_match = re.search(r"_s(\d{1,})", path.stem)
        created_sec = int(stamp_match.group(1)) if stamp_match else 0
        items.append({
            "filename": path.name,
            "filepath": str(path.resolve()),
            "created_sec": created_sec,
            "bytes": path.stat().st_size,
        })
    items.sort(key=lambda item: (int(item.get("created_sec") or 0), str(item.get("filename") or "")))
    return items


def _dedupe_slide_items(
    *,
    slide_dir: Path,
    items: list[dict[str, Any]],
    threshold: int,
    tag: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        from PIL import Image  # noqa: F401
    except Exception as e:
        info = {
            "enabled": False,
            "status": "skipped",
            "reason": f"Pillow unavailable: {e}",
        }
        print(f"[{tag}] Skipped dedupe: {info['reason']}")
        return items, info

    threshold = max(0, int(threshold))
    prepared: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda entry: (int(entry.get("created_sec") or 0), str(entry.get("filename") or ""))):
        filename = str(item.get("filename") or "").strip()
        path_value = str(item.get("filepath") or "").strip()
        path = Path(path_value).resolve() if path_value else (slide_dir / filename).resolve()
        if not path.is_file():
            continue
        try:
            slide_hash = _slide_perceptual_hash(path)
            clarity_score, (crop_w, crop_h), crop_pixels = _slide_clarity_score(path)
        except Exception as e:
            print(f"[{tag}] Skip invalid image {path.name}: {e}")
            continue

        copied = dict(item)
        copied["filename"] = path.name
        copied["filepath"] = str(path)
        copied["bytes"] = int(copied.get("bytes") or path.stat().st_size)
        copied["_slide_hash"] = slide_hash
        copied["_clarity_score"] = clarity_score
        copied["_crop_size"] = [crop_w, crop_h]
        copied["_crop_pixels"] = crop_pixels
        prepared.append(copied)

    if not prepared:
        info = {
            "enabled": True,
            "status": "empty",
            "threshold": threshold,
            "kept": 0,
            "removed": 0,
            "groups": 0,
        }
        return [], info

    groups: list[list[dict[str, Any]]] = []
    current_group: list[dict[str, Any]] = []
    group_hashes: list[list[int]] = []
    for item in prepared:
        if not current_group:
            current_group = [item]
            group_hashes = [item["_slide_hash"]]
            continue
        distance = min(_hash_hamming_distance(item["_slide_hash"], existing_hash) for existing_hash in group_hashes)
        if distance <= threshold:
            current_group.append(item)
            group_hashes.append(item["_slide_hash"])
        else:
            groups.append(current_group)
            current_group = [item]
            group_hashes = [item["_slide_hash"]]
    if current_group:
        groups.append(current_group)

    duplicate_dir = slide_dir / "_duplicates"
    duplicate_dir.mkdir(parents=True, exist_ok=True)

    kept_items: list[dict[str, Any]] = []
    group_records: list[dict[str, Any]] = []
    removed_count = 0

    for group_index, group in enumerate(groups, 1):
        best = max(
            group,
            key=lambda entry: (
                float(entry.get("_clarity_score") or 0.0),
                int(entry.get("_crop_pixels") or 0),
                int(entry.get("bytes") or 0),
                -int(entry.get("created_sec") or 0),
            ),
        )
        kept_copy = {k: v for k, v in best.items() if not str(k).startswith("_")}
        kept_copy["dedupe_group"] = group_index
        kept_copy["dedupe_group_size"] = len(group)
        kept_copy["clarity_score"] = round(float(best.get("_clarity_score") or 0.0), 2)
        kept_items.append(kept_copy)

        removed_entries: list[dict[str, Any]] = []
        for entry in group:
            if entry is best:
                continue
            source = Path(str(entry.get("filepath") or "")).resolve()
            target = duplicate_dir / source.name
            if target.exists():
                target = duplicate_dir / f"{target.stem}_dup{group_index}{target.suffix}"
            if source.is_file():
                shutil.move(str(source), str(target))
            removed_count += 1
            removed_entries.append({
                "filename": source.name,
                "moved_to": str(target),
                "created_sec": int(entry.get("created_sec") or 0),
                "clarity_score": round(float(entry.get("_clarity_score") or 0.0), 2),
            })

        group_records.append({
            "group": group_index,
            "kept": kept_copy["filename"],
            "kept_created_sec": int(best.get("created_sec") or 0),
            "group_size": len(group),
            "removed": removed_entries,
        })

    dedupe_report = {
        "enabled": True,
        "status": "done",
        "threshold": threshold,
        "groups": len(groups),
        "kept": len(kept_items),
        "removed": removed_count,
        "duplicates_dir": str(duplicate_dir.resolve()),
        "groups_detail": group_records,
    }

    dedupe_path = slide_dir / "dedupe.json"
    dedupe_path.write_text(json.dumps(dedupe_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[{tag}] Dedupe kept {len(kept_items)} unique slides and moved {removed_count} duplicates to {duplicate_dir}")
    return kept_items, dedupe_report


def _parse_srt(content: str) -> list[SrtCue]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    cues: list[SrtCue] = []
    for block in re.split(r"\n\s*\n", normalized):
        lines = [line.rstrip() for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue

        index = len(cues) + 1
        if re.fullmatch(r"\d+", lines[0].strip()):
            index = int(lines[0].strip())
            lines = lines[1:]

        if not lines:
            continue
        match = re.match(r"(.+?)\s*-->\s*(.+)", lines[0])
        if not match:
            continue

        text = "\n".join(lines[1:]).strip()
        if not text:
            continue
        cues.append(
            SrtCue(
                index=index,
                start=match.group(1).strip(),
                end=match.group(2).strip(),
                text=text,
            )
        )
    return cues


def _write_srt(cues: list[SrtCue], texts: list[str], out_path: Path) -> None:
    parts: list[str] = []
    for idx, (cue, text) in enumerate(zip(cues, texts), 1):
        cleaned = (text or "").strip()
        parts.append(f"{idx}\n{cue.start} --> {cue.end}\n{cleaned}\n")
    out_path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")


def _write_cues_srt(cues: list[SrtCue], out_path: Path) -> None:
    _write_srt(cues, [cue.text for cue in cues], out_path)


def _normalize_proofread_mode(value: str) -> str:
    mode = str(value or "off").strip().lower()
    if mode in {"local", "fast"}:
        return "local"
    if mode in {"ai", "openai"}:
        return "ai"
    return "off"


def _normalize_subtitle_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"([，。！？；：,.!?;:])\1+", r"\1", value)
    value = value.replace(" ,", ",").replace(" 。", "。").replace(" ，", "，")
    return value.strip()


def _local_proofread_text(text: str, prev_text: str = "", next_text: str = "") -> str:
    value = _normalize_subtitle_text(text)
    if not value:
        return value
    replacements = {
        "这个个": "这个",
        "那个个": "那个",
        "然后然后": "然后",
        "我们我们": "我们",
        "就是就是": "就是",
        "的话的话": "的话",
        "的的": "的",
        "了了": "了",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    if prev_text and value == prev_text.strip():
        value = re.sub(r"^(然后|那么|所以)\s*", "", value)
    if next_text and value == next_text.strip():
        value = re.sub(r"\s*(吧|啊|呢)$", "", value)
    return _normalize_subtitle_text(value)


def _finalize_proofread_model(value: str) -> str:
    text = str(value or os.environ.get("OPENAI_PROOFREAD_MODEL", "") or os.environ.get("OPENAI_TRANSLATION_MODEL", DEFAULT_TRANSLATION_MODEL)).strip()
    return text or DEFAULT_TRANSLATION_MODEL


def _proofread_batch_openai(
    *,
    texts: list[str],
    prev_texts: list[str],
    next_texts: list[str],
    model: str,
    timeout: int,
) -> list[str]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set for AI proofread mode.")

    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    api_style = os.environ.get("OPENAI_API_STYLE", "chat").strip().lower()
    payload_items = [
        {"i": i, "text": texts[i], "prev": prev_texts[i], "next": next_texts[i]}
        for i in range(len(texts))
    ]
    prompt = (
        "You are fixing ASR subtitle mistakes for a university lecture.\n"
        "Correct obvious homophone errors, broken phrasing, repeated filler, and punctuation.\n"
        "Keep meaning conservative. Do not invent new facts. Do not change numbering.\n"
        "Return ONLY a JSON array with the same length and order, formatted as "
        '[{"i":0,"text":"..."}, ...].\n\n'
        f"Subtitle items:\n{json.dumps(payload_items, ensure_ascii=False)}"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    system_prompt = (
        "You are a careful Chinese subtitle proofreader. "
        "Only output valid JSON. Keep each subtitle concise and natural."
    )

    last_error = ""
    text = ""
    if api_style in {"chat", "auto"}:
        resp = requests.post(
            _api_url(base_url, "/chat/completions"),
            headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
            },
            timeout=timeout,
        )
        if resp.status_code < 400:
            text = _chat_completion_text(resp.json())
        else:
            last_error = f"chat/completions {resp.status_code}: {resp.text[:300]}"

    if not text and api_style in {"responses", "auto"}:
        resp = requests.post(
            _api_url(base_url, "/responses"),
            headers=headers,
            json={
                "model": model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=timeout,
        )
        if resp.status_code < 400:
            text = _response_text(resp.json())
        else:
            last_error = f"responses {resp.status_code}: {resp.text[:300]}"

    if not text:
        raise RuntimeError(f"OpenAI proofread error: {last_error or 'empty response'}")

    values = _extract_json_array(text)
    corrected = [""] * len(texts)
    for item in values:
        if not isinstance(item, dict):
            continue
        idx = int(item.get("i", -1))
        if 0 <= idx < len(texts):
            corrected[idx] = _normalize_subtitle_text(str(item.get("text", "")).strip())

    if any(not item for item in corrected):
        raise RuntimeError("AI proofread response missed one or more subtitle items.")
    return corrected


def _proofread_cues(
    cues: list[SrtCue],
    *,
    mode: str,
    model: str,
    timeout: int,
) -> tuple[list[SrtCue], str]:
    normalized_mode = _normalize_proofread_mode(mode)
    if normalized_mode == "off" or not cues:
        return cues, "off"

    updated = [SrtCue(index=cue.index, start=cue.start, end=cue.end, text=cue.text) for cue in cues]
    if normalized_mode == "local":
        for idx, cue in enumerate(updated):
            prev_text = updated[idx - 1].text if idx > 0 else ""
            next_text = updated[idx + 1].text if idx + 1 < len(updated) else ""
            cue.text = _local_proofread_text(cue.text, prev_text=prev_text, next_text=next_text)
        return updated, "local"

    batch_size = 8
    for start in range(0, len(updated), batch_size):
        batch = updated[start : start + batch_size]
        texts = [item.text for item in batch]
        prev_texts = [updated[start + idx - 1].text if start + idx > 0 else "" for idx in range(len(batch))]
        next_texts = [updated[start + idx + 1].text if start + idx + 1 < len(updated) else "" for idx in range(len(batch))]
        corrected = _proofread_batch_openai(
            texts=texts,
            prev_texts=prev_texts,
            next_texts=next_texts,
            model=model,
            timeout=timeout,
        )
        for idx, text in enumerate(corrected):
            batch[idx].text = text
    return updated, "ai"


def _apply_subtitle_proofread(
    *,
    srt_path: Path,
    txt_path: Path | None,
    mode: str,
    model: str,
    timeout: int = 120,
    tag: str = "Proofread",
) -> str:
    normalized_mode = _normalize_proofread_mode(mode)
    if normalized_mode == "off" or not _file_ready(srt_path, min_bytes=20):
        return "off"

    cues = _parse_srt(srt_path.read_text(encoding="utf-8-sig", errors="replace"))
    if not cues:
        return "off"
    final_model = _finalize_proofread_model(model)
    updated_cues, used_mode = _proofread_cues(cues, mode=normalized_mode, model=final_model, timeout=timeout)
    _write_cues_srt(updated_cues, srt_path)
    if txt_path is not None:
        txt_path.write_text("\n".join(cue.text for cue in updated_cues).strip() + "\n", encoding="utf-8")
    print(f"[{tag}] Mode={used_mode} cues={len(updated_cues)} model={final_model}")
    return used_mode


def _file_ready(path: Path, min_bytes: int = 1) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= min_bytes
    except Exception:
        return False


class FreeTranslateRateLimited(RuntimeError):
    pass


def _short_error_text(text: str, limit: int = 140) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit] + ("..." if len(cleaned) > limit else "")


def _iter_exception_chain(exc: BaseException | None):
    seen: set[int] = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _friendly_exception_text(exc: BaseException, limit: int = 180) -> str:
    saw_connection_error = False
    for item in _iter_exception_chain(exc):
        if isinstance(item, requests.exceptions.Timeout):
            return "request timed out"
        if isinstance(item, requests.exceptions.ProxyError):
            return "proxy connection failed"
        if isinstance(item, requests.exceptions.SSLError):
            return "TLS/SSL handshake failed"
        if isinstance(item, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            code = getattr(item, "winerror", None)
            if code is None and item.args:
                try:
                    code = int(item.args[0])
                except Exception:
                    code = None
            if code == 10054:
                return "connection reset by remote host (WinError 10054)"
            if code == 10053:
                return "connection aborted by local network stack (WinError 10053)"
            return type(item).__name__
        if isinstance(item, requests.exceptions.ConnectionError):
            saw_connection_error = True
        elif isinstance(item, OSError):
            code = getattr(item, "winerror", None)
            if code == 10054:
                return "connection reset by remote host (WinError 10054)"
            if code == 10053:
                return "connection aborted by local network stack (WinError 10053)"

    text = _short_error_text(str(exc), limit=limit)
    lower = text.lower()
    if "connectionreseterror(10054" in lower or "winerror 10054" in lower:
        return "connection reset by remote host (WinError 10054)"
    if "connectionabortederror(10053" in lower or "winerror 10053" in lower:
        return "connection aborted by local network stack (WinError 10053)"
    if "connection aborted" in lower:
        return "network connection failed: remote side aborted the request"
    if "timed out" in lower or "timeout" in lower:
        return "request timed out"
    if saw_connection_error:
        return f"network connection failed: {text}" if text else "network connection failed"
    return text or type(exc).__name__


def _time_to_ms(value: str) -> int:
    match = re.match(r"(\d+):(\d+):(\d+)(?:[.,](\d+))?", value.strip())
    if not match:
        return 0
    hours, minutes, seconds = [int(x) for x in match.groups()[:3]]
    frac = (match.group(4) or "0")[:3].ljust(3, "0")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + int(frac)


def _ms_to_srt_time(value: int) -> str:
    value = max(0, int(round(value)))
    hours = value // 3600000
    value %= 3600000
    minutes = value // 60000
    value %= 60000
    seconds = value // 1000
    millis = value % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _duration_from_ffmpeg_line(line: str) -> int:
    match = re.search(r"Duration:\s*(\d+:\d+:\d+(?:[.,]\d+)?)", line)
    return _time_to_ms(match.group(1)) if match else 0


def _probe_media_duration_ms(path: Path, timeout: int = 30) -> int:
    try:
        proc = subprocess.run(
            [_ffmpeg_bin(), "-hide_banner", "-i", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **_hidden_subprocess_kwargs(),
        )
    except Exception:
        return 0
    for line in (proc.stdout or "").splitlines():
        duration = _duration_from_ffmpeg_line(line)
        if duration:
            return duration
    return 0


def _write_subtitle_health_report(*, srt_path: Path, video_path: Path | None = None) -> Path:
    report_path = srt_path.with_suffix(".subtitle-health.txt")
    warnings: list[str] = []
    cues = _parse_srt(srt_path.read_text(encoding="utf-8-sig"))
    if not cues:
        warnings.append("No valid subtitle cues found.")
    previous_end = -1
    for idx, cue in enumerate(cues, 1):
        start = _time_to_ms(cue.start)
        end = _time_to_ms(cue.end)
        if end <= start:
            warnings.append(f"Cue {idx}: end time is not after start time.")
        if previous_end >= 0 and start < previous_end:
            warnings.append(f"Cue {idx}: overlaps with previous cue.")
        previous_end = max(previous_end, end)

    video_duration = _probe_media_duration_ms(video_path) if video_path else 0
    last_end = _time_to_ms(cues[-1].end) if cues else 0
    if video_duration and last_end:
        diff = video_duration - last_end
        if last_end > video_duration + 5000:
            warnings.append("Last subtitle ends after the video duration.")
        elif abs(diff) > 120000:
            warnings.append(
                "Last subtitle time is more than 2 minutes away from video duration. "
                "This can be normal if the final minutes have no speech."
            )

    lines = [
        "Subtitle health report",
        f"SRT: {srt_path}",
        f"Cues: {len(cues)}",
    ]
    if video_path:
        lines.append(f"Video: {video_path}")
    if video_duration:
        lines.append(f"Video duration: {_ms_to_srt_time(video_duration)}")
    if last_end:
        lines.append(f"Last subtitle end: {_ms_to_srt_time(last_end)}")
    lines.append("")
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item}" for item in warnings[:50])
        if len(warnings) > 50:
            lines.append(f"- ... {len(warnings) - 50} more")
    else:
        lines.append("OK: no obvious subtitle timing problems found.")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    print(f"[HealthCheck] Report: {report_path}")
    return report_path


def _extract_mono_pcm_wav(video_path: Path, wav_path: Path, timeout: int = 900) -> None:
    cmd = [
        _ffmpeg_bin(),
        "-hide_banner",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
        str(wav_path),
    ]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **_hidden_subprocess_kwargs(),
    )
    if proc.returncode != 0 or not wav_path.is_file() or wav_path.stat().st_size < 1024:
        raise RuntimeError(f"ffmpeg audio extraction failed: {(proc.stdout or '')[-500:]}")


def _read_wav_energy_frames(wav_path: Path, frame_ms: int = 20) -> tuple[list[float], int, int]:
    with wave.open(str(wav_path), "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        if channels != 1 or width != 2:
            raise RuntimeError("Expected mono 16-bit WAV for subtitle sync")
        samples_per_frame = max(1, int(rate * frame_ms / 1000))
        energies: list[float] = []
        while True:
            raw = wf.readframes(samples_per_frame)
            if not raw:
                break
            count = len(raw) // 2
            if count <= 0:
                continue
            samples = array.array("h")
            samples.frombytes(raw)
            if sys.byteorder != "little":
                samples.byteswap()
            rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768.0
            energies.append(rms)
    return energies, rate, frame_ms


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[pos]


def _speech_mask_from_energy(energies: list[float], *, frame_ms: int) -> list[bool]:
    if not energies:
        return []
    floor = _percentile(energies, 0.20)
    high = _percentile(energies, 0.82)
    threshold = max(0.006, floor * 2.8, high * 0.18)
    raw = [value >= threshold for value in energies]

    # Fill very short gaps and remove isolated clicks.
    gap_frames = max(1, int(180 / frame_ms))
    min_speech_frames = max(1, int(100 / frame_ms))
    mask = raw[:]
    i = 0
    while i < len(mask):
        if mask[i]:
            i += 1
            continue
        start = i
        while i < len(mask) and not mask[i]:
            i += 1
        end = i
        if start > 0 and end < len(mask) and (end - start) <= gap_frames:
            for j in range(start, end):
                mask[j] = True

    i = 0
    while i < len(mask):
        if not mask[i]:
            i += 1
            continue
        start = i
        while i < len(mask) and mask[i]:
            i += 1
        end = i
        if end - start < min_speech_frames:
            for j in range(start, end):
                mask[j] = False
    return mask


def _speech_regions(mask: list[bool], frame_ms: int) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    i = 0
    while i < len(mask):
        if not mask[i]:
            i += 1
            continue
        start = i
        while i < len(mask) and mask[i]:
            i += 1
        end = i
        regions.append((start * frame_ms, end * frame_ms))
    return regions


def _find_nearby_speech_region(
    regions: list[tuple[int, int]],
    start_ms: int,
    end_ms: int,
    *,
    window_before_ms: int,
    window_after_ms: int,
) -> tuple[int, int] | None:
    probe_start = max(0, start_ms - window_before_ms)
    probe_end = end_ms + window_after_ms
    best: tuple[int, int] | None = None
    best_score = -1
    for region_start, region_end in regions:
        if region_end < probe_start:
            continue
        if region_start > probe_end:
            break
        overlap = max(0, min(end_ms, region_end) - max(start_ms, region_start))
        distance = abs(region_start - start_ms)
        score = overlap * 10 - distance
        if score > best_score:
            best_score = score
            best = (region_start, region_end)
    return best


def _estimate_global_subtitle_shift_ms(cues: list[SrtCue], mask: list[bool], frame_ms: int) -> tuple[int, float]:
    if not cues or not mask:
        return 0, 0.0
    limit_frames = len(mask)
    subtitle = [False] * limit_frames
    for cue in cues:
        start = max(0, _time_to_ms(cue.start) // frame_ms)
        end = min(limit_frames, max(start + 1, _time_to_ms(cue.end) // frame_ms))
        for i in range(start, end):
            subtitle[i] = True

    speech_true = sum(mask)
    sub_true = sum(subtitle)
    if speech_true < 20 or sub_true < 20:
        return 0, 0.0

    best_shift = 0
    best_score = -1
    best_union = 1
    max_shift_frames = int(2500 / frame_ms)
    step = max(1, int(100 / frame_ms))
    for shift in range(-max_shift_frames, max_shift_frames + 1, step):
        overlap = 0
        union = 0
        for i, speech in enumerate(mask):
            j = i - shift
            sub = 0 <= j < limit_frames and subtitle[j]
            if speech or sub:
                union += 1
                if speech and sub:
                    overlap += 1
        if overlap > best_score:
            best_score = overlap
            best_union = max(1, union)
            best_shift = shift

    confidence = best_score / best_union
    return best_shift * frame_ms, confidence


def _apply_subtitle_timing_sync(
    *,
    video_path: Path,
    srt_path: Path,
    output_path: Path | None = None,
    max_local_shift_ms: int = 1400,
    lead_ms: int = 80,
    force: bool = False,
) -> tuple[Path, dict[str, Any]]:
    cues = _parse_srt(srt_path.read_text(encoding="utf-8-sig", errors="replace"))
    if not cues:
        raise RuntimeError(f"No subtitle cues found: {srt_path}")
    video_path = video_path.expanduser().resolve()
    if not video_path.is_file():
        raise RuntimeError(f"Video file not found: {video_path}")

    with tempfile.TemporaryDirectory(prefix="tongji_sync_") as tmp:
        wav_path = Path(tmp) / "audio.wav"
        _extract_mono_pcm_wav(video_path, wav_path)
        energies, _rate, frame_ms = _read_wav_energy_frames(wav_path)

    mask = _speech_mask_from_energy(energies, frame_ms=frame_ms)
    regions = _speech_regions(mask, frame_ms)
    if not regions:
        raise RuntimeError("No speech regions detected in audio")

    global_shift_ms, confidence = _estimate_global_subtitle_shift_ms(cues, mask, frame_ms)
    use_global = force or (abs(global_shift_ms) >= 180 and confidence >= 0.10)
    if use_global:
        global_shift_ms = max(-max_local_shift_ms, min(max_local_shift_ms, global_shift_ms))
    else:
        global_shift_ms = 0

    adjusted: list[SrtCue] = []
    changed = 0
    previous_end = 0
    for cue in cues:
        original_start = _time_to_ms(cue.start)
        original_end = _time_to_ms(cue.end)
        duration = max(400, original_end - original_start)
        start = max(0, original_start + global_shift_ms)
        end = max(start + 300, original_end + global_shift_ms)

        region = _find_nearby_speech_region(
            regions,
            start,
            end,
            window_before_ms=500,
            window_after_ms=max_local_shift_ms,
        )
        if region:
            speech_start, speech_end = region
            candidate_start = max(0, speech_start - lead_ms)
            local_delta = candidate_start - start
            if -500 <= local_delta <= max_local_shift_ms:
                start = candidate_start
                end = max(start + 350, min(max(start + duration, speech_end + 120), start + duration + 800))

        start = max(previous_end + 20 if adjusted else 0, start)
        end = max(start + 300, end)
        if abs(start - original_start) >= 80 or abs(end - original_end) >= 120:
            changed += 1
        adjusted.append(
            SrtCue(
                index=len(adjusted) + 1,
                start=_ms_to_srt_time(start),
                end=_ms_to_srt_time(end),
                text=cue.text,
            )
        )
        previous_end = end

    out_path = output_path.expanduser().resolve() if output_path else srt_path
    if output_path is None:
        backup = srt_path.with_suffix(srt_path.suffix + ".before-sync")
        if not backup.exists():
            shutil.copy2(srt_path, backup)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_cues_srt(adjusted, out_path)
    report = {
        "cues": len(cues),
        "changed": changed,
        "speech_regions": len(regions),
        "global_shift_ms": global_shift_ms,
        "global_confidence": round(confidence, 4),
        "output": str(out_path),
    }
    return out_path, report


def _download_video_stream(
    *,
    stream_url: str,
    http_headers: str,
    output_path: Path,
    timeout: int,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_ffmpeg_bin(), "-hide_banner", "-y"]
    if http_headers:
        cmd += ["-headers", http_headers]
    cmd += [
        "-i",
        stream_url,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output_path),
    ]

    print("[VideoDownload] Downloading course video...")
    print(f"[VideoDownload] Output: {output_path}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_hidden_subprocess_kwargs(),
    )
    assert proc.stdout is not None

    duration_ms = 0
    last_percent = -1
    last_line = ""
    started_at = time.time()
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if not line:
            continue
        last_line = line
        duration_ms = duration_ms or _duration_from_ffmpeg_line(line)
        match = re.match(r"out_time_ms=(\d+)", line)
        if match and duration_ms:
            # FFmpeg's progress field is microseconds despite the name.
            out_ms = int(match.group(1)) // 1000
            percent = max(1, min(99, int(out_ms * 100 / duration_ms)))
            if percent >= last_percent + 2:
                last_percent = percent
                print(f"[VideoDownload] Progress: {percent}/100")
        elif line == "progress=end":
            print("[VideoDownload] Progress: 100/100")

    try:
        code = proc.wait(timeout=timeout if timeout and timeout > 0 else None)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"Video download timed out after {timeout}s")

    elapsed = time.time() - started_at
    if code != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {code}: {last_line}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("ffmpeg finished but output video is empty")

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"[VideoDownload] Done: {size_mb:.1f}MB in {elapsed:.0f}s")
    print(f"  - {output_path}")
    return output_path


def _extract_json_array(raw: str) -> list[Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end < start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, list):
        raise ValueError("translation response is not a JSON array")
    return value


def _response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]

    texts: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                texts.append(text)
    return "\n".join(texts).strip()


def _chat_completion_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    first = choices[0] or {}
    message = first.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


def _api_url(base_url: str, endpoint: str) -> str:
    base = (base_url or "https://api.openai.com/v1").strip().rstrip("/")
    if base.endswith(endpoint):
        return base
    if base.endswith("/v1"):
        return f"{base}{endpoint}"
    return f"{base}/v1{endpoint}"


def _translate_batch_openai(
    *,
    texts: list[str],
    target_language: str,
    model: str,
    timeout: int,
) -> list[str]:
    import requests

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to your environment or to the skill .env file."
        )

    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    api_style = os.environ.get("OPENAI_API_STYLE", "chat").strip().lower()
    payload_items = [{"i": i, "text": text} for i, text in enumerate(texts)]
    prompt = (
        "Translate each subtitle item to the target language.\n"
        "Preserve meaning, technical terms, numbers, names, formulas, and line breaks when useful.\n"
        "Keep each item concise enough for video subtitles.\n"
        "Return ONLY a JSON array with the same length and order, formatted as "
        '[{"i":0,"text":"..."}, ...].\n\n'
        f"Target language: {target_language}\n"
        f"Subtitle items:\n{json.dumps(payload_items, ensure_ascii=False)}"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    system_prompt = (
        "You are a careful subtitle translator. "
        "You only output valid JSON and never add commentary."
    )

    last_error = ""
    text = ""
    if api_style in {"chat", "auto"}:
        resp = requests.post(
            _api_url(base_url, "/chat/completions"),
            headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
            timeout=timeout,
        )
        if resp.status_code < 400:
            text = _chat_completion_text(resp.json())
        else:
            last_error = f"chat/completions {resp.status_code}: {resp.text[:500]}"

    if not text and api_style in {"responses", "auto"}:
        resp = requests.post(
            _api_url(base_url, "/responses"),
            headers=headers,
            json={
                "model": model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=timeout,
        )
        if resp.status_code < 400:
            text = _response_text(resp.json())
        else:
            last_error = f"responses {resp.status_code}: {resp.text[:500]}"

    if not text:
        raise RuntimeError(f"OpenAI-compatible API error: {last_error or 'empty response'}")

    values = _extract_json_array(text)
    translated = [""] * len(texts)
    for item in values:
        if not isinstance(item, dict):
            continue
        idx = int(item.get("i", -1))
        if 0 <= idx < len(texts):
            translated[idx] = str(item.get("text", "")).strip()

    if any(not item for item in translated):
        raise RuntimeError("Translation response missed one or more subtitle items.")
    return translated


def _translate_srt_file(
    *,
    srt_path: Path,
    target_language: str,
    model: str,
    batch_size: int,
    timeout: int,
    bilingual: bool,
    output_dir: str,
) -> tuple[Path, Path | None]:
    cues = _parse_srt(srt_path.read_text(encoding="utf-8-sig"))
    if not cues:
        raise RuntimeError(f"No subtitle cues found in {srt_path}")

    lang_name = _language_name(target_language)
    lang_suffix = _language_suffix(target_language)
    out_dir = Path(output_dir).expanduser().resolve() if output_dir else srt_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    translated: list[str] = []
    batch_size = max(1, min(int(batch_size), 80))
    print(f"[Subtitle] Translating {len(cues)} cues to {lang_name} with {model}...")
    for start in range(0, len(cues), batch_size):
        batch = cues[start : start + batch_size]
        translated.extend(
            _translate_batch_openai(
                texts=[cue.text for cue in batch],
                target_language=lang_name,
                model=model,
                timeout=timeout,
            )
        )
        print(f"[Subtitle] Progress: {min(start + batch_size, len(cues))}/{len(cues)}")

    translated_path = out_dir / f"{srt_path.stem}.{lang_suffix}.srt"
    _write_srt(cues, translated, translated_path)

    bilingual_path: Path | None = None
    if bilingual:
        bilingual_texts = [
            f"{target.strip()}\n{source.text.strip()}" for source, target in zip(cues, translated)
        ]
        bilingual_path = out_dir / f"{srt_path.stem}.zh-{lang_suffix}.srt"
        _write_srt(cues, bilingual_texts, bilingual_path)

    return translated_path, bilingual_path


def _free_translate_text_google(
    text: str,
    target_language: str,
    *,
    timeout: int,
    retries: int,
    delay: float,
) -> str:
    target = _language_suffix(target_language)
    last_error = ""
    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={
                    "client": "gtx",
                    "sl": "auto",
                    "tl": target,
                    "dt": "t",
                    "q": text,
                },
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=timeout,
            )
            if resp.status_code >= 400:
                last_error = f"HTTP {resp.status_code}: {_short_error_text(resp.text)}"
                if resp.status_code == 429:
                    raise FreeTranslateRateLimited(last_error)
                raise RuntimeError(last_error)
            data = resp.json()
            translated = "".join(part[0] for part in data[0] if part and part[0])
            if translated.strip():
                if delay > 0:
                    time.sleep(delay)
                return translated.strip()
            last_error = "empty translation"
        except FreeTranslateRateLimited:
            raise
        except Exception as e:
            last_error = _friendly_exception_text(e)
            if attempt < retries:
                time.sleep(min(20, attempt * 2))
    raise RuntimeError(f"Free translation failed: {last_error}")


def _mymemory_lang(value: str) -> str:
    suffix = _language_suffix(value)
    return {
        "zh": "zh-CN",
        "cn": "zh-CN",
        "ru": "ru-RU",
        "en": "en-US",
        "ja": "ja-JP",
        "ko": "ko-KR",
        "fr": "fr-FR",
        "de": "de-DE",
        "es": "es-ES",
    }.get(suffix, suffix)


def _free_translate_text_mymemory(
    text: str,
    target_language: str,
    *,
    timeout: int,
    retries: int,
    delay: float,
) -> str:
    target = _mymemory_lang(target_language)
    last_error = ""
    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = requests.get(
                "https://api.mymemory.translated.net/get",
                params={"q": text, "langpair": f"zh-CN|{target}"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=timeout,
            )
            if resp.status_code >= 400:
                last_error = f"HTTP {resp.status_code}: {_short_error_text(resp.text)}"
                raise RuntimeError(last_error)
            data = resp.json()
            translated = str(data.get("responseData", {}).get("translatedText", "")).strip()
            if translated:
                if delay > 0:
                    time.sleep(delay)
                return translated
            last_error = str(data)[:300]
        except Exception as e:
            last_error = _friendly_exception_text(e)
            if attempt < retries:
                time.sleep(min(20, attempt * 2))
    raise RuntimeError(f"MyMemory translation failed: {last_error}")


def _free_translate_text(
    text: str,
    target_language: str,
    *,
    timeout: int,
    retries: int,
    delay: float,
) -> str:
    try:
        return _free_translate_text_google(
            text,
            target_language,
            timeout=timeout,
            retries=max(1, min(retries, 2)),
            delay=delay,
        )
    except FreeTranslateRateLimited as google_error:
        print(f"[FreeTranslate] Google is rate-limited; using fallback now. {_friendly_exception_text(google_error)}")
        return _free_translate_text_mymemory(
            text,
            target_language,
            timeout=timeout,
            retries=max(1, min(retries, 2)),
            delay=delay,
        )
    except Exception as google_error:
        print(f"[FreeTranslate] Google request failed; switched to fallback: {_friendly_exception_text(google_error)}")
        return _free_translate_text_mymemory(
            text,
            target_language,
            timeout=timeout,
            retries=retries,
            delay=delay,
        )


def _free_batch_payload(texts: list[str]) -> str:
    parts: list[str] = []
    for idx, text in enumerate(texts):
        parts.append(f"ZXQ{idx:04d}ZXQ\n{text.strip()}")
    return "\n\n".join(parts)


def _split_free_batch_result(text: str, count: int) -> list[str]:
    marker_re = re.compile(r"ZXQ\s*(\d{4})\s*ZXQ", re.IGNORECASE)
    matches = list(marker_re.finditer(text or ""))
    if len(matches) < count:
        raise RuntimeError(f"batch markers lost ({len(matches)}/{count})")

    values = [""] * count
    for pos, match in enumerate(matches):
        idx = int(match.group(1))
        if not 0 <= idx < count:
            continue
        start = match.end()
        end = matches[pos + 1].start() if pos + 1 < len(matches) else len(text)
        cleaned = text[start:end].strip()
        cleaned = re.sub(r"^\s*[:：\-–—]+", "", cleaned).strip()
        values[idx] = cleaned
    if any(not item for item in values):
        raise RuntimeError("batch translation missed one or more items")
    return values


def _free_translate_batch_google(
    texts: list[str],
    target_language: str,
    *,
    timeout: int,
    retries: int,
    delay: float,
) -> list[str]:
    translated = _free_translate_text_google(
        _free_batch_payload(texts),
        target_language,
        timeout=timeout,
        retries=retries,
        delay=delay,
    )
    return _split_free_batch_result(translated, len(texts))


def _free_translate_batch_mymemory(
    texts: list[str],
    target_language: str,
    *,
    timeout: int,
    retries: int,
    delay: float,
) -> list[str]:
    translated = _free_translate_text_mymemory(
        _free_batch_payload(texts),
        target_language,
        timeout=timeout,
        retries=retries,
        delay=delay,
    )
    return _split_free_batch_result(translated, len(texts))


def _free_translate_batch_fallback(
    texts: list[str],
    target_language: str,
    *,
    timeout: int,
    retries: int,
    delay: float,
) -> list[str]:
    if len(texts) == 1:
        return [
            _free_translate_text_mymemory(
                texts[0],
                target_language,
                timeout=timeout,
                retries=retries,
                delay=delay,
            )
        ]
    try:
        return _free_translate_batch_mymemory(
            texts,
            target_language,
            timeout=timeout,
            retries=max(1, min(retries, 2)),
            delay=delay,
        )
    except Exception:
        mid = max(1, len(texts) // 2)
        return _free_translate_batch_fallback(
            texts[:mid],
            target_language,
            timeout=timeout,
            retries=retries,
            delay=delay,
        ) + _free_translate_batch_fallback(
            texts[mid:],
            target_language,
            timeout=timeout,
            retries=retries,
            delay=delay,
        )


def _iter_free_translation_batches(
    cues: list[SrtCue],
    translated: list[str],
    *,
    batch_size: int,
    max_chars: int = 3500,
) -> list[tuple[list[int], list[str]]]:
    batches: list[tuple[list[int], list[str]]] = []
    current_indices: list[int] = []
    current_texts: list[str] = []
    current_chars = 0
    batch_size = max(1, min(batch_size, 60))

    for idx, cue in enumerate(cues):
        if translated[idx]:
            continue
        text = cue.text.strip()
        projected = current_chars + len(text) + 16
        if current_indices and (len(current_indices) >= batch_size or projected > max_chars):
            batches.append((current_indices, current_texts))
            current_indices = []
            current_texts = []
            current_chars = 0
        current_indices.append(idx)
        current_texts.append(text)
        current_chars += len(text) + 16

    if current_indices:
        batches.append((current_indices, current_texts))
    return batches


def _translate_srt_file_free(
    *,
    srt_path: Path,
    target_language: str,
    timeout: int,
    retries: int,
    delay: float,
    batch_size: int,
    bilingual: bool,
    output_dir: str,
) -> tuple[Path, Path | None]:
    cues = _parse_srt(srt_path.read_text(encoding="utf-8-sig"))
    if not cues:
        raise RuntimeError(f"No subtitle cues found in {srt_path}")

    lang_name = _language_name(target_language)
    lang_suffix = _language_suffix(target_language)
    out_dir = Path(output_dir).expanduser().resolve() if output_dir else srt_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    cache_path = out_dir / f"{srt_path.stem}.{lang_suffix}.free-cache.json"
    translated: list[str] = [""] * len(cues)
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_items = cached.get("items", []) if isinstance(cached, dict) else cached
            for idx, value in enumerate(cached_items[: len(cues)]):
                translated[idx] = str(value or "").strip()
        except Exception:
            pass

    print(f"[FreeTranslate] Translating {len(cues)} cues to {lang_name} without API key...")
    done = sum(1 for item in translated if item)
    if done:
        print(f"[FreeTranslate] Resuming from cache: {done}/{len(cues)}")

    google_available = True
    google_limit_reported = False
    batches = _iter_free_translation_batches(cues, translated, batch_size=batch_size)
    for batch_no, (indices, texts) in enumerate(batches, 1):
        results: list[str] | None = None
        if google_available:
            try:
                results = _free_translate_batch_google(
                    texts,
                    target_language,
                    timeout=timeout,
                    retries=max(1, min(retries, 2)),
                    delay=delay,
                )
            except FreeTranslateRateLimited as e:
                google_available = False
                if not google_limit_reported:
                    print(f"[FreeTranslate] Google is rate-limited; switching to fallback. {_friendly_exception_text(e)}")
                    google_limit_reported = True
            except Exception as e:
                print(f"[FreeTranslate] Google batch request failed; switched to fallback: {_friendly_exception_text(e)}")

        if results is None:
            results = _free_translate_batch_fallback(
                texts,
                target_language,
                timeout=timeout,
                retries=max(1, min(retries, 2)),
                delay=delay,
            )

        for idx, value in zip(indices, results):
            translated[idx] = value

        cache_path.write_text(
            json.dumps(
                {
                    "source": str(srt_path),
                    "target": lang_suffix,
                    "items": translated,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        last_idx = indices[-1] + 1
        done = sum(1 for item in translated if item)
        print(f"[FreeTranslate] Progress: {done}/{len(cues)}")
        print(f"[FreeTranslate] Batch: {batch_no}/{len(batches)} cues={len(indices)} last={last_idx}/{len(cues)}")

    translated_path = out_dir / f"{srt_path.stem}.{lang_suffix}.srt"
    _write_srt(cues, translated, translated_path)

    bilingual_path: Path | None = None
    if bilingual:
        bilingual_texts = [
            f"{target.strip()}\n{source.text.strip()}" for source, target in zip(cues, translated)
        ]
        bilingual_path = out_dir / f"{srt_path.stem}.zh-{lang_suffix}.srt"
        _write_srt(cues, bilingual_texts, bilingual_path)

    print(f"[FreeTranslate] Done: {translated_path}")
    return translated_path, bilingual_path


def _create_translation_pack(
    *,
    srt_path: Path,
    target_language: str,
    output_dir: str,
) -> tuple[Path, Path]:
    if not srt_path.is_file():
        raise RuntimeError(f"SRT file not found: {srt_path}")
    cues = _parse_srt(srt_path.read_text(encoding="utf-8-sig"))
    if not cues:
        raise RuntimeError(f"No subtitle cues found in {srt_path}")

    lang_name = _language_name(target_language)
    lang_suffix = _language_suffix(target_language)
    out_dir = Path(output_dir).expanduser().resolve() if output_dir else srt_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    source_copy = out_dir / f"{srt_path.stem}.source.srt"
    source_copy.write_text(srt_path.read_text(encoding="utf-8-sig").strip() + "\n", encoding="utf-8")

    prompt_path = out_dir / f"{srt_path.stem}.translate-to-{lang_suffix}.prompt.txt"
    prompt = f"""请把我上传的 SRT 字幕文件翻译成{lang_name}。

严格要求：
1. 保留原来的 SRT 编号。
2. 保留所有时间轴，不要修改时间。
3. 只翻译字幕正文。
4. 输出仍然是完整有效的 SRT 格式。
5. 不要添加解释、标题、Markdown 代码块或额外说明。
6. 专业术语尽量准确；课程名、人名、学校名不确定时可以保留原文。
7. 字幕要自然、简洁，适合视频播放。

请直接输出翻译后的完整 SRT。
"""
    prompt_path.write_text(prompt, encoding="utf-8")
    return source_copy, prompt_path


def _normalize_manual_translation(
    *,
    source_srt_path: Path,
    translated_srt_path: Path,
    target_language: str,
    output_path: str,
    bilingual: bool,
) -> tuple[Path, Path | None, list[str]]:
    source_cues = _parse_srt(source_srt_path.read_text(encoding="utf-8-sig"))
    translated_cues = _parse_srt(translated_srt_path.read_text(encoding="utf-8-sig"))
    if not source_cues:
        raise RuntimeError(f"No subtitle cues found in source SRT: {source_srt_path}")
    if not translated_cues:
        raise RuntimeError(f"No subtitle cues found in translated SRT: {translated_srt_path}")
    if len(source_cues) != len(translated_cues):
        raise RuntimeError(
            "Cue count mismatch: "
            f"source has {len(source_cues)}, translated has {len(translated_cues)}. "
            "Ask the AI to translate again without merging or deleting subtitle blocks."
        )

    warnings: list[str] = []
    for idx, (src, trans) in enumerate(zip(source_cues, translated_cues), 1):
        if src.start != trans.start or src.end != trans.end:
            warnings.append(f"cue {idx}: timestamp differs; using source timestamp")

    lang_suffix = _language_suffix(target_language)
    out = (
        Path(output_path).expanduser().resolve()
        if output_path
        else translated_srt_path.with_name(f"{source_srt_path.stem}.{lang_suffix}.normalized.srt")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    translated_texts = [cue.text for cue in translated_cues]
    _write_srt(source_cues, translated_texts, out)

    bilingual_path: Path | None = None
    if bilingual:
        bilingual_path = out.with_name(f"{out.stem}.bilingual.srt")
        bilingual_texts = [
            f"{target.strip()}\n{source.text.strip()}" for source, target in zip(source_cues, translated_texts)
        ]
        _write_srt(source_cues, bilingual_texts, bilingual_path)

    return out, bilingual_path, warnings


def _prepare_player_files(
    *,
    video_path: Path,
    srt_path: Path,
    output_dir: str,
    copy_video: bool,
) -> tuple[Path, Path, Path]:
    if not video_path.is_file():
        raise RuntimeError(f"Video file not found: {video_path}")
    if not srt_path.is_file():
        raise RuntimeError(f"SRT file not found: {srt_path}")

    out_dir = Path(output_dir).expanduser().resolve() if output_dir else video_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    target_video = out_dir / video_path.name if copy_video else video_path.resolve()
    if copy_video and video_path.resolve() != target_video.resolve():
        print("[PlayerPack] Copying video file...")
        shutil.copy2(video_path, target_video)

    target_srt = target_video.with_suffix(".srt")
    try:
        srt_text = srt_path.read_text(encoding="utf-8-sig")
        target_srt.write_text(srt_text.strip() + "\n", encoding="utf-8-sig")
    except UnicodeDecodeError:
        shutil.copy2(srt_path, target_srt)
    _write_subtitle_health_report(srt_path=target_srt, video_path=target_video)

    readme = target_video.parent / "PotPlayer字幕使用说明.txt"
    readme.write_text(
        "使用方法：\n"
        "1. 保持视频文件和 SRT 字幕文件在同一个文件夹。\n"
        "2. 两个文件名必须一样，只保留扩展名不同，例如：lesson.mp4 和 lesson.srt。\n"
        "3. 用 PotPlayer 打开视频，一般会自动显示字幕。\n"
        "4. 如果没有自动显示字幕，在 PotPlayer 里右键视频，选择“字幕”或“添加/选择字幕”加载同名 SRT。\n"
        "5. 如果字幕乱码，在 PotPlayer 的字幕设置里把字幕编码改成 UTF-8。\n",
        encoding="utf-8",
    )
    return target_video, target_srt, readme


def _trash_dir() -> Path:
    return _skill_root() / ".trash"


def _move_to_trash(path: Path) -> None:
    if not path.exists():
        return
    _trash_dir().mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    target = _trash_dir() / f"{path.name}.{ts}"
    try:
        path.replace(target)
    except Exception:
        try:
            shutil.move(str(path), str(target))
        except Exception:
            pass


def _parse_env_lines(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        result[key] = value
    return result


def _quote_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f"\"{escaped}\""


def _write_env_file(path: Path, pairs: dict[str, str]) -> None:
    lines = ["# Auto-generated by look-tongji-notes", f"# Updated: {_now_iso()}"]
    for key, value in pairs.items():
        lines.append(f"{key}={_quote_env_value(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class AuthSession:
    username: str
    jwt_token: str


def _save_auth_session(session: AuthSession) -> None:
    _state_dir().mkdir(parents=True, exist_ok=True)
    _auth_session_file().write_text(
        json.dumps(
            {"username": session.username, "jwt_token": session.jwt_token, "updated_at": _now_iso()},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _load_auth_session() -> AuthSession | None:
    path = _auth_session_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        username = (data.get("username") or "").strip()
        jwt_token = (data.get("jwt_token") or "").strip()
        if not jwt_token:
            return None
        return AuthSession(username=username, jwt_token=jwt_token)
    except Exception:
        return None


def _clear_auth_session() -> None:
    _move_to_trash(_auth_session_file())


def _build_client_from_jwt(jwt_token: str) -> TongjiClient | None:
    auth = TongjiAuth()
    auth.jwt_token = jwt_token
    auth._setup_bearer_auth()
    auth.logged_in = True
    if not auth.check_alive():
        return None
    return TongjiClient(auth)


def _ensure_authenticated_client(force_login: bool = False) -> tuple[TongjiClient, str]:
    # 1) Try cached JWT first
    if not force_login:
        cached = _load_auth_session()
        if cached:
            client = _build_client_from_jwt(cached.jwt_token)
            if client is not None:
                return client, cached.username

    # 2) Login using env vars (loaded by tongji_backend.config)
    try:
        from tongji_backend import config
    except Exception as e:
        raise RuntimeError(f"Failed to import config: {e}") from e

    username = (config.TONGJI_USERNAME or "").strip()
    password = (config.TONGJI_PASSWORD or "").strip()
    if not username or not password:
        raise RuntimeError(
            "Missing credentials. Run `setup` to create .env, "
            "or set TONGJI_USERNAME/TONGJI_PASSWORD in the environment."
        )

    auth = TongjiAuth()
    auth.login(username=username, password=password)
    jwt_token = auth.get_jwt_token() or ""
    if jwt_token:
        _save_auth_session(AuthSession(username=username, jwt_token=jwt_token))
    return TongjiClient(auth), username


def _check_deps() -> list[str]:
    missing: list[str] = []
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg")
    for module in ("requests", "dotenv", "playwright.sync_api", "PIL"):
        try:
            __import__(module)
        except Exception:
            missing.append(module)
    return missing


def cmd_setup(args: argparse.Namespace) -> int:
    missing = _check_deps()
    if missing:
        print("[Setup] Missing dependencies:")
        for item in missing:
            print(f"  - {item}")
        print("\n[Setup] Install Python deps with:")
        print(f"  pip install -r \"{_skill_root() / 'requirements.txt'}\"")
        print("[Setup] Install Playwright browser with:")
        print("  python -m playwright install chromium")
        print()

    env_file = _env_path()
    if env_file.exists() and not args.overwrite:
        _print_err(f".env already exists at {env_file}. Re-run with --overwrite to replace it.")
        return 2

    username = (args.username or "").strip()
    password = (args.password or "").strip()

    if not username:
        username = input("Tongji username (student/staff ID): ").strip()
    if not password:
        password = getpass.getpass("Tongji password (input hidden): ").strip()

    if not username or not password:
        _print_err("Username/password cannot be empty.")
        return 2

    existing: dict[str, str] = {}
    if env_file.exists():
        try:
            existing = _parse_env_lines(env_file.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    existing["TONGJI_USERNAME"] = username
    existing["TONGJI_PASSWORD"] = password
    _write_env_file(env_file, existing)
    _clear_auth_session()
    print(f"[Setup] Saved credentials to: {env_file}")
    print("[Setup] Done.")
    return 0


def _save_last_course(course: dict[str, Any]) -> None:
    _state_dir().mkdir(parents=True, exist_ok=True)
    _last_course_file().write_text(
        json.dumps({"course": course, "updated_at": _now_iso()}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_last_course_id() -> str | None:
    path = _last_course_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        course = data.get("course") or {}
        course_id = (course.get("course_id") or "").strip()
        return course_id or None
    except Exception:
        return None


def cmd_list(args: argparse.Namespace) -> int:
    try:
        client, username = _ensure_authenticated_client(force_login=args.force_login)
    except Exception as e:
        _print_err(str(e))
        return 1

    query = (args.query or "").strip().lower()

    if args.all_courses:
        courses = client.get_all_courses()
    else:
        courses = client.get_recent_courses(per_page=max(1, int(args.limit)))

    if not courses:
        _print_err("No courses found.")
        return 1

    print(f"[List] Logged in as: {username or '(unknown)'}")

    def _course_title(course: dict[str, Any]) -> str:
        return str(course.get("title") or course.get("course_title") or "").strip()

    def _course_teacher(course: dict[str, Any]) -> str:
        return str(course.get("teacher") or course.get("realname") or "").strip()

    if query:
        courses = [
            c for c in courses
            if query in _course_title(c).lower() or query in _course_teacher(c).lower()
        ]

    if not courses:
        _print_err("No courses matched the query.")
        return 1

    header = "All courses" if args.all_courses else "Recent courses"
    if query:
        header += f" (query: {args.query})"
    print(f"[List] {header}:")

    shown = courses[: max(1, int(args.limit))]
    for idx, c in enumerate(shown, 1):
        title = _course_title(c)
        teacher = _course_teacher(c)
        cid = str(c.get("course_id") or "").strip()
        label = f"{title} ({cid})"
        if teacher:
            label += f" / {teacher}"
        print(f"  {idx}. {label}")

    choose = args.choose
    if choose is None:
        raw = input("\nChoose a course number (or press Enter to skip): ").strip()
        if not raw:
            return 0
        choose = int(raw)

    if choose < 1 or choose > len(shown):
        _print_err(f"Invalid selection: {choose}")
        return 2

    selected = shown[choose - 1]
    _save_last_course(selected)
    print(f"[List] Selected: {_course_title(selected)} ({selected.get('course_id', '')})")
    return 0


def _extract_ids_from_url(url: str) -> tuple[str | None, str | None]:
    parsed = urlparse(url)

    query_parts: list[str] = []
    if parsed.query:
        query_parts.append(parsed.query)
    if parsed.fragment and "?" in parsed.fragment:
        query_parts.append(parsed.fragment.split("?", 1)[1])

    params: dict[str, str] = {}
    for part in query_parts:
        for k, v in parse_qs(part).items():
            if not v:
                continue
            params[k.lower()] = v[0]

    course_id = (
        params.get("course_id")
        or params.get("courseid")
        or params.get("cid")
        or params.get("course")
    )
    sub_id = (
        params.get("sub_id")
        or params.get("subid")
        or params.get("sid")
        or params.get("sub")
    )

    # Best-effort: try to find `sub_id` in fragment path (e.g. "#/play/12345")
    if not sub_id and parsed.fragment:
        m = re.search(r"/play/(\d+)", parsed.fragment)
        if m:
            sub_id = m.group(1)

    return course_id, sub_id


def _choose_lecture_from_course(client: TongjiClient, course_id: str, limit: int) -> tuple[str, dict[str, Any] | None]:
    detail = client.get_course_detail(course_id)
    lectures = detail.get("lectures") or []
    if not isinstance(lectures, list) or not lectures:
        raise RuntimeError("No lectures found for this course.")

    # Prefer playable lectures; keep fallback to show something
    playable = [l for l in lectures if l.get("has_playback") is True]
    candidates = playable or lectures

    def _sort_key(item: dict[str, Any]) -> str:
        return str(item.get("date") or "")

    candidates = sorted(candidates, key=_sort_key, reverse=True)[:limit]

    print("[Select] Lectures (latest first):")
    for idx, lec in enumerate(candidates, 1):
        sub_id = str(lec.get("sub_id") or "")
        title = str(lec.get("sub_title") or "").strip()
        date = str(lec.get("date") or "").strip()
        flag = "playback" if lec.get("has_playback") else "no-playback"
        display = " ".join([p for p in [date, title] if p]).strip()
        print(f"  {idx}. {display} ({sub_id}) [{flag}]")

    raw = input("\nChoose a lecture number: ").strip()
    if not raw:
        raise RuntimeError("No lecture selected.")
    choose = int(raw)
    if choose < 1 or choose > len(candidates):
        raise RuntimeError(f"Invalid lecture selection: {choose}")

    selected = candidates[choose - 1]
    return str(selected.get("sub_id") or ""), selected


def _resolve_course_sub(
    client: TongjiClient,
    *,
    lecture_url: str,
    course_id: str,
    sub_id: str,
    lecture_limit: int,
    tag: str,
) -> tuple[str, str] | None:
    course_id = (course_id or "").strip()
    sub_id = (sub_id or "").strip()

    if lecture_url:
        parsed_course_id, parsed_sub_id = _extract_ids_from_url(lecture_url)
        course_id = course_id or (parsed_course_id or "")
        sub_id = sub_id or (parsed_sub_id or "")

    if not course_id:
        last = _load_last_course_id()
        if last:
            print(f"[{tag}] Using last selected course_id from state: {last}")
            course_id = last

    if not course_id:
        _print_err("Missing course_id. Provide --course-id or --lecture-url that contains it.")
        return None

    if not sub_id:
        try:
            sub_id, _ = _choose_lecture_from_course(client, course_id, limit=lecture_limit)
        except Exception as e:
            _print_err(str(e))
            return None
    return course_id, sub_id


def _run_transcript_job(
    *,
    client: TongjiClient,
    username: str,
    course_id: str,
    sub_id: str,
    lecture_url: str,
    output_dir: str,
    base_name: str | None = None,
    proofread_mode: str = "off",
    proofread_model: str = "",
    tag: str = "Transcript",
) -> int:
    print(f"[{tag}] Logged in as: {username or '(unknown)'}")
    print(f"[{tag}] course_id={course_id} sub_id={sub_id}")
    video_url = client.get_video_url(course_id, sub_id)
    if not video_url:
        _print_err("Failed to resolve video URL. The lecture may not have playback enabled.")
        return 1

    stream_url, http_headers = client.get_stream_params(video_url)
    transcriber = Transcriber()

    try:
        transcript, srt_content, utterances = transcriber.transcribe_url(
            stream_url, http_headers=http_headers
        )
    except NoAudioStreamError as e:
        _print_err(f"No audio stream: {e}")
        return 1
    except TranscriptionError as e:
        _print_err(f"Transcription failed: {e}")
        return 1
    except Exception as e:
        _print_err(f"Unexpected error: {type(e).__name__}: {e}")
        return 1

    out_dir = _output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base = _safe_output_name(base_name or f"{course_id}_{sub_id}")
    txt_path = out_dir / f"{base}.txt"
    srt_path = out_dir / f"{base}.srt"
    meta_path = out_dir / f"{base}.json"

    txt_path.write_text(transcript.strip() + "\n", encoding="utf-8")
    if srt_content:
        srt_path.write_text(srt_content.strip() + "\n", encoding="utf-8")
    used_proofread = _normalize_proofread_mode(proofread_mode) if srt_content else "off"
    meta_path.write_text(
        json.dumps(
            {
                "course_id": course_id,
                "sub_id": sub_id,
                "lecture_url": lecture_url or "",
                "video_url": video_url,
                "generated_at": _now_iso(),
                "user": username or "",
                "proofread_mode": used_proofread,
                "artifacts": {
                    "transcript_txt": str(txt_path),
                    "subtitle_srt": str(srt_path) if srt_content else "",
                },
                "utterances": utterances or [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"[{tag}] Done. Files written:")
    print(f"  - {txt_path}")
    if srt_content:
        print(f"  - {srt_path}")
    print(f"  - {meta_path}")
    return 0


def _run_video_download_job(
    *,
    client: TongjiClient,
    username: str,
    course_id: str,
    sub_id: str,
    lecture_url: str,
    output_dir: str,
    timeout: int,
    base_name: str | None = None,
) -> int:
    print(f"[VideoDownload] Logged in as: {username or '(unknown)'}")
    print(f"[VideoDownload] course_id={course_id} sub_id={sub_id}")
    video_url = client.get_video_url(course_id, sub_id)
    if not video_url:
        _print_err("Failed to resolve video URL. The lecture may not have playback enabled.")
        return 1

    stream_url, http_headers = client.get_stream_params(video_url)
    out_dir = _output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = _safe_output_name(base_name or f"{course_id}_{sub_id}")
    output_path = out_dir / f"{base}.mp4"

    try:
        if _file_ready(output_path, min_bytes=1024 * 1024):
            print(f"[VideoDownload] Reusing existing video: {output_path}")
            print("[VideoDownload] Progress: 100/100")
        else:
            _download_video_stream(
                stream_url=stream_url,
                http_headers=http_headers,
                output_path=output_path,
                timeout=timeout,
            )
    except Exception as e:
        _print_err(f"Video download failed: {type(e).__name__}: {e}")
        return 1

    meta_path = out_dir / f"{base}.video.json"
    meta_path.write_text(
        json.dumps(
            {
                "course_id": course_id,
                "sub_id": sub_id,
                "base_name": base,
                "lecture_url": lecture_url or "",
                "video_url": video_url,
                "generated_at": _now_iso(),
                "user": username or "",
                "artifacts": {"video_file": str(output_path)},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[VideoDownload] Metadata: {meta_path}")
    return 0


def _run_direct_video_download_job(
    *,
    media_url: str,
    output_dir: str,
    timeout: int,
    base_name: str | None = None,
    tag: str = "VideoDownload",
) -> Path:
    out_dir = _output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = _safe_output_name(base_name or _direct_output_base_name(output_dir))
    output_path = out_dir / f"{base}.mp4"

    print(f"[{tag}] Source: direct media URL")
    print(f"[{tag}] url={media_url}")
    if _file_ready(output_path, min_bytes=1024 * 1024):
        print(f"[{tag}] Reusing existing video: {output_path}")
        print(f"[{tag}] Progress: 100/100")
    else:
        _download_video_stream(
            stream_url=media_url,
            http_headers=None,
            output_path=output_path,
            timeout=timeout,
        )

    meta_path = out_dir / f"{base}.video.json"
    meta_path.write_text(
        json.dumps(
            {
                "source_type": "direct_media_url",
                "source_url": media_url,
                "generated_at": _now_iso(),
                "artifacts": {"video_file": str(output_path)},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[{tag}] Metadata: {meta_path}")
    return output_path


def _run_direct_transcript_job(
    *,
    media_url: str,
    output_dir: str,
    proofread_mode: str = "off",
    proofread_model: str = "",
    base_name: str | None = None,
    tag: str = "Transcript",
) -> Path:
    transcriber = Transcriber()
    base = _safe_output_name(base_name or _direct_output_base_name(output_dir))
    print(f"[{tag}] Source: direct media URL")
    print(f"[{tag}] url={media_url}")
    transcript, srt_content, utterances = transcriber.transcribe_url(media_url)

    out_dir = _output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / f"{base}.txt"
    srt_path = out_dir / f"{base}.srt"
    meta_path = out_dir / f"{base}.json"

    txt_path.write_text(transcript.strip() + "\n", encoding="utf-8")
    if srt_content:
        srt_path.write_text(srt_content.strip() + "\n", encoding="utf-8")
    used_proofread = _normalize_proofread_mode(proofread_mode) if srt_content else "off"
    meta_path.write_text(
        json.dumps(
            {
                "source_type": "direct_media_url",
                "source_url": media_url,
                "generated_at": _now_iso(),
                "proofread_mode": used_proofread,
                "artifacts": {
                    "transcript_txt": str(txt_path),
                    "subtitle_srt": str(srt_path) if srt_content else "",
                },
                "utterances": utterances or [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"[{tag}] Done. Files written:")
    print(f"  - {txt_path}")
    if srt_content:
        print(f"  - {srt_path}")
    print(f"  - {meta_path}")
    return srt_path


def _run_transcript_local_video_job(
    *,
    username: str,
    course_id: str,
    sub_id: str,
    lecture_url: str,
    video_path: Path,
    output_dir: str,
    base_name: str | None = None,
    proofread_mode: str = "off",
    proofread_model: str = "",
    tag: str = "Transcript",
) -> int:
    print(f"[{tag}] Logged in as: {username or '(unknown)'}")
    print(f"[{tag}] course_id={course_id} sub_id={sub_id}")
    print(f"[{tag}] Using local video for subtitle timing: {video_path}")
    if not video_path.exists() or video_path.stat().st_size == 0:
        _print_err(f"Local video file is missing or empty: {video_path}")
        return 1

    transcriber = Transcriber()
    try:
        transcript, srt_content, utterances = transcriber.transcribe_media_file(str(video_path))
    except NoAudioStreamError as e:
        _print_err(f"No audio stream: {e}")
        return 1
    except TranscriptionError as e:
        _print_err(f"Transcription failed: {e}")
        return 1
    except Exception as e:
        _print_err(f"Unexpected error: {type(e).__name__}: {e}")
        return 1

    out_dir = _output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base = _safe_output_name(base_name or f"{course_id}_{sub_id}")
    txt_path = out_dir / f"{base}.txt"
    srt_path = out_dir / f"{base}.srt"
    meta_path = out_dir / f"{base}.json"

    txt_path.write_text(transcript.strip() + "\n", encoding="utf-8")
    if srt_content:
        srt_path.write_text(srt_content.strip() + "\n", encoding="utf-8")
    used_proofread = _normalize_proofread_mode(proofread_mode) if srt_content else "off"
    meta_path.write_text(
        json.dumps(
            {
                "course_id": course_id,
                "sub_id": sub_id,
                "lecture_url": lecture_url or "",
                "video_file": str(video_path),
                "generated_at": _now_iso(),
                "user": username or "",
                "timing_source": "local_video_file",
                "proofread_mode": used_proofread,
                "artifacts": {
                    "transcript_txt": str(txt_path),
                    "subtitle_srt": str(srt_path) if srt_content else "",
                },
                "utterances": utterances or [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"[{tag}] Done. Files written:")
    print(f"  - {txt_path}")
    if srt_content:
        print(f"  - {srt_path}")
    print(f"  - {meta_path}")
    return 0


def _run_replay_with_subtitles_job(
    *,
    client: TongjiClient,
    username: str,
    course_id: str,
    sub_id: str,
    lecture_url: str,
    output_dir: str,
    video_timeout: int,
    target: str,
    translation_mode: str,
    model: str,
    batch_size: int,
    api_timeout: int,
    free_timeout: int,
    free_retries: int,
    free_delay: float,
    free_batch_size: int,
    sync_subtitle: bool,
    sync_max_shift_ms: int,
    sync_lead_ms: int,
    redownload: bool,
    retranscribe: bool,
    retranslate: bool,
    proofread_mode: str,
    proofread_model: str,
    base_name: str | None = None,
) -> dict[str, Any]:
    out_dir = _output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base = _safe_output_name(base_name or f"{course_id}_{sub_id}")
    video_path = out_dir / f"{base}.mp4"
    txt_path = out_dir / f"{base}.txt"
    raw_source_srt = out_dir / f"{base}.srt"
    source_backup_srt = out_dir / f"{base}.zh.srt"
    result: dict[str, Any] = {
        "course_id": course_id,
        "sub_id": sub_id,
        "lecture_url": lecture_url or "",
        "ok": False,
        "video_file": str(video_path),
        "source_srt": str(raw_source_srt),
        "transcript_txt": str(txt_path),
        "final_srt": "",
        "proofread_mode": _normalize_proofread_mode(proofread_mode),
        "target": target,
        "generated_at": _now_iso(),
    }

    if redownload and video_path.exists():
        try:
            video_path.unlink()
        except Exception:
            pass

    video_code = _run_video_download_job(
        client=client,
        username=username,
        course_id=course_id,
        sub_id=sub_id,
        lecture_url=lecture_url,
        output_dir=output_dir,
        timeout=video_timeout,
        base_name=base,
    )
    if video_code != 0:
        result["error"] = "video download failed"
        return result

    source_srt = raw_source_srt
    transcript_generated = False

    if source_backup_srt.exists() and not retranscribe:
        shutil.copy2(source_backup_srt, source_srt)
        print(f"[BatchReplay] Reusing Chinese source subtitles: {source_backup_srt}")
    elif _file_ready(raw_source_srt, min_bytes=100) and _file_ready(txt_path, min_bytes=20) and not retranscribe:
        print(f"[BatchReplay] Reusing transcript artifacts: {raw_source_srt}")
        if not source_backup_srt.exists():
            shutil.copy2(raw_source_srt, source_backup_srt)
    else:
        transcript_code = _run_transcript_local_video_job(
            username=username,
            course_id=course_id,
            sub_id=sub_id,
            lecture_url=lecture_url,
            video_path=video_path,
            output_dir=output_dir,
            base_name=base,
            proofread_mode=proofread_mode,
            proofread_model=proofread_model,
            tag="Transcript",
        )
        if transcript_code != 0:
            result["error"] = "subtitle generation failed"
            return result
        transcript_generated = True
        if _file_ready(raw_source_srt, min_bytes=100):
            shutil.copy2(raw_source_srt, source_backup_srt)
            print(f"[BatchReplay] Saved Chinese source subtitles: {source_backup_srt}")

    if sync_subtitle and transcript_generated and _file_ready(source_srt, min_bytes=100):
        try:
            synced_path, sync_report = _apply_subtitle_timing_sync(
                video_path=video_path,
                srt_path=source_srt,
                output_path=source_srt,
                max_local_shift_ms=sync_max_shift_ms,
                lead_ms=sync_lead_ms,
            )
            source_srt = synced_path
            shutil.copy2(source_srt, source_backup_srt)
            print(
                "[SubtitleSync] "
                f"adjusted={sync_report['changed']}/{sync_report['cues']} "
                f"global_shift_ms={sync_report['global_shift_ms']} "
                f"confidence={sync_report['global_confidence']}"
            )
        except Exception as e:
            print(f"[SubtitleSync] Warning: sync skipped: {type(e).__name__}: {e}")

    if _file_ready(source_srt, min_bytes=100):
        try:
            used_proofread = _apply_subtitle_proofread(
                srt_path=source_srt,
                txt_path=txt_path if _file_ready(txt_path, min_bytes=1) else None,
                mode=proofread_mode,
                model=proofread_model,
                tag="Proofread",
            )
            result["proofread_mode"] = used_proofread
        except Exception as e:
            print(f"[Proofread] Warning: proofread skipped: {type(e).__name__}: {e}")

    target_lower = (target or "zh").strip().lower()
    final_srt = source_srt

    if target_lower not in {"zh", "cn", "chinese"}:
        lang_suffix = _language_suffix(target)
        translated_path_hint = out_dir / f"{source_srt.stem}.{lang_suffix}.srt"
        if _file_ready(translated_path_hint, min_bytes=100) and not retranslate:
            normalized_path, _bilingual, warnings = _normalize_manual_translation(
                source_srt_path=source_srt,
                translated_srt_path=translated_path_hint,
                target_language=target,
                output_path=str(translated_path_hint),
                bilingual=False,
            )
            final_srt = normalized_path
            print(f"[BatchReplay] Reusing translated subtitles: {final_srt}")
            if warnings:
                print(f"[BatchReplay] Translation normalization warnings: {len(warnings)}")
        elif translation_mode == "free":
            final_srt, _ = _translate_srt_file_free(
                srt_path=source_srt,
                target_language=target,
                timeout=free_timeout,
                retries=free_retries,
                delay=free_delay,
                batch_size=free_batch_size,
                bilingual=False,
                output_dir=output_dir,
            )
        else:
            final_srt, _ = _translate_srt_file(
                srt_path=source_srt,
                target_language=target,
                model=model,
                batch_size=batch_size,
                timeout=api_timeout,
                bilingual=False,
                output_dir=output_dir,
            )

    result["final_srt"] = str(final_srt)
    result["ok"] = True
    return result


def _download_one_slide(
    client: TongjiClient,
    item: dict[str, Any],
    out_dir: Path,
    index: int,
    timeout: int,
    retries: int,
) -> tuple[dict[str, Any], str | None]:
    created_sec = int(item.get("created_sec") or 0)
    image_url = str(item.get("image_url") or "").strip()
    if not image_url:
        return item, "missing image_url"

    stamp = _format_hms(created_sec)
    ext = _guess_ext_from_url(image_url)
    filename = f"{index:04d}_t{stamp}_s{created_sec:06d}{ext}"
    path = out_dir / _safe_filename_part(filename)

    last_err = ""
    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = client.session.get(image_url, timeout=timeout)
            if resp.status_code == 200 and resp.content:
                path.write_bytes(resp.content)
                item["filename"] = path.name
                item["filepath"] = str(path)
                item["downloaded_at"] = _now_iso()
                item["bytes"] = len(resp.content)
                return item, None

            last_err = f"http {resp.status_code}"
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.5 * attempt)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(0.5 * attempt)

    return item, last_err or "download failed"


def _run_slide_job(
    *,
    client: TongjiClient,
    username: str,
    course_id: str,
    sub_id: str,
    lecture_url: str,
    output_dir: str,
    per_page: int,
    max_pages: int,
    max_items: int,
    concurrency: int,
    retries: int,
    timeout: int,
    dedupe: bool,
    dedupe_threshold: int,
    tag: str = "Slide",
) -> int:
    print(f"[{tag}] Logged in as: {username or '(unknown)'}")
    print(f"[{tag}] course_id={course_id} sub_id={sub_id}")
    try:
        snapshots = client.get_ppt_snapshots(
            course_id,
            sub_id,
            per_page=max(1, int(per_page)),
            max_pages=max(1, int(max_pages)),
        )
    except Exception as e:
        _print_err(f"Failed to list slide snapshots: {e}")
        return 1

    if not snapshots:
        _print_err("No slide snapshots found for this lecture.")
        return 1

    if max_items and max_items > 0:
        snapshots = snapshots[: max_items]

    out_dir = (
        Path(output_dir).expanduser().resolve()
        if output_dir
        else (Path.cwd() / "tongji-output" / f"slide_{course_id}_{sub_id}").resolve()
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    concurrency = max(1, min(int(concurrency), 16))
    retries = max(1, min(int(retries), 8))
    timeout = max(5, int(timeout))

    print(
        f"[{tag}] Found {len(snapshots)} snapshots. Downloading with "
        f"concurrency={concurrency}, retries={retries}, timeout={timeout}s ..."
    )

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        fut_map = {
            executor.submit(
                _download_one_slide,
                client,
                item,
                out_dir,
                idx,
                timeout,
                retries,
            ): item
            for idx, item in enumerate(snapshots, 1)
        }

        done_count = 0
        total = len(fut_map)
        for fut in concurrent.futures.as_completed(fut_map):
            item, err = fut.result()
            done_count += 1
            if err:
                failures.append({"item": item, "error": err})
            else:
                results.append(item)
            if done_count % 10 == 0 or done_count == total:
                print(f"[{tag}] Progress: {done_count}/{total}")

    results.sort(key=lambda x: int(x.get("created_sec") or 0))

    meta = {
        "course_id": course_id,
        "sub_id": sub_id,
        "lecture_url": lecture_url or "",
        "generated_at": _now_iso(),
        "user": username or "",
        "download": {
            "requested": len(snapshots),
            "succeeded": len(results),
            "failed": len(failures),
            "concurrency": concurrency,
            "retries": retries,
            "timeout_seconds": timeout,
        },
        "items": results,
        "failures": failures,
    }
    if dedupe:
        deduped_items, dedupe_info = _dedupe_slide_items(
            slide_dir=out_dir,
            items=results,
            threshold=dedupe_threshold,
            tag=f"{tag} Dedupe",
        )
        meta["items"] = deduped_items
        meta["dedupe"] = dedupe_info
    else:
        meta["dedupe"] = {
            "enabled": False,
            "status": "disabled",
        }

    meta_path = out_dir / "index.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[{tag}] Done.")
    print(f"  - output_dir: {out_dir}")
    print(f"  - success: {len(results)}")
    if dedupe and isinstance(meta.get("dedupe"), dict):
        print(f"  - unique_slides: {meta['dedupe'].get('kept', len(meta['items']))}")
        print(f"  - removed_duplicates: {meta['dedupe'].get('removed', 0)}")
    print(f"  - failed: {len(failures)}")
    print(f"  - index: {meta_path}")
    if failures:
        print(f"[{tag}] Some downloads failed. You can re-run with lower --concurrency (e.g. 2) or higher --retries.")
    return 0 if not failures else 3


def cmd_transcript(args: argparse.Namespace) -> int:
    direct_media_url = _direct_media_url_from_lecture_url(args.lecture_url)
    if direct_media_url:
        try:
            _run_direct_transcript_job(
                media_url=direct_media_url,
                output_dir=args.output_dir,
                proofread_mode=args.proofread_mode,
                proofread_model=args.proofread_model,
                tag="Transcript",
            )
            return 0
        except NoAudioStreamError as e:
            _print_err(f"No audio stream: {e}")
            return 1
        except TranscriptionError as e:
            _print_err(f"Transcription failed: {e}")
            return 1
        except Exception as e:
            _print_err(f"Unexpected error: {type(e).__name__}: {e}")
            return 1

    try:
        client, username = _ensure_authenticated_client(force_login=args.force_login)
    except Exception as e:
        _print_err(str(e))
        return 1
    resolved = _resolve_course_sub(
        client,
        lecture_url=args.lecture_url,
        course_id=args.course_id,
        sub_id=args.sub_id,
        lecture_limit=args.lecture_limit,
        tag="Transcript",
    )
    if not resolved:
        return 2
    course_id, sub_id = resolved
    base_name = _replay_output_base_name(client=client, course_id=course_id, sub_id=sub_id)
    return _run_transcript_job(
        client=client,
        username=username,
        course_id=course_id,
        sub_id=sub_id,
        lecture_url=args.lecture_url,
        output_dir=args.output_dir,
        base_name=base_name,
        proofread_mode=args.proofread_mode,
        proofread_model=args.proofread_model,
        tag="Transcript",
    )


def cmd_slide(args: argparse.Namespace) -> int:
    try:
        client, username = _ensure_authenticated_client(force_login=args.force_login)
    except Exception as e:
        _print_err(str(e))
        return 1
    resolved = _resolve_course_sub(
        client,
        lecture_url=args.lecture_url,
        course_id=args.course_id,
        sub_id=args.sub_id,
        lecture_limit=args.lecture_limit,
        tag="Slide",
    )
    if not resolved:
        return 2
    course_id, sub_id = resolved
    return _run_slide_job(
        client=client,
        username=username,
        course_id=course_id,
        sub_id=sub_id,
        lecture_url=args.lecture_url,
        output_dir=args.output_dir,
        per_page=args.per_page,
        max_pages=args.max_pages,
        max_items=args.max_items,
        concurrency=args.concurrency,
        retries=args.retries,
        timeout=args.timeout,
        dedupe=not args.no_dedupe,
        dedupe_threshold=args.dedupe_threshold,
        tag="Slide",
    )


def cmd_slide_dedupe(args: argparse.Namespace) -> int:
    slide_dir = Path(args.input_dir).expanduser().resolve()
    if not slide_dir.is_dir():
        _print_err(f"Slide directory not found: {slide_dir}")
        return 2

    items = _load_slide_items_from_dir(slide_dir)
    if not items:
        _print_err(f"No slide images found in: {slide_dir}")
        return 2

    deduped_items, dedupe_info = _dedupe_slide_items(
        slide_dir=slide_dir,
        items=items,
        threshold=args.dedupe_threshold,
        tag="Slide Dedupe",
    )

    index_path = slide_dir / "index.json"
    meta: dict[str, Any]
    if index_path.is_file():
        try:
            meta = json.loads(index_path.read_text(encoding="utf-8-sig"))
        except Exception:
            meta = {}
    else:
        meta = {}

    meta["generated_at"] = _now_iso()
    meta["items"] = deduped_items
    meta["dedupe"] = dedupe_info
    index_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[Slide Dedupe] Updated index: {index_path}")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    try:
        client, username = _ensure_authenticated_client(force_login=args.force_login)
    except Exception as e:
        _print_err(str(e))
        return 1
    resolved = _resolve_course_sub(
        client,
        lecture_url=args.lecture_url,
        course_id=args.course_id,
        sub_id=args.sub_id,
        lecture_limit=args.lecture_limit,
        tag="Note",
    )
    if not resolved:
        return 2
    course_id, sub_id = resolved

    jwt_token = client.auth.get_jwt_token() or ""
    t_client = _build_client_from_jwt(jwt_token) if jwt_token else client
    s_client = _build_client_from_jwt(jwt_token) if jwt_token else client
    t_client = t_client or client
    s_client = s_client or client

    print("[Note] Running transcript and slide jobs in parallel...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        fut_transcript = executor.submit(
            _run_transcript_job,
            client=t_client,
            username=username,
            course_id=course_id,
            sub_id=sub_id,
            lecture_url=args.lecture_url,
            output_dir=args.output_dir,
            tag="Transcript",
        )
        fut_slide = None
        if not args.no_slide:
            fut_slide = executor.submit(
                _run_slide_job,
                client=s_client,
                username=username,
                course_id=course_id,
                sub_id=sub_id,
                lecture_url=args.lecture_url,
                output_dir=args.slide_output_dir,
                per_page=args.per_page,
                max_pages=args.max_pages,
                max_items=args.max_items,
                concurrency=args.concurrency,
                retries=args.retries,
                timeout=args.timeout,
                dedupe=not args.no_dedupe,
                dedupe_threshold=args.dedupe_threshold,
                tag="Slide",
            )

        transcript_code = int(fut_transcript.result())
        slide_code = int(fut_slide.result()) if fut_slide is not None else 0

    if transcript_code != 0:
        return transcript_code
    if slide_code != 0:
        return slide_code
    return 0


def cmd_subtitle(args: argparse.Namespace) -> int:
    try:
        if args.srt:
            srt_path = Path(args.srt).expanduser().resolve()
            if not srt_path.is_file():
                _print_err(f"SRT file not found: {srt_path}")
                return 2
        else:
            direct_media_url = _direct_media_url_from_lecture_url(args.lecture_url)
            if direct_media_url:
                srt_path = _run_direct_transcript_job(
                    media_url=direct_media_url,
                    output_dir=args.output_dir,
                    proofread_mode=args.proofread_mode,
                    proofread_model=args.proofread_model,
                    tag="Transcript",
                )
            else:
                try:
                    client, username = _ensure_authenticated_client(force_login=args.force_login)
                except Exception as e:
                    _print_err(str(e))
                    return 1
                resolved = _resolve_course_sub(
                    client,
                    lecture_url=args.lecture_url,
                    course_id=args.course_id,
                    sub_id=args.sub_id,
                    lecture_limit=args.lecture_limit,
                    tag="Subtitle",
                )
                if not resolved:
                    return 2
                course_id, sub_id = resolved
                base_name = _replay_output_base_name(client=client, course_id=course_id, sub_id=sub_id)
                transcript_code = _run_transcript_job(
                    client=client,
                    username=username,
                    course_id=course_id,
                    sub_id=sub_id,
                    lecture_url=args.lecture_url,
                    output_dir=args.output_dir,
                    base_name=base_name,
                    proofread_mode=args.proofread_mode,
                    proofread_model=args.proofread_model,
                    tag="Transcript",
                )
                if transcript_code != 0:
                    return transcript_code
                srt_path = _output_dir(args.output_dir) / f"{base_name}.srt"

        translated_path, bilingual_path = _translate_srt_file(
            srt_path=srt_path,
            target_language=args.target,
            model=args.model,
            batch_size=args.batch_size,
            timeout=args.timeout,
            bilingual=not args.no_bilingual,
            output_dir=args.subtitle_output_dir,
        )
    except Exception as e:
        _print_err(f"Subtitle generation failed: {type(e).__name__}: {e}")
        return 1

    print("[Subtitle] Done. Files written:")
    print(f"  - {translated_path}")
    if bilingual_path:
        print(f"  - {bilingual_path}")
    return 0


def cmd_free_subtitle(args: argparse.Namespace) -> int:
    try:
        if args.srt:
            srt_path = Path(args.srt).expanduser().resolve()
            if not srt_path.is_file():
                _print_err(f"SRT file not found: {srt_path}")
                return 2
        else:
            direct_media_url = _direct_media_url_from_lecture_url(args.lecture_url)
            if direct_media_url:
                srt_path = _run_direct_transcript_job(
                    media_url=direct_media_url,
                    output_dir=args.output_dir,
                    proofread_mode=args.proofread_mode,
                    proofread_model=args.proofread_model,
                    tag="Transcript",
                )
            else:
                try:
                    client, username = _ensure_authenticated_client(force_login=args.force_login)
                except Exception as e:
                    _print_err(str(e))
                    return 1
                resolved = _resolve_course_sub(
                    client,
                    lecture_url=args.lecture_url,
                    course_id=args.course_id,
                    sub_id=args.sub_id,
                    lecture_limit=args.lecture_limit,
                    tag="FreeTranslate",
                )
                if not resolved:
                    return 2
                course_id, sub_id = resolved
                base_name = _replay_output_base_name(client=client, course_id=course_id, sub_id=sub_id)
                transcript_code = _run_transcript_job(
                    client=client,
                    username=username,
                    course_id=course_id,
                    sub_id=sub_id,
                    lecture_url=args.lecture_url,
                    output_dir=args.output_dir,
                    base_name=base_name,
                    proofread_mode=args.proofread_mode,
                    proofread_model=args.proofread_model,
                    tag="Transcript",
                )
                if transcript_code != 0:
                    return transcript_code
                srt_path = _output_dir(args.output_dir) / f"{base_name}.srt"

        translated_path, bilingual_path = _translate_srt_file_free(
            srt_path=srt_path,
            target_language=args.target,
            timeout=args.timeout,
            retries=args.retries,
            delay=args.delay,
            batch_size=args.batch_size,
            bilingual=not args.no_bilingual,
            output_dir=args.subtitle_output_dir,
        )
    except Exception as e:
        _print_err(f"Free subtitle translation failed: {type(e).__name__}: {e}")
        return 1

    print("[FreeTranslate] Done. Files written:")
    print(f"  - {translated_path}")
    if bilingual_path:
        print(f"  - {bilingual_path}")
    return 0


def cmd_download_video(args: argparse.Namespace) -> int:
    direct_media_url = _direct_media_url_from_lecture_url(args.lecture_url)
    if direct_media_url:
        try:
            _run_direct_video_download_job(
                media_url=direct_media_url,
                output_dir=args.output_dir,
                timeout=args.timeout,
                tag="VideoDownload",
            )
            return 0
        except Exception as e:
            _print_err(f"Video download failed: {type(e).__name__}: {e}")
            return 1

    try:
        client, username = _ensure_authenticated_client(force_login=args.force_login)
    except Exception as e:
        _print_err(f"Login failed: {type(e).__name__}: {e}")
        return 1

    resolved = _resolve_course_sub(
        client,
        lecture_url=args.lecture_url,
        course_id=args.course_id,
        sub_id=args.sub_id,
        lecture_limit=args.lecture_limit,
        tag="VideoDownload",
    )
    if not resolved:
        return 2
    course_id, sub_id = resolved
    base_name = _replay_output_base_name(client=client, course_id=course_id, sub_id=sub_id)
    return _run_video_download_job(
        client=client,
        username=username,
        course_id=course_id,
        sub_id=sub_id,
        lecture_url=args.lecture_url,
        output_dir=args.output_dir,
        timeout=args.timeout,
        base_name=base_name,
    )


def cmd_search_replay_range(args: argparse.Namespace) -> int:
    try:
        client, username = _ensure_authenticated_client(force_login=args.force_login)
    except Exception as e:
        _print_err(f"Login failed: {type(e).__name__}: {e}")
        return 1

    try:
        start_date = _normalize_date_text(args.start_date)
        end_date = _normalize_date_text(args.end_date)
        weekday = _parse_weekday_filter(args.weekday)
    except Exception as e:
        _print_err(str(e))
        return 2

    print(f"[SearchReplay] Logged in as: {username or '(unknown)'}")
    print(
        "[SearchReplay] Query: "
        f"teacher={args.teacher_keyword or '*'} "
        f"title={args.course_keyword or '*'} "
        f"start={start_date} end={end_date} "
        f"weekday={weekday or '*'}"
    )

    search_func = _search_owned_replay_range if args.owned_only else _search_replay_range
    if args.owned_only:
        print("[SearchReplay] Scope: only courses accessible to the current account")
        hits, failures = search_func(
            client,
            teacher_keyword=args.teacher_keyword,
            title_keyword=args.course_keyword,
            start_date=start_date,
            end_date=end_date,
            weekday=weekday,
            replay_only=not args.include_non_replay,
            max_results=args.max_results,
        )
    else:
        hits, failures = search_func(
            client,
            teacher_keyword=args.teacher_keyword,
            title_keyword=args.course_keyword,
            start_date=start_date,
            end_date=end_date,
            weekday=weekday,
            quantum_id=args.quantum_id,
            replay_only=not args.include_non_replay,
            max_results=args.max_results,
        )

    out_dir = _output_dir(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        Path(args.output_json).expanduser().resolve()
        if args.output_json
        else (
            out_dir
            / f"{_search_slug(teacher_keyword=args.teacher_keyword, title_keyword=args.course_keyword, start_date=start_date, end_date=end_date, weekday=weekday)}_replays.json"
        )
    )
    output_path.write_text(json.dumps(hits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[SearchReplay] Hits: {len(hits)}")
    for index, item in enumerate(hits[: max(1, int(args.show_limit))], start=1):
        print(
            f"  {index}. {item.get('date', '')} | {item.get('title', '')} | "
            f"{item.get('teacher', '')} | course_id={item.get('course_id', '')} "
            f"sub_id={item.get('sub_id', '')} | {item.get('status_label', '')}"
        )
    if len(hits) > max(1, int(args.show_limit)):
        print(f"  ... {len(hits) - int(args.show_limit)} more")

    if failures:
        failure_path = output_path.with_name(output_path.stem + "_failures.json")
        failure_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[SearchReplay] Failures: {len(failures)}")
        print(f"[SearchReplay] Failure log: {failure_path}")

    print(f"[SearchReplay] Output: {output_path}")
    return 0 if hits or not failures else 1


def cmd_batch_download_replays(args: argparse.Namespace) -> int:
    try:
        client, username = _ensure_authenticated_client(force_login=args.force_login)
    except Exception as e:
        _print_err(f"Login failed: {type(e).__name__}: {e}")
        return 1

    out_dir = _output_dir(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    weekday = None
    search_slug = ""
    failures: list[dict[str, str]] = []
    if args.input_json:
        input_path = Path(args.input_json).expanduser().resolve()
        try:
            items = _load_replay_items_json(input_path)
        except Exception as e:
            _print_err(f"Failed to read input JSON: {type(e).__name__}: {e}")
            return 2
        search_slug = _safe_filename_part(input_path.stem)
        print(f"[BatchReplay] Loaded {len(items)} item(s) from {input_path}")
    else:
        try:
            start_date = _normalize_date_text(args.start_date)
            end_date = _normalize_date_text(args.end_date)
            weekday = _parse_weekday_filter(args.weekday)
        except Exception as e:
            _print_err(str(e))
            return 2

        print(f"[BatchReplay] Logged in as: {username or '(unknown)'}")
        print(
            "[BatchReplay] Query: "
            f"teacher={args.teacher_keyword or '*'} "
            f"title={args.course_keyword or '*'} "
            f"start={start_date} end={end_date} "
            f"weekday={weekday or '*'} "
            f"target={args.target or 'zh'}"
        )
        if args.owned_only:
            print("[BatchReplay] Scope: only courses accessible to the current account")
            items, failures = _search_owned_replay_range(
                client,
                teacher_keyword=args.teacher_keyword,
                title_keyword=args.course_keyword,
                start_date=start_date,
                end_date=end_date,
                weekday=weekday,
                replay_only=not args.include_non_replay,
                max_results=args.max_results,
            )
        else:
            items, failures = _search_replay_range(
                client,
                teacher_keyword=args.teacher_keyword,
                title_keyword=args.course_keyword,
                start_date=start_date,
                end_date=end_date,
                weekday=weekday,
                quantum_id=args.quantum_id,
                replay_only=not args.include_non_replay,
                max_results=args.max_results,
            )
        search_slug = _search_slug(
            teacher_keyword=args.teacher_keyword,
            title_keyword=args.course_keyword,
            start_date=start_date,
            end_date=end_date,
            weekday=weekday,
        )
        hits_path = out_dir / f"{search_slug}_replays.json"
        hits_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[BatchReplay] Search hits saved: {hits_path}")
        if failures:
            failure_path = out_dir / f"{search_slug}_replays_failures.json"
            failure_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"[BatchReplay] Search failures saved: {failure_path}")

    if args.max_results and len(items) > args.max_results:
        items = items[: args.max_results]

    if not items:
        print("[BatchReplay] No matching replay items found.")
        return 0 if not failures else 1

    manifest: list[dict[str, Any]] = []
    total = len(items)
    target = args.target or "zh"
    for index, item in enumerate(items, start=1):
        course_id = str(item.get("course_id") or "").strip()
        sub_id = str(item.get("sub_id") or "").strip()
        title = str(item.get("title") or "").strip()
        teacher = str(item.get("teacher") or item.get("lecturer_name") or "").strip()
        date_text = str(item.get("date") or "").strip()
        print(f"[BatchReplay] Progress: {index}/{total}")
        print(
            f"[BatchReplay] {date_text} | {title} | {teacher} | "
            f"course_id={course_id} sub_id={sub_id}"
        )

        result: dict[str, Any] = {
            "index": index,
            "date": date_text,
            "title": title,
            "teacher": teacher,
            "course_id": course_id,
            "sub_id": sub_id,
            "status_label": item.get("status_label", ""),
            "target": target,
            "ok": False,
            "started_at": _now_iso(),
        }
        if not course_id or not sub_id:
            result["error"] = "missing course_id or sub_id"
            manifest.append(result)
            print("[BatchReplay] FAIL missing course_id or sub_id")
            continue

        try:
            base_name = _replay_output_base_name(
                client=client,
                course_id=course_id,
                sub_id=sub_id,
                title_hint=title,
                date_hint=date_text,
            )
            job_result = _run_replay_with_subtitles_job(
                client=client,
                username=username,
                course_id=course_id,
                sub_id=sub_id,
                lecture_url="",
                output_dir=args.output_dir,
                video_timeout=args.video_timeout,
                target=target,
                translation_mode=args.translation_mode,
                model=args.model,
                batch_size=args.batch_size,
                api_timeout=args.api_timeout,
                free_timeout=args.free_timeout,
                free_retries=args.free_retries,
                free_delay=args.free_delay,
                free_batch_size=args.free_batch_size,
                sync_subtitle=not args.no_sync,
                sync_max_shift_ms=args.sync_max_shift_ms,
                sync_lead_ms=args.sync_lead_ms,
                redownload=args.redownload,
                retranscribe=args.retranscribe,
                retranslate=args.retranslate,
                proofread_mode=args.proofread_mode,
                proofread_model=args.proofread_model,
                base_name=base_name,
            )
            result.update(job_result)
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"

        manifest.append(result)
        if result.get("ok"):
            print(
                f"[BatchReplay] OK video={result.get('video_file', '')} "
                f"srt={result.get('final_srt', '')}"
            )
        else:
            print(f"[BatchReplay] FAIL {result.get('error', 'unknown error')}")

    manifest_path = (
        Path(args.manifest).expanduser().resolve()
        if args.manifest
        else out_dir / f"{search_slug or 'batch_replays'}_batch_manifest.json"
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok_count = sum(1 for item in manifest if item.get("ok"))
    print(f"[BatchReplay] Done: {ok_count}/{len(manifest)} succeeded")
    print(f"[BatchReplay] Manifest: {manifest_path}")
    return 0 if ok_count == len(manifest) else 2


def cmd_subtitle_pack(args: argparse.Namespace) -> int:
    try:
        srt_path = Path(args.srt).expanduser().resolve()
        source_copy, prompt_path = _create_translation_pack(
            srt_path=srt_path,
            target_language=args.target,
            output_dir=args.output_dir,
        )
    except Exception as e:
        _print_err(f"Failed to create translation pack: {type(e).__name__}: {e}")
        return 1

    print("[SubtitlePack] Done. Give these to your AI translator:")
    print(f"  - source_srt: {source_copy}")
    print(f"  - prompt: {prompt_path}")
    print("[SubtitlePack] After AI returns the translated SRT, run subtitle-import to normalize it.")
    return 0


def cmd_subtitle_import(args: argparse.Namespace) -> int:
    try:
        normalized_path, bilingual_path, warnings = _normalize_manual_translation(
            source_srt_path=Path(args.source_srt).expanduser().resolve(),
            translated_srt_path=Path(args.translated_srt).expanduser().resolve(),
            target_language=args.target,
            output_path=args.output,
            bilingual=not args.no_bilingual,
        )
    except Exception as e:
        _print_err(f"Failed to import translated SRT: {type(e).__name__}: {e}")
        return 1

    print("[SubtitleImport] Done. Files written:")
    print(f"  - {normalized_path}")
    if bilingual_path:
        print(f"  - {bilingual_path}")
    if warnings:
        print(f"[SubtitleImport] Warnings: {len(warnings)}")
        for warning in warnings[:10]:
            print(f"  - {warning}")
        if len(warnings) > 10:
            print(f"  - ... {len(warnings) - 10} more")
    return 0


def cmd_player_pack(args: argparse.Namespace) -> int:
    try:
        video_path = Path(args.video_file).expanduser().resolve()
        srt_path = Path(args.srt).expanduser().resolve()
        copy_video = bool(args.output_dir) and not args.no_copy_video
        video_out, srt_out, readme = _prepare_player_files(
            video_path=video_path,
            srt_path=srt_path,
            output_dir=args.output_dir,
            copy_video=copy_video,
        )
    except Exception as e:
        _print_err(f"Player subtitle pack failed: {type(e).__name__}: {e}")
        return 1

    print("[PlayerPack] Done. Keep these files together:")
    print(f"  - video: {video_out}")
    print(f"  - subtitle: {srt_out}")
    print(f"  - readme: {readme}")
    print("[PlayerPack] Progress: 100/100")
    return 0


def cmd_sync_subtitle(args: argparse.Namespace) -> int:
    try:
        out_path, report = _apply_subtitle_timing_sync(
            video_path=Path(args.video_file).expanduser().resolve(),
            srt_path=Path(args.srt).expanduser().resolve(),
            output_path=Path(args.output).expanduser().resolve() if args.output else None,
            max_local_shift_ms=args.max_shift_ms,
            lead_ms=args.lead_ms,
            force=args.force,
        )
    except Exception as e:
        _print_err(f"Subtitle sync failed: {type(e).__name__}: {e}")
        return 1

    print("[SubtitleSync] Done.")
    print(f"  - output: {out_path}")
    print(f"  - cues: {report['cues']}")
    print(f"  - adjusted: {report['changed']}")
    print(f"  - speech_regions: {report['speech_regions']}")
    print(f"  - global_shift_ms: {report['global_shift_ms']}")
    print(f"  - confidence: {report['global_confidence']}")
    return 0


def cmd_auto_potplayer(args: argparse.Namespace) -> int:
    direct_media_url = _direct_media_url_from_lecture_url(args.lecture_url)
    if direct_media_url:
        try:
            out_dir = _output_dir(args.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            base_name = _direct_output_base_name(args.output_dir)
            video_path = out_dir / f"{base_name}.mp4"
            raw_source_srt = out_dir / f"{base_name}.srt"
            source_backup_srt = out_dir / f"{base_name}.zh.srt"
            source_srt = raw_source_srt

            print("[Auto] Step 1/4: download course video")
            print("[Auto] Progress: 1/4")
            video_path = _run_direct_video_download_job(
                media_url=direct_media_url,
                output_dir=args.output_dir,
                timeout=args.video_timeout,
                base_name=base_name,
                tag="VideoDownload",
            )

            print("[Auto] Step 2/4: generate Chinese subtitles")
            print("[Auto] Progress: 2/4")
            if _file_ready(source_backup_srt, min_bytes=100):
                shutil.copy2(source_backup_srt, source_srt)
                print(f"[Auto] Reusing existing Chinese source subtitles: {source_backup_srt}")
            else:
                transcript_code = _run_transcript_local_video_job(
                    username="",
                    course_id=base_name,
                    sub_id="direct",
                    lecture_url=args.lecture_url,
                    video_path=video_path,
                    output_dir=args.output_dir,
                    base_name=base_name,
                    proofread_mode=args.proofread_mode,
                    proofread_model=args.proofread_model,
                    tag="Transcript",
                )
                if transcript_code != 0:
                    return transcript_code
                if _file_ready(raw_source_srt, min_bytes=100):
                    shutil.copy2(raw_source_srt, source_backup_srt)
                    print(f"[Auto] Saved Chinese source subtitles: {source_backup_srt}")

            if not args.no_sync and _file_ready(source_srt, min_bytes=100) and _file_ready(video_path, min_bytes=1000):
                print("[Auto] Step 2.5/4: align subtitle timing to audio")
                try:
                    synced_path, sync_report = _apply_subtitle_timing_sync(
                        video_path=video_path,
                        srt_path=source_srt,
                        output_path=source_srt,
                        max_local_shift_ms=args.sync_max_shift_ms,
                        lead_ms=args.sync_lead_ms,
                    )
                    print(
                        "[SubtitleSync] "
                        f"adjusted={sync_report['changed']}/{sync_report['cues']} "
                        f"global_shift_ms={sync_report['global_shift_ms']} "
                        f"confidence={sync_report['global_confidence']}"
                    )
                    source_srt = synced_path
                    shutil.copy2(source_srt, source_backup_srt)
                except Exception as e:
                    print(f"[SubtitleSync] Warning: sync skipped: {type(e).__name__}: {e}")

            try:
                txt_path = out_dir / f"{base_name}.txt"
                used_proofread = _apply_subtitle_proofread(
                    srt_path=source_srt,
                    txt_path=txt_path if _file_ready(txt_path, min_bytes=1) else None,
                    mode=args.proofread_mode,
                    model=args.proofread_model,
                    tag="Proofread",
                )
                print(f"[Auto] Subtitle proofread mode: {used_proofread}")
                if _file_ready(source_srt, min_bytes=100):
                    shutil.copy2(source_srt, source_backup_srt)
            except Exception as e:
                print(f"[Proofread] Warning: proofread skipped: {type(e).__name__}: {e}")

            target = (args.target or "ru").strip()
            if target.lower() in {"zh", "cn", "chinese", "中文", "简体中文"}:
                final_srt = source_srt
                print("[Auto] Step 3/4: keep Chinese subtitles")
            else:
                print("[Auto] Step 3/4: translate subtitles")
                lang_suffix = _language_suffix(target)
                expected_translation = out_dir / f"{source_srt.stem}.{lang_suffix}.srt"
                if _file_ready(expected_translation, min_bytes=100):
                    normalized_path, _bilingual, warnings = _normalize_manual_translation(
                        source_srt_path=source_srt,
                        translated_srt_path=expected_translation,
                        target_language=target,
                        output_path=str(expected_translation),
                        bilingual=False,
                    )
                    translated_path = normalized_path
                    print(f"[Auto] Reusing existing translated subtitles: {translated_path}")
                    if warnings:
                        print(f"[Auto] Normalized reused subtitles with {len(warnings)} timing warning(s).")
                elif args.translation_mode == "free":
                    translated_path, _ = _translate_srt_file_free(
                        srt_path=source_srt,
                        target_language=target,
                        timeout=args.free_timeout,
                        retries=args.free_retries,
                        delay=args.free_delay,
                        batch_size=args.free_batch_size,
                        bilingual=False,
                        output_dir=args.output_dir,
                    )
                else:
                    translated_path, _ = _translate_srt_file(
                        srt_path=source_srt,
                        target_language=target,
                        model=args.model,
                        batch_size=args.batch_size,
                        timeout=args.api_timeout,
                        bilingual=False,
                        output_dir=args.output_dir,
                    )
                final_srt = translated_path
            print("[Auto] Progress: 3/4")

            print("[Auto] Step 4/4: prepare PotPlayer files")
            video_out, srt_out, readme = _prepare_player_files(
                video_path=video_path,
                srt_path=final_srt,
                output_dir="",
                copy_video=False,
            )
            print("[Auto] Done. PotPlayer files:")
            print(f"  - video: {video_out}")
            print(f"  - subtitle: {srt_out}")
            print(f"  - readme: {readme}")
            print("[Auto] Progress: 4/4")
            return 0
        except Exception as e:
            _print_err(f"Auto processing failed: {type(e).__name__}: {e}")
            return 1

    try:
        client, username = _ensure_authenticated_client(force_login=args.force_login)
    except Exception as e:
        _print_err(f"Login failed: {type(e).__name__}: {e}")
        return 1

    resolved = _resolve_course_sub(
        client,
        lecture_url=args.lecture_url,
        course_id=args.course_id,
        sub_id=args.sub_id,
        lecture_limit=args.lecture_limit,
        tag="Auto",
    )
    if not resolved:
        return 2
    course_id, sub_id = resolved
    base_name = _replay_output_base_name(client=client, course_id=course_id, sub_id=sub_id)
    out_dir = _output_dir(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / f"{base_name}.mp4"
    raw_source_srt = out_dir / f"{base_name}.srt"
    source_backup_srt = out_dir / f"{base_name}.zh.srt"
    source_srt = raw_source_srt

    print("[Auto] Step 1/4: download course video")
    print("[Auto] Progress: 1/4")
    video_code = _run_video_download_job(
        client=client,
        username=username,
        course_id=course_id,
        sub_id=sub_id,
        lecture_url=args.lecture_url,
        output_dir=args.output_dir,
        timeout=args.video_timeout,
        base_name=base_name,
    )
    if video_code != 0:
        return video_code

    print("[Auto] Step 2/4: generate Chinese subtitles")
    print("[Auto] Progress: 2/4")
    if _file_ready(source_backup_srt, min_bytes=100):
        shutil.copy2(source_backup_srt, source_srt)
        print(f"[Auto] Reusing existing Chinese source subtitles: {source_backup_srt}")
    else:
        transcript_code = _run_transcript_local_video_job(
            username=username,
            course_id=course_id,
            sub_id=sub_id,
            lecture_url=args.lecture_url,
            video_path=video_path,
            output_dir=args.output_dir,
            base_name=base_name,
            proofread_mode=args.proofread_mode,
            proofread_model=args.proofread_model,
            tag="Transcript",
        )
        if transcript_code != 0:
            return transcript_code
        if _file_ready(raw_source_srt, min_bytes=100):
            shutil.copy2(raw_source_srt, source_backup_srt)
            print(f"[Auto] Saved Chinese source subtitles: {source_backup_srt}")

    if not args.no_sync and _file_ready(source_srt, min_bytes=100) and _file_ready(video_path, min_bytes=1000):
        print("[Auto] Step 2.5/4: align subtitle timing to audio")
        try:
            synced_path, sync_report = _apply_subtitle_timing_sync(
                video_path=video_path,
                srt_path=source_srt,
                output_path=source_srt,
                max_local_shift_ms=args.sync_max_shift_ms,
                lead_ms=args.sync_lead_ms,
            )
            print(
                "[SubtitleSync] "
                f"adjusted={sync_report['changed']}/{sync_report['cues']} "
                f"global_shift_ms={sync_report['global_shift_ms']} "
                f"confidence={sync_report['global_confidence']}"
            )
            source_srt = synced_path
            shutil.copy2(source_srt, source_backup_srt)
        except Exception as e:
            print(f"[SubtitleSync] Warning: sync skipped: {type(e).__name__}: {e}")

    try:
        used_proofread = _apply_subtitle_proofread(
            srt_path=source_srt,
            txt_path=(out_dir / f"{base_name}.txt") if _file_ready(out_dir / f"{base_name}.txt", min_bytes=1) else None,
            mode=args.proofread_mode,
            model=args.proofread_model,
            tag="Proofread",
        )
        print(f"[Auto] Subtitle proofread mode: {used_proofread}")
        if _file_ready(source_srt, min_bytes=100):
            shutil.copy2(source_srt, source_backup_srt)
    except Exception as e:
        print(f"[Proofread] Warning: proofread skipped: {type(e).__name__}: {e}")

    target = (args.target or "ru").strip()
    if target.lower() in {"zh", "cn", "chinese", "中文", "简体中文"}:
        final_srt = source_srt
        print("[Auto] Step 3/4: keep Chinese subtitles")
    else:
        print("[Auto] Step 3/4: translate subtitles")
        lang_suffix = _language_suffix(target)
        expected_translation = out_dir / f"{source_srt.stem}.{lang_suffix}.srt"
        if _file_ready(expected_translation, min_bytes=100):
            normalized_path, _bilingual, warnings = _normalize_manual_translation(
                source_srt_path=source_srt,
                translated_srt_path=expected_translation,
                target_language=target,
                output_path=str(expected_translation),
                bilingual=False,
            )
            translated_path = normalized_path
            print(f"[Auto] Reusing existing translated subtitles: {translated_path}")
            if warnings:
                print(f"[Auto] Normalized reused subtitles with {len(warnings)} timing warning(s).")
        elif args.translation_mode == "free":
            translated_path, _ = _translate_srt_file_free(
                srt_path=source_srt,
                target_language=target,
                timeout=args.free_timeout,
                retries=args.free_retries,
                delay=args.free_delay,
                batch_size=args.free_batch_size,
                bilingual=False,
                output_dir=args.output_dir,
            )
        else:
            translated_path, _ = _translate_srt_file(
                srt_path=source_srt,
                target_language=target,
                model=args.model,
                batch_size=args.batch_size,
                timeout=args.api_timeout,
                bilingual=False,
                output_dir=args.output_dir,
            )
        final_srt = translated_path
    print("[Auto] Progress: 3/4")

    print("[Auto] Step 4/4: prepare PotPlayer files")
    video_out, srt_out, readme = _prepare_player_files(
        video_path=video_path,
        srt_path=final_srt,
        output_dir="",
        copy_video=False,
    )
    print("[Auto] Done. PotPlayer files:")
    print(f"  - video: {video_out}")
    print(f"  - subtitle: {srt_out}")
    print(f"  - readme: {readme}")
    print("[Auto] Progress: 4/4")
    return 0


def cmd_api_test(args: argparse.Namespace) -> int:
    target = args.target or "ru"
    try:
        result = _translate_batch_openai(
            texts=["你好，这是字幕翻译测试。"],
            target_language=_language_name(target),
            model=args.model,
            timeout=args.timeout,
        )
    except Exception as e:
        _print_err(f"API test failed: {type(e).__name__}: {e}")
        return 1

    print("[ApiTest] OK")
    print(f"  - model: {args.model}")
    print(f"  - base_url: {os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')}")
    print(f"  - api_style: {os.environ.get('OPENAI_API_STYLE', 'chat')}")
    print(f"  - sample: {result[0] if result else ''}")
    return 0


def _check_system_browser() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return False, f"Playwright unavailable: {e}"

    channels = os.environ.get("LOOK_TONGJI_BROWSER_CHANNELS", "msedge,chrome").split(",")
    errors: list[str] = []
    with sync_playwright() as p:
        for channel in [item.strip() for item in channels if item.strip()]:
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                browser.close()
                return True, channel
            except Exception as e:
                errors.append(f"{channel}: {e}")
    return False, " | ".join(errors) or "no browser channel configured"


def cmd_doctor(args: argparse.Namespace) -> int:
    print("[Doctor] Checking environment...")
    ok = True

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        print(f"[Doctor] OK ffmpeg: {ffmpeg}")
    else:
        ok = False
        print("[Doctor] FAIL ffmpeg: not found on PATH")

    browser_ok, browser_msg = _check_system_browser()
    if browser_ok:
        print(f"[Doctor] OK system browser: {browser_msg}")
    else:
        ok = False
        print(f"[Doctor] FAIL system browser: {browser_msg}")

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    api_style = os.environ.get("OPENAI_API_STYLE", "chat").strip()
    print(f"[Doctor] API key: {'set' if api_key else 'not set'}")
    print(f"[Doctor] API base URL: {base_url}")
    print(f"[Doctor] API style: {api_style}")

    if args.login:
        try:
            client, username = _ensure_authenticated_client(force_login=args.force_login)
            alive = client.auth.check_alive()
            print(f"[Doctor] {'OK' if alive else 'FAIL'} Tongji login: {username or '(unknown)'}")
            ok = ok and alive
        except Exception as e:
            ok = False
            print(f"[Doctor] FAIL Tongji login: {type(e).__name__}: {e}")

    return 0 if ok else 1


def cmd_login_test(args: argparse.Namespace) -> int:
    try:
        client, username = _ensure_authenticated_client(force_login=args.force_login)
        alive = client.auth.check_alive()
    except Exception as e:
        _print_err(f"Tongji login test failed: {type(e).__name__}: {e}")
        return 1

    if alive:
        print(f"[LoginTest] OK Tongji login: {username or '(unknown)'}")
        return 0

    _print_err("Tongji login test failed: token was obtained but session check failed")
    return 1


def _add_proofread_args(parser: argparse.ArgumentParser, *, default_mode: str = "off") -> None:
    parser.add_argument(
        "--proofread-mode",
        choices=["off", "local", "ai"],
        default=os.environ.get("LOOK_TONGJI_PROOFREAD_MODE", default_mode),
        help="Subtitle proofread mode after ASR: off, local, or ai",
    )
    parser.add_argument(
        "--proofread-model",
        default=os.environ.get("OPENAI_PROOFREAD_MODEL", os.environ.get("OPENAI_TRANSLATION_MODEL", DEFAULT_TRANSLATION_MODEL)),
        help=f"OpenAI-compatible model for AI proofread (default: {DEFAULT_TRANSLATION_MODEL})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="look_tongji.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser("setup", help="Check deps and write <skill>/.env")
    p_setup.add_argument("--username", default="", help="Tongji username (optional)")
    p_setup.add_argument("--password", default="", help="Tongji password (optional; avoid CLI if possible)")
    p_setup.add_argument("--overwrite", action="store_true", help="Overwrite existing .env")
    p_setup.set_defaults(func=cmd_setup)

    p_list = sub.add_parser("list", help="Login and list recent courses")
    p_list.add_argument("--limit", type=int, default=8, help="Number of courses to show")
    p_list.add_argument(
        "--all",
        dest="all_courses",
        action="store_true",
        help="List all courses (slower but more complete)",
    )
    p_list.add_argument(
        "--query",
        default="",
        help="Filter courses by keyword in title/teacher (case-insensitive)",
    )
    p_list.add_argument("--choose", type=int, default=None, help="Auto-select course number (1-based)")
    p_list.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_list.set_defaults(func=cmd_list)

    p_search_replay = sub.add_parser(
        "search-replay-range",
        aliases=["search-replays", "find-replays"],
        help="Search Today Courses replay items by teacher/title/date range and save the hit list to JSON",
    )
    p_search_replay.add_argument("--teacher-keyword", default="", help="Teacher keyword, such as 陆有军")
    p_search_replay.add_argument("--course-keyword", default="", help="Course title keyword, such as 计算机网络")
    p_search_replay.add_argument("--start-date", required=True, help="Start date, such as 2025-09-01")
    p_search_replay.add_argument("--end-date", required=True, help="End date, such as 2026-01-31")
    p_search_replay.add_argument(
        "--weekday",
        default="",
        help="Optional weekday filter. Use 1-7 or mon/tue/wed/... (1=Monday, 3=Wednesday)",
    )
    p_search_replay.add_argument("--quantum-id", type=int, default=0, help="Today Courses quantum_id parameter (default: 0)")
    p_search_replay.add_argument(
        "--owned-only",
        action="store_true",
        help="Search only within courses accessible to the current account instead of Today Courses",
    )
    p_search_replay.add_argument("--output-dir", default="", help="Output directory (default: ./tongji-output)")
    p_search_replay.add_argument("--output-json", default="", help="Output JSON file path")
    p_search_replay.add_argument("--show-limit", type=int, default=30, help="Show at most N hits in terminal output")
    p_search_replay.add_argument("--max-results", type=int, default=0, help="Stop after N hits (0 means no limit)")
    p_search_replay.add_argument("--include-non-replay", action="store_true", help="Also include non-replay items")
    p_search_replay.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_search_replay.set_defaults(func=cmd_search_replay_range)

    p_batch_replay = sub.add_parser(
        "batch-download-replays",
        aliases=["batch-replays", "batch-download-subtitles"],
        help="Batch download replay videos and generate subtitles from a replay hit list or a teacher/title/date search",
    )
    p_batch_replay.add_argument("--input-json", default="", help="Existing replay hit list JSON from search-replay-range")
    p_batch_replay.add_argument("--teacher-keyword", default="", help="Teacher keyword when searching directly")
    p_batch_replay.add_argument("--course-keyword", default="", help="Course title keyword when searching directly")
    p_batch_replay.add_argument("--start-date", default="", help="Start date when searching directly")
    p_batch_replay.add_argument("--end-date", default="", help="End date when searching directly")
    p_batch_replay.add_argument(
        "--weekday",
        default="",
        help="Optional weekday filter. Use 1-7 or mon/tue/wed/... (1=Monday, 3=Wednesday)",
    )
    p_batch_replay.add_argument("--quantum-id", type=int, default=0, help="Today Courses quantum_id parameter (default: 0)")
    p_batch_replay.add_argument(
        "--owned-only",
        action="store_true",
        help="Search only within courses accessible to the current account instead of Today Courses",
    )
    p_batch_replay.add_argument("--output-dir", default="", help="Output directory (default: ./tongji-output)")
    p_batch_replay.add_argument("--manifest", default="", help="Manifest JSON output path")
    p_batch_replay.add_argument("--target", default="zh", help="Subtitle language to keep or generate (default: zh)")
    p_batch_replay.add_argument(
        "--model",
        default=os.environ.get("OPENAI_TRANSLATION_MODEL", DEFAULT_TRANSLATION_MODEL),
        help=f"OpenAI-compatible model for translation (default: {DEFAULT_TRANSLATION_MODEL})",
    )
    p_batch_replay.add_argument("--batch-size", type=int, default=40, help="Subtitle cues per translation request")
    p_batch_replay.add_argument("--api-timeout", type=int, default=120, help="OpenAI request timeout seconds")
    p_batch_replay.add_argument(
        "--translation-mode",
        choices=["api", "free"],
        default="api",
        help="Translation mode when target is not Chinese: api or free",
    )
    p_batch_replay.add_argument("--free-timeout", type=int, default=25, help="Free translation request timeout seconds")
    p_batch_replay.add_argument("--free-retries", type=int, default=3, help="Retry attempts per free translation request")
    p_batch_replay.add_argument("--free-delay", type=float, default=0.05, help="Delay seconds between free translation requests")
    p_batch_replay.add_argument("--free-batch-size", type=int, default=25, help="Subtitle cues per free translation request")
    p_batch_replay.add_argument("--video-timeout", type=int, default=7200, help="ffmpeg download timeout seconds")
    p_batch_replay.add_argument("--no-sync", action="store_true", help="Skip audio-based subtitle timing alignment after fresh ASR")
    p_batch_replay.add_argument("--sync-max-shift-ms", type=int, default=1400, help="Maximum subtitle sync adjustment per cue")
    p_batch_replay.add_argument("--sync-lead-ms", type=int, default=80, help="Lead subtitle this many ms before detected speech")
    p_batch_replay.add_argument("--redownload", action="store_true", help="Force mp4 re-download")
    p_batch_replay.add_argument("--retranscribe", action="store_true", help="Force Chinese subtitle regeneration")
    p_batch_replay.add_argument("--retranslate", action="store_true", help="Force translated subtitle regeneration")
    _add_proofread_args(p_batch_replay, default_mode="local")
    p_batch_replay.add_argument("--max-results", type=int, default=0, help="Download at most N hits (0 means no limit)")
    p_batch_replay.add_argument("--include-non-replay", action="store_true", help="Also include non-replay items when searching directly")
    p_batch_replay.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_batch_replay.set_defaults(func=cmd_batch_download_replays)

    p_transcript = sub.add_parser("transcribe", aliases=["transcript", "trans"], help="Transcribe one lecture to SRT/TXT")
    p_transcript.add_argument("--lecture-url", default="", help="Tongji replay page URL or an already-obtained direct media URL")
    p_transcript.add_argument("--course-id", default="", help="Course ID")
    p_transcript.add_argument("--sub-id", default="", help="Lecture sub_id")
    p_transcript.add_argument("--lecture-limit", type=int, default=20, help="Max lectures shown for interactive choice")
    p_transcript.add_argument("--output-dir", default="", help="Output directory (default: ./tongji-output)")
    _add_proofread_args(p_transcript, default_mode="local")
    p_transcript.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_transcript.set_defaults(func=cmd_transcript)

    p_video = sub.add_parser("download-video", aliases=["video", "dl-video"], help="Download one course replay video")
    p_video.add_argument("--lecture-url", default="", help="Tongji replay page URL or an already-obtained direct media URL")
    p_video.add_argument("--course-id", default="", help="Course ID")
    p_video.add_argument("--sub-id", default="", help="Lecture sub_id")
    p_video.add_argument("--lecture-limit", type=int, default=20, help="Max lectures shown for interactive choice")
    p_video.add_argument("--output-dir", default="", help="Output directory (default: ./tongji-output)")
    p_video.add_argument("--timeout", type=int, default=7200, help="ffmpeg download timeout seconds")
    p_video.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_video.set_defaults(func=cmd_download_video)

    p_slide = sub.add_parser("slide", help="Download lecture slide snapshots for one lecture")
    p_slide.add_argument("--lecture-url", default="", help="Tongji replay page URL or an already-obtained direct media URL")
    p_slide.add_argument("--course-id", default="", help="Course ID")
    p_slide.add_argument("--sub-id", default="", help="Lecture sub_id")
    p_slide.add_argument("--lecture-limit", type=int, default=20, help="Max lectures shown for interactive choice")
    p_slide.add_argument(
        "--output-dir",
        default="",
        help="Output directory (default: ./tongji-output/slide_<course_id>_<sub_id>)",
    )
    p_slide.add_argument("--per-page", type=int, default=100, help="search-ppt per_page parameter")
    p_slide.add_argument("--max-pages", type=int, default=20, help="Max pages to request from search-ppt")
    p_slide.add_argument("--max-items", type=int, default=0, help="Download at most N snapshots (0 means all)")
    p_slide.add_argument("--concurrency", type=int, default=4, help="Concurrent download workers (1-16)")
    p_slide.add_argument("--retries", type=int, default=3, help="Retry attempts per image")
    p_slide.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds per image request")
    p_slide.add_argument("--no-dedupe", action="store_true", help="Keep all raw snapshots and skip dedupe")
    p_slide.add_argument("--dedupe-threshold", type=int, default=10, help="Perceptual hash threshold for consecutive duplicate slides")
    p_slide.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_slide.set_defaults(func=cmd_slide)

    p_slide_dedupe = sub.add_parser(
        "slide-dedupe",
        aliases=["dedupe-slide", "dedupe-slides"],
        help="Dedupe an existing slide snapshot directory and keep the clearest file per consecutive slide group",
    )
    p_slide_dedupe.add_argument("--input-dir", required=True, help="Existing slide snapshot directory")
    p_slide_dedupe.add_argument(
        "--dedupe-threshold",
        type=int,
        default=10,
        help="Perceptual hash threshold for consecutive duplicate slides",
    )
    p_slide_dedupe.set_defaults(func=cmd_slide_dedupe)

    p_note = sub.add_parser("note", help="Run transcript + slide in parallel for one lecture")
    p_note.add_argument("--lecture-url", default="", help="Tongji replay page URL or an already-obtained direct media URL")
    p_note.add_argument("--course-id", default="", help="Course ID")
    p_note.add_argument("--sub-id", default="", help="Lecture sub_id")
    p_note.add_argument("--lecture-limit", type=int, default=20, help="Max lectures shown for interactive choice")
    p_note.add_argument("--output-dir", default="", help="Transcript output directory (default: ./tongji-output)")
    p_note.add_argument(
        "--slide-output-dir",
        default="",
        help="Slide output directory (default: ./tongji-output/slide_<course_id>_<sub_id>)",
    )
    p_note.add_argument("--no-slide", action="store_true", help="Skip slide download and run transcript only")
    p_note.add_argument("--per-page", type=int, default=100, help="search-ppt per_page parameter")
    p_note.add_argument("--max-pages", type=int, default=20, help="Max pages to request from search-ppt")
    p_note.add_argument("--max-items", type=int, default=0, help="Download at most N slide snapshots (0 means all)")
    p_note.add_argument("--concurrency", type=int, default=4, help="Concurrent slide download workers (1-16)")
    p_note.add_argument("--retries", type=int, default=3, help="Retry attempts per slide image")
    p_note.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds per slide image request")
    p_note.add_argument("--no-dedupe", action="store_true", help="Keep all raw slide snapshots and skip dedupe")
    p_note.add_argument("--dedupe-threshold", type=int, default=10, help="Perceptual hash threshold for consecutive duplicate slides")
    p_note.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_note.set_defaults(func=cmd_note)

    p_subtitle = sub.add_parser(
        "subtitle",
        aliases=["translate-srt", "ru-subtitle"],
        help="Generate translated subtitles from a lecture or an existing SRT",
    )
    p_subtitle.add_argument("--srt", default="", help="Existing SRT file to translate")
    p_subtitle.add_argument("--lecture-url", default="", help="Tongji replay page URL or an already-obtained direct media URL")
    p_subtitle.add_argument("--course-id", default="", help="Course ID")
    p_subtitle.add_argument("--sub-id", default="", help="Lecture sub_id")
    p_subtitle.add_argument("--lecture-limit", type=int, default=20, help="Max lectures shown for interactive choice")
    p_subtitle.add_argument("--output-dir", default="", help="Transcript output directory (default: ./tongji-output)")
    p_subtitle.add_argument(
        "--subtitle-output-dir",
        default="",
        help="Translated subtitle output directory (default: same folder as source SRT)",
    )
    p_subtitle.add_argument("--target", default="ru", help="Target subtitle language (default: ru)")
    p_subtitle.add_argument(
        "--model",
        default=os.environ.get("OPENAI_TRANSLATION_MODEL", DEFAULT_TRANSLATION_MODEL),
        help=f"OpenAI model for translation (default: {DEFAULT_TRANSLATION_MODEL})",
    )
    p_subtitle.add_argument("--batch-size", type=int, default=40, help="Subtitle cues per translation request")
    p_subtitle.add_argument("--timeout", type=int, default=120, help="OpenAI request timeout seconds")
    p_subtitle.add_argument("--no-bilingual", action="store_true", help="Only write target-language SRT")
    _add_proofread_args(p_subtitle, default_mode="local")
    p_subtitle.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_subtitle.set_defaults(func=cmd_subtitle)

    p_free = sub.add_parser(
        "free-subtitle",
        aliases=["free-translate-srt"],
        help="Translate subtitles without API key using a free online translator with local cache",
    )
    p_free.add_argument("--srt", default="", help="Existing SRT file to translate")
    p_free.add_argument("--lecture-url", default="", help="Tongji replay page URL or an already-obtained direct media URL")
    p_free.add_argument("--course-id", default="", help="Course ID")
    p_free.add_argument("--sub-id", default="", help="Lecture sub_id")
    p_free.add_argument("--lecture-limit", type=int, default=20, help="Max lectures shown for interactive choice")
    p_free.add_argument("--output-dir", default="", help="Transcript output directory (default: ./tongji-output)")
    p_free.add_argument(
        "--subtitle-output-dir",
        default="",
        help="Translated subtitle output directory (default: same folder as source SRT)",
    )
    p_free.add_argument("--target", default="ru", help="Target subtitle language (default: ru)")
    p_free.add_argument("--timeout", type=int, default=25, help="Free translation request timeout seconds")
    p_free.add_argument("--retries", type=int, default=3, help="Retry attempts per free translation request")
    p_free.add_argument("--delay", type=float, default=0.05, help="Delay seconds between free translation requests")
    p_free.add_argument("--batch-size", type=int, default=25, help="Subtitle cues per free translation request")
    p_free.add_argument("--no-bilingual", action="store_true", help="Only write target-language SRT")
    _add_proofread_args(p_free, default_mode="local")
    p_free.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_free.set_defaults(func=cmd_free_subtitle)

    p_pack = sub.add_parser(
        "subtitle-pack",
        aliases=["manual-subtitle", "export-translation-pack"],
        help="Create a prompt + source SRT pack for manual AI translation",
    )
    p_pack.add_argument("--srt", required=True, help="Source SRT file to translate manually")
    p_pack.add_argument("--target", default="ru", help="Target subtitle language (default: ru)")
    p_pack.add_argument("--output-dir", default="", help="Output directory (default: same folder as source SRT)")
    p_pack.set_defaults(func=cmd_subtitle_pack)

    p_import = sub.add_parser(
        "subtitle-import",
        aliases=["normalize-subtitle", "check-subtitle"],
        help="Normalize an AI-translated SRT against the original source SRT",
    )
    p_import.add_argument("--source-srt", required=True, help="Original source SRT")
    p_import.add_argument("--translated-srt", required=True, help="AI-translated SRT")
    p_import.add_argument("--target", default="ru", help="Target subtitle language (default: ru)")
    p_import.add_argument("--output", default="", help="Output SRT path")
    p_import.add_argument("--no-bilingual", action="store_true", help="Only write target-language SRT")
    p_import.set_defaults(func=cmd_subtitle_import)

    p_player = sub.add_parser(
        "player-pack",
        aliases=["subtitle-player-pack", "prepare-player-files"],
        help="Prepare same-name video + SRT files for normal video players",
    )
    p_player.add_argument("--video-file", required=True, help="Local video file, such as .mp4")
    p_player.add_argument("--srt", required=True, help="Final SRT subtitle file")
    p_player.add_argument(
        "--output-dir",
        default="",
        help="Output folder. If set, the video is copied there and the SRT is renamed beside it.",
    )
    p_player.add_argument(
        "--no-copy-video",
        action="store_true",
        help="Do not copy the video; only write the same-name SRT beside the original video.",
    )
    p_player.set_defaults(func=cmd_player_pack)

    p_sync = sub.add_parser(
        "sync-subtitle",
        aliases=["sync-srt", "align-subtitle"],
        help="Lightly align SRT timing to video audio using speech activity detection",
    )
    p_sync.add_argument("--video-file", required=True, help="Local video file, such as .mp4")
    p_sync.add_argument("--srt", required=True, help="SRT subtitle file to align")
    p_sync.add_argument("--output", default="", help="Output SRT path. Empty means overwrite input with backup.")
    p_sync.add_argument("--max-shift-ms", type=int, default=1400, help="Maximum local timing shift in milliseconds")
    p_sync.add_argument("--lead-ms", type=int, default=80, help="Subtitle lead before detected speech in milliseconds")
    p_sync.add_argument("--force", action="store_true", help="Apply detected global shift even with low confidence")
    p_sync.set_defaults(func=cmd_sync_subtitle)

    p_auto = sub.add_parser(
        "auto-potplayer",
        aliases=["one-click", "auto"],
        help="Download video, generate subtitles, translate if needed, and prepare PotPlayer files",
    )
    p_auto.add_argument("--lecture-url", default="", help="Tongji replay page URL or an already-obtained direct media URL")
    p_auto.add_argument("--course-id", default="", help="Course ID")
    p_auto.add_argument("--sub-id", default="", help="Lecture sub_id")
    p_auto.add_argument("--lecture-limit", type=int, default=20, help="Max lectures shown for interactive choice")
    p_auto.add_argument("--output-dir", default="", help="Output directory (default: ./tongji-output)")
    p_auto.add_argument("--target", default="ru", help="Final subtitle language, e.g. ru, en, zh")
    p_auto.add_argument(
        "--model",
        default=os.environ.get("OPENAI_TRANSLATION_MODEL", DEFAULT_TRANSLATION_MODEL),
        help=f"OpenAI-compatible model for translation (default: {DEFAULT_TRANSLATION_MODEL})",
    )
    p_auto.add_argument("--batch-size", type=int, default=40, help="Subtitle cues per translation request")
    p_auto.add_argument("--api-timeout", type=int, default=120, help="OpenAI request timeout seconds")
    p_auto.add_argument(
        "--translation-mode",
        choices=["api", "free"],
        default="api",
        help="Translation mode for non-Chinese targets: api or free",
    )
    p_auto.add_argument("--free-timeout", type=int, default=25, help="Free translation request timeout seconds")
    p_auto.add_argument("--free-retries", type=int, default=3, help="Retry attempts per free translation request")
    p_auto.add_argument("--free-delay", type=float, default=0.05, help="Delay seconds between free translation requests")
    p_auto.add_argument("--free-batch-size", type=int, default=25, help="Subtitle cues per free translation request")
    p_auto.add_argument("--video-timeout", type=int, default=7200, help="ffmpeg download timeout seconds")
    p_auto.add_argument("--no-sync", action="store_true", help="Skip audio-based subtitle timing alignment")
    p_auto.add_argument("--sync-max-shift-ms", type=int, default=1400, help="Maximum subtitle sync adjustment per cue")
    p_auto.add_argument("--sync-lead-ms", type=int, default=80, help="Lead subtitle this many ms before detected speech")
    _add_proofread_args(p_auto, default_mode="local")
    p_auto.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_auto.set_defaults(func=cmd_auto_potplayer)

    p_api_test = sub.add_parser("api-test", help="Test OpenAI-compatible translation API settings")
    p_api_test.add_argument("--target", default="ru", help="Target language for test translation")
    p_api_test.add_argument(
        "--model",
        default=os.environ.get("OPENAI_TRANSLATION_MODEL", DEFAULT_TRANSLATION_MODEL),
        help=f"OpenAI-compatible model for translation (default: {DEFAULT_TRANSLATION_MODEL})",
    )
    p_api_test.add_argument("--timeout", type=int, default=60, help="API request timeout seconds")
    p_api_test.set_defaults(func=cmd_api_test)

    p_doctor = sub.add_parser("doctor", help="Check ffmpeg, system browser, API config, and optional Tongji login")
    p_doctor.add_argument("--login", action="store_true", help="Also test Tongji login")
    p_doctor.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_doctor.set_defaults(func=cmd_doctor)

    p_login_test = sub.add_parser("login-test", help="Test Tongji login only")
    p_login_test.add_argument("--force-login", action="store_true", help="Ignore cached JWT and login again")
    p_login_test.set_defaults(func=cmd_login_test)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
