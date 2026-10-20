@echo off
REM Open the GO board: the page where a milestone gets a human's yes.
REM Read-only against the store; the only thing it writes is milestone.go-issued.

setlocal
cd /d "%~dp0"

if not exist "src\progressdesk\go_board.html" (
  echo Cannot find src\progressdesk\go_board.html -- run this from the repo root.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo No .venv here. Run: uv venv ^&^& uv pip install -e .
  pause
  exit /b 1
)

set PYTHONPATH=src
start "" http://127.0.0.1:8765/
".venv\Scripts\python.exe" -m progressdesk.go_board "%CD%" 8765

endlocal
