# Tongji Look Subtitles

Windows subtitle tool for `look.tongji.edu.cn`.

## Download

If you just want to use the program, open `Releases` and download `LookTongjiSubtitles.zip`.

After extracting the zip, double-click `LookTongjiSubtitles.exe`.

The source-code zip from `Code -> Download ZIP` is not the runnable package.

## What It Does

- Sign in with your own Tongji account
- Open Tongji replay page links you can already access normally
- Process an MP4 direct URL that you already obtained elsewhere
- Download the replay video
- Generate subtitle files for the downloaded video
- Save output in a layout that is easy to use with PotPlayer

## Scope

This public build can also process a direct MP4 URL if you already have one.

It does not include any browser-assisted direct-link capture helper.

## Build From Source

Requirements:

- Windows
- Python 3.11 or newer
- `pip`

Install dependencies:

```bash
pip install -r requirements.txt
```

Build the public Windows app:

```bash
python scripts/build_windows_app.py
```

Run the source GUI directly:

```bash
python scripts/look_tongji_gui_public.py
```

## Notes

- Please send the whole extracted folder if you share it with someone else.
- Do not send only the `exe`.
- Please follow school and platform rules when using this project.
