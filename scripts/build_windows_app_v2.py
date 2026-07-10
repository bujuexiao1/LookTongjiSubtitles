#!/usr/bin/env python3
"""Build the PySide6 GUI V2 Windows app folder for Tongji Look subtitles."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BUILD_ROOT = PROJECT_ROOT / "build" / "windows_app_v2"
BROWSER_DIR = BUILD_ROOT / "ms-playwright"
DIST_ROOT = PROJECT_ROOT / "dist"

APP_NAME = "LookTongjiSubtitlesV2"
HELPER_NAME = "LookTongjiSubtitlesV2CLI"
ENTRY_FILE = SCRIPT_DIR / "look_tongji_gui_v2.py"
HELPER_ENTRY_FILE = SCRIPT_DIR / "look_tongji_cli_helper_v2.py"

HIDDEN_IMPORTS = [
    "look_tongji",
    "tongji_backend.auth",
    "tongji_backend.client",
    "tongji_backend.config",
    "tongji_backend.transcriber",
]

EXCLUDED_MODULES = [
    "IPython",
    "matplotlib",
    "numpy",
    "PIL",
    "pandas",
    "scipy",
    "jedi",
    "pygments",
]

PLAYWRIGHT_TRIM_PATHS = [
    Path("_internal/playwright/async_api"),
    Path("_internal/playwright/driver/README.md"),
    Path("_internal/playwright/driver/package/README.md"),
    Path("_internal/playwright/driver/package/api.json"),
    Path("_internal/playwright/driver/package/protocol.yml"),
    Path("_internal/playwright/driver/package/types"),
    Path("_internal/playwright/driver/package/lib/vite"),
]

README_TEXT = """Tongji Look Subtitles

这是一个可以直接使用的 Windows 字幕工具。

使用方法：
1. 解压整个文件夹。
2. 双击 LookTongjiSubtitlesV2.exe。
3. 到“设置”填写同济账号、密码和输出目录。
4. 如果只需要中文字幕，不用填写 API Key。
5. 单个回放去“单个回放”，批量查课去“批量搜索”。
6. 搜索结果左侧可以直接勾选要处理的回放。
7. 完成后到“结果文件”打开视频和字幕。

输出目录里主要保留 mp4 视频和 srt 字幕。
其他中间文件会放进“中间产物”文件夹。

播放器下载：
推荐使用 PotPlayer 播放生成的视频和字幕。
打开官网 https://potplayer.tv/ ，根据自己的 Windows 系统选择 64 位或 32 位版本下载。
安装后用 PotPlayer 打开生成的 mp4 视频即可。视频和字幕文件名相同、放在同一个文件夹里时，一般会自动加载字幕。

