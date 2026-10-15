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
