@echo off
chcp 65001 >nul
rem exe 만들기(Claude 요약은 빠짐). Python 이 있는 PC에서 한 번 돌리면 dist\morning_brief 폴더가 생깁니다. 이 폴더를 통째로 옮겨 씁니다.
cd /d "%~dp0.."
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m pip install -q google-play-scraper==1.2.7 "numpy>=2.0" "holidays>=0.60" "openpyxl>=3.1" pyinstaller
if errorlevel 1 exit /b 1
%PY% -m PyInstaller --noconfirm --clean --name morning_brief --collect-all holidays --exclude-module anthropic --exclude-module pytest --add-data "%CD%\config.toml;." --add-data "%CD%\docs\index.html;docs" --distpath dist --workpath build --specpath build scripts\exe_entry.py
if errorlevel 1 exit /b 1
copy /y scripts\exe_run_brief.bat dist\morning_brief\run_brief.bat >nul
echo 완료: dist\morning_brief 폴더를 통째로 옮겨 쓰세요.
