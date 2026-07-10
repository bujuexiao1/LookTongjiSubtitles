#!/usr/bin/env python3
"""Shared app state helpers for Tongji Look desktop GUIs."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent


def _is_packaged_runtime() -> bool:
    try:
        return Path(sys.argv[0]).suffix.lower() == ".exe"
    except Exception:
        return getattr(sys, "frozen", False)


def _frozen_app_dir() -> Path:
    candidates: list[Path] = []
    for raw in (sys.argv[0] if sys.argv else "", sys.executable):
        if not raw:
            continue
        try:
            candidates.append(Path(raw).resolve().parent)
        except Exception:
            continue
    for candidate in candidates:
        if (candidate / "LookTongjiSubtitlesV2.exe").exists() or (candidate / "LookTongjiSubtitles.exe").exists():
            return candidate
    return candidates[0] if candidates else Path.cwd()


APP_DIR = _frozen_app_dir() if _is_packaged_runtime() else SKILL_ROOT
LOG_DIR = APP_DIR / "logs"
LOG_PATH = LOG_DIR / "app.log"


def _candidate_env_paths() -> list[Path]:
    candidates: list[Path] = []
    for base in (APP_DIR, Path.cwd()):
        path = base / ".env"
        if path not in candidates:
            candidates.append(path)
    return candidates


def effective_env_path() -> Path:
    for path in _candidate_env_paths():
        if path.exists():
            return path
    return APP_DIR / ".env"


ENV_PATH = effective_env_path()


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.lstrip("\ufeff").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().lstrip("\ufeff")] = value.strip()
    return values


def read_env() -> dict[str, str]:
    path = effective_env_path()
    if not path.exists():
        return {}
    return parse_env(path.read_text(encoding="utf-8", errors="replace"))


def write_env(values: dict[str, str]) -> None:
    path = APP_DIR / ".env"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in sorted(values.items()) if value not in (None, "")]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def append_app_log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


@dataclass
class SettingsModel:
    username: str = ""
    password: str = ""
    api_key: str = ""
    api_base_url: str = ""
    output_dir: str = ""
    subtitle_language: str = "zh"
    translation_model: str = "gpt-4.1-mini"
    teacher_keyword: str = ""
    course_keyword: str = ""
    start_date: str = ""
    end_date: str = ""
    weekday: str = ""

    @classmethod
    def load(cls) -> "SettingsModel":
        env = read_env()
        return cls(
            username=env.get("TONGJI_USERNAME", ""),
            password=env.get("TONGJI_PASSWORD", ""),
            api_key=env.get("OPENAI_API_KEY", ""),
            api_base_url=env.get("OPENAI_BASE_URL", ""),
            output_dir=env.get("LOOK_TONGJI_OUTPUT_DIR", ""),
            subtitle_language=env.get("LOOK_TONGJI_SUBTITLE_LANGUAGE", "zh") or "zh",
            translation_model=env.get("OPENAI_TRANSLATION_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini",
            teacher_keyword=env.get("LOOK_TONGJI_TEACHER_KEYWORD", ""),
            course_keyword=env.get("LOOK_TONGJI_COURSE_KEYWORD", ""),
            start_date=env.get("LOOK_TONGJI_START_DATE", ""),
            end_date=env.get("LOOK_TONGJI_END_DATE", ""),
            weekday=env.get("LOOK_TONGJI_WEEKDAY", ""),
        )

    def save(self) -> None:
        env = read_env()
        env.update(
            {
                "TONGJI_USERNAME": self.username,
                "TONGJI_PASSWORD": self.password,
                "OPENAI_API_KEY": self.api_key,
                "OPENAI_BASE_URL": self.api_base_url,
                "LOOK_TONGJI_OUTPUT_DIR": self.output_dir,
                "LOOK_TONGJI_SUBTITLE_LANGUAGE": self.subtitle_language,
                "OPENAI_TRANSLATION_MODEL": self.translation_model,
                "LOOK_TONGJI_TEACHER_KEYWORD": self.teacher_keyword,
                "LOOK_TONGJI_COURSE_KEYWORD": self.course_keyword,
                "LOOK_TONGJI_START_DATE": self.start_date,
                "LOOK_TONGJI_END_DATE": self.end_date,
                "LOOK_TONGJI_WEEKDAY": self.weekday,
            }
        )
        write_env(env)


def bundled_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    path = effective_env_path()
    env["LOOK_TONGJI_ENV_PATH"] = str(path)
    for key, value in read_env().items():
        env.setdefault(key, value)
    if _is_packaged_runtime():
        ffmpeg_dir = APP_DIR / "tools" / "ffmpeg" / "bin"
        browser_dir = APP_DIR / "tools" / "ms-playwright"
        if ffmpeg_dir.exists():
            env["PATH"] = str(ffmpeg_dir) + os.pathsep + env.get("PATH", "")
        if browser_dir.exists():
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir)
    return env
