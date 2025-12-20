@echo off
echo Building Wellness at Work Eye Tracker for Windows...

cd /d "%~dp0"

REM Install dependencies
pip install -r requirements.txt

REM Build with PyInstaller
pyinstaller --onefile --windowed --name "WaW_EyeTracker" --icon "icon.ico" main.py

REM Create dist directory if it doesn't exist
if not exist "dist" mkdir "dist"

REM Copy additional files
copy "blink_buffer.json" "dist\" 2>nul
copy ".token.json" "dist\" 2>nul

echo Build complete! Executable is in dist\WaW_EyeTracker.exe
echo.
echo To create an MSI installer, you can use tools like:
echo - Inno Setup (https://jrsoftware.org/isinfo.php)
echo - WiX Toolset (https://wixtoolset.org/)
echo - cx_Freeze with MSI builder
echo.
pause