# 中文说明

## 下载

如果你只是想直接使用程序，请到 `Releases` 下载 `LookTongjiSubtitles.zip`。

解压之后，双击 `LookTongjiSubtitles.exe` 即可运行。

`Code -> Download ZIP` 下载到的是源码，不是可直接运行的成品包。

## 这个版本能做什么

- 使用你自己的 Tongji 账号登录
- 处理你账号本来就能正常访问的 Tongji Look 回放页面
- 也可以直接处理你已经通过其他方式获取到的 MP4 长链接
- 下载视频
- 生成字幕文件
- 输出适合配合 PotPlayer 使用的同名 `mp4 + srt`

## 使用方式

1. 打开程序。
2. 在主界面中粘贴 Tongji 回放页面链接，或者粘贴你已经拿到的 MP4 长链接。
3. 选择字幕语言。
4. 点击对应按钮开始下载和生成字幕。
5. 完成后，到输出目录里用 PotPlayer 打开生成的视频即可。

也可以使用“批量回放”功能，按老师、课程名称和日期范围搜索你账号权限内可访问的回放，再批量下载和生成字幕。

## 说明

- 这个公开版可以处理你已经拿到的 MP4 直链，但不会帮你抓取长链接。
- 转录和添加字幕通常需要较长时间，建议在观看前提前准备。
- 分享给别人时，请发送整个解压后的文件夹，不要只发送 `exe`。
- 使用时请遵守学校和平台规则。

## 从源码构建

需要：

- Windows
- Python 3.11 或更新版本
- `pip`

安装依赖：

```bash
pip install -r requirements.txt
```

构建公开版 Windows 程序：

```bash
python scripts/build_windows_app.py
```

直接运行源码版 GUI：

```bash
python scripts/look_tongji_gui_public.py
```
