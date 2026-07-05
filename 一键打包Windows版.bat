@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 正在打包 Tongji Look 公开版字幕工具，请不要关闭这个窗口。
echo 第一次打包时，可能会安装依赖或下载浏览器运行时，请耐心等待。
python "%~dp0scripts\build_windows_app.py"
if errorlevel 1 (
  echo.
  echo 打包失败。请把这个窗口里的报错信息发给维护者。
  pause
  exit /b 1
)
echo.
echo 打包完成。
echo 发布文件夹位置：
echo %~dp0dist\LookTongjiSubtitles
echo.
echo 请把整个 LookTongjiSubtitles 文件夹发给别人，不要只发 exe。
pause
