# Tongji Look Subtitles

Windows GUI tool for `look.tongji.edu.cn`.

This public edition is intended for normal personal use only:

- It only works with replay content your own Tongji Look account can already access.
- It does not include any permission-bypass or browser-assisted capture helper.
- It can download replay videos you can already play normally and generate subtitle files for them.

## Features

- Windows GUI, no command line required for end users
- Tongji account login and local config saving
- Replay page URL input
- Batch replay search within your own accessible course scope
- Video download
- Chinese subtitle generation
- Optional translated subtitle workflows
- PotPlayer-friendly output naming

## For End Users

Regular users should download the packaged Windows build from the repository `Releases` page, not the source-code ZIP from `Code -> Download ZIP`.

If you are distributing the packaged app to other users:

1. Send the whole `LookTongjiSubtitles` folder or the release zip.
2. The user extracts it.
3. The user double-clicks `LookTongjiSubtitles.exe`.
4. The GUI opens and can be used directly.

Do not send only the `exe`, because the surrounding runtime files are required.

## Build A Windows App

Requirements:

- Windows
- Python 3.11+ or newer
- `pip`

Install dependencies:

```bash
pip install -r requirements.txt
```

Build the public Windows GUI app:

```bash
python scripts/build_windows_app.py
```

Output:

- `dist/LookTongjiSubtitles/`
- `dist/LookTongjiSubtitles.zip`

Run the source GUI directly:

```bash
python scripts/look_tongji_gui_public.py
```

## Notes

- The default build bundles `ffmpeg` when it is available on the build machine.
- The default build uses the user's local Edge or Chrome installation.
- If you want to bundle a Playwright Chromium runtime too, build with:

```bash
python scripts/build_windows_app.py --bundle-browser
```

- Bundling a browser makes the package larger.

## Compliance

Please follow school and platform rules when using this project.

This repository is for authorized personal learning workflows only.
