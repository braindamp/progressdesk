"""Install complete ProgressDesk files over the accepted pre-SCHOTTY stage."""
from pathlib import Path
import shutil
import sys

if len(sys.argv) != 2:
    raise SystemExit(r"Usage: python apply.py D:\Coding\progressDesk")
source = Path(__file__).resolve().parent / "src" / "progressdesk"
target = Path(sys.argv[1]).resolve() / "src" / "progressdesk"
if not (target / "runtime.py").is_file() or not (target / "loop.py").is_file():
    raise SystemExit(f"Not a ProgressDesk checkout: {target}")
for file in sorted(source.rglob("*")):
    if file.is_file():
        destination = target / file.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, destination)
        print("Installed", destination.relative_to(target.parent.parent))
print("Installed. Project data, feature lists, assignments, and event journal unchanged.")
