@echo off
echo Starting SmartOCR with PaddleOCR engine...
cd /d "%~dp0"
venv312\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pause
