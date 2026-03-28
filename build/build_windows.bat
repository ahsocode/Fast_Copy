@echo off
REM Build CopySoft.exe for Windows (portable, no installer needed)
REM Run this script ON A WINDOWS MACHINE with Python 3.11+ installed.

cd /d "%~dp0\.."

echo =^> Installing dependencies...
pip install PyQt5==5.15.11 pyinstaller==6.11.1

echo =^> Building Windows exe with spec file...
pyinstaller copysoft.spec --clean --noconfirm

echo.
if exist dist\CopySoft.exe (
    echo =^> SUCCESS: dist\CopySoft.exe is ready
    echo    Size:
    for %%A in (dist\CopySoft.exe) do echo    %%~zA bytes
) else (
    echo =^> ERROR: Build failed, check output above
)
pause
