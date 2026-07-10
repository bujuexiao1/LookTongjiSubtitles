# Tongji Look Subtitles

A Windows desktop tool for downloading accessible Tongji Look replay videos and generating PotPlayer-ready subtitle files.

## Download Ready-To-Use Version

If you only want to use the Windows app, download the latest zip from:

https://github.com/bujuexiao1/LookTongjiSubtitles/releases/latest

Unzip the whole folder and run `LookTongjiSubtitlesV2.exe`. Do not move the exe out of the folder.

## Features

- Sign in with your own Tongji account.
- Search replay courses that your account can already access.
- Download replay videos.
- Generate Chinese `.srt` subtitles and transcript text.
- Optionally translate subtitles through an OpenAI-compatible API.
- Package the final output as same-name `.mp4` + `.srt` files for PotPlayer.
- Archive intermediate files into `中间产物`, keeping the output folder clean.
- V2 build uses two executables:
  - `LookTongjiSubtitlesV2.exe`: graphical desktop app.
  - `LookTongjiSubtitlesV2CLI.exe`: console helper used by the GUI for stable background tasks.

## Privacy

This repository does not include credentials, login sessions, generated videos, generated subtitles, logs, or local settings.

Runtime-only files are ignored by Git:

- `.env`
- `state/`
- `logs/`
- `tongji-output/`
- `build/`
- `dist/`

Store credentials only in your local `.env` file or environment variables. Do not commit them.

## Requirements

- Windows
- Python 3.11 or newer
- `pip`

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run From Source

Public GUI:

```bash
python scripts/look_tongji_gui_public.py
```

V2 GUI:

```bash
python scripts/look_tongji_gui_v2.py
```

CLI:

```bash
python scripts/look_tongji.py --help
```

## Build Windows App

Build the V2 Windows folder:

```bash
python scripts/build_windows_app_v2.py
```

The built app folder will be created under `dist/LookTongjiSubtitlesV2/`.

Build the older public app:

```bash
python scripts/build_windows_app.py
```

## Usage Notes

- Send the whole built folder when sharing a packaged app. Do not send only the `.exe`.
- Subtitle generation can take a while for long lectures.
- Use this tool only for replays that your account is allowed to access.
- Follow your school and platform rules when using downloaded materials.