提醒：
- 不要只移动 exe，请保留整个文件夹结构。
- 同一天同一门课可能会有多段回放，软件会显示“第 1/2 段”这类标记。
- 生成字幕需要一些时间，长视频请耐心等待。
- 如果 Windows 提示风险，点“更多信息”后选择“仍要运行”。
- 使用时请遵守学校和平台规则。
"""


def run(cmd: list[str]) -> None:
    print("$ " + " ".join(f'"{item}"' if " " in item else item for item in cmd))
    subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=True)


def format_size(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def folder_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for file in path.rglob("*"):
        if file.is_file():
            total += file.stat().st_size
    return total


def ensure_pyinstaller() -> None:
    req = PROJECT_ROOT / "requirements.txt"
    if req.exists():
        run([sys.executable, "-m", "pip", "install", "-r", str(req)])
    try:
        import PyInstaller  # noqa: F401
    except Exception:
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])


def ensure_playwright_browser() -> None:
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSER_DIR)
    print("$ " + " ".join([sys.executable, "-m", "playwright", "install", "chromium"]))
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        cwd=str(PROJECT_ROOT),
        env=env,
        check=True,
    )


def copy_ffmpeg(dist_app: Path) -> None:
    target = dist_app / "tools" / "ffmpeg" / "bin"
    target.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    try:
        import imageio_ffmpeg  # type: ignore

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).exists():
            ffmpeg = bundled
    except Exception:
        pass
    if not ffmpeg:
        print("[WARN] ffmpeg.exe was not found on this computer.")
        return
    shutil.copy2(ffmpeg, target / "ffmpeg.exe")
    print(f"[OK] Copied ffmpeg: {ffmpeg}")


def copy_playwright_browser(dist_app: Path) -> None:
    target = dist_app / "tools" / "ms-playwright"
    if target.exists():
        shutil.rmtree(target)
    if BROWSER_DIR.exists():
        shutil.copytree(BROWSER_DIR, target)
        print(f"[OK] Copied Playwright browser to: {target}")
    else:
        print("[WARN] Playwright browser folder not found; users need local Edge/Chrome.")


def trim_distribution(dist_app: Path) -> None:
    before = folder_size(dist_app)
    removed_bytes = 0
    removed_items: list[str] = []
    for rel_path in PLAYWRIGHT_TRIM_PATHS:
        target = dist_app / rel_path
        if not target.exists():
            continue
        removed_bytes += folder_size(target)
        removed_items.append(rel_path.as_posix())
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    after = folder_size(dist_app)
    print(f"[OK] Trimmed package: {format_size(before)} -> {format_size(after)}")
    if removed_items:
        print(f"[OK] Removed {len(removed_items)} Playwright extras, reclaimed {format_size(removed_bytes)}")


def write_readme(dist_app: Path, *, bundle_ffmpeg: bool, bundle_browser: bool) -> None:
    suffix = [
        "",
        f"ffmpeg: {'bundled' if bundle_ffmpeg else 'not bundled'}",
        f"browser: {'bundled Playwright Chromium' if bundle_browser else 'use local Edge/Chrome'}",
        "",
        "分享给别人时，请发送整个文件夹。",
        "",
    ]
    (dist_app / "README.txt").write_text(README_TEXT + "\n".join(suffix), encoding="utf-8-sig")


def _pyinstaller_cmd(*, name: str, console: bool, collect_playwright: bool) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--console" if console else "--noconsole",
        "--onedir",
        "--name",
        name,
        "--paths",
        str(SCRIPT_DIR),
    ]
    if collect_playwright:
        cmd += ["--collect-all", "playwright"]
    for hidden_import in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", hidden_import]
    for module_name in EXCLUDED_MODULES:
        cmd += ["--exclude-module", module_name]
    return cmd


def merge_helper_dist(dist_app: Path, dist_helper: Path) -> None:
    if not dist_helper.exists():
        raise FileNotFoundError(f"Helper build output not found: {dist_helper}")
    helper_exe = dist_helper / f"{HELPER_NAME}.exe"
    if not helper_exe.exists():
        raise FileNotFoundError(f"Helper exe not found: {helper_exe}")
    shutil.copy2(helper_exe, dist_app / helper_exe.name)
    helper_internal = dist_helper / "_internal"
    app_internal = dist_app / "_internal"
    if helper_internal.exists():
        shutil.copytree(helper_internal, app_internal, dirs_exist_ok=True)
    print(f"[OK] Merged CLI helper into app folder: {dist_app / helper_exe.name}")


def build_v2(*, bundle_browser: bool, bundle_ffmpeg: bool) -> Path:
    dist_app = DIST_ROOT / APP_NAME
    dist_helper = DIST_ROOT / HELPER_NAME
    if dist_app.exists():
        shutil.rmtree(dist_app)
    if dist_helper.exists():
        shutil.rmtree(dist_helper)
    gui_cmd = _pyinstaller_cmd(name=APP_NAME, console=False, collect_playwright=True)
    gui_cmd.append(str(ENTRY_FILE))
    run(gui_cmd)
    helper_cmd = _pyinstaller_cmd(name=HELPER_NAME, console=True, collect_playwright=False)
    helper_cmd.append(str(HELPER_ENTRY_FILE))
    run(helper_cmd)
    merge_helper_dist(dist_app, dist_helper)
    if bundle_ffmpeg:
        copy_ffmpeg(dist_app)
    else:
        print("[OK] Skipping bundled ffmpeg. End users need ffmpeg on PATH.")
    if bundle_browser:
        copy_playwright_browser(dist_app)
    trim_distribution(dist_app)
    write_readme(dist_app, bundle_ffmpeg=bundle_ffmpeg, bundle_browser=bundle_browser)
    return dist_app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bundle-browser",
        action="store_true",
        help="Bundle Playwright Chromium for machines without Edge/Chrome.",
    )
    parser.add_argument(
        "--no-ffmpeg",
        action="store_true",
        help="Do not bundle ffmpeg. Smaller, but users need ffmpeg on PATH.",
    )
    args = parser.parse_args()
    ensure_pyinstaller()
    if args.bundle_browser:
        ensure_playwright_browser()
    dist_app = build_v2(bundle_browser=args.bundle_browser, bundle_ffmpeg=not args.no_ffmpeg)
    print(f"Built V2 app at: {dist_app}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
