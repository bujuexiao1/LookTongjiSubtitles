#!/usr/bin/env python3
"""Build the public Windows app folder for Tongji Look subtitles."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BUILD_ROOT = PROJECT_ROOT / "build" / "windows_app"
BROWSER_DIR = BUILD_ROOT / "ms-playwright"
DIST_ROOT = PROJECT_ROOT / "dist"

APP_NAME = "LookTongjiSubtitles"
ENTRY_FILE = SCRIPT_DIR / "look_tongji_gui_public.py"

COMMON_HIDDEN_IMPORTS = [
    "look_tongji",
    "tongji_backend.auth",
    "tongji_backend.client",
    "tongji_backend.config",
    "tongji_backend.transcriber",
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

README_TEXT = """Look 回放字幕工具（公开版）

这个版本给正常公开使用准备，只处理你自己的 Tongji Look 账号本来就能访问的回放内容。

怎么用：
1. 解压整个压缩包。
2. 双击 LookTongjiSubtitles.exe。
3. 填写账号信息，或者直接粘贴回放页面链接。
4. 按界面提示下载视频并生成字幕。

提醒：
- 发送给别人时，请把整个文件夹一起发，不要只发 exe。
- 这个公开版不带浏览器辅助抓取功能。
- 使用时请遵守学校和平台规则。
"""


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("$ " + " ".join(f'"{item}"' if " " in item else item for item in cmd))
    subprocess.run(cmd, cwd=str(cwd or PROJECT_ROOT), env=env, check=True)


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
    run([sys.executable, "-m", "playwright", "install", "chromium"], env=env)


def copy_ffmpeg(dist_app: Path, *, bundle_ffmpeg: bool) -> None:
    if not bundle_ffmpeg:
        print("[OK] Skipping bundled ffmpeg. End users need ffmpeg on PATH.")
        return
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
        "Package Info: Public build",
        f"ffmpeg: {'bundled' if bundle_ffmpeg else 'not bundled; user needs local ffmpeg'}",
        f"browser: {'bundled Playwright Chromium' if bundle_browser else 'use local Edge/Chrome'}",
        "",
        "Send the whole folder to users, not only the exe.",
        "",
    ]
    readme = dist_app / "README.txt"
    readme.write_text(README_TEXT + "\n".join(suffix), encoding="utf-8")


def create_release_zip(dist_app: Path) -> Path:
    archive_base = DIST_ROOT / dist_app.name
    archive_path = archive_base.with_suffix(".zip")
    if archive_path.exists():
        archive_path.unlink()
    created = shutil.make_archive(str(archive_base), "zip", root_dir=dist_app.parent, base_dir=dist_app.name)
    result = Path(created)
    print(f"[OK] Created zip archive: {result} ({format_size(result.stat().st_size)})")
    return result


def build_public(*, bundle_browser: bool, bundle_ffmpeg: bool, make_zip: bool) -> list[Path]:
    dist_app = DIST_ROOT / APP_NAME
    if dist_app.exists():
        shutil.rmtree(dist_app)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--noconsole",
        "--onedir",
        "--name",
        APP_NAME,
        "--paths",
        str(SCRIPT_DIR),
        "--collect-all",
        "playwright",
    ]
    for hidden_import in COMMON_HIDDEN_IMPORTS:
        cmd += ["--hidden-import", hidden_import]
    cmd += [
        "--exclude-module",
        "IPython",
        "--exclude-module",
        "matplotlib",
        "--exclude-module",
        "numpy",
        "--exclude-module",
        "PIL",
        "--exclude-module",
        "pandas",
        "--exclude-module",
        "scipy",
        "--exclude-module",
        "jedi",
        "--exclude-module",
        "pygments",
        str(ENTRY_FILE),
    ]
    run(cmd, cwd=PROJECT_ROOT)

    copy_ffmpeg(dist_app, bundle_ffmpeg=bundle_ffmpeg)
    if bundle_browser:
        copy_playwright_browser(dist_app)
    trim_distribution(dist_app)
    write_readme(dist_app, bundle_ffmpeg=bundle_ffmpeg, bundle_browser=bundle_browser)

    outputs: list[Path] = [dist_app]
    if make_zip:
        outputs.append(create_release_zip(dist_app))
    return outputs


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
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="Do not create a zip archive after build.",
    )
    args = parser.parse_args()

    ensure_pyinstaller()
    if args.bundle_browser:
        ensure_playwright_browser()

    outputs = build_public(
        bundle_browser=args.bundle_browser,
        bundle_ffmpeg=not args.no_ffmpeg,
        make_zip=not args.no_zip,
    )
    print("\nDone:")
    for item in outputs:
        print(f"  - {item}")
    print("Send the whole folder to users, not only the exe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
