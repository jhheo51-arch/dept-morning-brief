@echo off
chcp 65001 >nul
rem 아침 점검 한 번 실행(exe 판). 처음이면 양식과 설정 파일부터 만듭니다. 작업 스케줄러에서는 run_brief.bat quiet 로 등록합니다.
cd /d "%~dp0"
if not exist output mkdir output
if not exist config.local.toml (
  "%~dp0morning_brief.exe" init
  echo inputs 폴더의 엑셀에 내 자료를 붙여 넣은 뒤 run_brief.bat 를 다시 실행하세요.
  if /i not "%1"=="quiet" pause
  exit /b 0
)
echo [%date% %time%] >> output\run.log
"%~dp0morning_brief.exe" >> output\run.log 2>&1
if errorlevel 1 (
  echo 실행 실패. 이유는 output\run.log 맨 아래에 있습니다.
  powershell -NoProfile -Command "Get-Content -Encoding UTF8 -Tail 2 'output\run.log'"
  if /i not "%1"=="quiet" pause
  exit /b 1
)
if /i not "%1"=="quiet" start "" "output\site\index.html"
