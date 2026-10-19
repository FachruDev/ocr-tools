@echo off
REM Instalasi pertama kali: buat virtual environment dan pasang semua paket.
cd /d "%~dp0"
if not exist .venv (
    echo Membuat virtual environment...
    python -m venv .venv || goto :error
)
echo Memasang paket (butuh internet, hanya sekali)...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt || goto :error
echo.
echo Selesai. Jalankan "jalankan_desktop.bat" atau "jalankan_web.bat".
pause
exit /b 0

:error
echo.
echo Instalasi gagal. Pastikan Python 3.10+ terpasang dan ada koneksi internet.
pause
exit /b 1
