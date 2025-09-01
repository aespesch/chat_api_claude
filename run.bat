@echo off
REM Script to run the Claude Chat Streamlit application on Windows

echo ========================================
echo Starting Claude Chat Interface...
echo ========================================

REM Check if .env file exists
if not exist .env (
    echo WARNING: .env file not found!
    echo Please create a .env file with your API key:
    echo KEY=your-anthropic-api-key-here
    pause
    exit /b 1
)

REM Check if virtual environment exists
if exist venv (
    echo Activating virtual environment...
    call venv\Scripts\activate
) else (
    echo Creating virtual environment...
    python -m venv venv
    call venv\Scripts\activate
)

REM Install dependencies
echo Installing dependencies...
pip install -q -r requirements.txt

REM Create .streamlit directory if it doesn't exist
if not exist .streamlit (
    echo Creating .streamlit configuration directory...
    mkdir .streamlit
)

REM Run the Streamlit app
echo ========================================
echo Launching Streamlit app...
echo Opening at: http://localhost:8501
echo Press Ctrl+C to stop the server
echo ========================================

streamlit run app.py

pause