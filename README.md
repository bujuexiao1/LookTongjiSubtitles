# Tongji Look Subtitles

同济课堂回放字幕工具。可以下载自己账号有权限访问的 Tongji Look 回放视频，并生成适合 PotPlayer 使用的 `.srt` 字幕。

## 下载即用版

只想直接使用的话，打开 Releases 下载最新版 Windows 压缩包：

https://github.com/bujuexiao1/LookTongjiSubtitles/releases/latest

下载后解压整个文件夹，双击 `LookTongjiSubtitlesV2.exe` 启动。不要把 exe 单独拎出来运行，旁边的 `_internal`、`tools` 等文件夹都需要保留。

## 使用前准备

推荐使用 PotPlayer 播放生成后的视频和字幕：

https://potplayer.daum.net/

如果字幕文件和视频文件在同一个目录、文件名也一致，PotPlayer 一般会自动加载字幕。

## 基本用法

1. 打开 `LookTongjiSubtitlesV2.exe`。
2. 在设置里填写同济账号信息，先点登录测试。
3. 选择日期范围，也可以填写课程名或老师关键词。
4. 搜索课程回放，勾选需要处理的视频。
5. 点击开始处理，等待下载和字幕生成完成。
6. 处理完成后，到输出目录查看 `.mp4` 和 `.srt` 文件。

成品目录会尽量保持清爽，主要保留视频和字幕。转写文本、健康检查、临时文件等会放到“中间产物”文件夹里。

## 说明

- 工具只会搜索和处理当前账号本来就有权限访问的课程。
- 长视频生成字幕会比较慢，期间不要反复关闭程序。
- 如果要翻译字幕，需要在设置里填写可用的 OpenAI 兼容 API 信息。
- 下载和生成的课程内容请只用于个人学习，遵守学校和平台规则。

## 从源码运行

如果你想自己改代码或调试，可以使用源码版。

安装依赖：

```bash
pip install -r requirements.txt
```

运行 V2 图形界面：

```bash
python scripts/look_tongji_gui_v2.py
```

查看命令行帮助：

```bash
python scripts/look_tongji.py --help
```

## 打包 Windows 版

```bash
python scripts/build_windows_app_v2.py
```

打包结果会生成在 `dist/LookTongjiSubtitlesV2/`，发布时请打包整个文件夹，不要只发单个 exe。

## 隐私

仓库不包含账号、密码、登录缓存、生成的视频字幕、日志和本地设置。运行时产生的这些文件也已经加入 `.gitignore`，不要手动提交到仓库。
