@echo off
REM ===================================================================
REM  Build IBL Pressure into a one-folder Windows executable.
REM
REM  Double-click this file, or run it from a terminal in this folder.
REM  Result:  dist\IBLpressure\IBLpressure.exe
REM ===================================================================
setlocal

cd /d "%~dp0"

REM --- use the project virtual environment if there is one ------------
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else if exist "..\.venv\Scripts\python.exe" (
    set "PY=..\.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo.
echo === Using %PY%
"%PY%" --version || goto :fail

echo.
echo === Installing / updating dependencies
"%PY%" -m pip install --upgrade pip                || goto :fail
"%PY%" -m pip install -r requirements.txt          || goto :fail
"%PY%" -m pip install pyinstaller                  || goto :fail

echo.
echo === Checking the pressure conversions against the VGC083A manual
"%PY%" -m ibl.conversion                           || goto :fail

echo.
echo === Cleaning old build output
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo.
echo === Running PyInstaller (one folder, windowed)
"%PY%" -m PyInstaller IBLpressure.spec --noconfirm || goto :fail

echo.
echo ===================================================================
echo  Done.
echo  Your program is:  dist\IBLpressure\IBLpressure.exe
echo.
echo  Copy the WHOLE dist\IBLpressure folder to the control PC.
echo  That PC also needs the LabJack LJM software installed:
echo      https://support.labjack.com/docs/ljm-software-installer
echo ===================================================================
echo.
pause
exit /b 0

:fail
echo.
echo *** BUILD FAILED - see the messages above. ***
echo.
pause
exit /b 1
