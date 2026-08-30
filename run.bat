@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0" >nul 2>&1 || goto :fatal_cd

if not exist "build" mkdir "build" >nul 2>&1
set "RUN_LOG=%CD%\build\run-bat.log"
>"%RUN_LOG%" echo [%DATE% %TIME%] KajovoKarty run.bat started.

set "MODE=%~1"
if not defined MODE set "MODE=--run"
if not "%~2"=="" goto :usage
if /I "%MODE%"=="--run" goto :mode_ok
if /I "%MODE%"=="--check" goto :mode_ok
if /I "%MODE%"=="--test" goto :mode_ok
if /I "%MODE%"=="--repair" goto :mode_ok
goto :usage

:mode_ok
call :log Mode=%MODE%

set "NATIVE_ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "NATIVE_ARCH=%PROCESSOR_ARCHITEW6432%"
if /I not "%NATIVE_ARCH%"=="AMD64" goto :unsupported_windows
call :log Native architecture=%NATIVE_ARCH%

set "BASE_PYTHON="
call :find_python
if not defined BASE_PYTHON call :install_python
if not defined BASE_PYTHON goto :python_missing
call :log Base Python=%BASE_PYTHON%

"%BASE_PYTHON%" -c "import struct,sys; w=getattr(sys,'getwindowsversion',lambda:None)(); raise SystemExit(0 if w and w.major>=10 and sys.version_info[:2]==(3,11) and struct.calcsize('P')*8==64 else 1)" >nul 2>&1
if errorlevel 1 goto :python_incompatible

if /I "%MODE%"=="--repair" if exist ".venv" (
  echo Opravuji lokalni virtualni prostredi...
  call :log Removing existing .venv
  rmdir /s /q ".venv"
  if exist ".venv" goto :venv_remove_failed
)

if not exist ".venv\Scripts\python.exe" (
  echo Vytvarim lokalni virtualni prostredi .venv...
  call :log Creating .venv
  "%BASE_PYTHON%" -m venv ".venv"
  if errorlevel 1 goto :venv_failed
)

set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
"%PYTHON_EXE%" -m pip --version >nul 2>&1
if errorlevel 1 (
  call :log pip missing; running ensurepip
  "%PYTHON_EXE%" -m ensurepip --upgrade
  if errorlevel 1 goto :pip_failed
)

call :log Starting scripts\bootstrap.py
"%PYTHON_EXE%" "scripts\bootstrap.py" "%MODE%"
set "EXIT_CODE=%ERRORLEVEL%"
call :log Bootstrap exit code=%EXIT_CODE%
if not "%EXIT_CODE%"=="0" goto :bootstrap_failed
exit /b 0

:find_python
set "CANDIDATE="
for %%P in ("%LocalAppData%\Programs\Python\Python311\python.exe" "%ProgramFiles%\Python311\python.exe") do (
  if exist "%%~P" (
    "%%~P" -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2]==(3,11) and struct.calcsize('P')*8==64 else 1)" >nul 2>&1
    if not errorlevel 1 set "BASE_PYTHON=%%~P"
  )
)
if defined BASE_PYTHON exit /b 0
where py >nul 2>&1
if errorlevel 1 exit /b 0
for /f "usebackq delims=" %%P in (`py -3.11-64 -c "import sys;print(sys.executable)" 2^>nul`) do set "CANDIDATE=%%P"
if defined CANDIDATE (
  "%CANDIDATE%" -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2]==(3,11) and struct.calcsize('P')*8==64 else 1)" >nul 2>&1
  if not errorlevel 1 set "BASE_PYTHON=%CANDIDATE%"
)
exit /b 0

:install_python
where winget >nul 2>&1
if errorlevel 1 exit /b 0
echo Python 3.11 x64 nebyl nalezen. Pokousim se jej nainstalovat pro aktualniho uzivatele...
call :log Installing Python 3.11.9 through winget
winget install --exact --id Python.Python.3.11 --version 3.11.9 --scope user --accept-package-agreements --accept-source-agreements --silent
if errorlevel 1 (
  echo Presna verze 3.11.9 neni dostupna. Zkousim nejnovejsi kompatibilni Python 3.11 x64...
  call :log Exact Python 3.11.9 install failed; trying current Python 3.11
  winget install --exact --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements --silent
)
set "BASE_PYTHON="
set "CANDIDATE="
call :find_python
exit /b 0

:usage
echo.
echo Pouziti:
echo   run.bat           kontrola prostredi a spusteni aplikace
echo   run.bat --check   pouze kontrola prostredi, souboru a databaze
echo   run.bat --test    kontrola prostredi a automaticke testy
echo   run.bat --repair  nove virtualni prostredi a oprava zavislosti
echo.
call :log Invalid command line
pause
exit /b 2

:fatal_cd
echo CHYBA: Nelze nastavit pracovni adresar aplikace.
set "EXIT_CODE=1"
goto :fatal

:unsupported_windows
echo CHYBA: KajovoKarty podporuje pouze Windows 10/11 x64.
set "EXIT_CODE=1"
goto :fatal

:python_missing
echo CHYBA: Kompatibilni 64bitovy Python 3.11 nebyl nalezen ani nainstalovan.
echo Nainstalujte Python 3.11 x64 pro aktualniho uzivatele nebo zpristupnete winget.
set "EXIT_CODE=1"
goto :fatal

:python_incompatible
echo CHYBA: Nalezeny Python nebo Windows nejsou podporovane.
echo Je vyzadovan Windows 10/11 x64 a Python 3.11 x64.
set "EXIT_CODE=1"
goto :fatal

:venv_remove_failed
echo CHYBA: Nelze odstranit .venv. Zavrete aplikace, ktere tuto slozku pouzivaji.
set "EXIT_CODE=1"
goto :fatal

:venv_failed
echo CHYBA: Nepodarilo se vytvorit lokalni virtualni prostredi .venv.
set "EXIT_CODE=1"
goto :fatal

:pip_failed
echo CHYBA: V lokalnim virtualnim prostredi nelze zprovoznit pip.
set "EXIT_CODE=1"
goto :fatal

:bootstrap_failed
echo.
echo KajovoKarty nebylo mozne pripravit nebo spustit.
echo Diagnosticky log: "%CD%\build\bootstrap.log"
echo Spousteci log: "%RUN_LOG%"
echo Navratovy kod: %EXIT_CODE%
pause
exit /b %EXIT_CODE%

:fatal
if not defined EXIT_CODE set "EXIT_CODE=1"
if defined RUN_LOG call :log Fatal error, exit code=%EXIT_CODE%
echo Diagnosticky log: "%CD%\build\bootstrap.log"
if defined RUN_LOG echo Spousteci log: "%RUN_LOG%"
pause
exit /b %EXIT_CODE%

:log
if defined RUN_LOG >>"%RUN_LOG%" echo [%DATE% %TIME%] %*
exit /b 0
