# Tongji Look Subtitles

给 Tongji Look 课堂回放用的字幕小工具。

它可以把自己账号能看的回放视频下载下来，并生成同名 `.srt` 字幕。视频和字幕放在一起后，用 PotPlayer 打开视频就能看。

## 下载

Windows 版在这里下载：

https://github.com/bujuexiao1/LookTongjiSubtitles/releases/latest

下载 zip 后，先完整解压，再双击里面的 `LookTongjiSubtitlesV2.exe`。

不要只把 exe 单独拖出来用，整个文件夹要放在一起。

## 播放器

推荐用 PotPlayer：

https://potplayer.daum.net/

生成完成后，输出目录里会有 `.mp4` 视频和 `.srt` 字幕。两个文件名字一样、放在同一个文件夹里时，PotPlayer 一般会自动加载字幕。

## 怎么用

1. 打开 `LookTongjiSubtitlesV2.exe`。
2. 到设置里填同济账号，先点一次登录测试。
3. 选择日期范围，可以再填课程名或老师关键词。
4. 搜索回放，勾选想处理的视频。
5. 点开始处理，等下载和字幕生成结束。
6. 到输出目录里，用 PotPlayer 打开 `.mp4`。

输出目录里主要看视频和字幕就行。其他临时文件会放到“中间产物”文件夹里。

## 提醒

- 只能处理你自己的账号本来就能看的课程回放。
- 长视频生成字幕会慢一点，放着等它跑完就好。
- 只要中文字幕的话，不需要填 API Key。
- 如果要翻译字幕，再到设置里填 OpenAI 兼容接口。
- `.mp4` 和 `.srt` 文件名一样、放在同一个文件夹里时，PotPlayer 一般会自动加载字幕。
- 课程内容请只用于个人学习。

## 源码运行

想自己改或调试的话，可以用源码版：

```bash
pip install -r requirements.txt
python scripts/look_tongji_gui_v2.py
```
