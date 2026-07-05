#!/usr/bin/env python3
"""Small Tkinter GUI for Look Tongji Notes."""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import traceback
import webbrowser
import json
from datetime import datetime
from pathlib import Path
from tkinter import (
    BooleanVar,
    Button,
    Canvas,
    Checkbutton,
    END,
    Entry,
    filedialog,
    Frame,
    Label,
    LabelFrame,
    OptionMenu,
    Scrollbar,
    StringVar,
    Text,
    Tk,
    W,
    X,
    Y,
    messagebox,
)
from tkinter import ttk


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
CLI_PATH = SCRIPT_DIR / "look_tongji.py"
SELFUSE_HELPER_PATH = SCRIPT_DIR / "look_tongji_selfuse_helper.py"
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SKILL_ROOT
ENV_PATH = APP_DIR / ".env"
LOG_DIR = APP_DIR / "logs"
LOG_PATH = LOG_DIR / "app.log"
APP_VARIANT = os.environ.get("LOOK_TONGJI_APP_VARIANT", "public").strip().lower() or "public"
SELFUSE_ENABLED = APP_VARIANT == "selfuse"
APP_EXE_NAME = "LookTongjiSubtitlesSelfUse" if SELFUSE_ENABLED else "LookTongjiSubtitles"
BG_COLOR = "#f4f7fb"
PANEL_BG = "#ffffff"
TEXT_COLOR = "#172033"
MUTED_COLOR = "#5f6f89"
ACCENT_COLOR = "#2563eb"
ACCENT_DARK = "#1d4ed8"
SUCCESS_COLOR = "#16a34a"
ENTRY_BG = "#ffffff"
LOG_BG = "#0f172a"
LOG_FG = "#dbeafe"
UI_FONT = "{Microsoft YaHei UI} 10"
UI_FONT_HERO = "{Microsoft YaHei UI} 18 bold"
UI_FONT_SMALL = "{Microsoft YaHei UI} 10"
UI_FONT_TAB = "{Microsoft YaHei UI} 10"
MONO_FONT = "Consolas 10"


def _bundled_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    env["LOOK_TONGJI_ENV_PATH"] = str(ENV_PATH)
    for key, value in _read_env().items():
        env.setdefault(key, value)
    if getattr(sys, "frozen", False):
        ffmpeg_dir = APP_DIR / "tools" / "ffmpeg" / "bin"
        browser_dir = APP_DIR / "tools" / "ms-playwright"
        if ffmpeg_dir.exists():
            env["PATH"] = str(ffmpeg_dir) + os.pathsep + env.get("PATH", "")
        if browser_dir.exists():
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir)
    return env

LANGUAGE_LABELS = {
    "zh": "中文",
    "en": "English",
    "ru": "Русский",
}
LANGUAGE_CODES = {label: code for code, label in LANGUAGE_LABELS.items()}
SUBTITLE_LANGUAGE_LABELS = {
    "ru": "俄语 / Russian",
    "en": "英语 / English",
    "zh": "中文 / Chinese",
}
SUBTITLE_LANGUAGE_CODES = {label: code for code, label in SUBTITLE_LANGUAGE_LABELS.items()}

PROOFREAD_MODE_LABELS = {
    "zh": {"off": "关闭", "local": "本地快速校对", "ai": "AI 增强校对"},
    "en": {"off": "Off", "local": "Local quick proofread", "ai": "AI proofread"},
    "ru": {"off": "Выкл", "local": "Локальная правка", "ai": "AI-правка"},
}


def proofread_mode_label(lang: str, code: str) -> str:
    labels = PROOFREAD_MODE_LABELS.get(lang, PROOFREAD_MODE_LABELS["en"])
    return labels.get(code, labels["local"])


def proofread_mode_code(lang: str, label: str) -> str:
    labels = PROOFREAD_MODE_LABELS.get(lang, PROOFREAD_MODE_LABELS["en"])
    for code, value in labels.items():
        if value == label:
            return code
    return "local"

