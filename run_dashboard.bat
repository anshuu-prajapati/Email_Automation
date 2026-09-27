@echo off
REM Start the Streamlit dashboard on Windows

echo.
echo ========================================
echo  Job Outreach Automation Dashboard
echo ========================================
echo.

REM Check if venv exists
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found!
    echo Please run: python -m venv venv
    echo Then: venv\Scripts\activate
    echo Then: pip install -r requirements.txt
    pause
    exit /b 1
)

REM Activate venv
call venv\Scripts\activate.bat

REM Check if streamlit is installed
python -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo Installing Streamlit...
    pip install streamlit
)

REM Run streamlit
echo.
echo Starting dashboard...
echo Open your browser to: http://localhost:8501
echo.
echo Press Ctrl+C to stop the dashboard
echo.

streamlit run streamlit_app.py

pause
