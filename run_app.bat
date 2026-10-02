@echo off
rem Starts the HRM Converter app in your browser. Double-click this file.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First-time setup: creating the Python environment...
    py -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -e ".[app]" || goto :error
)
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless false
goto :eof
:error
echo Setup failed. Check that Python 3.10 or newer is installed.
pause
