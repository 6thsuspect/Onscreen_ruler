@echo off
REM ===========================================================================
REM  Build OnscreenRuler.exe on Windows  (double-click this file)
REM ===========================================================================
setlocal
cd /d "%~dp0"

echo.
echo === Onscreen Measuring Ruler - build script ===
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python was not found on PATH.
    echo     Install Python 3.9+ from https://www.python.org/downloads/windows/
    echo     and tick "Add python.exe to PATH" during setup, then run this again.
    pause
    exit /b 1
)

echo [1/3] Installing / updating PyInstaller ...
python -m pip install --upgrade pip >nul
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [X] Could not install PyInstaller.
    pause
    exit /b 1
)

echo [2/3] Cleaning old build ...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [3/3] Building OnscreenRuler.exe ...
python -m PyInstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name OnscreenRuler ^
    --icon icon.ico ^
    --version-file version_info.txt ^
    onscreen_ruler.py
if errorlevel 1 (
    echo [X] Build failed.
    pause
    exit /b 1
)

copy /y "dist\OnscreenRuler.exe" "OnscreenRuler.exe" >nul
echo.
echo ===========================================================
echo  Done!  Your app is:  %CD%\OnscreenRuler.exe
echo  Double-click it to measure anything on your screen.
echo ===========================================================
echo.
pause
