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
echo === Checking the pressure conversions against the VGC083A manual
set "PYTHONPATH=%~dp0src"
"%PY%" -m ibl.conversion                           || goto :fail

echo.
echo === Creating README for end users
(
echo ============================================================
echo  IBL Pressure
echo ============================================================
echo.
echo  IMPORTANT: Extract this ENTIRE folder before running.
echo  Do NOT double-click IBLpressure.exe from inside a .zip
echo  or .7z archive -- it will fail with a missing DLL error.
echo.
echo  After extracting, just run IBLpressure.exe.
echo.
echo  This PC also needs the LabJack LJM software installed:
echo      https://support.labjack.com/docs/ljm-software-installer
echo ============================================================
) > README.txt

echo.
echo === Cleaning old build output
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo.
echo === Running PyInstaller (one folder, windowed)
"%PY%" -m PyInstaller IBLpressure.spec --noconfirm || goto :fail

echo.
echo === Copying LabJack installer into dist
for %%F in (vendor\*.exe) do copy /y "%%F" "dist\IBLpressure\%%~nxF" || goto :fail

echo.
echo === Putting the README where end users will actually see it
copy /y README.txt "dist\IBLpressure\README.txt" >nul || goto :fail

echo.
echo === Verifying the build output
"%PY%" verify_build.py                             || goto :failverify

echo.
echo ===================================================================
echo  Done - build verified.
echo  Your program is:  dist\IBLpressure\IBLpressure.exe
echo.
echo  Copy the WHOLE dist\IBLpressure folder to the control PC.
echo.
echo  After copying, you can prove nothing was lost in transit with:
echo      python verify_build.py --check "D:\wherever\IBLpressure"
echo  (or just compare the file count printed in MANIFEST.txt)
echo ===================================================================
echo.
exit /b 0

:fail
echo.
echo *** BUILD FAILED - see the messages above. ***
echo.
exit /b 1

:failverify
echo.
echo *** BUILD FINISHED BUT THE OUTPUT IS INCOMPLETE. ***
echo.
echo  PyInstaller said it was done, but files it collected are missing
echo  from dist\IBLpressure. The usual cause is antivirus quarantining a
echo  .pyd file right after it was written.
echo.
echo  Check Windows Security -^> Protection history, restore anything it
echo  took, add this folder to the exclusion list, then build again.
echo.
echo  Do NOT ship this folder - it will crash on the control PC with a
echo  ModuleNotFoundError.
echo.
exit /b 1
