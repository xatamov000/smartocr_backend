@echo off
title SmartOCR Local Server
color 0A

echo ================================================
echo   SmartOCR Local Server - Windows
echo ================================================
echo.

:: Python tekshirish
python --version >nul 2>&1
if errorlevel 1 (
    echo [XATO] Python topilmadi!
    echo Python o'rnating: https://python.org
    pause
    exit /b 1
)

:: Tesseract tekshirish
if not exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    echo [OGOHLANTIRISH] Tesseract topilmadi!
    echo Tesseract o'rnating: https://github.com/UB-Mannheim/tesseract/wiki
    echo O'rnatish papkasi: C:\Program Files\Tesseract-OCR\
    pause
    exit /b 1
)

:: Tesseract PATH ga qo'shish
set PATH=%PATH%;C:\Program Files\Tesseract-OCR

:: Virtual environment tekshirish
if not exist "venv" (
    echo [INFO] Virtual environment yaratilmoqda...
    python -m venv venv
)

:: Virtual environmentni faollashtirish
call venv\Scripts\activate.bat

:: Kutubxonalar o'rnatish
echo [INFO] Kutubxonalar tekshirilmoqda...
pip install -r requirements.txt -q

:: Kompyuter IP manzilini ko'rsatish
echo.
echo ================================================
echo   SERVER MA'LUMOTLARI:
echo ================================================
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do (
    set IP=%%a
    set IP=!IP: =!
    echo   IP manzil: http://%%a:8000
)
echo   (Flutterdagi IP ni shu manzilga o'zgartiring)
echo ================================================
echo.
echo Server ishga tushmoqda... (Ctrl+C bilan to'xtatish)
echo.

:: Serverni ishga tushirish
cd /d "%~dp0"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

pause