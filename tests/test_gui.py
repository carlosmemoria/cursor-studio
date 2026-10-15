import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cursor_studio.app import STYLE, Window
from cursor_studio.core import read_cur
from test_core import make_cur


def test_import_preview_assign_remove(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    window = Window()
    cursor = read_cur(make_cur(tmp_path / "arrow.cur"))
    window.imported(([cursor], []))
    assert window.files.count() == 1
    assert window.preview.frame.image.size == (48, 48)
    assert window.export.isEnabled()
    window.role.setCurrentIndex(0)
    assert not window.export.isEnabled()
    window.role.setCurrentIndex(window.role.findData("left_ptr"))
    assert window.install.isEnabled()
    window.remove_current()
    assert window.files.count() == 0
    assert not window.export.isEnabled()
    window.deleteLater()
    app.processEvents()


def test_async_import_runs_to_completion(tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer
    app = QApplication.instance() or QApplication([])
    window = Window()
    source = make_cur(tmp_path / "arrow.cur")
    window.import_paths([source])
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if not window.busy else None)
    poll.start(10)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    poll.stop()
    assert not window.busy
    assert len(window.cursors) == 1
    assert window.install.isEnabled()
    window.deleteLater()
    app.processEvents()


def test_preview_controls_do_not_overlap_at_minimum_size(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.imported(([read_cur(make_cur(tmp_path / "arrow.cur"))], []))
    window.resize(930, 700)
    window.show()
    app.processEvents()
    assert window.preview.geometry().bottom() < window.zoom.geometry().top()
    window.hide()
    window.deleteLater()
    app.processEvents()


def test_gui_exports_theme_in_background(tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.imported(([read_cur(make_cur(tmp_path / "arrow.cur"))], []))
    window.name.setText("GUI Theme")
    window.save_theme(tmp_path / "export", False)
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if not window.busy else None)
    poll.start(10)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    poll.stop()
    assert not window.busy
    assert (tmp_path / "export/gui-theme/cursors/left_ptr").read_bytes().startswith(b"Xcur")
    assert window.install.isEnabled()
    window.deleteLater()
    app.processEvents()



def test_role_transfer_accept_and_cancel(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = Window()
    cursors = [read_cur(make_cur(tmp_path / name)) for name in ["arrow.cur", "link.cur"]]
    window.imported((cursors, []))
    window.files.setCurrentRow(1)
    monkeypatch.setattr(window, "ask", lambda *args: False)
    window.role.setCurrentIndex(window.role.findData("left_ptr"))
    assert window.roles[cursors[0].path] == "left_ptr"
    assert window.roles[cursors[1].path] == "hand2"
    monkeypatch.setattr(window, "ask", lambda *args: True)
    window.role.setCurrentIndex(window.role.findData("left_ptr"))
    assert window.roles[cursors[0].path] is None
    assert window.roles[cursors[1].path] == "left_ptr"
    window.deleteLater()
    app.processEvents()


def test_dialog_contrast_under_light_system_palette():
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QLabel, QMessageBox
    app = QApplication.instance() or QApplication([])
    previous = app.palette()
    light = QPalette()
    light.setColor(QPalette.ColorRole.Window, QColor("white"))
    light.setColor(QPalette.ColorRole.WindowText, QColor("black"))
    app.setPalette(light)
    app.setStyleSheet(STYLE)
    dialog = QMessageBox()
    dialog.setText("Mensagem legível")
    dialog.show()
    app.processEvents()
    text = dialog.findChild(QLabel, "qt_msgbox_label")
    assert dialog.palette().color(QPalette.ColorRole.Window).lightness() < 70
    assert text.palette().color(QPalette.ColorRole.WindowText).lightness() > 180
    dialog.hide()
    dialog.deleteLater()
    app.setPalette(previous)
    app.processEvents()


def test_overwrite_cancel_and_confirm(tmp_path, monkeypatch):
    from PySide6.QtCore import QEventLoop, QTimer
    from cursor_studio.core import export_theme
    app = QApplication.instance() or QApplication([])
    window = Window()
    cursor = read_cur(make_cur(tmp_path / "arrow.cur"))
    window.imported(([cursor], []))
    window.name.setText("Existing")
    parent = tmp_path / "out"
    theme = export_theme({"left_ptr": cursor}, "Existing", parent)
    original = (theme / "cursors/left_ptr").read_bytes()
    monkeypatch.setattr(window, "ask", lambda *args: False)
    window.save_theme(parent, False)
    assert not window.busy
    assert (theme / "cursors/left_ptr").read_bytes() == original
    monkeypatch.setattr(window, "ask", lambda *args: True)
    window.save_theme(parent, False)
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if not window.busy else None)
    poll.start(10)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    poll.stop()
    assert not window.busy
    assert (theme / "cursors/left_ptr").read_bytes() != original
    assert len(list((parent / ".cursor-studio-backups").iterdir())) == 1
    window.deleteLater()
    app.processEvents()


def test_activation_restores_window_and_keeps_forwarded_files_while_busy(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.showMinimized()
    app.processEvents()
    window.busy = True
    window.activate_instance([str(tmp_path / "next.cur")])
    app.processEvents()
    assert not window.isMinimized()
    assert window.pending_paths == [str(tmp_path / "next.cur")]
    imported = []
    monkeypatch.setattr(window, "import_paths", imported.extend)
    window.unlock()
    app.processEvents()
    assert imported == [str(tmp_path / "next.cur")]
    assert window.pending_paths == []
    window.hide()
    window.deleteLater()
    app.processEvents()


def test_actual_launcher_reuses_window_and_imports_files(tmp_path):
    import sys
    import tempfile
    from pathlib import Path
    from PySide6.QtCore import QEventLoop, QProcess, QProcessEnvironment, QTimer
    from cursor_studio.instance import SingleInstance
    app = QApplication.instance() or QApplication([])
    source = make_cur(tmp_path / "arrow.cur")
    window = Window()
    window.show()
    with tempfile.TemporaryDirectory(prefix="cs-ipc-") as runtime:
        guard = SingleInstance(str(Path(runtime) / "memoria-cursor-studio.sock"))
        assert guard.start([])
        guard.received.connect(window.activate_instance)
        process = QProcess()
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("XDG_RUNTIME_DIR", runtime)
        environment.insert("QT_QPA_PLATFORM", "offscreen")
        process.setProcessEnvironment(environment)
        process.start(sys.executable, ["-m", "cursor_studio.app", str(source)])
        loop = QEventLoop()
        poll = QTimer()
        poll.timeout.connect(lambda: loop.quit() if (
            process.state() == QProcess.ProcessState.NotRunning and not window.busy
            and bool(window.cursors)) else None)
        poll.start(10)
        QTimer.singleShot(8000, loop.quit)
        try:
            loop.exec()
            assert process.state() == QProcess.ProcessState.NotRunning
            assert process.exitCode() == 0, bytes(process.readAllStandardError()).decode()
            assert len(window.cursors) == 1
            assert window.cursors[0].path == source.resolve()
            assert len([w for w in app.topLevelWidgets() if isinstance(w, Window) and w.isVisible()]) == 1
        finally:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(2000)
            guard.close()
            window.hide()
            window.deleteLater()
            app.processEvents()
