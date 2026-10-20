@echo off
REM Run the workshop against the target.
REM
REM   workshop  D:\Coding\progressDesk5-acceptance   the engine: dispatches
REM                                                       builders, judges them
REM   target    D:\Coding\ProgressDesk               the code under construction
REM
REM The workshop runs FROM its own source but operates ON the target, so every
REM round lands under %TARGET%\projects and every builder writes there.

setlocal
set "WORKSHOP=%~dp0"
set "TARGET=D:\Coding\ProgressDesk"

if not exist "%WORKSHOP%src\progressdesk\go_board.html" (
  echo Cannot find the workshop source -- run this from progressDesk5-acceptance.
  pause
  exit /b 1
)
if not exist "%TARGET%" (
  echo No output target at %TARGET%
  pause
  exit /b 1
)
if not exist "%WORKSHOP%.venv\Scripts\python.exe" (
  echo No .venv in the workshop. Run: uv venv ^&^& uv pip install -e .
  pause
  exit /b 1
)

cd /d "%WORKSHOP%"
set "PYTHONPATH=%WORKSHOP%src"

REM %1 is the port, default 8765.
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8765"

start "" http://127.0.0.1:%PORT%/
"%WORKSHOP%.venv\Scripts\python.exe" -m progressdesk.go_board "%TARGET%" %PORT%

endlocal