TEXT = {
    "zh": {
        "title": "同济课程字幕工具",
        "config": "配置",
        "ui_language": "界面语言",
        "username": "同济账号",
        "password": "同济密码",
        "api_key": "API Key",
        "api_base_url": "API 地址",
        "api_style": "API 类型",
        "model": "翻译模型",
        "proofread_mode": "字幕校对",
        "proofread_hint": "本地快速校对适合常规使用；AI 增强校对需要 API Key，并会使用上面的模型配置。",
        "save_config": "保存配置",
        "api_hint": "只生成中文字幕不需要 API Key；API 自动翻译才需要。",
        "api_base_hint": "中转站请填写它给你的 API 地址，例如 https://xxx.com/v1。",
        "show_secret": "显示",
        "progress": "进度",
        "progress_idle": "空闲",
        "progress_running": "正在处理，请等待...",
        "progress_done": "已完成",
        "progress_failed": "任务失败，请查看日志",
        "progress_cancelled": "已中止",
        "cancel_task": "中止任务",
        "test_api": "测试 API",
        "check_env": "检查环境",
        "test_login": "测试同济登录",
        "open_log": "打开报错日志",
        "api_test_running": "正在测试 API...",
        "api_test_ok": "API 测试成功。",
        "api_test_failed": "API 测试失败，请查看日志。",
        "env_check_done": "环境检查完成，请查看日志。",
        "login_check_done": "同济登录测试完成，请查看日志。",
        "optional": "可选",
        "advanced": "高级选项",
        "show_advanced": "显示高级选项",
        "hide_advanced": "隐藏高级选项",
        "simple_source": "第 1 步：粘贴课程回放链接",
        "simple_source_hint": "通常只需要粘贴课程页面链接。下面的 course_id / sub_id 不懂可以不填。",
        "existing_srt_hint": "如果你已经有中文字幕 SRT，可以直接选择它，然后跳过第 1 步。",
        "translation_methods": "第 2 步：选择翻译方式",
        "api_method_hint": "有 API Key：点自动翻译，最省事。",
        "manual_method_hint": "没有 API Key：先导出翻译包，把文件给任意 AI 翻译，再把译回的 SRT 选回来整理。",
        "manual_return": "第 3 步：整理 AI 返回的字幕",
        "keep_default": "看不懂就保持默认。",
        "source": "课程 / 字幕来源",
        "lecture_url": "课程回放链接",
        "source_srt": "原始 SRT",
        "pick_srt": "选择 SRT",
        "translated_srt": "AI 译回 SRT",
        "pick_translation": "选择译文",
        "video_file": "本地视频",
        "final_srt": "最终 SRT",
        "pick_video": "选择视频",
        "pick_final_srt": "选择最终字幕",
        "player_pack": "4. 准备播放器文件",
        "player_pack_hint": "把视频和字幕放到同一文件夹，并自动改成同名，适合 PotPlayer 自动加载。",
        "one_click": "一键生成 PotPlayer 成品",
        "one_click_hint": "选择字幕语言后点这里，自动下载视频、生成字幕、翻译并整理。",
        "subtitle_language": "字幕语言",
        "output_dir": "输出目录",
        "pick_dir": "选择目录",
        "actions": "操作",
        "target_language": "目标语言",
        "bilingual": "同时生成双语 SRT",
        "download_video": "1A. 下载课程视频",
        "transcribe": "1. 生成中文字幕",
        "api_translate": "2A. API 自动翻译",
        "manual_pack": "2B. 导出手动翻译包",
        "import_translation": "3. 整理 AI 译回 SRT",
        "open_output": "打开输出目录",
        "log": "日志",
        "saved_title": "已保存",
        "saved_body": "配置已保存到:",
        "pick_srt_title": "选择 SRT 字幕",
        "pick_translated_title": "选择 AI 翻译回来的 SRT",
        "pick_output_title": "选择输出目录",
        "missing_source_title": "缺少来源",
        "missing_source_body": "请填写课程回放链接，或填写 course_id / sub_id。",
        "missing_source_or_srt": "请选择已有 SRT，或填写课程回放链接。",
        "missing_source_srt_title": "缺少原始 SRT",
        "missing_source_srt_body": "请先选择原始中文字幕 SRT。",
        "missing_translation_title": "缺少译文 SRT",
        "missing_translation_body": "请先选择 AI 翻译回来的 SRT。",
        "missing_video_title": "缺少视频",
        "missing_video_body": "请先选择本地视频文件。",
        "missing_final_srt_title": "缺少最终字幕",
        "missing_final_srt_body": "请先选择要给播放器使用的最终 SRT。",
        "running_title": "正在运行",
        "running_body": "已有任务在运行，请等它结束。",
        "task_done": "任务结束，退出码",
        "start_failed": "启动失败",
        "batch_replay": "批量回放",
        "batch_teacher_keyword": "教师关键词",
        "batch_course_keyword": "课程关键词",
        "batch_start_date": "开始日期",
        "batch_end_date": "结束日期",
        "batch_weekday": "星期筛选",
        "batch_search_hint": "按“今日课程”批量搜索回放。星期可填 3 或 wed，3 表示周三。",
        "batch_search": "搜索回放",
        "batch_download": "批量下载视频+字幕",
        "missing_batch_range_title": "缺少批量检索条件",
        "missing_batch_range_body": "请至少填写开始日期和结束日期。",
        "selfuse_tools": "自用浏览器抓流",
        "selfuse_hint": "仅用于你自己已登录且能正常播放的页面。不会绕过权限。",
        "selfuse_capture": "抓取长链接",
        "selfuse_download": "抓流并下载+字幕",
        "selfuse_results": "搜索结果列表",
        "selfuse_results_hint": "先搜索老师/课程和日期，再勾选要导出或下载的回放。",
        "selfuse_no_results": "还没有搜索结果。先在上方填写条件后点击“搜索回放”。",
        "selfuse_select_all": "全选",
        "selfuse_clear_all": "清空选择",
        "selfuse_export_all": "导出当前列表",
        "selfuse_export_selected": "导出所选列表",
        "selfuse_download_selected": "下载所选+字幕",
        "selfuse_selected_missing_title": "未选择回放",
        "selfuse_selected_missing_body": "请先在结果列表里勾选至少一条回放。",
        "selfuse_export_done_title": "导出完成",
        "selfuse_export_done_body": "列表已导出到：",
        "selfuse_results_summary": "共 {total} 条，已选 {selected} 条",
    },
    "en": {
        "title": "Tongji Subtitle Tool",
        "config": "Settings",
        "ui_language": "UI language",
        "username": "Tongji ID",
        "password": "Tongji password",
        "api_key": "API Key",
        "api_base_url": "API base URL",
        "api_style": "API type",
        "model": "Translation model",
        "proofread_mode": "Subtitle proofread",
        "proofread_hint": "Local proofread is good for daily use. AI proofread needs an API key and uses the model above.",
        "save_config": "Save settings",
        "api_hint": "Chinese subtitles do not need an API key; API translation does.",
        "api_base_hint": "For relay services, enter the API URL they provide, such as https://xxx.com/v1.",
        "show_secret": "Show",
        "progress": "Progress",
        "progress_idle": "Idle",
        "progress_running": "Working, please wait...",
        "progress_done": "Done",
        "progress_failed": "Task failed. Check the log.",
        "progress_cancelled": "Cancelled",
        "cancel_task": "Cancel task",
        "test_api": "Test API",
        "check_env": "Check environment",
        "test_login": "Test Tongji login",
        "open_log": "Open error log",
        "api_test_running": "Testing API...",
        "api_test_ok": "API test succeeded.",
        "api_test_failed": "API test failed. Check the log.",
        "env_check_done": "Environment check finished. Check the log.",
        "login_check_done": "Tongji login test finished. Check the log.",
        "optional": "optional",
        "advanced": "Advanced options",
        "show_advanced": "Show advanced options",
        "hide_advanced": "Hide advanced options",
        "simple_source": "Step 1: Paste the course replay link",
        "simple_source_hint": "Usually you only need the course page link. Leave course_id / sub_id empty if unsure.",
        "existing_srt_hint": "Already have a Chinese SRT? Choose it here and skip Step 1.",
        "translation_methods": "Step 2: Choose a translation method",
        "api_method_hint": "With an API key: click automatic translation. This is the easiest path.",
        "manual_method_hint": "Without an API key: export a pack, give it to any AI, then import the returned SRT.",
        "manual_return": "Step 3: Clean up the AI-returned subtitles",
        "keep_default": "If unsure, keep the default.",
        "source": "Course / Subtitle Source",
        "lecture_url": "Replay URL",
        "source_srt": "Source SRT",
        "pick_srt": "Choose SRT",
        "translated_srt": "AI SRT",
        "pick_translation": "Choose translation",
        "video_file": "Local video",
        "final_srt": "Final SRT",
        "pick_video": "Choose video",
        "pick_final_srt": "Choose final SRT",
        "player_pack": "4. Prepare player files",
        "player_pack_hint": "Put the video and subtitles in one folder with the same name for PotPlayer.",
        "one_click": "One-click PotPlayer output",
        "one_click_hint": "Choose a subtitle language, then download, subtitle, translate, and pack automatically.",
        "subtitle_language": "Subtitle language",
        "output_dir": "Output folder",
        "pick_dir": "Choose folder",
        "actions": "Actions",
        "target_language": "Target language",
        "bilingual": "Also write bilingual SRT",
        "download_video": "1A. Download course video",
        "transcribe": "1. Generate Chinese subtitles",
        "api_translate": "2A. API translation",
        "manual_pack": "2B. Export manual pack",
        "import_translation": "3. Normalize AI SRT",
        "open_output": "Open output folder",
        "log": "Log",
        "saved_title": "Saved",
        "saved_body": "Settings saved to:",
        "pick_srt_title": "Choose SRT subtitles",
        "pick_translated_title": "Choose AI-translated SRT",
        "pick_output_title": "Choose output folder",
        "missing_source_title": "Missing source",
        "missing_source_body": "Enter a replay URL, or fill course_id / sub_id.",
        "missing_source_or_srt": "Choose an existing SRT, or enter a replay URL.",
        "missing_source_srt_title": "Missing source SRT",
        "missing_source_srt_body": "Choose the original Chinese SRT first.",
        "missing_translation_title": "Missing translated SRT",
        "missing_translation_body": "Choose the AI-translated SRT first.",
        "missing_video_title": "Missing video",
        "missing_video_body": "Choose a local video file first.",
        "missing_final_srt_title": "Missing final SRT",
        "missing_final_srt_body": "Choose the final SRT for the video player first.",
        "running_title": "Running",
        "running_body": "A task is already running. Please wait for it to finish.",
        "task_done": "Task finished, exit code",
        "start_failed": "Failed to start",
        "batch_replay": "Batch replays",
        "batch_teacher_keyword": "Teacher keyword",
        "batch_course_keyword": "Course keyword",
        "batch_start_date": "Start date",
        "batch_end_date": "End date",
        "batch_weekday": "Weekday",
        "batch_search_hint": "Search Today Courses in bulk. Use 3 or wed for Wednesday.",
        "batch_search": "Search replays",
        "batch_download": "Batch download video + subtitles",
        "missing_batch_range_title": "Missing batch range",
        "missing_batch_range_body": "Fill in at least the start date and end date.",
        "selfuse_tools": "Browser-assisted capture",
        "selfuse_hint": "Only for pages you are already logged into and can play normally. No permission bypass.",
        "selfuse_capture": "Capture media link",
        "selfuse_download": "Capture + download + subtitles",
        "selfuse_results": "Replay results",
        "selfuse_results_hint": "Search by teacher/course/date, then select which replay items to export or download.",
        "selfuse_no_results": "No replay results yet. Fill in the search fields above and click Search replays.",
        "selfuse_select_all": "Select all",
        "selfuse_clear_all": "Clear",
        "selfuse_export_all": "Export current list",
        "selfuse_export_selected": "Export selected",
        "selfuse_download_selected": "Download selected + subtitles",
        "selfuse_selected_missing_title": "No replay selected",
        "selfuse_selected_missing_body": "Select at least one replay item in the result list first.",
        "selfuse_export_done_title": "Export complete",
        "selfuse_export_done_body": "The list was exported to:",
        "selfuse_results_summary": "{selected} selected / {total} total",
    },
    "ru": {
        "title": "Субтитры Tongji",
        "config": "Настройки",
        "ui_language": "Язык интерфейса",
        "username": "Аккаунт Tongji",
        "password": "Пароль Tongji",
        "api_key": "API-ключ",
        "api_base_url": "Адрес API",
        "api_style": "Тип API",
        "model": "Модель перевода",
        "proofread_mode": "Проверка субтитров",
        "proofread_hint": "Локальная правка подходит для обычного использования. AI-правка требует API-ключ и использует модель выше.",
        "save_config": "Сохранить",
        "api_hint": "Китайские субтитры не требуют API-ключ; API-перевод требует ключ.",
        "api_base_hint": "Для посредника укажите его API-адрес, например https://xxx.com/v1.",
        "show_secret": "Показать",
        "progress": "Прогресс",
        "progress_idle": "Ожидание",
        "progress_running": "Выполняется, подождите...",
        "progress_done": "Готово",
        "progress_failed": "Ошибка. Проверьте журнал.",
        "progress_cancelled": "Отменено",
        "cancel_task": "Остановить",
        "test_api": "Проверить API",
        "check_env": "Проверить среду",
        "test_login": "Проверить вход Tongji",
        "open_log": "Открыть журнал ошибок",
        "api_test_running": "Проверка API...",
        "api_test_ok": "API успешно проверен.",
        "api_test_failed": "Ошибка проверки API. Смотрите журнал.",
        "env_check_done": "Проверка среды завершена. Смотрите журнал.",
        "login_check_done": "Проверка входа Tongji завершена. Смотрите журнал.",
        "optional": "необязательно",
        "advanced": "Дополнительно",
        "show_advanced": "Показать дополнительные настройки",
        "hide_advanced": "Скрыть дополнительные настройки",
        "simple_source": "Шаг 1: вставьте ссылку на запись курса",
        "simple_source_hint": "Обычно нужна только ссылка на страницу курса. course_id / sub_id можно не заполнять.",
        "existing_srt_hint": "Уже есть китайский SRT? Выберите его здесь и пропустите шаг 1.",
        "translation_methods": "Шаг 2: выберите способ перевода",
        "api_method_hint": "Есть API-ключ: нажмите автоматический перевод. Это самый простой путь.",
        "manual_method_hint": "Нет API-ключа: экспортируйте пакет, отдайте его любому AI, затем импортируйте SRT.",
        "manual_return": "Шаг 3: исправьте субтитры, возвращенные AI",
        "keep_default": "Если не уверены, оставьте по умолчанию.",
        "source": "Курс / источник субтитров",
        "lecture_url": "Ссылка на запись",
        "source_srt": "Исходный SRT",
        "pick_srt": "Выбрать SRT",
        "translated_srt": "SRT от AI",
        "pick_translation": "Выбрать перевод",
        "video_file": "Видео",
        "final_srt": "Готовый SRT",
        "pick_video": "Выбрать видео",
        "pick_final_srt": "Выбрать SRT",
        "player_pack": "4. Подготовить файлы",
        "player_pack_hint": "Видео и SRT будут в одной папке с одинаковым именем для PotPlayer.",
        "one_click": "Один клик для PotPlayer",
        "one_click_hint": "Выберите язык субтитров, затем программа всё сделает автоматически.",
        "subtitle_language": "Язык субтитров",
        "output_dir": "Папка вывода",
        "pick_dir": "Выбрать папку",
        "actions": "Действия",
        "target_language": "Язык перевода",
        "bilingual": "Также создать двуязычный SRT",
        "download_video": "1A. Скачать видео курса",
        "transcribe": "1. Создать китайские субтитры",
        "api_translate": "2A. API-перевод",
        "manual_pack": "2B. Пакет для ручного перевода",
        "import_translation": "3. Исправить SRT от AI",
        "open_output": "Открыть папку",
        "log": "Журнал",
        "saved_title": "Сохранено",
        "saved_body": "Настройки сохранены в:",
        "pick_srt_title": "Выберите SRT",
        "pick_translated_title": "Выберите SRT, переведенный AI",
        "pick_output_title": "Выберите папку вывода",
        "missing_source_title": "Нет источника",
        "missing_source_body": "Введите ссылку на запись или course_id / sub_id.",
        "missing_source_or_srt": "Выберите SRT или введите ссылку на запись.",
        "missing_source_srt_title": "Нет исходного SRT",
        "missing_source_srt_body": "Сначала выберите исходный китайский SRT.",
        "missing_translation_title": "Нет переведенного SRT",
        "missing_translation_body": "Сначала выберите SRT, переведенный AI.",
        "missing_video_title": "Нет видео",
        "missing_video_body": "Сначала выберите локальный видеофайл.",
        "missing_final_srt_title": "Нет готового SRT",
        "missing_final_srt_body": "Сначала выберите готовый SRT для плеера.",
        "running_title": "Выполняется",
        "running_body": "Задача уже выполняется. Дождитесь завершения.",
        "task_done": "Задача завершена, код выхода",
        "start_failed": "Не удалось запустить",
        "batch_replay": "Batch replays",
        "batch_teacher_keyword": "Teacher keyword",
        "batch_course_keyword": "Course keyword",
        "batch_start_date": "Start date",
        "batch_end_date": "End date",
        "batch_weekday": "Weekday",
        "batch_search_hint": "Search Today Courses in bulk. Use 3 or wed for Wednesday.",
        "batch_search": "Search replays",
        "batch_download": "Batch download video + subtitles",
        "missing_batch_range_title": "Missing batch range",
        "missing_batch_range_body": "Fill in at least the start date and end date.",
        "selfuse_tools": "Browser-assisted capture",
        "selfuse_hint": "Only for pages you are already logged into and can play normally. No permission bypass.",
        "selfuse_capture": "Capture media link",
        "selfuse_download": "Capture + download + subtitles",
        "selfuse_results": "Replay results",
        "selfuse_results_hint": "Search by teacher/course/date, then select which replay items to export or download.",
        "selfuse_no_results": "No replay results yet. Fill in the search fields above and click Search replays.",
        "selfuse_select_all": "Select all",
        "selfuse_clear_all": "Clear",
        "selfuse_export_all": "Export current list",
        "selfuse_export_selected": "Export selected",
        "selfuse_download_selected": "Download selected + subtitles",
        "selfuse_selected_missing_title": "No replay selected",
        "selfuse_selected_missing_body": "Select at least one replay item in the result list first.",
        "selfuse_export_done_title": "Export complete",
        "selfuse_export_done_body": "The list was exported to:",
        "selfuse_results_summary": "{selected} selected / {total} total",
    },
}


TAB_LABELS = {
    "zh": ("工具", "使用说明", "报错日志"),
    "en": ("Tool", "Guide", "Error log"),
    "ru": ("Инструмент", "Инструкция", "Журнал"),
}

SIMPLE_LABELS = {
    "zh": {
        "quick": "一键流程",
        "manual": "不用 API：手动翻译",
        "config_line": "基础配置",
        "manual_step1": "先有中文字幕",
        "manual_step2": "让 AI 翻译后导回",
        "manual_step3": "最后给 PotPlayer 用",
        "prepare_manual": "下载视频 + 中文字幕",
        "api_one_click": "API 自动生成",
        "free_one_click": "免费自动生成",
        "auto_generate": "生成视频 + 目标语言字幕",
        "free_hint": "有 API Key 自动用 API；没有 Key 自动用免费翻译；选中文时只生成中文字幕。",
        "potplayer_download": "打开 PotPlayer 官网",
        "refresh_log": "刷新日志",
        "clear_log": "清空显示",
        "log_hint": "这里会显示运行输出和报错信息。滚轮只会滚动日志区域。",
        "open_api_source": "打开 api.yunyao.shop",
        "use_api_source": "填入推荐 API 地址",
        "copy_api_base": "复制 API 地址",
        "hero_title": "同济课程字幕工具",
        "hero_subtitle": "粘贴课程回放链接，选择字幕语言，然后一键生成视频和字幕。",
        "primary_action": "开始生成",
    },
    "en": {
        "quick": "One-click workflow",
        "manual": "No API: manual translation",
        "config_line": "Basic settings",
        "manual_step1": "First get Chinese subtitles",
        "manual_step2": "Translate with AI, then import",
        "manual_step3": "Prepare for PotPlayer",
        "prepare_manual": "Download video + Chinese SRT",
        "api_one_click": "API automatic",
        "free_one_click": "Free automatic",
        "auto_generate": "Generate video + target subtitles",
        "free_hint": "With an API key, API translation is used. Without a key, free translation is used. Chinese needs no translation.",
        "potplayer_download": "Open PotPlayer website",
        "refresh_log": "Refresh log",
        "clear_log": "Clear display",
        "log_hint": "Runtime output and errors appear here. Mouse wheel only scrolls this log area.",
        "open_api_source": "Open api.yunyao.shop",
        "use_api_source": "Use recommended API URL",
        "copy_api_base": "Copy API URL",
        "hero_title": "Tongji Course Subtitle Tool",
        "hero_subtitle": "Paste a replay link, choose a subtitle language, then generate the video and subtitles.",
        "primary_action": "Start",
    },
    "ru": {
        "quick": "Один клик",
        "manual": "Без API: ручной перевод",
        "config_line": "Основные настройки",
        "manual_step1": "Сначала китайские субтитры",
        "manual_step2": "Перевести через AI и импортировать",
        "manual_step3": "Подготовить для PotPlayer",
        "prepare_manual": "Скачать видео + китайский SRT",
        "api_one_click": "API автоматически",
        "free_one_click": "Бесплатно автоматически",
        "auto_generate": "Создать видео + нужные субтитры",
        "free_hint": "С API-ключом используется API. Без ключа используется бесплатный перевод. Для китайского перевод не нужен.",
        "potplayer_download": "Открыть сайт PotPlayer",
        "refresh_log": "Обновить журнал",
        "clear_log": "Очистить экран",
        "log_hint": "Здесь отображаются вывод и ошибки. Колесо мыши прокручивает только журнал.",
        "open_api_source": "Открыть api.yunyao.shop",
        "use_api_source": "Заполнить URL API",
        "copy_api_base": "Копировать URL API",
        "hero_title": "Tongji Course Subtitle Tool",
        "hero_subtitle": "Вставьте ссылку, выберите язык субтитров и создайте видео с субтитрами.",
        "primary_action": "Start",
    },
}

