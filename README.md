# Tongji Look Subtitles

Windows subtitle tool for `look.tongji.edu.cn`.

## Download

If you just want to use the program, open `Releases` and download `LookTongjiSubtitles.zip`.

After extracting the zip, double-click `LookTongjiSubtitles.exe`.

The source-code zip from `Code -> Download ZIP` is not the runnable package.

## What It Does

- Sign in with your own Tongji account
- Open replay links you can already access normally
- Download the replay video
- Generate subtitle files for the downloaded video
- Save output in a layout that is easy to use with PotPlayer

## Scope

This public build is only meant for replay content that your own account can already watch on Tongji Look.

It does not include any browser-assisted capture helper or permission-bypass workflow.

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
