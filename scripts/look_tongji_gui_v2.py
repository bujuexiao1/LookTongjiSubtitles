#!/usr/bin/env python3
"""PySide6 GUI V2 for Tongji Look subtitles."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import QEasingCurve, Property, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from look_tongji_app_state import APP_DIR, LOG_PATH, SettingsModel, append_app_log, bundled_env, effective_env_path


APP_TITLE = "Tongji Look Subtitles V2"
WINDOW_MIN_WIDTH = 1360
WINDOW_MIN_HEIGHT = 860
SCRIPT_DIR = Path(__file__).resolve().parent
CLI_PATH = SCRIPT_DIR / "look_tongji.py"
CLI_HELPER_NAME = "LookTongjiSubtitlesV2CLI.exe"

PAGE_HOME = "home"
PAGE_SINGLE = "single"
PAGE_BATCH = "batch"
PAGE_TASKS = "tasks"
PAGE_RESULTS = "results"
PAGE_SETTINGS = "settings"
PAGE_HELP = "help"

PAGE_LABELS = {
    PAGE_HOME: "首页",
    PAGE_SINGLE: "单个回放",
    PAGE_BATCH: "批量搜索",
    PAGE_TASKS: "任务中心",
    PAGE_RESULTS: "结果文件",
    PAGE_SETTINGS: "设置",
    PAGE_HELP: "帮助",
}

USER_VISIBLE_SUFFIXES = {".mp4", ".srt", ".txt", ".vtt", ".ass"}
HIDDEN_OUTPUT_NAMES = {
    "v2_batch_search_results.json",
    "v2_selected_replays.json",
}

STYLE_SHEET = """
QMainWindow, QWidget {
    color: #163247;
    font-family: "Microsoft YaHei UI";
    font-size: 14px;
}
QFrame#RootShell {
    background: transparent;
}
QFrame#SidebarCard, QFrame#SurfaceCard, QFrame#PanelCard, QFrame#HeroCard, QFrame#StatCard, QFrame#TimelineCard {
    border: 1px solid rgba(255, 255, 255, 0.32);
}
QFrame#SidebarCard {
    background: rgba(255, 252, 247, 0.92);
    border-radius: 28px;
}
QFrame#SurfaceCard {
    background: rgba(255, 253, 250, 0.90);
    border-radius: 30px;
}
QFrame#PanelCard {
    background: rgba(255, 255, 255, 0.82);
    border-radius: 24px;
}
QFrame#HeroCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(15,118,110,235), stop:1 rgba(36,153,140,225));
    border-radius: 30px;
}
QFrame#StatCard {
    background: rgba(255, 255, 255, 0.72);
    border-radius: 22px;
}
QFrame#TimelineCard {
    background: rgba(250, 255, 253, 0.88);
    border-radius: 20px;
}
QLabel#AppTitle {
    font-size: 26px;
    font-weight: 700;
    color: #0f172a;
}
QLabel#SidebarTitle {
    font-size: 20px;
    font-weight: 700;
    color: #133549;
}
QLabel#SectionTitle {
    font-size: 20px;
    font-weight: 700;
    color: #153042;
}
QLabel#SubtleText {
    color: #557086;
    font-size: 13px;
}
QLabel#HeroTitle {
    color: white;
    font-size: 30px;
    font-weight: 700;
}
QLabel#HeroBody {
    color: rgba(255,255,255,0.88);
    font-size: 14px;
}
QLabel#Badge {
    color: #0f766e;
    background: rgba(255,255,255,0.22);
    border: 1px solid rgba(255,255,255,0.32);
    border-radius: 14px;
    padding: 6px 12px;
    font-weight: 700;
}
QLabel#MetricValue {
    font-size: 28px;
    font-weight: 700;
    color: #103246;
}
QLabel#MetricLabel {
    font-size: 13px;
    color: #5b7487;
}
QPushButton#NavButton {
    text-align: left;
    padding: 14px 16px;
    border-radius: 18px;
    border: 1px solid transparent;
    background: transparent;
    color: #27485e;
    font-size: 14px;
    font-weight: 600;
}
QPushButton#NavButton:hover {
    background: rgba(15, 118, 110, 0.10);
}
QPushButton#NavButton:checked {
    background: rgba(15, 118, 110, 0.16);
    border-color: rgba(15, 118, 110, 0.18);
    color: #0f766e;
}
QPushButton#PrimaryButton {
    background: #0f766e;
    color: white;
    border: none;
    border-radius: 18px;
    padding: 13px 18px;
    font-size: 14px;
    font-weight: 700;
}
QPushButton#PrimaryButton:hover {
    background: #0c675f;
}
QPushButton#SecondaryButton {
    background: rgba(15, 118, 110, 0.10);
    color: #0f766e;
    border: 1px solid rgba(15, 118, 110, 0.16);
    border-radius: 18px;
    padding: 13px 18px;
    font-size: 14px;
    font-weight: 700;
}
QPushButton#SecondaryButton:hover {
    background: rgba(15, 118, 110, 0.16);
}
QPushButton#GhostButton {
    background: rgba(255,255,255,0.72);
    color: #284457;
    border: 1px solid rgba(28, 65, 84, 0.10);
    border-radius: 16px;
    padding: 11px 16px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#GhostButton:hover {
    background: rgba(255,255,255,0.95);
}
QLineEdit, QTextEdit {
    background: rgba(255,255,255,0.88);
    border: 1px solid rgba(93, 120, 140, 0.24);
    border-radius: 16px;
    padding: 12px 14px;
    selection-background-color: rgba(15, 118, 110, 0.24);
}
QLineEdit:focus, QTextEdit:focus {
    border: 1px solid rgba(15, 118, 110, 0.56);
}
QProgressBar {
    border: none;
    background: rgba(217, 231, 235, 0.72);
    border-radius: 9px;
    text-align: center;
    height: 16px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f766e, stop:1 #35b38c);
    border-radius: 9px;
}
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item {
    background: rgba(255,255,255,0.65);
    border: 1px solid rgba(89, 118, 137, 0.10);
    border-radius: 14px;
    padding: 14px;
    margin: 5px 0px;
}
QListWidget::item:selected {
    background: rgba(15, 118, 110, 0.12);
    color: #0f766e;
}
QListWidget::indicator {
    width: 24px;
    height: 24px;
}
QScrollArea {
    border: none;
    background: transparent;
}
"""


def add_shadow(widget: QWidget, blur: int = 32, dy: int = 12, alpha: int = 36) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(17, 24, 39, alpha))
    widget.setGraphicsEffect(effect)


class FloatingBackdrop(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

    def _tick(self) -> None:
        self._phase += 0.015
        if self._phase > 1000:
            self._phase = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor("#f7efe2"))
        gradient.setColorAt(0.4, QColor("#f4fbf7"))
        gradient.setColorAt(1.0, QColor("#eef6ff"))
        painter.fillRect(self.rect(), gradient)

        self._draw_blob(painter, QRect(70, 60, 300, 220), QColor(255, 214, 170, 85), self._phase * 12)
        self._draw_blob(painter, QRect(self.width() - 360, 100, 280, 190), QColor(148, 233, 211, 95), -self._phase * 10)
        self._draw_blob(painter, QRect(self.width() - 260, self.height() - 260, 250, 180), QColor(180, 210, 255, 85), self._phase * 9)
        self._draw_blob(painter, QRect(130, self.height() - 240, 220, 170), QColor(255, 181, 197, 70), -self._phase * 8)

        pen = QPen(QColor(255, 255, 255, 90))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawArc(120, 120, 180, 100, 10 * 16, 140 * 16)
        painter.drawArc(self.width() - 280, 180, 150, 88, 200 * 16, 120 * 16)

    def _draw_blob(self, painter: QPainter, rect: QRect, color: QColor, drift: float) -> None:
        path = QPainterPath()
        dx = int(drift % 18) - 9
        dy = int((drift / 2) % 14) - 7
        moved = rect.adjusted(dx, dy, dx, dy)
        path.moveTo(moved.left() + 35, moved.center().y())
        path.cubicTo(moved.left(), moved.top() + 25, moved.left() + 50, moved.top() - 8, moved.center().x(), moved.top() + 18)
        path.cubicTo(moved.right() - 25, moved.top() - 8, moved.right() + 18, moved.top() + 35, moved.right() - 8, moved.center().y())
        path.cubicTo(moved.right() + 6, moved.bottom() - 15, moved.center().x() + 35, moved.bottom() + 18, moved.left() + 55, moved.bottom() - 6)
        path.cubicTo(moved.left() - 15, moved.bottom() - 12, moved.left() - 12, moved.center().y() + 18, moved.left() + 35, moved.center().y())
        painter.fillPath(path, color)


class NavButton(QPushButton):
    def __init__(self, text: str, page_key: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.page_key = page_key
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("NavButton")


class SectionCard(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", object_name: str = "PanelCard", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        add_shadow(self, blur=28, dy=10, alpha=24)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(22, 20, 22, 20)
        self.layout.setSpacing(14)
        if title:
            title_label = QLabel(title)
            title_label.setObjectName("SectionTitle")
            self.layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            subtitle_label.setObjectName("SubtleText")
            self.layout.addWidget(subtitle_label)


class HeroCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HeroCard")
        add_shadow(self, blur=42, dy=14, alpha=45)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        badge = QLabel("V2")
        badge.setObjectName("Badge")
        badge.setFixedWidth(84)
        layout.addWidget(badge, alignment=Qt.AlignLeft)

        title = QLabel("直接下载 Tongji Look 回放并生成字幕")
        title.setWordWrap(True)
        title.setObjectName("HeroTitle")
        layout.addWidget(title)

        body = QLabel(
            "先在“设置”里填账号和输出目录，再去“单个回放”或“批量搜索”开始处理。"
        )
        body.setWordWrap(True)
        body.setObjectName("HeroBody")
        layout.addWidget(body)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.quick_start = QPushButton("打开设置")
        self.quick_start.setObjectName("PrimaryButton")
        self.quick_preview = QPushButton("任务中心")
        self.quick_preview.setObjectName("SecondaryButton")
        actions.addWidget(self.quick_start)
        actions.addWidget(self.quick_preview)
        actions.addStretch(1)
        layout.addLayout(actions)


class MetricCard(QFrame):
    def __init__(self, value: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatCard")
        add_shadow(self, blur=24, dy=10, alpha=18)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)
        metric_value = QLabel(value)
        metric_value.setObjectName("MetricValue")
        metric_label = QLabel(label)
        metric_label.setObjectName("MetricLabel")
        metric_label.setWordWrap(True)
        layout.addWidget(metric_value)
        layout.addWidget(metric_label)


class TimelineStep(QFrame):
    def __init__(self, title: str, body: str, status: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TimelineCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(16)

        dot = QLabel("●")
        dot.setAlignment(Qt.AlignTop)
        dot.setStyleSheet(
            "font-size: 18px; color: %s;" % {"done": "#0f766e", "active": "#f59e0b", "todo": "#94a3b8"}.get(status, "#94a3b8")
        )
        layout.addWidget(dot)

        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        title_label.setStyleSheet("font-size: 16px;")
        body_label = QLabel(body)
        body_label.setObjectName("SubtleText")
        body_label.setWordWrap(True)
        text_box.addWidget(title_label)
        text_box.addWidget(body_label)
        layout.addLayout(text_box, 1)


class FadableStackedWidget(QStackedWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fade_value = 1.0
        self._animation = QPropertyAnimation(self, b"fadeValue", self)
        self._animation.setDuration(240)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    def getFadeValue(self) -> float:
        return self._fade_value

    def setFadeValue(self, value: float) -> None:
        self._fade_value = value
        self.setWindowOpacity(max(0.0, min(1.0, value)))

    fadeValue = Property(float, getFadeValue, setFadeValue)

    def switch_to(self, index: int) -> None:
        self._animation.stop()
        self.setCurrentIndex(index)
        self.setFadeValue(0.55)
        self._animation.setStartValue(0.55)
        self._animation.setEndValue(1.0)
        self._animation.start()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = SettingsModel.load()
        self.nav_buttons: dict[str, NavButton] = {}
        self.page_indices: dict[str, int] = {}
        self.log_preview: QTextEdit | None = None
        self.progress_bar: QProgressBar | None = None
        self.progress_label: QLabel | None = None
        self.output_dir_input: QLineEdit | None = None
        self.target_language_input: QLineEdit | None = None
        self.translation_model_input: QLineEdit | None = None
        self.username_input: QLineEdit | None = None
        self.password_input: QLineEdit | None = None
        self.api_key_input: QLineEdit | None = None
        self.api_base_input: QLineEdit | None = None
        self.single_url_input: QTextEdit | None = None
        self.teacher_input: QLineEdit | None = None
        self.course_input: QLineEdit | None = None
        self.start_date_input: QLineEdit | None = None
        self.end_date_input: QLineEdit | None = None
        self.weekday_input: QLineEdit | None = None
        self.batch_result_list: QListWidget | None = None
        self.batch_search_output_json: Path | None = None
        self.batch_search_results: list[dict[str, object]] = []
        self.output_file_list: QListWidget | None = None
        self.running = False
        self.current_task = ""
        self.current_command_id = 0
        self.cancelled_command_ids: set[int] = set()
        self.current_proc: subprocess.Popen[str] | None = None
        self.cancel_requested = False
        self.last_error_summary = ""
        self.log_queue: queue.Queue[tuple[str, int, object]] = queue.Queue()

        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.resize(1460, 920)

        self.backdrop = FloatingBackdrop(self)
        self.backdrop.lower()

        shell = QWidget(self)
        self.setCentralWidget(shell)
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(24, 24, 24, 24)
        shell_layout.setSpacing(20)

        root = QFrame()
        root.setObjectName("RootShell")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(20)
        shell_layout.addWidget(root)

        sidebar = self._build_sidebar()
        content = self._build_content()
        root_layout.addWidget(sidebar, 0)
        root_layout.addWidget(content, 1)

        self.setStyleSheet(STYLE_SHEET)
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self._drain_log_queue)
        self.log_timer.start(120)
        self._go_to(PAGE_HOME)
        self._load_log_preview()
        self._refresh_output_files()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.backdrop:
            self.backdrop.setGeometry(self.rect())

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("SidebarCard")
        sidebar.setFixedWidth(260)
        add_shadow(sidebar, blur=34, dy=12, alpha=30)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(20, 22, 20, 22)
        layout.setSpacing(14)

        title = QLabel("Tongji Look")
        title.setObjectName("SidebarTitle")
        subtitle = QLabel("回放下载与字幕工具")
        subtitle.setObjectName("SubtleText")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: rgba(79, 104, 122, 0.15);")
        layout.addWidget(line)

        for page_key in (
            PAGE_HOME,
            PAGE_SINGLE,
            PAGE_BATCH,
            PAGE_TASKS,
            PAGE_RESULTS,
            PAGE_SETTINGS,
            PAGE_HELP,
        ):
            button = NavButton(PAGE_LABELS[page_key], page_key)
            button.clicked.connect(lambda checked=False, key=page_key: self._go_to(key))
            self.nav_buttons[page_key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        return sidebar

    def _build_content(self) -> QWidget:
        surface = QFrame()
        surface.setObjectName("SurfaceCard")
        add_shadow(surface, blur=40, dy=14, alpha=26)
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(14)
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title = QLabel(APP_TITLE)
        title.setObjectName("AppTitle")
        subtitle = QLabel("下载回放、生成字幕、查看任务和结果。")
        subtitle.setObjectName("SubtleText")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        save_button = QPushButton("保存当前配置")
        save_button.setObjectName("SecondaryButton")
        save_button.clicked.connect(self._save_settings)
        open_log_button = QPushButton("打开日志")
        open_log_button.setObjectName("GhostButton")
        open_log_button.clicked.connect(self._open_log_file)
        header.addWidget(open_log_button)
        header.addWidget(save_button)
        layout.addLayout(header)

        self.stack = FadableStackedWidget()
        layout.addWidget(self.stack, 1)

        self._add_page(PAGE_HOME, self._build_home_page())
        self._add_page(PAGE_SINGLE, self._build_single_page())
        self._add_page(PAGE_BATCH, self._build_batch_page())
        self._add_page(PAGE_TASKS, self._build_tasks_page())
        self._add_page(PAGE_RESULTS, self._build_results_page())
        self._add_page(PAGE_SETTINGS, self._build_settings_page())
        self._add_page(PAGE_HELP, self._build_help_page())
        return surface

    def _add_page(self, key: str, widget: QWidget) -> None:
        index = self.stack.addWidget(widget)
        self.page_indices[key] = index

    def _build_scroll_page(self, content: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(18)

        hero = HeroCard()
        hero.quick_start.clicked.connect(lambda: self._go_to(PAGE_SETTINGS))
        hero.quick_preview.clicked.connect(lambda: self._go_to(PAGE_TASKS))
        layout.addWidget(hero)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)
        stats_row.addWidget(MetricCard("单个回放", "回放页链接和 MP4 直链都能直接处理"))
        stats_row.addWidget(MetricCard("批量搜索", "按老师、课程名、日期范围筛回放"))
        stats_row.addWidget(MetricCard("任务日志", "运行进度、报错和结果都在这里看"))
        layout.addLayout(stats_row)

        quick = SectionCard("开始使用", "")
        quick.layout.addWidget(self._bullet_label("先在“设置”里填同济账号、密码和输出目录。"))
        quick.layout.addWidget(self._bullet_label("单个视频去“单个回放”，批量查课去“批量搜索”。"))
        quick.layout.addWidget(self._bullet_label("任务开始后，到“任务中心”看进度和日志。"))
        quick.layout.addWidget(self._bullet_label("处理完成后，到“结果文件”看视频和字幕。"))
        layout.addWidget(quick)
        layout.addStretch(1)
        return self._build_scroll_page(page)

    def _build_single_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(18)

        form = SectionCard("单个回放", "支持 Tongji Look 回放页链接和 MP4 直链。")
        self.single_url_input = QTextEdit()
        self.single_url_input.setPlaceholderText("把回放页链接或 MP4 直链粘贴到这里。")
        self.single_url_input.setMinimumHeight(150)
        form.layout.addWidget(self.single_url_input)

        button_row = QHBoxLayout()
        preview = QPushButton("一键生成视频 + 字幕")
        preview.setObjectName("PrimaryButton")
        preview.clicked.connect(self._start_single_auto_task)
        video_only = QPushButton("只下载视频")
        video_only.setObjectName("SecondaryButton")
        video_only.clicked.connect(self._start_single_video_task)
        clear = QPushButton("清空")
        clear.setObjectName("GhostButton")
        clear.clicked.connect(lambda: self.single_url_input.setPlainText(""))
        button_row.addWidget(preview)
        button_row.addWidget(video_only)
        button_row.addWidget(clear)
        button_row.addStretch(1)
        form.layout.addLayout(button_row)
        layout.addWidget(form)

        hints = SectionCard("输入示例", "")
        hints.layout.addWidget(self._bullet_label("回放页链接通常形如 `https://look.tongji.edu.cn/...`。"))
        hints.layout.addWidget(self._bullet_label("直链通常是 `.mp4` 结尾的长链接。"))
        hints.layout.addWidget(self._bullet_label("你只想做中文字幕时，不需要填写 API Key。"))
        layout.addWidget(hints)
        layout.addStretch(1)
        return self._build_scroll_page(page)

    def _build_batch_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(18)

        search = SectionCard("批量搜索", "按老师、课程名和日期范围搜索当前账号能访问的回放。")
        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(14)
        self.teacher_input = self._line_edit(self.settings.teacher_keyword, "例如：迪迦")
        self.course_input = self._line_edit(self.settings.course_keyword, "例如：计算机网络")
        self.start_date_input = self._line_edit(self.settings.start_date, "例如：2026-03-01")
        self.end_date_input = self._line_edit(self.settings.end_date, "例如：2026-06-30")
        self.weekday_input = self._line_edit(self.settings.weekday, "可选，例如：3")
        form.addWidget(self._field_label("老师关键词"), 0, 0)
        form.addWidget(self.teacher_input, 0, 1)
        form.addWidget(self._field_label("课程关键词"), 0, 2)
        form.addWidget(self.course_input, 0, 3)
        form.addWidget(self._field_label("开始日期"), 1, 0)
        form.addWidget(self.start_date_input, 1, 1)
        form.addWidget(self._field_label("结束日期"), 1, 2)
        form.addWidget(self.end_date_input, 1, 3)
        form.addWidget(self._field_label("星期筛选"), 2, 0)
        form.addWidget(self.weekday_input, 2, 1)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        search.layout.addLayout(form)

        actions = QHBoxLayout()
        search_button = QPushButton("搜索回放")
        search_button.setObjectName("PrimaryButton")
        search_button.clicked.connect(self._start_batch_search)
        download_button = QPushButton("下载所选+字幕")
        download_button.setObjectName("SecondaryButton")
        download_button.clicked.connect(self._start_batch_download_selected)
        select_all_button = QPushButton("全选")
        select_all_button.setObjectName("GhostButton")
        select_all_button.clicked.connect(self._select_all_batch_results)
        clear_button = QPushButton("清空选择")
        clear_button.setObjectName("GhostButton")
        clear_button.clicked.connect(self._clear_batch_result_selection)
        save = QPushButton("保存筛选条件")
        save.setObjectName("GhostButton")
        save.clicked.connect(self._save_settings)
        actions.addWidget(search_button)
        actions.addWidget(download_button)
        actions.addWidget(select_all_button)
        actions.addWidget(clear_button)
        actions.addWidget(save)
        actions.addStretch(1)
        search.layout.addLayout(actions)
        layout.addWidget(search)

        result_card = SectionCard("搜索结果", "")
        self.batch_result_list = QListWidget()
        self.batch_result_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.batch_result_list.addItem(QListWidgetItem("还没有搜索结果。"))
        result_card.layout.addWidget(self.batch_result_list)
        layout.addWidget(result_card)
        layout.addStretch(1)
        return self._build_scroll_page(page)

    def _build_tasks_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(18)

        top = SectionCard("任务中心", "")
        self.progress_label = QLabel("当前状态：等待任务")
        self.progress_label.setObjectName("SubtleText")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(18)
        top.layout.addWidget(self.progress_label)
        top.layout.addWidget(self.progress_bar)

        action_row = QHBoxLayout()
        simulate = QPushButton("刷新日志")
        simulate.setObjectName("PrimaryButton")
        simulate.clicked.connect(self._load_log_preview)
        open_log = QPushButton("打开日志")
        open_log.setObjectName("GhostButton")
        open_log.clicked.connect(self._open_log_file)
        open_output = QPushButton("打开输出目录")
        open_output.setObjectName("GhostButton")
        open_output.clicked.connect(self._open_output_dir)
        stop = QPushButton("中断任务")
        stop.setObjectName("SecondaryButton")
        stop.clicked.connect(self.cancel_task)
        action_row.addWidget(simulate)
        action_row.addWidget(open_log)
        action_row.addWidget(open_output)
        action_row.addWidget(stop)
        action_row.addStretch(1)
        top.layout.addLayout(action_row)
        layout.addWidget(top)

        notes = SectionCard("任务说明", "")
        notes.layout.addWidget(self._bullet_label("运行时日志会实时写到下面。"))
        notes.layout.addWidget(self._bullet_label("中断后可以重新发起任务，不会影响已经生成好的文件。"))
        notes.layout.addWidget(self._bullet_label("处理完成后，结果会自动跳到“结果文件”。"))
        layout.addWidget(notes)

        self.log_preview = QTextEdit()
        self.log_preview.setReadOnly(True)
        self.log_preview.setMinimumHeight(320)
        log_card = SectionCard("日志", "")
        log_card.layout.addWidget(self.log_preview)
        layout.addWidget(log_card)
        layout.addStretch(1)
        return self._build_scroll_page(page)

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(18)

        result = SectionCard("结果文件", "这里只显示视频、字幕和使用说明。")
        result.layout.addWidget(self._bullet_label("回放页链接生成的内容会按日期-课程名命名。"))
        result.layout.addWidget(self._bullet_label("MP4 直链生成的内容会按日期-随机数命名。"))

        self.output_file_list = QListWidget()
        self.output_file_list.addItem(QListWidgetItem("当前还没有输出文件。"))
        self.output_file_list.itemDoubleClicked.connect(self._open_selected_output)
        result.layout.addWidget(self.output_file_list)

        actions = QHBoxLayout()
        refresh_button = QPushButton("刷新列表")
        refresh_button.setObjectName("PrimaryButton")
        refresh_button.clicked.connect(self._refresh_output_files)
        open_selected = QPushButton("打开所选文件")
        open_selected.setObjectName("GhostButton")
        open_selected.clicked.connect(self._open_selected_output)
        choose_output = QPushButton("选择输出目录")
        choose_output.setObjectName("GhostButton")
        choose_output.clicked.connect(self._pick_output_dir)
        open_output = QPushButton("打开输出目录")
        open_output.setObjectName("SecondaryButton")
        open_output.clicked.connect(self._open_output_dir)
        actions.addWidget(refresh_button)
        actions.addWidget(open_selected)
        actions.addWidget(choose_output)
        actions.addWidget(open_output)
        actions.addStretch(1)
        result.layout.addLayout(actions)
        layout.addWidget(result)
        layout.addStretch(1)
        return self._build_scroll_page(page)

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(18)

        card = SectionCard("基础设置", "登录、输出目录和字幕相关配置都在这里。")
        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(14)
        self.username_input = self._line_edit(self.settings.username, "学号 / 工号")
        self.password_input = self._line_edit(self.settings.password, "Tongji 统一身份认证密码")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.api_key_input = self._line_edit(self.settings.api_key, "可选，仅翻译时需要")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_base_input = self._line_edit(self.settings.api_base_url, "可选，例如：https://api.openai.com/v1")
        self.output_dir_input = self._line_edit(self.settings.output_dir, "选择默认输出目录")
        self.target_language_input = self._line_edit(self.settings.subtitle_language, "例如：zh / en / ru")
        self.translation_model_input = self._line_edit(self.settings.translation_model, "例如：gpt-4.1-mini")

        form.addWidget(self._field_label("同济账号"), 0, 0)
        form.addWidget(self.username_input, 0, 1)
        form.addWidget(self._field_label("同济密码"), 0, 2)
        form.addWidget(self.password_input, 0, 3)
        form.addWidget(self._field_label("API Key"), 1, 0)
        form.addWidget(self.api_key_input, 1, 1)
        form.addWidget(self._field_label("API Base URL"), 1, 2)
        form.addWidget(self.api_base_input, 1, 3)
        form.addWidget(self._field_label("默认输出目录"), 2, 0)
        form.addWidget(self.output_dir_input, 2, 1, 1, 3)
        form.addWidget(self._field_label("字幕语言"), 3, 0)
        form.addWidget(self.target_language_input, 3, 1)
        form.addWidget(self._field_label("翻译模型"), 3, 2)
        form.addWidget(self.translation_model_input, 3, 3)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        card.layout.addLayout(form)

        actions = QHBoxLayout()
        pick_dir = QPushButton("选择输出目录")
        pick_dir.setObjectName("GhostButton")
        pick_dir.clicked.connect(self._pick_output_dir)
        test_login = QPushButton("测试同济登录")
        test_login.setObjectName("SecondaryButton")
        test_login.clicked.connect(self._test_login)
        test_api = QPushButton("测试 API")
        test_api.setObjectName("GhostButton")
        test_api.clicked.connect(self._test_api)
        save = QPushButton("保存设置")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self._save_settings)
        actions.addWidget(pick_dir)
        actions.addWidget(test_login)
        actions.addWidget(test_api)
        actions.addWidget(save)
        actions.addStretch(1)
        card.layout.addLayout(actions)
        layout.addWidget(card)

        info = SectionCard("注意事项", "")
        info.layout.addWidget(self._bullet_label("只要中文字幕时，不必填写 API Key。"))
        info.layout.addWidget(self._bullet_label("日期格式统一按 `2026-03-01` 这种方式填写。"))
        info.layout.addWidget(self._bullet_label("如果运行报错，先去任务中心看日志。"))
        layout.addWidget(info)
        layout.addStretch(1)
        return self._build_scroll_page(page)

    def _build_help_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(18)

        guide = SectionCard("使用说明", "")
        guide.layout.addWidget(self._bullet_label("单个回放：粘贴回放页链接或 MP4 直链，生成视频和字幕。"))
        guide.layout.addWidget(self._bullet_label("批量搜索：按老师、课程名和日期筛选当前账号权限内可访问的回放。"))
        guide.layout.addWidget(self._bullet_label("任务中心：查看当前进度、完整日志和错误信息。"))
        guide.layout.addWidget(self._bullet_label("结果文件：统一展示视频、中文字幕和翻译后的字幕文件。"))
        layout.addWidget(guide)

        faq = SectionCard("常见提醒", "")
        faq.layout.addWidget(self._bullet_label("转录和生成字幕通常需要一段时间，建议在观看前提前准备。"))
        faq.layout.addWidget(self._bullet_label("请保留整个文件夹结构，不要只移动 exe。"))
        faq.layout.addWidget(self._bullet_label("如果任务失败，先看日志末尾几行，再决定是否重试。"))
        layout.addWidget(faq)
        layout.addStretch(1)
        return self._build_scroll_page(page)

    def _go_to(self, page_key: str) -> None:
        index = self.page_indices[page_key]
        self.stack.switch_to(index)
        for key, button in self.nav_buttons.items():
            button.setChecked(key == page_key)

    def _line_edit(self, value: str, placeholder: str) -> QLineEdit:
        widget = QLineEdit(value)
        widget.setPlaceholderText(placeholder)
        widget.setMinimumHeight(48)
        return widget

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SubtleText")
        label.setStyleSheet("font-size: 13px; font-weight: 700; color: #21445b;")
        return label

    def _bullet_label(self, text: str) -> QLabel:
        label = QLabel("• " + text)
        label.setObjectName("SubtleText")
        label.setWordWrap(True)
        return label

    def _sync_settings_from_ui(self) -> None:
        if self.username_input:
            self.settings.username = self.username_input.text().strip()
        if self.password_input:
            self.settings.password = self.password_input.text().strip()
        if self.api_key_input:
            self.settings.api_key = self.api_key_input.text().strip()
        if self.api_base_input:
            self.settings.api_base_url = self.api_base_input.text().strip()
        if self.output_dir_input:
            self.settings.output_dir = self.output_dir_input.text().strip()
        if self.target_language_input:
            self.settings.subtitle_language = self.target_language_input.text().strip() or "zh"
        if self.translation_model_input:
            self.settings.translation_model = self.translation_model_input.text().strip() or "gpt-4.1-mini"
        if self.teacher_input:
            self.settings.teacher_keyword = self.teacher_input.text().strip()
        if self.course_input:
            self.settings.course_keyword = self.course_input.text().strip()
        if self.start_date_input:
            self.settings.start_date = self.start_date_input.text().strip()
        if self.end_date_input:
            self.settings.end_date = self.end_date_input.text().strip()
        if self.weekday_input:
            self.settings.weekday = self.weekday_input.text().strip()

    def _save_settings(self, show_message: bool = True) -> None:
        self._sync_settings_from_ui()
        self.settings.save()
        append_app_log("Saved V2 settings to .env")
        self._load_log_preview()
        self._refresh_output_files()
        if show_message:
            QMessageBox.information(self, APP_TITLE, "设置已保存。")

    def _pick_output_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择输出目录", self.settings.output_dir or str(Path.home()))
        if not chosen:
            return
        self.settings.output_dir = chosen
        if self.output_dir_input:
            self.output_dir_input.setText(chosen)
        self._refresh_output_files()

    def _single_source_args(self) -> list[str]:
        text = self.single_url_input.toPlainText().strip() if self.single_url_input else ""
        if not text:
            return []
        return ["--lecture-url", text]

    def _start_single_auto_task(self) -> None:
        self._save_settings(show_message=False)
        args = self._single_source_args()
        if not args:
            QMessageBox.warning(self, APP_TITLE, "请先粘贴回放页链接或 MP4 直链。")
            return
        target = (self.settings.subtitle_language or "zh").strip() or "zh"
        cmd = self._base_cmd() + [
            "auto-potplayer",
            *args,
            "--target",
            target,
            "--output-dir",
            self.settings.output_dir,
            "--model",
            self.settings.translation_model or "gpt-4.1-mini",
        ]
        if target.lower() not in {"zh", "cn", "chinese"} and not self.settings.api_key:
            cmd += ["--translation-mode", "free"]
        self.run_command(cmd, task="one_click")
        self._go_to(PAGE_TASKS)

    def _start_single_video_task(self) -> None:
        self._save_settings(show_message=False)
        args = self._single_source_args()
        if not args:
            QMessageBox.warning(self, APP_TITLE, "请先粘贴回放页链接或 MP4 直链。")
            return
        cmd = self._base_cmd() + ["download-video", *args, "--output-dir", self.settings.output_dir]
        self.run_command(cmd, task="download_video")
        self._go_to(PAGE_TASKS)

    def _batch_search_args(self) -> list[str]:
        self._sync_settings_from_ui()
        if not self.settings.start_date or not self.settings.end_date:
            return []
        args = [
            "--start-date",
            self.settings.start_date,
            "--end-date",
            self.settings.end_date,
            "--output-dir",
            self.settings.output_dir or str(APP_DIR / "tongji-output"),
            "--show-limit",
            "20",
            "--owned-only",
        ]
        if self.settings.teacher_keyword:
            args += ["--teacher-keyword", self.settings.teacher_keyword]
        if self.settings.course_keyword:
            args += ["--course-keyword", self.settings.course_keyword]
        if self.settings.weekday:
            args += ["--weekday", self.settings.weekday]
        return args

    def _start_batch_search(self) -> None:
        self._save_settings(show_message=False)
        args = self._batch_search_args()
        if not args:
            QMessageBox.warning(self, APP_TITLE, "请先填写开始日期和结束日期。")
            return
        output_dir = Path(self.settings.output_dir or (APP_DIR / "tongji-output")).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        intermediate_dir = output_dir / "中间产物"
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        self.batch_search_output_json = intermediate_dir / "v2_batch_search_results.json"
        cmd = self._base_cmd() + [
            "search-replay-range",
            *args,
            "--output-json",
            str(self.batch_search_output_json),
        ]
        self.run_command(cmd, task="batch_search")
        self._go_to(PAGE_TASKS)

    def _load_batch_search_results(self) -> None:
        if self.batch_result_list is None:
            return
        self.batch_result_list.clear()
        self.batch_search_results = []
        path = self.batch_search_output_json
        if path is None or not path.exists():
            self.batch_result_list.addItem(QListWidgetItem("没有找到搜索结果。"))
            return
        try:
            import json

            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            self.batch_result_list.addItem(QListWidgetItem(f"读取搜索结果失败：{type(exc).__name__}: {exc}"))
            return
        if not isinstance(payload, list) or not payload:
            self.batch_result_list.addItem(QListWidgetItem("没有找到搜索结果。"))
            return
        rows: list[dict[str, object]] = []
        seen_replays: set[tuple[str, str]] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            course_id = str(item.get("course_id") or "").strip()
            sub_id = str(item.get("sub_id") or "").strip()
            replay_key = (course_id, sub_id)
            if course_id and sub_id and replay_key in seen_replays:
                continue
            if course_id and sub_id:
                seen_replays.add(replay_key)
            rows.append(item)

        group_counts: dict[tuple[str, str, str, str], int] = defaultdict(int)
        for item in rows:
            group_key = (
                str(item.get("date") or "").strip(),
                str(item.get("title") or "").strip(),
                str(item.get("teacher") or "").strip(),
                str(item.get("course_id") or "").strip(),
            )
            group_counts[group_key] += 1

        group_seen: dict[tuple[str, str, str, str], int] = defaultdict(int)
        for idx, item in enumerate(rows):
            self.batch_search_results.append(item)
            date_text = str(item.get("date") or "").strip()
            title = str(item.get("title") or "").strip()
            teacher = str(item.get("teacher") or "").strip()
            course_id = str(item.get("course_id") or "").strip()
            sub_id = str(item.get("sub_id") or "").strip()
            status = str(item.get("status_label") or "").strip()
            group_key = (date_text, title, teacher, course_id)
            group_seen[group_key] += 1
            part_text = ""
            if group_counts[group_key] > 1:
                part_text = f" | 第 {group_seen[group_key]}/{group_counts[group_key]} 段"
            text = f"{date_text} | {title} | {teacher}{part_text} | course_id={course_id} | sub_id={sub_id}"
            if status:
                text += f" | {status}"
            list_item = QListWidgetItem(text)
            list_item.setData(Qt.UserRole, idx)
            list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            list_item.setCheckState(Qt.CheckState.Unchecked)
            self.batch_result_list.addItem(list_item)

    def _selected_batch_result_items(self) -> list[dict[str, object]]:
        if self.batch_result_list is None:
            return []
        selected: list[dict[str, object]] = []
        for row in range(self.batch_result_list.count()):
            item = self.batch_result_list.item(row)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            index = item.data(Qt.UserRole)
            if isinstance(index, int) and 0 <= index < len(self.batch_search_results):
                selected.append(dict(self.batch_search_results[index]))
        return selected

    def _select_all_batch_results(self) -> None:
        if self.batch_result_list is None:
            return
        for row in range(self.batch_result_list.count()):
            item = self.batch_result_list.item(row)
            if isinstance(item.data(Qt.UserRole), int):
                item.setCheckState(Qt.CheckState.Checked)

    def _clear_batch_result_selection(self) -> None:
        if self.batch_result_list is None:
            return
        for row in range(self.batch_result_list.count()):
            item = self.batch_result_list.item(row)
            if isinstance(item.data(Qt.UserRole), int):
                item.setCheckState(Qt.CheckState.Unchecked)
        self.batch_result_list.clearSelection()

    def _write_selected_batch_results(self, items: list[dict[str, object]]) -> Path:
        output_dir = Path(self.settings.output_dir or (APP_DIR / "tongji-output")).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        export_path = output_dir / "v2_selected_replays.json"
        export_path.write_text(__import__("json").dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return export_path

    def _start_batch_download_selected(self) -> None:
        self._save_settings(show_message=False)
        items = self._selected_batch_result_items()
        if not items:
            QMessageBox.warning(self, APP_TITLE, "请先在搜索结果左侧勾选要下载的回放。")
            return
        export_path = self._write_selected_batch_results(items)
        target = (self.settings.subtitle_language or "zh").strip() or "zh"
        cmd = self._base_cmd() + [
            "batch-download-replays",
            "--input-json",
            str(export_path),
            "--output-dir",
            self.settings.output_dir or str(APP_DIR / "tongji-output"),
            "--target",
            target,
            "--model",
            self.settings.translation_model or "gpt-4.1-mini",
        ]
        if target.lower() not in {"zh", "cn", "chinese"} and not self.settings.api_key:
            cmd += ["--translation-mode", "free"]
        self.run_command(cmd, task="batch_download_replays")
        self._go_to(PAGE_TASKS)

    def _refresh_output_files(self) -> None:
        if self.output_file_list is None:
            return
        self.output_file_list.clear()
        output_dir = Path(self.settings.output_dir or (APP_DIR / "tongji-output")).expanduser().resolve()
        if not output_dir.exists():
            self.output_file_list.addItem(QListWidgetItem("输出目录还不存在。"))
            return
        files = [
            path
            for path in output_dir.iterdir()
            if path.is_file()
            and path.name not in HIDDEN_OUTPUT_NAMES
            and path.suffix.lower() in USER_VISIBLE_SUFFIXES
        ]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        if not files:
            self.output_file_list.addItem(QListWidgetItem("当前还没有输出文件。"))
            return
        for path in files[:200]:
            size_mb = path.stat().st_size / (1024 * 1024)
            item = QListWidgetItem(f"{path.name}    {size_mb:.1f} MB")
            item.setToolTip(str(path))
            item.setData(Qt.UserRole, str(path))
            self.output_file_list.addItem(item)

    def _open_output_dir(self) -> None:
        output_dir = Path(self.settings.output_dir or (APP_DIR / "tongji-output")).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(output_dir)  # type: ignore[attr-defined]
        except Exception:
            QMessageBox.information(self, APP_TITLE, f"输出目录：\n{output_dir}")

    def _open_selected_output(self, item: QListWidgetItem | None = None) -> None:
        if self.output_file_list is None:
            return
        item = item or self.output_file_list.currentItem()
        if item is None:
            QMessageBox.information(self, APP_TITLE, "请先在结果列表里选中文件。")
            return
        path_text = item.data(Qt.UserRole)
        if not path_text:
            return
        path = Path(str(path_text))
        if not path.exists():
            QMessageBox.warning(self, APP_TITLE, f"文件不存在：\n{path}")
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            QMessageBox.information(self, APP_TITLE, f"文件位置：\n{path}")

    def _load_log_preview(self) -> None:
        if not self.log_preview:
            return
        if not LOG_PATH.exists():
            self.log_preview.setPlainText("日志文件尚未生成。")
            return
        text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        preview = "\n".join(lines[-60:]) if lines else "日志文件为空。"
        self.log_preview.setPlainText(preview)

    def _open_log_file(self) -> None:
        if LOG_PATH.exists():
            try:
                import os

                os.startfile(LOG_PATH)  # type: ignore[attr-defined]
                return
            except Exception:
                pass
        QMessageBox.information(self, APP_TITLE, f"日志位置：\n{LOG_PATH}")

    def _base_cmd(self) -> list[str]:
        if getattr(sys, "frozen", False):
            helper_path = Path(sys.executable).resolve().parent / CLI_HELPER_NAME
            if helper_path.exists():
                return [str(helper_path)]
            append_app_log(f"CLI helper not found, falling back to GUI executable: {helper_path}")
            return [sys.executable, "--cli"]
        return [sys.executable, str(CLI_PATH)]

    def _test_login(self) -> None:
        self._save_settings(show_message=False)
        self.run_command(self._base_cmd() + ["login-test"], task="login_test")
        self._go_to(PAGE_TASKS)

    def _test_api(self) -> None:
        self._save_settings(show_message=False)
        target = (self.settings.subtitle_language or "zh").strip() or "zh"
        cmd = self._base_cmd() + [
            "api-test",
            "--target",
            target,
            "--model",
            self.settings.translation_model or "gpt-4.1-mini",
        ]
        self.run_command(cmd, task="api_test")
        self._go_to(PAGE_TASKS)

    def _append_log(self, text: str) -> None:
        if not self.log_preview:
            return
        cursor = self.log_preview.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.log_preview.setTextCursor(cursor)
        self.log_preview.ensureCursorVisible()

    def _decode_process_output(self, raw: bytes) -> str:
        candidates: list[str] = []
        for encoding in ("utf-8-sig", "utf-8", "mbcs", "cp936", sys.getdefaultencoding()):
            try:
                text = raw.decode(encoding, errors="replace")
            except LookupError:
                continue
            if text not in candidates:
                candidates.append(text)
        if not candidates:
            return raw.decode("utf-8", errors="replace")

        def score(text: str) -> tuple[int, int]:
            replacement_count = text.count("\ufffd")
            mojibake_count = text.count("锟") + text.count("�")
            return replacement_count + mojibake_count, replacement_count

        return min(candidates, key=score)

    def _task_start_percent(self, task: str) -> int:
        return {
            "api_test": 18,
            "batch_search": 12,
            "batch_download_replays": 10,
            "login_test": 18,
            "download_video": 10,
            "one_click": 6,
        }.get(task, 10)

    def _start_progress(self, task: str) -> None:
        percent = self._task_start_percent(task)
        if self.progress_bar:
            self.progress_bar.setValue(percent)
        if self.progress_label:
            self.progress_label.setText(f"当前状态：任务已启动 ({percent}%)")

    def _set_progress_percent(self, percent: int, label: str | None = None) -> None:
        percent = max(0, min(100, int(percent)))
        if self.progress_bar:
            self.progress_bar.setValue(percent)
        if self.progress_label:
            self.progress_label.setText(label or f"当前状态：进行中 ({percent}%)")

    def _finish_progress(self, code: int) -> None:
        if self.progress_bar:
            self.progress_bar.setValue(100 if code == 0 else 0)
        if self.progress_label:
            self.progress_label.setText("当前状态：任务已完成" if code == 0 else "当前状态：任务失败")
        task = self.current_task
        self.current_task = ""
        if task == "login_test":
            if code == 0:
                QMessageBox.information(self, APP_TITLE, "同济登录测试成功。")
            else:
                detail = self.last_error_summary or f"登录测试失败，请查看日志：\n{LOG_PATH}"
                QMessageBox.critical(self, APP_TITLE, detail)
        elif task == "batch_search":
            self._load_batch_search_results()
            self._go_to(PAGE_BATCH)
            if code == 0:
                QMessageBox.information(self, APP_TITLE, "搜索完成。")
            else:
                detail = self.last_error_summary or f"搜索失败，请查看日志：\n{LOG_PATH}"
                QMessageBox.critical(self, APP_TITLE, detail)
        elif task == "batch_download_replays":
            self._refresh_output_files()
            self._go_to(PAGE_RESULTS)
            if code == 0:
                QMessageBox.information(self, APP_TITLE, "所选回放已处理完成。")
            else:
                detail = self.last_error_summary or f"批量处理未全部成功，请查看日志：\n{LOG_PATH}"
                QMessageBox.warning(self, APP_TITLE, detail)
        elif task == "api_test":
            if code == 0:
                QMessageBox.information(self, APP_TITLE, "API 测试成功。")
            else:
                detail = self.last_error_summary or f"API 测试失败，请查看日志：\n{LOG_PATH}"
                QMessageBox.critical(self, APP_TITLE, detail)
        elif task in {"one_click", "download_video"} and code == 0:
            self._refresh_output_files()
            self._go_to(PAGE_RESULTS)
            out_dir = self.settings.output_dir or str(APP_DIR / "tongji-output")
            QMessageBox.information(self, APP_TITLE, f"任务完成。\n输出目录：\n{out_dir}")

    def _cancel_progress(self) -> None:
        if self.progress_bar:
            self.progress_bar.setValue(0)
        if self.progress_label:
            self.progress_label.setText("当前状态：任务已中断")
        self.current_task = ""

    def _capture_progress(self, text: str) -> None:
        if self.current_task == "batch_search":
            match = __import__("re").search(r"\[SearchReplay\]\s+Progress:\s*(\d+)\s*/\s*(\d+)", text)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                percent = 12 + int(current * 78 / max(total, 1))
                self._set_progress_percent(percent, f"当前状态：正在搜索回放 ({current}/{total})")
                return
        if self.current_task == "batch_download_replays":
            match = __import__("re").search(r"\[BatchReplay\]\s+Progress:\s*(\d+)\s*/\s*(\d+)", text)
            if match:
                current, total = int(match.group(1)), int(match.group(2))
                percent = 10 + int(current * 82 / max(total, 1))
                self._set_progress_percent(percent, f"当前状态：正在处理所选回放 ({current}/{total})")
                return
        if self.current_task == "one_click":
            auto = __import__("re").search(r"\[Auto\]\s+Progress:\s*(\d+)\s*/\s*4", text)
            if auto:
                mapped = {1: 8, 2: 38, 3: 90, 4: 100}
                self._set_progress_percent(mapped.get(int(auto.group(1)), 8))
                return
        if self.current_task == "download_video":
            video = __import__("re").search(r"\[VideoDownload\]\s+Progress:\s*(\d+)\s*/\s*100", text)
            if video:
                percent = 10 + int(int(video.group(1)) * 85 / 100)
                self._set_progress_percent(percent, f"当前状态：正在下载视频 ({percent}%)")
                return
        if "[LoginTest] OK" in text:
            self._set_progress_percent(100, "当前状态：同济登录测试成功")
            return
        if "[ApiTest] OK" in text:
            self._set_progress_percent(100, "当前状态：API 测试成功")
            return
        rules = [
            ("[Auth] Logging in", 20, "当前状态：正在登录 Tongji Look"),
            ("[VideoDownload] Downloading", 25, "当前状态：正在下载视频"),
            ("[Transcriber] Downloading audio", 42, "当前状态：正在准备音频"),
            ("[Transcriber] Upload progress", 58, "当前状态：正在上传音频识别"),
            ("[Transcriber] ASR task created", 66, "当前状态：已提交语音识别任务"),
            ("[Subtitle] Translating", 82, "当前状态：正在生成字幕"),
            ("[Auto] Done", 100, "当前状态：任务已完成"),
            ("[VideoDownload] Done", 100, "当前状态：视频下载完成"),
        ]
        for needle, percent, label in rules:
            if needle in text:
                self._set_progress_percent(percent, label)
                return

    def run_command(self, cmd: list[str], task: str = "") -> None:
        if self.running:
            QMessageBox.information(self, APP_TITLE, "当前已有任务在运行，请先等待完成或中断。")
            return
        self.current_command_id += 1
        command_id = self.current_command_id
        self.cancelled_command_ids.discard(command_id)
        self.running = True
        self.current_task = task
        self.cancel_requested = False
        self.last_error_summary = ""
        self._start_progress(task)
        append_app_log("Running V2 command: " + " ".join(cmd))
        self._append_log("\n$ " + " ".join(f'"{part}"' if " " in part else part for part in cmd) + "\n")
        thread = threading.Thread(target=self._worker, args=(cmd, command_id), daemon=True)
        thread.start()

    def _worker(self, cmd: list[str], command_id: int) -> None:
        env = bundled_env(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        try:
            popen_kwargs: dict[str, object] = {}
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if creationflags:
                    popen_kwargs["creationflags"] = creationflags
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                popen_kwargs["startupinfo"] = startupinfo
            proc = subprocess.Popen(
                cmd,
                cwd=str(APP_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                env=env,
                **popen_kwargs,
            )
            self.current_proc = proc
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                if command_id in self.cancelled_command_ids:
                    break
                line = self._decode_process_output(raw_line)
                append_app_log(line.rstrip("\n"))
                self.log_queue.put(("log", command_id, line))
            if command_id in self.cancelled_command_ids and proc.poll() is None:
                self._stop_process_tree(proc)
            code = proc.wait()
            if command_id in self.cancelled_command_ids:
                self.log_queue.put(("cancelled", command_id, code))
            else:
                self.log_queue.put(("done", command_id, code))
        except Exception as exc:
            append_app_log("Worker exception:\n" + traceback.format_exc())
            self.log_queue.put(("error", command_id, f"{type(exc).__name__}: {exc}"))
        finally:
            if self.current_command_id == command_id:
                self.current_proc = None
                self.running = False

    def _stop_process_tree(self, proc: subprocess.Popen[str] | None) -> None:
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
                append_app_log(f"taskkill failed: {type(exc).__name__}: {exc}")
        try:
            proc.terminate()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def cancel_task(self) -> None:
        if not self.running:
            self._cancel_progress()
            return
        command_id = self.current_command_id
        self.cancelled_command_ids.add(command_id)
        self.cancel_requested = True
        self.running = False
        self._cancel_progress()
        self._stop_process_tree(self.current_proc)
        self.current_proc = None
        append_app_log("Cancel requested by user in GUI V2")

    def _drain_log_queue(self) -> None:
        while True:
            try:
                kind, command_id, payload = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if command_id != self.current_command_id:
                continue
            if kind == "log":
                text = str(payload)
                self._append_log(text)
                self._capture_progress(text)
                lowered = text.lower()
                if "[error]" in lowered or "failed" in lowered or "traceback" in lowered:
                    self.last_error_summary = text.strip()
            elif kind == "done":
                self._finish_progress(int(payload))
            elif kind == "cancelled":
                self._cancel_progress()
            elif kind == "error":
                self.last_error_summary = str(payload)
                self._cancel_progress()
                QMessageBox.critical(self, APP_TITLE, str(payload))


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        os.environ.update(bundled_env(os.environ))
        os.environ["LOOK_TONGJI_ENV_PATH"] = str(effective_env_path())
        sys.argv = ["look_tongji.py", *sys.argv[2:]]
        import look_tongji

        raise SystemExit(look_tongji.main())
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
