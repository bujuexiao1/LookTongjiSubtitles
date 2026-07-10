# Tongji Look Subtitles

这是一个用于 Tongji Look 回放视频下载和字幕生成的 Windows 桌面工具。

## 下载即用版

如果只是想直接使用 Windows 程序，请到 Releases 下载最新版 zip：

https://github.com/bujuexiao1/LookTongjiSubtitles/releases/latest

解压整个文件夹后，双击 `LookTongjiSubtitlesV2.exe`。不要把 exe 单独移出文件夹。

## 功能

- 使用你自己的同济账号登录。
- 搜索当前账号有权限访问的回放课程。
- 下载课程回放视频。
- 生成中文字幕 `.srt` 和转录文本。
- 可选：通过 OpenAI 兼容 API 翻译字幕。
- 自动整理成 PotPlayer 易用的同名 `.mp4` + `.srt`。
- 自动把中间产物归档到 `中间产物` 文件夹，成品目录只保留视频和字幕。
- V2 打包版使用双入口：
  - `LookTongjiSubtitlesV2.exe`：给用户双击使用的图形界面。
  - `LookTongjiSubtitlesV2CLI.exe`：给 GUI 调用的后台命令行 helper，用来稳定收集日志、进度和退出码。

## 隐私说明

仓库不包含账号密码、登录缓存、生成的视频/字幕、日志或本地设置。

以下运行时文件不会提交到 Git：

- `.env`
- `state/`
- `logs/`
- `tongji-output/`
- `build/`
- `dist/`

请只把账号、密码和 API Key 保存在你本机的 `.env` 或环境变量里，不要提交到仓库。

## 环境要求

- Windows
- Python 3.11 或更新版本
- `pip`

安装依赖：

```bash
pip install -r requirements.txt
```

## 从源码运行

公开版 GUI：

```bash
python scripts/look_tongji_gui_public.py
```

V2 GUI：

```bash
python scripts/look_tongji_gui_v2.py
```

命令行：

```bash
python scripts/look_tongji.py --help
```

## 打包 Windows 程序

构建 V2 Windows 文件夹：

```bash
python scripts/build_windows_app_v2.py
```

构建结果会输出到 `dist/LookTongjiSubtitlesV2/`。

构建旧版公开 GUI：

```bash
python scripts/build_windows_app.py
```

## 使用说明

- 分享打包版时请发送整个构建文件夹，不要只发送单个 `.exe`。
- 长视频生成字幕可能需要一段时间。
- 请只处理当前账号有权限访问的课程回放。
- 使用下载内容时请遵守学校和平台规则。
