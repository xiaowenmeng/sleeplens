@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Please install the project environment first. See README.md.
    pause
    exit /b 1
)
echo SleepLens: http://127.0.0.1:8501
echo Viewing records is free. AI questions use your configured API credits.
echo Close this window or press Ctrl+C to stop the app.
".venv\Scripts\python.exe" -m streamlit run app.py
pause
