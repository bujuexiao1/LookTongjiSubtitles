# Tongji Look 字幕工具

这是一个面向 `look.tongji.edu.cn` 的 Windows 图形界面工具。

这个公开版的使用边界很明确：

- 只支持你自己的 Tongji Look 账号本来就有权限访问的课程回放
- 只支持下载你本来就能正常播放的回放视频
- 不包含任何绕过权限的功能
- 不包含自用版里的浏览器辅助抓流能力

## 主要功能

- 可直接双击打开的 Windows GUI
- 支持保存同济账号配置
- 支持输入回放页面链接
- 支持在账号权限范围内批量搜索回放
- 支持下载视频
- 支持生成中文字幕
- 支持字幕翻译相关流程
- 支持输出适合 PotPlayer 使用的文件命名

## 给普通使用者

普通用户不要下载源码 ZIP，请直接下载本仓库 `Releases` 页面里的 Windows 成品包。

如果你要把打包好的版本发给别人，用法很简单：

1. 把整个 `LookTongjiSubtitles` 文件夹，或者发布用的 zip 压缩包发给对方
2. 对方解压后，双击 `LookTongjiSubtitles.exe`
3. 打开 GUI 后，填写账号信息和课程链接即可使用

注意：

- 不能只单独发送 `exe`
- 必须把整个文件夹一起发，因为运行依赖都在同级目录里
- GitHub 的 `Code -> Download ZIP` 下载到的是源码，不是可直接运行的成品包

## 给维护者

### 安装依赖

```bash
pip install -r requirements.txt
```

### 直接运行源码版 GUI

```bash
python scripts/look_tongji_gui_public.py
```

### 打包 Windows 可执行版本

```bash
python scripts/build_windows_app.py
```

打包完成后会生成：

- `dist/LookTongjiSubtitles/`
- `dist/LookTongjiSubtitles.zip`

## 打包说明

- 默认情况下，如果打包机器上能找到 `ffmpeg`，会自动一起打包进去
- 默认情况下，程序使用用户本机已有的 Edge 或 Chrome
- 如果你希望把 Playwright 的 Chromium 也一起打包进去，可以使用：

```bash
python scripts/build_windows_app.py --bundle-browser
```

这样体积会更大，但在部分环境下更省心。

## 适用范围

这个公开版适合发到 GitHub，也适合给其他正常用户使用。

前提是：

- 用户自己有 Tongji Look 账号
- 用户访问的是自己本来就有权限观看的内容
- 用户遵守学校和平台的相关规则

## 合规说明

本项目仅用于已授权内容的个人学习辅助。

请勿将其用于未授权传播、绕过权限或违反平台规则的用途。
