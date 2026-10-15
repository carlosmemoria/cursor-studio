"""Install a desktop launcher for the current venv, without root privileges."""
import os
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
xdg = os.environ.get("XDG_DATA_HOME", "")
data = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".local/share"
launcher = Path(sys.executable).parent / "cursor-studio"
if not launcher.exists():
    raise SystemExit("Install the project in this environment first: python -m pip install -e .")
icons = data / "icons/hicolor/scalable/apps"
icons.mkdir(parents=True, exist_ok=True)
shutil.copyfile(root / "packaging/cursor-studio.svg", icons / "cursor-studio.svg")
applications = data / "applications"
applications.mkdir(parents=True, exist_ok=True)
# Desktop Entry quoted argument escaping (not shell quoting).
escaped = str(launcher).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
entry = applications / "cursor-studio.desktop"
entry.write_text(
    '[Desktop Entry]\nType=Application\nName=Cursor Studio\n'
    'Comment=Convert Windows cursors into Linux themes\n'
    f'Exec="{escaped}" %F\nIcon=cursor-studio\nTerminal=false\nStartupNotify=true\n'
    'Categories=Graphics;Utility;\nKeywords=cursor;theme;cur;xcursor;\n', encoding="utf-8")
print(entry)