GUIDE_TEXT = {
    "zh": """最推荐：一键生成 PotPlayer 成品

1. 在“配置”里填写同济账号、同济密码。
2. 如果要自动翻译成俄语/英语，填写 API Key 和 API 地址，然后点“测试 API”。
3. 点“保存配置”。
4. 在“第 1 步”粘贴课程回放链接。
5. 在“字幕语言”选择最终字幕语言。
6. 点“一键生成 PotPlayer 成品”。
7. 完成后点“打开输出目录”，用 PotPlayer 打开生成的 mp4。

结果会是同名文件，例如：
sample_course.mp4
sample_course.srt

PotPlayer 通常会自动加载同名 srt。


两种翻译方式

1. API 自动生成：推荐。有 API Key 时使用，速度和质量更稳。
2. 免费自动生成：没有 API Key 时使用。工具会自动逐条翻译并缓存进度，字幕很多时也可以跑；如果中途失败，再点一次会继续。

免费自动生成不需要 API Key，但会比 API 慢，也可能被免费翻译服务限流。2317 条这种长字幕建议让电脑放着慢慢跑。

两种方式都会自动输出 PotPlayer 可用的同名 mp4+srt。


PotPlayer 下载和字幕使用

下载方式：
1. 打开 https://potplayer.tv
2. 下载 64bit 版本并安装。
3. 安装后，用 PotPlayer 打开生成的 mp4。

SRT 使用方式：
1. mp4 和 srt 要放在同一个文件夹。
2. 文件名要完全相同，只保留扩展名不同。

正确示例：
lesson.mp4
lesson.srt

错误示例：
lesson.mp4
lesson.ru.srt

如果字幕没有自动显示：
1. 在 PotPlayer 里右键视频。
2. 找到“字幕”相关菜单。
3. 手动加载这个 srt 文件。


常用按钮

保存配置：保存账号、密码、API 地址等，下次打开不用重新填。
测试 API：检查 API Key、API 地址、模型是否可用。
检查环境：检查 ffmpeg、浏览器、API 基础配置。
测试同济登录：只测试能不能登录同济回放平台。
打开报错日志：打开详细错误文件，方便排查。

一键生成 PotPlayer 成品：自动下载视频、生成中文字幕、按所选语言翻译、整理成同名 mp4+srt。
1A. 下载课程视频：只下载 mp4。
1. 生成中文字幕：只生成中文 srt/txt。
2A. API 自动翻译：把已有中文 SRT 自动翻译成所选语言。
2B. 导出手动翻译包：没有 API 时使用。
3. 整理 AI 译回 SRT：把 AI 返回的字幕对齐到原字幕时间轴。
4. 准备播放器文件：把视频和字幕放到同一文件夹，并改成同名。

中止任务：停止当前正在运行的下载、识别或翻译。
打开输出目录：查看生成的视频、字幕和中间文件。
""",
    "en": """Recommended: one-click PotPlayer output

1. Fill Tongji ID and password.
2. For automatic translation, fill API Key and API base URL, then click Test API.
3. Save settings.
4. Paste the course replay link.
5. Choose the final subtitle language.
6. Click One-click PotPlayer output.
7. Open the output folder and play the mp4 with PotPlayer.

Two translation modes:

1. API automatic: recommended when you have an API key.
2. Free automatic: no API key. The tool translates cue by cue and caches progress, so you can click again to resume after a failure.

Free automatic translation is slower and may be rate-limited, but it can handle long SRT files without asking the user to paste them into a web AI.

PotPlayer loads subtitles automatically when video and SRT have the same name.""",
    "ru": """Рекомендуемый путь: один клик для PotPlayer

1. Введите аккаунт и пароль Tongji.
2. Для автоматического перевода введите API Key и API base URL, затем проверьте API.
3. Сохраните настройки.
4. Вставьте ссылку на запись курса.
5. Выберите язык субтитров.
6. Нажмите один клик для PotPlayer.
7. Откройте папку результата и запустите mp4 в PotPlayer.

Без API:

1. Создайте китайский SRT.
2. Экспортируйте пакет ручного перевода.
3. Отправьте prompt.txt и source.srt любому AI.
4. Попросите вернуть только полный SRT, сохранив номера и таймкоды.
5. Сохраните ответ AI как .srt.
6. Выберите его и нормализуйте AI SRT.
7. Подготовьте файлы для проигрывателя.

PotPlayer обычно сам загружает SRT, если mp4 и srt имеют одинаковое имя.""",
}


