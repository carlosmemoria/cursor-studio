import json
import os
import subprocess
import sys

from PySide6.QtCore import QCoreApplication

from cursor_studio.instance import SingleInstance


def test_second_process_forwards_to_first(tmp_path):
    endpoint = str(tmp_path / "app.sock")
    result = tmp_path / "received.json"
    script = """
import json,sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication,QTimer
from cursor_studio.instance import SingleInstance
app=QCoreApplication([])
guard=SingleInstance(sys.argv[1])
assert guard.start([])
def receive(paths):
 Path(sys.argv[2]).write_text(json.dumps({"paths":paths,"token":guard.activation_token}))
 QTimer.singleShot(100,app.quit)
guard.received.connect(receive)
QTimer.singleShot(10000,app.quit)
print('READY',flush=True)
app.exec()
guard.close()
"""
    env = os.environ.copy()
    env["XDG_ACTIVATION_TOKEN"] = "cursor-studio-test-token"
    primary = subprocess.Popen([sys.executable, "-c", script, endpoint, str(result)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        assert primary.stdout.readline().strip() == "READY"
        forwarded = subprocess.run(
            [sys.executable, "-c",
             "import sys; from PySide6.QtCore import QCoreApplication; "
             "from cursor_studio.instance import SingleInstance; "
             "a=QCoreApplication([]); g=SingleInstance(sys.argv[1]); "
             "assert g.start(['/tmp/a cursor.cur']) is False",
             endpoint], capture_output=True, text=True, timeout=8, env=env)
        assert forwarded.returncode == 0, forwarded.stderr
        primary.communicate(timeout=8)
        assert primary.returncode == 0
        assert json.loads(result.read_text()) == {"paths": ["/tmp/a cursor.cur"], "token": "cursor-studio-test-token"}
    finally:
        if primary.poll() is None:
            primary.kill()
            primary.communicate()


def test_recovery_after_primary_crash(tmp_path):
    endpoint = str(tmp_path / "crash.sock")
    primary = subprocess.Popen(
        [sys.executable, "-c",
         "import sys; from PySide6.QtCore import QCoreApplication,QTimer; "
         "from cursor_studio.instance import SingleInstance; "
         "a=QCoreApplication([]); g=SingleInstance(sys.argv[1]); assert g.start([]); "
         "QTimer.singleShot(10000,a.quit); print('READY',flush=True); a.exec()",
         endpoint], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert primary.stdout.readline().strip() == "READY"
        primary.kill()
        primary.communicate(timeout=5)
        app = QCoreApplication.instance() or QCoreApplication([])
        guard = SingleInstance(endpoint)
        assert guard.start([])
        guard.close()
        app.processEvents()
    finally:
        if primary.poll() is None:
            primary.kill()
            primary.communicate()
