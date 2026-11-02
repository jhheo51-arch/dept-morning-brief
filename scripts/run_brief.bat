@echo off
chcp 65001 >nul
rem 아침 점검 한 번 실행. 작업 스케줄러에서는 run_brief.bat quiet 로 등록하면 화면을 띄우지 않습니다.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
if not exist output mkdir output
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
echo [%date% %time%] >> output\run.log
%PY% -m brief.main >> output\run.log 2>&1
if errorlevel 1 (
  echo 실행 실패. 이유는 output\run.log 맨 아래에 있습니다.
  powershell -NoProfile -Command "Get-Content -Encoding UTF8 -Tail 2 'output\run.log'"
  if /i not "%1"=="quiet" pause
  exit /b 1
)
if /i not "%1"=="quiet" start "" "output\site\index.html"