def _parse_env(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        result[key.strip()] = value
    return result


def _quote_env(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _read_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    try:
        return _parse_env(ENV_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_env(values: dict[str, str]) -> None:
    lines = ["# Auto-generated by look-tongji-notes GUI"]
    for key in sorted(values):
        if values[key]:
            lines.append(f"{key}={_quote_env(values[key])}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_app_log(text: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {text.rstrip()}\n")
    except Exception:
        pass


class LookTongjiGui:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.geometry("1040x760")
        self.root.minsize(920, 660)
        self._setup_theme()

        env = _read_env()
        default_output = str((Path.cwd() / "tongji-output").resolve())
        saved_lang = env.get("LOOK_TONGJI_GUI_LANG", "zh")
        if saved_lang not in TEXT:
            saved_lang = "zh"
        saved_guide_lang = env.get("LOOK_TONGJI_GUIDE_LANG", saved_lang)
        if saved_guide_lang not in GUIDE_TEXT:
            saved_guide_lang = saved_lang

        self.lang = saved_lang
        self.guide_lang = saved_guide_lang
        self.language_label = StringVar(value=LANGUAGE_LABELS[self.lang])
        self.guide_language_label = StringVar(value=LANGUAGE_LABELS[self.guide_lang])
        self.username = StringVar(value=env.get("TONGJI_USERNAME", ""))
        self.password = StringVar(value=env.get("TONGJI_PASSWORD", ""))
        self.api_key = StringVar(value=env.get("OPENAI_API_KEY", ""))
        self.api_base_url = StringVar(value=env.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
        self.api_style = StringVar(value=env.get("OPENAI_API_STYLE", "chat"))
        self.model = StringVar(value=env.get("OPENAI_TRANSLATION_MODEL", "gpt-4.1-mini"))
        saved_proofread_mode = env.get("LOOK_TONGJI_PROOFREAD_MODE", "local").strip().lower()
        if saved_proofread_mode not in {"off", "local", "ai"}:
            saved_proofread_mode = "local"
        self.proofread_mode = StringVar(value=saved_proofread_mode)
        self.proofread_mode_label = StringVar(value=proofread_mode_label(self.lang, saved_proofread_mode))
        self.lecture_url = StringVar()
        self.course_id = StringVar()
        self.sub_id = StringVar()
        self.srt_path = StringVar()
        self.translated_srt_path = StringVar()
        self.video_path = StringVar()
        self.final_srt_path = StringVar()
        self.output_dir = StringVar(value=default_output)
        self.batch_teacher_keyword = StringVar(value=env.get("LOOK_TONGJI_BATCH_TEACHER", ""))
        self.batch_course_keyword = StringVar(value=env.get("LOOK_TONGJI_BATCH_COURSE", ""))
        self.batch_start_date = StringVar(value=env.get("LOOK_TONGJI_BATCH_START_DATE", ""))
        self.batch_end_date = StringVar(value=env.get("LOOK_TONGJI_BATCH_END_DATE", ""))
        self.batch_weekday = StringVar(value=env.get("LOOK_TONGJI_BATCH_WEEKDAY", ""))
        self.target = StringVar(value="ru")
        self.subtitle_language_label = StringVar(value=SUBTITLE_LANGUAGE_LABELS.get(self.target.get(), SUBTITLE_LANGUAGE_LABELS["ru"]))
        self.bilingual = BooleanVar(value=True)
        self.show_advanced = BooleanVar(value=False)
        self.show_password = BooleanVar(value=False)
        self.show_api_key = BooleanVar(value=False)
        self.progress_text = StringVar(value=TEXT[self.lang]["progress_idle"])

        self.log: Text | None = None
        self.log_widgets: list[Text] = []
        self.progress_bar = None
        self.password_entry = None
        self.api_key_entry = None
        self.log_queue: queue.Queue = queue.Queue()
        self.selfuse_replay_items: list[dict[str, object]] = []
        self.selfuse_replay_vars: list[BooleanVar] = []
        self.selfuse_results_summary = StringVar(value=self.t("selfuse_results_summary").format(total=0, selected=0))
        self.selfuse_results_frame = None
        self.selfuse_results_canvas = None
        self.selfuse_last_search_json = ""
        self.running = False
        self.current_task = ""
        self.last_error_summary = ""
        self.current_proc = None
        self.cancel_requested = False

        self._build()
        self.root.after(100, self._drain_log_queue)

    def _setup_theme(self) -> None:
        self.root.configure(bg=BG_COLOR)
        self.root.option_add("*Font", UI_FONT)
        self.root.option_add("*Button.Font", UI_FONT)
        self.root.option_add("*Entry.Font", UI_FONT)
        self.root.option_add("*Text.Font", MONO_FONT)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=BG_COLOR, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=UI_FONT_TAB)
        style.map("TNotebook.Tab", background=[("selected", PANEL_BG)], foreground=[("selected", ACCENT_COLOR)])
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#e6edf7",
            background=SUCCESS_COLOR,
            bordercolor="#e6edf7",
            lightcolor=SUCCESS_COLOR,
            darkcolor=SUCCESS_COLOR,
        )

    def t(self, key: str) -> str:
        return TEXT[self.lang].get(key, TEXT["en"].get(key, key))

    def _build(self, log_text: str = "") -> None:
        title = self.t("title")
        if SELFUSE_ENABLED:
            title += " [自用版]"
        self.root.title(title)
        self.proofread_mode_label.set(proofread_mode_label(self.lang, self.proofread_mode.get().strip() or "local"))
        for child in self.root.winfo_children():
            child.destroy()
        self.log = None
        self.log_widgets = []

        tabs = TAB_LABELS.get(self.lang, TAB_LABELS["zh"])
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=8)

        tool_tab = Frame(notebook, padx=10, pady=8)
        guide_tab = Frame(notebook, padx=10, pady=8)
        log_tab = Frame(notebook, padx=10, pady=8)
        notebook.add(tool_tab, text=tabs[0])
        notebook.add(guide_tab, text=tabs[1])
        notebook.add(log_tab, text=tabs[2])

        self._build_simple_tool(self._make_scrollable_tab(tool_tab), log_text=log_text)
        self._build_guide_tab(guide_tab)
        self._build_log_tab(log_tab, log_text=log_text)
        self._polish_tree(self.root)
        return

        outer = Frame(self.root)
        outer.pack(fill="both", expand=True)
        canvas = Canvas(outer, highlightthickness=0)
        page_scrollbar = Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=page_scrollbar.set)
        page_scrollbar.pack(side="right", fill=Y)
        canvas.pack(side="left", fill="both", expand=True)

        container = Frame(canvas, padx=10, pady=8)
        window_id = canvas.create_window((0, 0), window=container, anchor="nw")

        def refresh_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def fit_width(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        def enable_mousewheel(_event=None) -> None:
            canvas.bind_all("<MouseWheel>", on_mousewheel)

        def disable_mousewheel(_event=None) -> None:
            canvas.unbind_all("<MouseWheel>")

        def on_mousewheel(event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        container.bind("<Configure>", refresh_scroll_region)
        canvas.bind("<Configure>", fit_width)
        canvas.bind("<Enter>", enable_mousewheel)
        canvas.bind("<Leave>", disable_mousewheel)

        cfg = LabelFrame(container, text=self.t("config"), padx=10, pady=8)
        cfg.pack(fill=X)
        self._row(
            cfg,
            0,
            self.t("ui_language"),
            OptionMenu(cfg, self.language_label, *LANGUAGE_LABELS.values(), command=self.change_language),
        )
        self._row(cfg, 1, self.t("username"), Entry(cfg, textvariable=self.username, width=28))
        self.password_entry = Entry(
            cfg,
            textvariable=self.password,
            width=28,
            show="" if self.show_password.get() else "*",
        )
        self._row(cfg, 2, self.t("password"), self.password_entry)
        Checkbutton(
            cfg,
            text=self.t("show_secret"),
            variable=self.show_password,
            command=self.toggle_secret_visibility,
        ).grid(row=2, column=2, sticky=W, padx=8)
        self.api_key_entry = Entry(
            cfg,
            textvariable=self.api_key,
            width=56,
            show="" if self.show_api_key.get() else "*",
        )
        self._row(
            cfg,
            3,
            f"{self.t('api_key')} ({self.t('optional')})",
            self.api_key_entry,
        )
        Checkbutton(
            cfg,
            text=self.t("show_secret"),
            variable=self.show_api_key,
            command=self.toggle_secret_visibility,
        ).grid(row=3, column=2, sticky=W, padx=8)
        self._row(
            cfg,
            4,
            f"{self.t('api_base_url')} ({self.t('optional')})",
            Entry(cfg, textvariable=self.api_base_url, width=56),
        )
        Label(cfg, textvariable=self.progress_text, fg="#005a9e").grid(
            row=5, column=1, columnspan=3, sticky=W, pady=(6, 0)
        )
        Button(cfg, text=self.t("save_config"), command=self.save_config, padx=16, pady=5).grid(
            row=6, column=1, sticky=W, pady=(8, 0)
        )
        Checkbutton(
            cfg,
            text=self.t("hide_advanced") if self.show_advanced.get() else self.t("show_advanced"),
            variable=self.show_advanced,
            command=self.toggle_advanced,
        ).grid(row=6, column=2, sticky=W, padx=8, pady=(8, 0))
        Label(cfg, text=self.t("api_hint"), fg="#555555").grid(
            row=7, column=1, columnspan=3, sticky=W, pady=(6, 0)
        )
        Label(cfg, text=self.t("api_base_hint"), fg="#555555").grid(
            row=8, column=1, columnspan=3, sticky=W
        )
        Button(cfg, text=self.t("test_api"), command=self.test_api, padx=12).grid(
            row=9, column=1, sticky=W, pady=(8, 0)
        )
        Button(cfg, text=self.t("check_env"), command=self.check_environment, padx=12).grid(
            row=9, column=2, sticky=W, padx=8, pady=(8, 0)
        )
        Button(cfg, text=self.t("test_login"), command=self.test_login, padx=12).grid(
            row=9, column=3, sticky=W, padx=8, pady=(8, 0)
        )
        Button(cfg, text=self.t("open_log"), command=self.open_log, padx=12).grid(
            row=10, column=1, sticky=W, pady=(6, 0)
        )

        src = LabelFrame(container, text=self.t("simple_source"), padx=10, pady=8)
        src.pack(fill=X, pady=(10, 0))
        self._row(src, 0, self.t("lecture_url"), Entry(src, textvariable=self.lecture_url, width=76))
        Label(src, text=self.t("simple_source_hint"), fg="#555555").grid(
            row=1, column=1, columnspan=2, sticky=W
        )
        self._row(
            src,
            2,
            self.t("subtitle_language"),
            OptionMenu(src, self.subtitle_language_label, *SUBTITLE_LANGUAGE_LABELS.values(), command=self.change_subtitle_language),
        )
        Button(src, text=self.t("one_click"), command=self.one_click, padx=18, pady=8).grid(
            row=3, column=1, sticky=W, pady=(8, 0)
        )
        Label(src, text=self.t("one_click_hint"), fg="#555555").grid(row=3, column=2, sticky=W, padx=8)
        Button(src, text=self.t("download_video"), command=self.download_video, padx=18, pady=8).grid(
            row=4, column=1, sticky=W, pady=(8, 0)
        )
        Button(src, text=self.t("transcribe"), command=self.transcribe, padx=18, pady=8).grid(
            row=4, column=2, sticky=W, padx=8, pady=(8, 0)
        )

        files = LabelFrame(container, text=self.t("source_srt"), padx=10, pady=8)
        files.pack(fill=X, pady=(10, 0))
        self._row(files, 0, self.t("source_srt"), Entry(files, textvariable=self.srt_path, width=62))
        Button(files, text=self.t("pick_srt"), command=self.pick_srt, padx=10).grid(row=0, column=2, sticky=W, padx=8)
        Label(files, text=self.t("existing_srt_hint"), fg="#555555").grid(
            row=1, column=1, columnspan=2, sticky=W
        )

        translate = LabelFrame(container, text=self.t("translation_methods"), padx=10, pady=8)
        translate.pack(fill=X, pady=(10, 0))
        Button(translate, text=self.t("api_translate"), command=self.subtitle, padx=18, pady=8).grid(
            row=0, column=1, sticky=W, pady=4
        )
        Label(translate, text=self.t("api_method_hint"), fg="#555555").grid(row=0, column=2, sticky=W, padx=8)
        Button(translate, text=self.t("manual_pack"), command=self.subtitle_pack, padx=18, pady=8).grid(
            row=1, column=1, sticky=W, pady=4
        )
        Label(translate, text=self.t("manual_method_hint"), fg="#555555").grid(row=1, column=2, sticky=W, padx=8)

        returned = LabelFrame(container, text=self.t("manual_return"), padx=10, pady=8)
        returned.pack(fill=X, pady=(10, 0))
        self._row(returned, 0, self.t("translated_srt"), Entry(returned, textvariable=self.translated_srt_path, width=62))
        Button(returned, text=self.t("pick_translation"), command=self.pick_translated_srt, padx=10).grid(
            row=0, column=2, sticky=W, padx=8
        )
        Button(returned, text=self.t("import_translation"), command=self.subtitle_import, padx=18, pady=8).grid(
            row=1, column=1, sticky=W, pady=(8, 0)
        )

        player = LabelFrame(container, text=self.t("player_pack"), padx=10, pady=8)
        player.pack(fill=X, pady=(10, 0))
        self._row(player, 0, self.t("video_file"), Entry(player, textvariable=self.video_path, width=62))
        Button(player, text=self.t("pick_video"), command=self.pick_video, padx=10).grid(
            row=0, column=2, sticky=W, padx=8
        )
        self._row(player, 1, self.t("final_srt"), Entry(player, textvariable=self.final_srt_path, width=62))
        Button(player, text=self.t("pick_final_srt"), command=self.pick_final_srt, padx=10).grid(
            row=1, column=2, sticky=W, padx=8
        )
        Button(player, text=self.t("player_pack"), command=self.player_pack, padx=18, pady=8).grid(
            row=2, column=1, sticky=W, pady=(8, 0)
        )
        Label(player, text=self.t("player_pack_hint"), fg="#555555").grid(row=2, column=2, sticky=W, padx=8)

        out = LabelFrame(container, text=self.t("output_dir"), padx=10, pady=8)
        out.pack(fill=X, pady=(10, 0))
        self._row(out, 0, self.t("output_dir"), Entry(out, textvariable=self.output_dir, width=62))
        Button(out, text=self.t("pick_dir"), command=self.pick_output_dir, padx=10).grid(row=0, column=2, sticky=W, padx=8)
        Button(out, text=self.t("open_output"), command=self.open_output_dir, padx=12).grid(row=0, column=3, sticky=W, padx=8)

        progress = LabelFrame(container, text=self.t("progress"), padx=10, pady=8)
        progress.pack(fill=X, pady=(10, 0))
        self.progress_bar = ttk.Progressbar(progress, mode="determinate", maximum=100, length=520)
        self.progress_bar.grid(row=0, column=1, sticky=W)
        Label(progress, textvariable=self.progress_text, fg="#555555").grid(row=0, column=2, sticky=W, padx=10)
        Button(progress, text=self.t("cancel_task"), command=self.cancel_task, padx=12).grid(
            row=0, column=3, sticky=W, padx=8
        )

        if self.show_advanced.get():
            advanced = LabelFrame(container, text=self.t("advanced"), padx=10, pady=8)
            advanced.pack(fill=X, pady=(10, 0))
            self._row(advanced, 0, "course_id", Entry(advanced, textvariable=self.course_id, width=28))
            self._row(advanced, 1, "sub_id", Entry(advanced, textvariable=self.sub_id, width=28))
            self._row(advanced, 2, self.t("target_language"), Entry(advanced, textvariable=self.target, width=12))
            self._row(advanced, 3, self.t("api_style"), Entry(advanced, textvariable=self.api_style, width=12))
            self._row(advanced, 4, self.t("model"), Entry(advanced, textvariable=self.model, width=28))
            Checkbutton(advanced, text=self.t("bilingual"), variable=self.bilingual).grid(
                row=5, column=1, sticky=W, pady=(4, 0)
            )
            Label(advanced, text=self.t("keep_default"), fg="#555555").grid(
                row=5, column=2, sticky=W, padx=8
            )

        log_frame = LabelFrame(container, text=self.t("log"), padx=8, pady=8)
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        scrollbar = Scrollbar(log_frame)
        scrollbar.pack(side="right", fill=Y)
        self.log = Text(log_frame, height=5, wrap="word", yscrollcommand=scrollbar.set)
        self.log.pack(fill="both", expand=True)
        scrollbar.config(command=self.log.yview)

        def on_log_mousewheel(event) -> str:
            if self.log is not None:
                self.log.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        def on_log_button4(_event) -> str:
            if self.log is not None:
                self.log.yview_scroll(-1, "units")
            return "break"

        def on_log_button5(_event) -> str:
            if self.log is not None:
                self.log.yview_scroll(1, "units")
            return "break"

        for widget in (self.log, scrollbar, log_frame):
            widget.bind("<MouseWheel>", on_log_mousewheel)
            widget.bind("<Button-4>", on_log_button4)
            widget.bind("<Button-5>", on_log_button5)

        if log_text:
            self._append_log(log_text)

    def _make_scrollable_tab(self, parent: Frame) -> Frame:
        canvas = Canvas(parent, highlightthickness=0, bg=BG_COLOR)
        scrollbar = Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill=Y)
        canvas.pack(side="left", fill="both", expand=True)

        container = Frame(canvas, padx=8, pady=8, bg=BG_COLOR)
        window_id = canvas.create_window((0, 0), window=container, anchor="nw")

        def refresh_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def fit_width(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        def on_mousewheel(event) -> str:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        def on_button4(_event) -> str:
            canvas.yview_scroll(-1, "units")
            return "break"

        def on_button5(_event) -> str:
            canvas.yview_scroll(1, "units")
            return "break"

        def enable_mousewheel(_event=None) -> None:
            canvas.bind_all("<MouseWheel>", on_mousewheel)
            canvas.bind_all("<Button-4>", on_button4)
            canvas.bind_all("<Button-5>", on_button5)

        def disable_mousewheel(_event=None) -> None:
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        container.bind("<Configure>", refresh_scroll_region)
        canvas.bind("<Configure>", fit_width)
        canvas.bind("<Enter>", enable_mousewheel)
        canvas.bind("<Leave>", disable_mousewheel)
        container.bind("<Enter>", enable_mousewheel)
        container.bind("<Leave>", disable_mousewheel)
        return container

    def _simple_label(self, key: str) -> str:
        return SIMPLE_LABELS.get(self.lang, SIMPLE_LABELS["zh"]).get(key, key)

    def _build_simple_tool(self, container: Frame, log_text: str = "") -> None:
        header = Frame(container, bg=BG_COLOR)
        header.pack(fill=X, pady=(0, 10))
        Label(
            header,
            text=self._simple_label("hero_title"),
            bg=BG_COLOR,
            fg=TEXT_COLOR,
            font=UI_FONT_HERO,
        ).pack(anchor="w")
        Label(
            header,
            text=self._simple_label("hero_subtitle"),
            bg=BG_COLOR,
            fg=MUTED_COLOR,
            font=UI_FONT_SMALL,
        ).pack(anchor="w", pady=(4, 0))

        cfg = LabelFrame(container, text=self._simple_label("config_line"), padx=16, pady=12)
        cfg.pack(fill=X)
        for col in (1, 3):
            cfg.grid_columnconfigure(col, weight=1)

        Label(cfg, text=self.t("ui_language")).grid(row=0, column=0, sticky=W, pady=3)
        OptionMenu(cfg, self.language_label, *LANGUAGE_LABELS.values(), command=self.change_language).grid(
            row=0, column=1, sticky=W, pady=3
        )
        Label(cfg, text=self.t("username")).grid(row=0, column=2, sticky=W, padx=(18, 4), pady=3)
        Entry(cfg, textvariable=self.username, width=20).grid(row=0, column=3, sticky=W, pady=3)

        Label(cfg, text=self.t("password")).grid(row=1, column=0, sticky=W, pady=3)
        self.password_entry = Entry(
            cfg,
            textvariable=self.password,
            width=24,
            show="" if self.show_password.get() else "*",
        )
        self.password_entry.grid(row=1, column=1, sticky=W, pady=3)
        Checkbutton(
            cfg,
            text=self.t("show_secret"),
            variable=self.show_password,
            command=self.toggle_secret_visibility,
        ).grid(row=1, column=2, sticky=W, padx=(8, 0), pady=3)

        Label(cfg, text=f"{self.t('api_key')} ({self.t('optional')})").grid(row=2, column=0, sticky=W, pady=3)
        self.api_key_entry = Entry(
            cfg,
            textvariable=self.api_key,
            width=38,
            show="" if self.show_api_key.get() else "*",
        )
        self.api_key_entry.grid(row=2, column=1, columnspan=2, sticky=W, pady=3)
        Checkbutton(
            cfg,
            text=self.t("show_secret"),
            variable=self.show_api_key,
            command=self.toggle_secret_visibility,
        ).grid(row=2, column=3, sticky=W, pady=3)

        Label(cfg, text=f"{self.t('api_base_url')} ({self.t('optional')})").grid(row=3, column=0, sticky=W, pady=3)
        Entry(cfg, textvariable=self.api_base_url, width=48).grid(row=3, column=1, columnspan=3, sticky=W, pady=3)

        Label(cfg, text=self.t("proofread_mode")).grid(row=4, column=0, sticky=W, pady=3)
        OptionMenu(
            cfg,
            self.proofread_mode_label,
            *PROOFREAD_MODE_LABELS.get(self.lang, PROOFREAD_MODE_LABELS["zh"]).values(),
            command=self.change_proofread_mode,
        ).grid(row=4, column=1, sticky=W, pady=3)
        Label(cfg, text=self.t("proofread_hint"), fg="#555555").grid(row=4, column=2, columnspan=2, sticky=W, pady=3)

        Button(cfg, text=self.t("save_config"), command=self.save_config, padx=12).grid(row=5, column=1, sticky=W, pady=(8, 0))
        Button(cfg, text=self.t("test_api"), command=self.test_api, padx=10).grid(row=5, column=2, sticky=W, padx=8, pady=(8, 0))
        Button(cfg, text=self.t("test_login"), command=self.test_login, padx=10).grid(row=5, column=3, sticky=W, pady=(8, 0))

        quick = LabelFrame(container, text=self._simple_label("quick"), padx=16, pady=12)
        quick.pack(fill=X, pady=(10, 0))
        quick.grid_columnconfigure(1, weight=1)
        Label(quick, text=self.t("lecture_url")).grid(row=0, column=0, sticky=W, pady=3)
        Entry(quick, textvariable=self.lecture_url, width=76).grid(row=0, column=1, columnspan=4, sticky="ew", pady=3)
        Label(quick, text=self.t("subtitle_language")).grid(row=1, column=0, sticky=W, pady=3)
        OptionMenu(
            quick,
            self.subtitle_language_label,
            *SUBTITLE_LANGUAGE_LABELS.values(),
            command=self.change_subtitle_language,
        ).grid(row=1, column=1, sticky=W, pady=3)
        primary_button = Button(
            quick,
            text=f"{self._simple_label('primary_action')}  -  {self._simple_label('auto_generate')}",
            command=self.auto_generate,
            padx=22,
            pady=10,
            bg=ACCENT_COLOR,
            fg="white",
            activebackground=ACCENT_DARK,
            activeforeground="white",
            relief="flat",
            cursor="hand2",
        )
        primary_button.grid(
            row=1, column=2, sticky=W, padx=10, pady=3
        )
        Button(quick, text=self.t("open_output"), command=self.open_output_dir, padx=12).grid(
            row=1, column=3, sticky=W, padx=6, pady=3
        )
        Button(quick, text=self._simple_label("potplayer_download"), command=self.open_potplayer_site, padx=12).grid(
            row=1, column=4, sticky=W, padx=6, pady=3
        )
        Label(quick, text=self._simple_label("free_hint"), fg="#555555").grid(
            row=2, column=1, columnspan=4, sticky=W, pady=(2, 4)
        )
        Label(quick, text=self.t("output_dir")).grid(row=3, column=0, sticky=W, pady=3)
        Entry(quick, textvariable=self.output_dir, width=56).grid(row=3, column=1, columnspan=2, sticky=W, pady=3)
        Button(quick, text=self.t("pick_dir"), command=self.pick_output_dir, padx=10).grid(
            row=3, column=3, sticky=W, padx=6, pady=3
        )

        progress = LabelFrame(container, text=self.t("progress"), padx=16, pady=12)
        progress.pack(fill=X, pady=(10, 0))
        progress.grid_columnconfigure(0, weight=1)
        self.progress_bar = ttk.Progressbar(progress, mode="determinate", maximum=100)
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        Label(progress, textvariable=self.progress_text, fg="#555555").grid(row=0, column=1, sticky=W, padx=10)
        Button(progress, text=self.t("cancel_task"), command=self.cancel_task, padx=12).grid(row=0, column=2, sticky=W, padx=8)

        advanced = LabelFrame(container, text=self.t("advanced"), padx=16, pady=12)
        advanced.pack(fill=X, pady=(10, 0))
        Checkbutton(
            advanced,
            text=self.t("hide_advanced") if self.show_advanced.get() else self.t("show_advanced"),
            variable=self.show_advanced,
            command=self.toggle_advanced,
        ).grid(row=0, column=0, sticky=W)
        if self.show_advanced.get():
            self._row(advanced, 1, "course_id", Entry(advanced, textvariable=self.course_id, width=24))
            self._row(advanced, 2, "sub_id", Entry(advanced, textvariable=self.sub_id, width=24))
            self._row(advanced, 3, self.t("target_language"), Entry(advanced, textvariable=self.target, width=12))
            self._row(advanced, 4, self.t("model"), Entry(advanced, textvariable=self.model, width=28))
            Checkbutton(advanced, text=self.t("bilingual"), variable=self.bilingual).grid(row=5, column=1, sticky=W)
            batch = LabelFrame(advanced, text=self.t("batch_replay"), padx=10, pady=8)
            batch.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 0))
            Label(batch, text=self.t("batch_teacher_keyword")).grid(row=0, column=0, sticky=W, pady=3)
            Entry(batch, textvariable=self.batch_teacher_keyword, width=24).grid(row=0, column=1, sticky=W, pady=3)
            Label(batch, text=self.t("batch_course_keyword")).grid(row=0, column=2, sticky=W, padx=(12, 0), pady=3)
            Entry(batch, textvariable=self.batch_course_keyword, width=24).grid(row=0, column=3, sticky=W, pady=3)
            Label(batch, text=self.t("batch_start_date")).grid(row=1, column=0, sticky=W, pady=3)
            Entry(batch, textvariable=self.batch_start_date, width=16).grid(row=1, column=1, sticky=W, pady=3)
            Label(batch, text=self.t("batch_end_date")).grid(row=1, column=2, sticky=W, padx=(12, 0), pady=3)
            Entry(batch, textvariable=self.batch_end_date, width=16).grid(row=1, column=3, sticky=W, pady=3)
            Label(batch, text=self.t("batch_weekday")).grid(row=2, column=0, sticky=W, pady=3)
            Entry(batch, textvariable=self.batch_weekday, width=16).grid(row=2, column=1, sticky=W, pady=3)
            Label(batch, text=self.t("batch_search_hint"), fg="#555555").grid(row=3, column=0, columnspan=4, sticky=W, pady=(2, 4))
            Button(batch, text=self.t("batch_search"), command=self.search_replays, padx=12).grid(row=4, column=0, sticky=W, pady=(4, 0))
            Button(batch, text=self.t("batch_download"), command=self.batch_download_replays, padx=12).grid(row=4, column=1, columnspan=2, sticky=W, padx=8, pady=(4, 0))
            if SELFUSE_ENABLED:
                selfuse = LabelFrame(advanced, text=self.t("selfuse_tools"), padx=10, pady=8)
                selfuse.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(10, 0))
                Label(selfuse, text=self.t("selfuse_hint"), fg="#555555").grid(row=0, column=0, columnspan=3, sticky=W, pady=(0, 4))
                Button(selfuse, text=self.t("selfuse_capture"), command=self.selfuse_capture_media, padx=12).grid(row=1, column=0, sticky=W, pady=(4, 0))
                Button(selfuse, text=self.t("selfuse_download"), command=self.selfuse_download_with_subtitles, padx=12).grid(row=1, column=1, sticky=W, padx=8, pady=(4, 0))
                results = LabelFrame(selfuse, text=self.t("selfuse_results"), padx=10, pady=8)
                results.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
                results.grid_columnconfigure(0, weight=1)
                Label(results, text=self.t("selfuse_results_hint"), fg="#555555").grid(row=0, column=0, sticky=W)

                actions = Frame(results)
                actions.grid(row=1, column=0, sticky=W, pady=(8, 0))
                Button(actions, text=self.t("selfuse_select_all"), command=self.selfuse_select_all, padx=10).pack(side="left")
                Button(actions, text=self.t("selfuse_clear_all"), command=self.selfuse_clear_all, padx=10).pack(side="left", padx=8)
                Button(actions, text=self.t("selfuse_export_all"), command=self.selfuse_export_all, padx=10).pack(side="left")
                Button(actions, text=self.t("selfuse_export_selected"), command=self.selfuse_export_selected, padx=10).pack(side="left", padx=8)
                Button(actions, text=self.t("selfuse_download_selected"), command=self.selfuse_download_selected, padx=12).pack(side="left")

                Label(results, textvariable=self.selfuse_results_summary, fg="#555555").grid(row=2, column=0, sticky=W, pady=(6, 6))

                list_host = Frame(results)
                list_host.grid(row=3, column=0, sticky="ew")
                list_canvas = Canvas(list_host, height=220, highlightthickness=0, bg=PANEL_BG)
                list_scroll = Scrollbar(list_host, orient="vertical", command=list_canvas.yview)
                list_canvas.configure(yscrollcommand=list_scroll.set)
                list_canvas.pack(side="left", fill="both", expand=True)
                list_scroll.pack(side="right", fill=Y)

                inner = Frame(list_canvas)
                window_id = list_canvas.create_window((0, 0), window=inner, anchor="nw")

                def _refresh_selfuse_scroll(_event=None) -> None:
                    list_canvas.configure(scrollregion=list_canvas.bbox("all"))

                def _fit_selfuse_width(event) -> None:
                    list_canvas.itemconfigure(window_id, width=event.width)

                inner.bind("<Configure>", _refresh_selfuse_scroll)
                list_canvas.bind("<Configure>", _fit_selfuse_width)
                self.selfuse_results_frame = inner
                self.selfuse_results_canvas = list_canvas
                self._render_selfuse_results()

        self._add_log_box(container, height=8, initial=log_text)

    def _build_guide_tab(self, container: Frame) -> None:
        top = Frame(container)
        top.pack(fill=X, pady=(0, 8))
        Label(top, text=self.t("ui_language")).pack(side="left")
        OptionMenu(
            top,
            self.guide_language_label,
            *LANGUAGE_LABELS.values(),
            command=self.change_guide_language,
        ).pack(side="left", padx=8)
        Button(
            top,
            text=self._simple_label("potplayer_download"),
            command=self.open_potplayer_site,
            padx=12,
            pady=5,
        ).pack(side="left", padx=8)

        scrollbar = Scrollbar(container)
        scrollbar.pack(side="right", fill=Y)
        guide = Text(container, wrap="word", yscrollcommand=scrollbar.set, padx=10, pady=10)
        guide.pack(fill="both", expand=True)
        scrollbar.config(command=guide.yview)
        guide.insert("1.0", GUIDE_TEXT.get(self.guide_lang, GUIDE_TEXT["zh"]))
        guide.config(state="disabled")

    def _build_log_tab(self, container: Frame, log_text: str = "") -> None:
        top = Frame(container)
        top.pack(fill=X, pady=(0, 8))
        Button(top, text=self._simple_label("refresh_log"), command=self.refresh_log_display, padx=12).pack(side="left")
        Button(top, text=self.t("open_log"), command=self.open_log, padx=12).pack(side="left", padx=8)
        Button(top, text=self._simple_label("clear_log"), command=self.clear_log_display, padx=12).pack(side="left")
        Label(top, text=self._simple_label("log_hint"), fg="#555555").pack(side="left", padx=12)

        initial = log_text or self._read_log_file_tail()
        self.log = self._add_log_box(container, height=20, initial=initial)

    def _read_log_file_tail(self, max_chars: int = 40000) -> str:
        try:
            if not LOG_PATH.exists():
                return ""
            raw = LOG_PATH.read_text(encoding="utf-8", errors="replace")
            if len(raw) > max_chars:
                return raw[-max_chars:]
            return raw
        except Exception:
            return ""

    def refresh_log_display(self) -> None:
        if self.log is None:
            return
        self.log.delete("1.0", END)
        self.log.insert("1.0", self._read_log_file_tail())
        self.log.see(END)

    def clear_log_display(self) -> None:
        for log_widget in list(self.log_widgets):
            try:
                log_widget.delete("1.0", END)
            except Exception:
                pass

    def _add_log_box(self, parent: Frame, height: int, initial: str = "") -> Text:
        log_frame = LabelFrame(parent, text=self.t("log"), padx=10, pady=10)
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        scrollbar = Scrollbar(log_frame)
        scrollbar.pack(side="right", fill=Y)
        log_widget = Text(
            log_frame,
            height=height,
            wrap="word",
            yscrollcommand=scrollbar.set,
            bg=LOG_BG,
            fg=LOG_FG,
            insertbackground=LOG_FG,
            relief="flat",
            padx=10,
            pady=8,
        )
        log_widget.pack(fill="both", expand=True)
        scrollbar.config(command=log_widget.yview)
        self._bind_log_mousewheel(log_widget, scrollbar, log_frame)
        self.log_widgets.append(log_widget)
        if initial:
            log_widget.insert(END, initial)
            log_widget.see(END)
        return log_widget

    def _bind_log_mousewheel(self, log_widget, scrollbar, log_frame) -> None:
        def on_log_mousewheel(event) -> str:
            log_widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        def on_log_button4(_event) -> str:
            log_widget.yview_scroll(-1, "units")
            return "break"

        def on_log_button5(_event) -> str:
            log_widget.yview_scroll(1, "units")
            return "break"

        for widget in (log_widget, scrollbar, log_frame):
            widget.bind("<MouseWheel>", on_log_mousewheel)
            widget.bind("<Button-4>", on_log_button4)
            widget.bind("<Button-5>", on_log_button5)

    def _polish_tree(self, widget) -> None:
        for child in widget.winfo_children():
            cls = child.winfo_class()
            try:
                if cls in {"Frame", "Canvas"}:
                    child.configure(bg=BG_COLOR)
                elif cls == "Labelframe":
                    child.configure(bg=PANEL_BG, fg=TEXT_COLOR, relief="solid", bd=1)
                elif cls == "Label":
                    parent_cls = child.master.winfo_class() if child.master else ""
                    bg = PANEL_BG if parent_cls == "Labelframe" else BG_COLOR
                    child.configure(bg=bg, fg=TEXT_COLOR)
                elif cls == "Button":
                    if child.cget("bg") != ACCENT_COLOR:
                        child.configure(
                            bg="#eef4ff",
                            fg=ACCENT_DARK,
                            activebackground="#dbeafe",
                            activeforeground=ACCENT_DARK,
                            relief="flat",
                            bd=0,
                            padx=max(int(child.cget("padx") or 0), 10),
                            pady=max(int(child.cget("pady") or 0), 5),
                            cursor="hand2",
                        )
                elif cls == "Entry":
                    child.configure(bg=ENTRY_BG, fg=TEXT_COLOR, relief="solid", bd=1)
                elif cls == "Menubutton":
                    child.configure(
                        bg="#eef4ff",
                        fg=ACCENT_DARK,
                        activebackground="#dbeafe",
                        activeforeground=ACCENT_DARK,
                        relief="flat",
                        bd=0,
                        padx=10,
                        pady=5,
                        cursor="hand2",
                    )
                elif cls == "Checkbutton":
                    parent_cls = child.master.winfo_class() if child.master else ""
                    child.configure(
                        bg=PANEL_BG if parent_cls == "Labelframe" else BG_COLOR,
                        fg=TEXT_COLOR,
                        activebackground=PANEL_BG,
                    )
                elif cls == "Text" and child not in self.log_widgets:
                    child.configure(bg=PANEL_BG, fg=TEXT_COLOR, relief="flat")
            except Exception:
                pass
            self._polish_tree(child)

    def _row(self, parent: Frame, row: int, label: str, widget) -> None:
        Label(parent, text=label, width=16, anchor="e").grid(row=row, column=0, sticky=W, pady=3)
        widget.grid(row=row, column=1, sticky=W, pady=3)

    def _current_log_text(self) -> str:
        for log_widget in self.log_widgets:
            try:
                return log_widget.get("1.0", END)
            except Exception:
                continue
        return ""

    def change_language(self, label: str) -> None:
        next_lang = LANGUAGE_CODES.get(label, "zh")
        if next_lang == self.lang:
            return
        log_text = self._current_log_text()
        self.lang = next_lang
        self.language_label.set(LANGUAGE_LABELS[self.lang])
        self._build(log_text=log_text)

    def change_guide_language(self, label: str) -> None:
        next_lang = LANGUAGE_CODES.get(label, "zh")
        if next_lang == self.guide_lang:
            return
        log_text = self._current_log_text()
        self.guide_lang = next_lang
        self.guide_language_label.set(LANGUAGE_LABELS[self.guide_lang])
        self._build(log_text=log_text)

    def change_subtitle_language(self, label: str) -> None:
        code = SUBTITLE_LANGUAGE_CODES.get(label, "ru")
        self.target.set(code)
        self.subtitle_language_label.set(SUBTITLE_LANGUAGE_LABELS.get(code, label))

    def change_proofread_mode(self, label: str) -> None:
        code = proofread_mode_code(self.lang, label)
        self.proofread_mode.set(code)
        self.proofread_mode_label.set(proofread_mode_label(self.lang, code))

    def toggle_advanced(self) -> None:
        log_text = self._current_log_text()
        self._build(log_text=log_text)

    def toggle_secret_visibility(self) -> None:
        if self.password_entry is not None:
            self.password_entry.config(show="" if self.show_password.get() else "*")
        if self.api_key_entry is not None:
            self.api_key_entry.config(show="" if self.show_api_key.get() else "*")

    def save_config(self, show_message: bool = True) -> None:
        values = _read_env()
        values["LOOK_TONGJI_GUI_LANG"] = self.lang
        values["LOOK_TONGJI_GUIDE_LANG"] = self.guide_lang
        values["TONGJI_USERNAME"] = self.username.get().strip()
        values["TONGJI_PASSWORD"] = self.password.get().strip()
        if self.api_key.get().strip():
            values["OPENAI_API_KEY"] = self.api_key.get().strip()
        if self.api_base_url.get().strip():
            values["OPENAI_BASE_URL"] = self.api_base_url.get().strip()
        if self.api_style.get().strip():
            values["OPENAI_API_STYLE"] = self.api_style.get().strip()
        if self.model.get().strip():
            values["OPENAI_TRANSLATION_MODEL"] = self.model.get().strip()
        values["LOOK_TONGJI_PROOFREAD_MODE"] = self.proofread_mode.get().strip() or "local"
        values["LOOK_TONGJI_BATCH_TEACHER"] = self.batch_teacher_keyword.get().strip()
        values["LOOK_TONGJI_BATCH_COURSE"] = self.batch_course_keyword.get().strip()
        values["LOOK_TONGJI_BATCH_START_DATE"] = self.batch_start_date.get().strip()
        values["LOOK_TONGJI_BATCH_END_DATE"] = self.batch_end_date.get().strip()
        values["LOOK_TONGJI_BATCH_WEEKDAY"] = self.batch_weekday.get().strip()
        _write_env(values)
        _write_app_log(f"Saved config to {ENV_PATH}")
        if show_message:
            messagebox.showinfo(self.t("saved_title"), f"{self.t('saved_body')}\n{ENV_PATH}")

    def pick_srt(self) -> None:
        path = filedialog.askopenfilename(
            title=self.t("pick_srt_title"),
            filetypes=[("SRT subtitles", "*.srt"), ("All files", "*.*")],
        )
        if path:
            self.srt_path.set(path)

    def pick_translated_srt(self) -> None:
        path = filedialog.askopenfilename(
            title=self.t("pick_translated_title"),
            filetypes=[("SRT subtitles", "*.srt"), ("All files", "*.*")],
        )
        if path:
            self.translated_srt_path.set(path)

    def pick_video(self) -> None:
        path = filedialog.askopenfilename(
            title=self.t("pick_video"),
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.mov *.avi *.wmv *.m4v"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.video_path.set(path)

    def pick_final_srt(self) -> None:
        path = filedialog.askopenfilename(
            title=self.t("pick_final_srt"),
            filetypes=[("SRT subtitles", "*.srt"), ("All files", "*.*")],
        )
        if path:
            self.final_srt_path.set(path)

    def pick_output_dir(self) -> None:
        path = filedialog.askdirectory(title=self.t("pick_output_title"))
        if path:
            self.output_dir.set(path)

    def _base_cmd(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--cli"]
        return [sys.executable, str(CLI_PATH)]

    def _selfuse_cmd_base(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--selfuse-cli"]
        return [sys.executable, str(SELFUSE_HELPER_PATH)]

    def _proofread_args(self) -> list[str]:
        mode = self.proofread_mode.get().strip() or "local"
        args = ["--proofread-mode", mode]
        if mode == "ai":
            args += ["--proofread-model", self.model.get().strip() or "gpt-4.1-mini"]
        return args

    def _source_args(self) -> list[str]:
        args: list[str] = []
        if self.lecture_url.get().strip():
            args += ["--lecture-url", self.lecture_url.get().strip()]
        if self.course_id.get().strip():
            args += ["--course-id", self.course_id.get().strip()]
        if self.sub_id.get().strip():
            args += ["--sub-id", self.sub_id.get().strip()]
        return args

    def _selfuse_source_args(self) -> list[str]:
        args: list[str] = []
        if self.lecture_url.get().strip():
            args += ["--page-url", self.lecture_url.get().strip()]
        if self.course_id.get().strip():
            args += ["--course-id", self.course_id.get().strip()]
        if self.sub_id.get().strip():
            args += ["--sub-id", self.sub_id.get().strip()]
        return args

    def _batch_search_args(self) -> list[str]:
        start_date = self.batch_start_date.get().strip()
        end_date = self.batch_end_date.get().strip()
        if not start_date or not end_date:
            return []
        args = [
            "--start-date",
            start_date,
            "--end-date",
            end_date,
        ]
        if self.batch_teacher_keyword.get().strip():
            args += ["--teacher-keyword", self.batch_teacher_keyword.get().strip()]
        if self.batch_course_keyword.get().strip():
            args += ["--course-keyword", self.batch_course_keyword.get().strip()]
        if self.batch_weekday.get().strip():
            args += ["--weekday", self.batch_weekday.get().strip()]
        return args

    def _format_selfuse_replay_item(self, index: int, item: dict[str, object]) -> str:
        date_text = str(item.get("date") or "").strip()
        title = str(item.get("title") or item.get("course_name") or "").strip()
        teacher = str(item.get("teacher") or item.get("lecturer_name") or "").strip()
        course_id = str(item.get("course_id") or "").strip()
        sub_id = str(item.get("sub_id") or "").strip()
        status_label = str(item.get("status_label") or "").strip()
        parts = [f"{index}. {date_text}"]
        if title:
            parts.append(title)
        if teacher:
            parts.append(teacher)
        if status_label:
            parts.append(status_label)
        head = " | ".join(part for part in parts if part)
        tail = f"course_id={course_id}  sub_id={sub_id}"
        return f"{head}\n{tail}"

    def _update_selfuse_results_summary(self) -> None:
        selected = sum(1 for var in self.selfuse_replay_vars if var.get())
        total = len(self.selfuse_replay_items)
        self.selfuse_results_summary.set(self.t("selfuse_results_summary").format(total=total, selected=selected))

    def _render_selfuse_results(self) -> None:
        frame = self.selfuse_results_frame
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()

        self.selfuse_replay_vars = []
        if not self.selfuse_replay_items:
            Label(frame, text=self.t("selfuse_no_results"), fg="#555555", justify="left", anchor="w").pack(
                fill=X, anchor="w", pady=(2, 4)
            )
            self._update_selfuse_results_summary()
            self._polish_tree(frame)
            if self.selfuse_results_canvas is not None:
                self.selfuse_results_canvas.configure(scrollregion=self.selfuse_results_canvas.bbox("all"))
            return

        for index, item in enumerate(self.selfuse_replay_items, start=1):
            var = BooleanVar(value=False)
            self.selfuse_replay_vars.append(var)
            Checkbutton(
                frame,
                text=self._format_selfuse_replay_item(index, item),
                variable=var,
                justify="left",
                anchor="w",
                wraplength=900,
                command=self._update_selfuse_results_summary,
            ).pack(fill=X, anchor="w", pady=2)

        self._update_selfuse_results_summary()
        self._polish_tree(frame)
        if self.selfuse_results_canvas is not None:
            self.selfuse_results_canvas.configure(scrollregion=self.selfuse_results_canvas.bbox("all"))

    def _load_selfuse_replay_json(self, path: str) -> None:
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_file():
            return
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            _write_app_log(f"Failed to load replay JSON {candidate}: {type(exc).__name__}: {exc}")
            return
        if not isinstance(payload, list):
            _write_app_log(f"Replay JSON is not a list: {candidate}")
            return
        self.selfuse_replay_items = [dict(item) for item in payload if isinstance(item, dict)]
        self.selfuse_last_search_json = str(candidate)
        self._render_selfuse_results()
        self._append_log(f"[GUI] Loaded {len(self.selfuse_replay_items)} replay item(s): {candidate}\n")

    def _capture_replay_search_output(self, text: str) -> None:
        match = re.search(r"\[SearchReplay\]\s+Output:\s*([A-Za-z]:\\[^\r\n]+?\.json)", text)
        if match:
            self.selfuse_last_search_json = match.group(1).strip()

    def _selected_selfuse_replay_items(self) -> list[dict[str, object]]:
        selected: list[dict[str, object]] = []
        for item, var in zip(self.selfuse_replay_items, self.selfuse_replay_vars):
            if var.get():
                selected.append(dict(item))
        return selected

    def selfuse_select_all(self) -> None:
        for var in self.selfuse_replay_vars:
            var.set(True)
        self._update_selfuse_results_summary()

    def selfuse_clear_all(self) -> None:
        for var in self.selfuse_replay_vars:
            var.set(False)
        self._update_selfuse_results_summary()

    def _selfuse_default_export_path(self, *, selected_only: bool) -> Path:
        base_dir = Path(self.output_dir.get().strip() or ".").expanduser().resolve()
        base_dir.mkdir(parents=True, exist_ok=True)
        if self.selfuse_last_search_json:
            source_path = Path(self.selfuse_last_search_json).expanduser().resolve()
            if not selected_only:
                return source_path
            return source_path.with_name(source_path.stem + "_selected.json")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = "_selected" if selected_only else ""
        return base_dir / f"selfuse_replays_{stamp}{suffix}.json"

    def _export_selfuse_items(self, items: list[dict[str, object]], *, selected_only: bool) -> Path | None:
        if selected_only and not items:
            messagebox.showwarning(self.t("selfuse_selected_missing_title"), self.t("selfuse_selected_missing_body"))
            return None
        default_path = self._selfuse_default_export_path(selected_only=selected_only)
        chosen = filedialog.asksaveasfilename(
            title=self.t("selfuse_export_selected") if selected_only else self.t("selfuse_export_all"),
            defaultextension=".json",
            initialdir=str(default_path.parent),
            initialfile=default_path.name,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not chosen:
            return None
        output_path = Path(chosen).expanduser().resolve()
        output_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        messagebox.showinfo(self.t("selfuse_export_done_title"), f"{self.t('selfuse_export_done_body')}\n{output_path}")
        return output_path

    def _write_selfuse_items(self, items: list[dict[str, object]], *, selected_only: bool) -> Path | None:
        if selected_only and not items:
            messagebox.showwarning(self.t("selfuse_selected_missing_title"), self.t("selfuse_selected_missing_body"))
            return None
        output_path = self._selfuse_default_export_path(selected_only=selected_only)
        output_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._append_log(f"[GUI] Saved replay list: {output_path}\n")
        return output_path

    def selfuse_export_all(self) -> None:
        self._export_selfuse_items([dict(item) for item in self.selfuse_replay_items], selected_only=False)

    def selfuse_export_selected(self) -> None:
        self._export_selfuse_items(self._selected_selfuse_replay_items(), selected_only=True)

    def selfuse_download_selected(self) -> None:
        self.save_config(show_message=False)
        items = self._selected_selfuse_replay_items()
        export_path = self._write_selfuse_items(items, selected_only=True)
        if export_path is None:
            return
        target = self.target.get().strip() or "zh"
        translation_mode = "none"
        if target.lower() not in {"zh", "cn", "chinese"}:
            translation_mode = "api" if self.api_key.get().strip() else "free"
        cmd = self._selfuse_cmd_base() + [
            "batch-browser-download-subtitle",
            "--input-json",
            str(export_path),
            "--output-dir",
            self.output_dir.get().strip(),
            "--target",
            target,
            "--translation-mode",
            translation_mode,
            "--model",
            self.model.get().strip() or "gpt-4.1-mini",
            "--sync-subtitle",
        ] + self._proofread_args()
        self.run_command(cmd, task="selfuse_batch_download")

    def transcribe(self) -> None:
        self.save_config(show_message=False)
        args = self._source_args()
        if not args:
            messagebox.showwarning(self.t("missing_source_title"), self.t("missing_source_body"))
            return
        cmd = self._base_cmd() + ["transcribe"] + args + ["--output-dir", self.output_dir.get().strip()] + self._proofread_args()
        self.run_command(cmd, task="transcribe")

    def download_video(self) -> None:
        self.save_config(show_message=False)
        args = self._source_args()
        if not args:
            messagebox.showwarning(self.t("missing_source_title"), self.t("missing_source_body"))
            return
        cmd = self._base_cmd() + ["download-video"] + args + ["--output-dir", self.output_dir.get().strip()]
        self.run_command(cmd, task="download_video")

    def search_replays(self) -> None:
        self.save_config(show_message=False)
        args = self._batch_search_args()
        if not args:
            messagebox.showwarning(self.t("missing_batch_range_title"), self.t("missing_batch_range_body"))
            return
        cmd = self._base_cmd() + ["search-replay-range", *args, "--output-dir", self.output_dir.get().strip()]
        self.run_command(cmd, task="batch_search")

    def batch_download_replays(self) -> None:
        self.save_config(show_message=False)
        args = self._batch_search_args()
        if not args:
            messagebox.showwarning(self.t("missing_batch_range_title"), self.t("missing_batch_range_body"))
            return
        target = self.target.get().strip() or "zh"
        cmd = self._base_cmd() + [
            "batch-download-replays",
            *args,
            "--output-dir",
            self.output_dir.get().strip(),
            "--target",
            target,
        ] + self._proofread_args()
        if target.lower() not in {"zh", "cn", "chinese"}:
            if self.api_key.get().strip():
                cmd += ["--model", self.model.get().strip() or "gpt-4.1-mini"]
            else:
                cmd += ["--translation-mode", "free"]
        self.run_command(cmd, task="batch_download_replays")

    def selfuse_capture_media(self) -> None:
        self.save_config(show_message=False)
        args = self._selfuse_source_args()
        if not args:
            messagebox.showwarning(self.t("missing_source_title"), self.t("missing_source_body"))
            return
        cmd = self._selfuse_cmd_base() + [
            "catch-media",
            *args,
            "--output-dir",
            self.output_dir.get().strip(),
            "--browser-fallback",
        ]
        if self.lecture_url.get().strip():
            cmd.append("--interactive")
        self.run_command(cmd, task="selfuse_capture")

    def selfuse_download_with_subtitles(self) -> None:
        self.save_config(show_message=False)
        args = self._selfuse_source_args()
        if not args:
            messagebox.showwarning(self.t("missing_source_title"), self.t("missing_source_body"))
            return
        target = self.target.get().strip() or "zh"
        translation_mode = "none"
        if target.lower() not in {"zh", "cn", "chinese"}:
            translation_mode = "api" if self.api_key.get().strip() else "free"
        cmd = self._selfuse_cmd_base() + [
            "browser-download-subtitle",
            *args,
            "--output-dir",
            self.output_dir.get().strip(),
            "--target",
            target,
            "--translation-mode",
            translation_mode,
            "--model",
            self.model.get().strip() or "gpt-4.1-mini",
            "--sync-subtitle",
        ] + self._proofread_args()
        if self.lecture_url.get().strip():
            cmd += ["--browser-fallback", "--interactive"]
        self.run_command(cmd, task="selfuse_download")

    def prepare_manual_assets(self) -> None:
        self.save_config(show_message=False)
        args = self._source_args()
        if not args:
            messagebox.showwarning(self.t("missing_source_title"), self.t("missing_source_body"))
            return
        cmd = self._base_cmd() + [
            "auto-potplayer",
            *args,
            "--target",
            "zh",
            "--output-dir",
            self.output_dir.get().strip(),
            "--model",
            self.model.get().strip() or "gpt-4.1-mini",
        ] + self._proofread_args()
        self.run_command(cmd, task="manual_prepare")

    def auto_generate(self) -> None:
        target = (self.target.get().strip() or "ru").lower()
        if target in {"zh", "cn", "chinese"}:
            self.prepare_manual_assets()
        elif self.api_key.get().strip():
            self.one_click()
        else:
            self.free_one_click()

    def one_click(self) -> None:
        self.save_config(show_message=False)
        args = self._source_args()
        if not args:
            messagebox.showwarning(self.t("missing_source_title"), self.t("missing_source_body"))
            return
        cmd = self._base_cmd() + [
            "auto-potplayer",
            *args,
            "--target",
            self.target.get().strip() or "ru",
            "--output-dir",
            self.output_dir.get().strip(),
            "--model",
            self.model.get().strip() or "gpt-4.1-mini",
        ] + self._proofread_args()
        self.run_command(cmd, task="one_click")

    def free_one_click(self) -> None:
        self.save_config(show_message=False)
        args = self._source_args()
        if not args:
            messagebox.showwarning(self.t("missing_source_title"), self.t("missing_source_body"))
            return
        cmd = self._base_cmd() + [
            "auto-potplayer",
            *args,
            "--target",
            self.target.get().strip() or "ru",
            "--output-dir",
            self.output_dir.get().strip(),
            "--translation-mode",
            "free",
        ] + self._proofread_args()
        self.run_command(cmd, task="free_one_click")

    def subtitle(self) -> None:
        self.save_config(show_message=False)
        cmd = self._base_cmd() + ["subtitle"]
        if self.srt_path.get().strip():
            cmd += ["--srt", self.srt_path.get().strip()]
        else:
            args = self._source_args()
            if not args:
                messagebox.showwarning(self.t("missing_source_title"), self.t("missing_source_or_srt"))
                return
            cmd += args + ["--output-dir", self.output_dir.get().strip()] + self._proofread_args()
        cmd += ["--target", self.target.get().strip() or "ru"]
        if self.output_dir.get().strip():
            cmd += ["--subtitle-output-dir", self.output_dir.get().strip()]
        if not self.bilingual.get():
            cmd.append("--no-bilingual")
        self.run_command(cmd, task="subtitle")

    def subtitle_pack(self) -> None:
        if not self.srt_path.get().strip():
            messagebox.showwarning(self.t("missing_source_srt_title"), self.t("missing_source_srt_body"))
            return
        cmd = self._base_cmd() + [
            "subtitle-pack",
            "--srt",
            self.srt_path.get().strip(),
            "--target",
            self.target.get().strip() or "ru",
            "--output-dir",
            self.output_dir.get().strip(),
        ]
        self.run_command(cmd, task="subtitle_pack")

    def subtitle_import(self) -> None:
        if not self.srt_path.get().strip():
            messagebox.showwarning(self.t("missing_source_srt_title"), self.t("missing_source_srt_body"))
            return
        if not self.translated_srt_path.get().strip():
            messagebox.showwarning(self.t("missing_translation_title"), self.t("missing_translation_body"))
            return
        source = Path(self.srt_path.get().strip())
        target = self.target.get().strip() or "ru"
        output = Path(self.output_dir.get().strip() or ".") / f"{source.stem}.{target}.normalized.srt"
        self.final_srt_path.set(str(output))
        cmd = self._base_cmd() + [
            "subtitle-import",
            "--source-srt",
            self.srt_path.get().strip(),
            "--translated-srt",
            self.translated_srt_path.get().strip(),
            "--target",
            target,
            "--output",
            str(output),
        ]
        if not self.bilingual.get():
            cmd.append("--no-bilingual")
        self.run_command(cmd, task="subtitle_import")

    def player_pack(self) -> None:
        if not self.video_path.get().strip():
            messagebox.showwarning(self.t("missing_video_title"), self.t("missing_video_body"))
            return
        final_srt = self.final_srt_path.get().strip() or self.translated_srt_path.get().strip() or self.srt_path.get().strip()
        if not final_srt:
            messagebox.showwarning(self.t("missing_final_srt_title"), self.t("missing_final_srt_body"))
            return
        cmd = self._base_cmd() + [
            "player-pack",
            "--video-file",
            self.video_path.get().strip(),
            "--srt",
            final_srt,
            "--output-dir",
            self.output_dir.get().strip(),
        ]
        self.run_command(cmd, task="player_pack")

    def test_api(self) -> None:
        self.save_config(show_message=False)
        cmd = self._base_cmd() + [
            "api-test",
            "--target",
            self.target.get().strip() or "ru",
            "--model",
            self.model.get().strip() or "gpt-4.1-mini",
        ]
        self.progress_text.set(self.t("api_test_running"))
        self.run_command(cmd, task="api_test")

    def check_environment(self) -> None:
        self.save_config(show_message=False)
        self.run_command(self._base_cmd() + ["doctor"], task="doctor")

    def test_login(self) -> None:
        self.save_config(show_message=False)
        self.run_command(self._base_cmd() + ["login-test"], task="login_test")

    def run_command(self, cmd: list[str], task: str = "") -> None:
        if self.running:
            messagebox.showinfo(self.t("running_title"), self.t("running_body"))
            return
        self.running = True
        self.current_task = task
        self.last_error_summary = ""
        if task == "batch_search":
            self.selfuse_last_search_json = ""
        self.cancel_requested = False
        self._start_progress(task)
        _write_app_log("Running command: " + " ".join(cmd))
        self._append_log("\n$ " + " ".join(f'"{x}"' if " " in x else x for x in cmd) + "\n")
        thread = threading.Thread(target=self._worker, args=(cmd,), daemon=True)
        thread.start()

    def _worker(self, cmd: list[str]) -> None:
        env = _bundled_env(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        try:
            popen_kwargs = {}
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(
                cmd,
                cwd=str(Path.cwd()),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                **popen_kwargs,
            )
            self.current_proc = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                if self.cancel_requested:
                    break
                _write_app_log(line)
                self.log_queue.put(("log", line))
            if self.cancel_requested and proc.poll() is None:
                self._stop_process_tree(proc)
                code = proc.poll()
                if code is None:
                    try:
                        code = proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        code = proc.wait()
            else:
                code = proc.wait()
            _write_app_log(f"Command finished with exit code {code}")
            self.log_queue.put(("cancelled", code) if self.cancel_requested else ("done", code))
        except Exception as exc:
            _write_app_log("Worker exception:\n" + traceback.format_exc())
            self.log_queue.put(("error", f"{type(exc).__name__}: {exc}"))
        finally:
            self.current_proc = None
            self.running = False

    def _task_start_percent(self, task: str) -> int:
        return {
            "api_test": 15,
            "doctor": 20,
            "login_test": 20,
            "subtitle_pack": 40,
            "subtitle_import": 35,
            "player_pack": 20,
            "subtitle": 10,
            "download_video": 10,
            "one_click": 5,
            "free_one_click": 5,
            "manual_prepare": 5,
            "transcribe": 8,
            "batch_search": 5,
            "batch_download_replays": 5,
            "selfuse_capture": 5,
            "selfuse_download": 5,
            "selfuse_batch_download": 5,
        }.get(task, 10)

    def _start_progress(self, task: str = "") -> None:
        start = self._task_start_percent(task)
        self.progress_text.set(f"{start}%")
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.config(mode="determinate", maximum=100, value=start)

    def _set_progress_percent(self, percent: int, label: str | None = None) -> None:
        percent = max(0, min(100, int(percent)))
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.config(mode="determinate", maximum=100, value=percent)
        self.progress_text.set(label or f"{percent}%")

    def _set_progress_fraction(self, current: int, total: int) -> None:
        if total <= 0 or self.progress_bar is None:
            return
        self.progress_bar.stop()
        percent = int(current * 100 / total)
        self.progress_bar.config(mode="determinate", maximum=100, value=percent)
        self.progress_text.set(f"{percent}% ({current}/{total})")

    def _finish_progress(self, code: int) -> None:
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.config(mode="determinate", maximum=100, value=100 if code == 0 else 0)
        self.progress_text.set(self.t("progress_done") if code == 0 else self.t("progress_failed"))
        task = self.current_task
        self.current_task = ""
        if task == "batch_search" and SELFUSE_ENABLED and self.selfuse_last_search_json:
            self._load_selfuse_replay_json(self.selfuse_last_search_json)
        if task == "api_test":
            if code == 0:
                messagebox.showinfo(self.t("test_api"), self.t("api_test_ok"))
            else:
                messagebox.showerror(self.t("test_api"), f"{self.t('api_test_failed')}\n{LOG_PATH}")
        elif task == "doctor":
            messagebox.showinfo(self.t("check_env"), f"{self.t('env_check_done')}\n{LOG_PATH}")
        elif task == "login_test":
            if code == 0:
                messagebox.showinfo(self.t("test_login"), self.t("login_check_done"))
            else:
                detail = self.last_error_summary or self.t("progress_failed")
                messagebox.showerror(self.t("test_login"), f"{detail}\n\n{LOG_PATH}")
        elif task in {"one_click", "free_one_click", "manual_prepare", "selfuse_download"} and code == 0:
            self._show_final_result()

    def _show_final_result(self) -> None:
        lines = [self.t("progress_done")]
        if self.video_path.get().strip():
            lines.append(f"Video: {self.video_path.get().strip()}")
        if self.final_srt_path.get().strip():
            lines.append(f"SRT: {self.final_srt_path.get().strip()}")
        elif self.srt_path.get().strip():
            lines.append(f"SRT: {self.srt_path.get().strip()}")
        lines.append("")
        lines.append("PotPlayer: keep the mp4 and srt in the same folder with the same name.")
        messagebox.showinfo(self.t("progress_done"), "\n".join(lines))

    def _cancel_progress(self) -> None:
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.config(mode="determinate", maximum=100, value=0)
        self.progress_text.set(self.t("progress_cancelled"))
        self.current_task = ""

    def cancel_task(self) -> None:
        if not self.running:
            self._cancel_progress()
            return
        self.cancel_requested = True
        self.progress_text.set(self.t("progress_cancelled"))
        self._stop_process_tree(self.current_proc)
        _write_app_log("Cancel requested by user")

    def _stop_process_tree(self, proc: subprocess.Popen | None) -> None:
        if proc is None or proc.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                return
            except Exception as exc:
                _write_app_log(f"taskkill failed: {type(exc).__name__}: {exc}")
        try:
            proc.terminate()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _append_log(self, text: str) -> None:
        for log_widget in list(self.log_widgets):
            try:
                log_widget.insert(END, text)
                log_widget.see(END)
            except Exception:
                pass

    def _capture_progress(self, text: str) -> None:
        if self.current_task == "selfuse_batch_download":
            batch = re.search(r"\[SelfUseBatch\]\s+Progress:\s*(\d+)\s*/\s*(\d+)", text)
            if batch:
                current, total = int(batch.group(1)), int(batch.group(2))
                self._set_progress_fraction(current, total)
                return
            if "[SelfUse] Progress:" in text:
                return

        if self.current_task in {"one_click", "free_one_click", "manual_prepare", "selfuse_download"}:
            auto = re.search(r"\[Auto\]\s+Progress:\s*(\d+)\s*/\s*4", text)
            if auto:
                mapped = {1: 8, 2: 38, 3: 90, 4: 100}
                percent = mapped.get(int(auto.group(1)), 5)
                self._set_progress_percent(percent)
                return

            selfuse = re.search(r"\[SelfUse\]\s+Progress:\s*(\d+)\s*/\s*4", text)
            if selfuse:
                mapped = {1: 10, 2: 35, 3: 70, 4: 95}
                percent = mapped.get(int(selfuse.group(1)), 5)
                self._set_progress_percent(percent)
                return

            video = re.search(r"\[VideoDownload\]\s+Progress:\s*(\d+)\s*/\s*100", text)
            if video:
                percent = 10 + int(int(video.group(1)) * 25 / 100)
                self._set_progress_percent(percent, f"{percent}% 下载视频")
                return

            match = re.search(r"\[Transcriber\]\s+Download progress:\s*(\d+)\s*/\s*(\d+)", text)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                percent = 38 + int(current * 8 / max(total, 1))
                self._set_progress_percent(percent, f"{percent}% 下载音频")
                return

            match = re.search(r"\[Transcriber\]\s+Upload progress:\s*(\d+)\s*/\s*(\d+)", text)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                percent = 52 + int(current * 6 / max(total, 1))
                self._set_progress_percent(percent, f"{percent}% 上传音频识别")
                return

            match = re.search(r"\[Transcriber\]\s+ASR polling:\s*(\d+)\s*/\s*(\d+)", text)
            if match:
                current = int(match.group(1))
                percent = 58 + min(9, int(current * 9 / 120))
                self._set_progress_percent(percent, f"{percent}% 等待字幕识别 {current}秒")
                return

            match = re.search(r"\[Subtitle\]\s+Progress:\s*(\d+)\s*/\s*(\d+)", text)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                percent = 70 + int(current * 18 / max(total, 1))
                self._set_progress_percent(percent, f"{percent}% 翻译字幕")
                return

            match = re.search(r"\[FreeTranslate\]\s+Progress:\s*(\d+)\s*/\s*(\d+)", text)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                percent = 70 + int(current * 18 / max(total, 1))
                self._set_progress_percent(percent, f"{percent}% 免费翻译 {current}/{total}")
                return

        match = re.search(r"Progress:\s*(\d+)\s*/\s*(\d+)", text)
        if match:
            self._set_progress_fraction(int(match.group(1)), int(match.group(2)))
            return

        rules = [
            ("[Auth] Logging in", 12),
            ("[Auth] Opening browser", 18),
            ("[Auth] Browser login successful", 25),
            ("[Transcript] Logged in", 18),
            ("[Transcriber] Downloading audio", 30),
            ("[Transcriber] Parallel download", 35),
            ("[Transcriber] Download progress", 42),
            ("[Transcriber] Downloaded", 45),
            ("[Transcriber] Extracting audio", 50),
            ("[Transcriber] Upload progress", 60),
            ("[Transcriber] ASR task created", 64),
            ("[Transcriber] ASR polling", 68),
            ("[Transcriber] Attempt", 55),
            ("[Transcriber] Success", 88),
            ("[Transcript] Done", 100),
            ("[VideoDownload] Logged in", 18),
            ("[VideoDownload] Downloading", 25),
            ("[VideoDownload] Done", 100),
            ("[Auto] Step 1/4", 5),
            ("[Auto] Step 2/4", 35),
            ("[Auto] Step 3/4", 65),
            ("[Auto] Step 4/4", 90),
            ("[Auto] Done", 100),
            ("[Subtitle] Translating", 20),
            ("[Subtitle] Done", 100),
            ("[FreeTranslate] Translating", 70),
            ("[FreeTranslate] Done", 100),
            ("[ApiTest] OK", 100),
            ("[Doctor] OK", 70),
            ("[LoginTest] OK", 100),
            ("[SubtitlePack] Done", 100),
            ("[SubtitleImport] Done", 100),
            ("[PlayerPack] Copying video", 35),
            ("[PlayerPack] Done", 100),
        ]
        for needle, percent in rules:
            if needle in text:
                self._set_progress_percent(percent)
                return

    def _capture_error_summary(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            return
        if "[ERROR]" in stripped or "FAIL" in stripped or "failed:" in stripped.lower():
            self.last_error_summary = stripped[:600]

    def _capture_srt_path(self, text: str) -> None:
        match = re.search(r"([A-Za-z]:\\[^\r\n]+?\.srt)", text)
        if not match:
            return
        path = match.group(1).strip()
        name = Path(path).name.lower()
        if "subtitle:" in text.lower():
            self.final_srt_path.set(path)
            return
        if ".source." in name:
            return
        if ".normalized." in name or ".bilingual." in name or ".zh-" in name or re.search(r"\.(ru|en|ja|ko|fr|de|es)\.srt$", name):
            self.final_srt_path.set(path)
            return
        if name.endswith(".srt") and not self.srt_path.get().strip():
            self.srt_path.set(path)

    def _capture_video_path(self, text: str) -> None:
        match = re.search(r"([A-Za-z]:\\[^\r\n]+?\.(?:mp4|mkv|mov|avi|wmv|m4v))", text, re.IGNORECASE)
        if match:
            self.video_path.set(match.group(1).strip())

    def _drain_log_queue(self) -> None:
        while True:
            try:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple):
                    kind, payload = item
                    if kind == "log":
                        self._append_log(payload)
                        self._capture_progress(payload)
                        self._capture_error_summary(payload)
                        self._capture_srt_path(payload)
                        self._capture_video_path(payload)
                        self._capture_replay_search_output(payload)
                    elif kind == "done":
                        self._append_log(f"\n[GUI] {self.t('task_done')}: {payload}\n")
                        self._finish_progress(int(payload))
                    elif kind == "cancelled":
                        self._append_log(f"\n[GUI] {self.t('progress_cancelled')}\n")
                        self._cancel_progress()
                    elif kind == "error":
                        self._append_log(f"\n[GUI] {self.t('start_failed')}: {payload}\n")
                        self._finish_progress(1)
                else:
                    text = str(item)
                    self._append_log(text)
                    self._capture_progress(text)
                    self._capture_error_summary(text)
                    self._capture_srt_path(text)
                    self._capture_video_path(text)
                    self._capture_replay_search_output(text)
            except queue.Empty:
                break
        self.root.after(100, self._drain_log_queue)

    def open_output_dir(self) -> None:
        path = Path(self.output_dir.get().strip() or ".").expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def open_potplayer_site(self) -> None:
        webbrowser.open("https://potplayer.tv/")

    def open_log(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if not LOG_PATH.exists():
            LOG_PATH.write_text("", encoding="utf-8")
        os.startfile(LOG_PATH)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        os.environ.update(_bundled_env(os.environ))
        sys.argv = ["look_tongji.py", *sys.argv[2:]]
        import look_tongji

        raise SystemExit(look_tongji.main())
    if len(sys.argv) > 1 and sys.argv[1] == "--selfuse-cli":
        os.environ.update(_bundled_env(os.environ))
        sys.argv = ["look_tongji_selfuse_helper.py", *sys.argv[2:]]
        import look_tongji_selfuse_helper

        raise SystemExit(look_tongji_selfuse_helper.main())

    root = Tk()
    LookTongjiGui(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        detail = traceback.format_exc()
        _write_app_log("Unhandled exception:\n" + detail)
        try:
            messagebox.showerror(APP_EXE_NAME, f"{type(exc).__name__}: {exc}\n\nLog: {LOG_PATH}")
        except Exception:
            print(detail, file=sys.stderr)
        raise SystemExit(1)
