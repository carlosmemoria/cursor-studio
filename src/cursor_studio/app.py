"""Native Qt 6 desktop application."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QLayout, QSplitter, QVBoxLayout, QWidget,
)

from . import __version__
from .core import Cursor, ROLES, export_theme, guess_role, install_user_theme, read_cur, user_icons_dir

STYLE = """
* { font-family: 'Inter', 'Noto Sans', sans-serif; font-size: 13px; }
QDialog, QMessageBox { background-color: #191c24; color: #e8eaf2; }
QMessageBox QLabel { color: #e8eaf2; background: transparent; }
QMainWindow, QWidget#root { background: #101217; color: #e8eaf2; }
QLabel { color: #e8eaf2; background: transparent; }
QLabel#muted { color: #8e96a9; }
QLabel#eyebrow { color: #a8a0ff; font-size: 11px; font-weight: 700; }
QLabel#title { font-size: 29px; font-weight: 700; }
QLabel#section { font-size: 16px; font-weight: 650; }
QFrame#rail { background: #15171e; border-right: 1px solid #282b36; }
QFrame#panel { background: #191c24; border: 1px solid #2c303d; border-radius: 16px; }
QFrame#footer { border-top: 1px solid #292d38; }
QPushButton { color: #e8eaf2; background: #272b37; border: 1px solid #383e50;
 border-radius: 9px; padding: 10px 17px; font-weight: 600; }
QPushButton:hover { background: #34394a; border-color: #7c72df; }
QPushButton:pressed { background: #48405f; }
QPushButton:disabled { color: #686e80; background: #20232d; border-color: #2b303c; }
QPushButton#primary { background: #a79bff; color: #151125; border: none; }
QPushButton#primary:hover { background: #bcb3ff; }
QPushButton#primary:disabled { background: #413b60; color: #8d87a6; }
QPushButton#quiet { background: transparent; border: none; color: #a6adbf; text-align: left; }
QLineEdit, QComboBox { background: #12151c; color: #e8eaf2; border: 1px solid #363b4b;
 border-radius: 8px; padding: 10px; selection-background-color: #6357ad; }
QLineEdit:focus, QComboBox:focus { border-color: #a79bff; }
QComboBox QAbstractItemView { background: #222632; color: #eee; selection-background-color: #504776; }
QListWidget { background: transparent; color: #e8eaf2; border: none; outline: none; }
QListWidget::item { padding: 13px; border: 1px solid transparent; border-radius: 10px; margin: 3px 0; }
QListWidget::item:selected { background: #302b48; border-color: #796bbd; }
QListWidget::item:hover:!selected { background: #232833; }
QCheckBox { color: #a6adbf; spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; }
QProgressBar { border: none; background: #242836; height: 3px; }
QProgressBar::chunk { background: #a79bff; }
QSplitter::handle { background: transparent; width: 14px; }
QToolTip { background: #303446; color: #fff; border: 1px solid #5e557e; padding: 6px; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #42495c; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def label(text: str, kind: str = "") -> QLabel:
    result = QLabel(text)
    result.setObjectName(kind)
    result.setWordWrap(True)
    return result


def pixmap(cursor: Cursor, index: int = -1) -> QPixmap:
    frame = cursor.largest if index < 0 else cursor.images[index]
    image = frame.image
    return QPixmap.fromImage(QImage(image.tobytes(), image.width, image.height,
                                    image.width * 4, QImage.Format.Format_RGBA8888).copy())


class Preview(QWidget):
    def __init__(self):
        super().__init__()
        self.frame = None
        self.zoom = 3
        self.hotspot = True
        self.light = False
        self.setMinimumSize(220, 120)
        self.setAccessibleName("Prévia do cursor em fundo quadriculado")

    def paintEvent(self, event):
        painter = QPainter(self)
        bg = QColor("#e1e4eb" if self.light else "#12151c")
        tile = QColor("#cdd2dd" if self.light else "#1c202b")
        painter.fillRect(self.rect(), bg)
        for x in range(0, self.width(), 20):
            for y in range(0, self.height(), 20):
                if (x // 20 + y // 20) % 2 == 0:
                    painter.fillRect(x, y, 20, 20, tile)
        if not self.frame:
            painter.setPen(QColor("#788196"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Arraste seus arquivos .cur\npara começar")
            return
        frame = self.frame
        image = frame.image
        pm = QPixmap.fromImage(QImage(image.tobytes(), image.width, image.height,
                                      image.width * 4, QImage.Format.Format_RGBA8888).copy())
        scale = min(self.zoom, (self.width() - 40) / image.width,
                    (self.height() - 40) / image.height)
        w, h = int(image.width * scale), int(image.height * scale)
        x, y = (self.width() - w) // 2, (self.height() - h) // 2
        painter.drawPixmap(x, y, w, h, pm)
        if self.hotspot:
            hx, hy = int(x + (frame.hotspot_x + .5) * scale), int(y + (frame.hotspot_y + .5) * scale)
            painter.setPen(QPen(QColor("#ff8a9e"), 1))
            painter.drawLine(hx - 9, hy, hx + 9, hy)
            painter.drawLine(hx, hy - 9, hx, hy + 9)
            painter.drawEllipse(hx - 3, hy - 3, 6, 6)


class Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = Signals()

    def run(self):
        try:
            result = self.function()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.done.emit(result)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cursors: list[Cursor] = []
        self.roles: dict[Path, str | None] = {}
        self.busy = False
        self.task = None
        self.setWindowTitle("Cursor Studio")
        self.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.svg"))))
        self.resize(1180, 800)
        self.setMinimumSize(930, 700)
        self.setAcceptDrops(True)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(170)
        nav = QVBoxLayout(rail)
        nav.setContentsMargins(22, 30, 20, 24)
        logo = label("↖", "title")
        logo.setStyleSheet("color: #b4a9ff; font-size: 48px;")
        nav.addWidget(logo)
        nav.addWidget(label("CURSOR\nSTUDIO", "section"))
        nav.addSpacing(36)
        active = label("◉   Criar tema")
        active.setStyleSheet("color: #b6abff; padding: 12px 0;")
        nav.addWidget(active)
        nav.addWidget(label(".cur → Linux", "muted"))
        nav.addStretch()
        info = QPushButton("Sobre o projeto")
        info.setObjectName("quiet")
        info.clicked.connect(self.about)
        nav.addWidget(info)
        nav.addWidget(label(f"v{__version__} · por Memória", "muted"))
        outer.addWidget(rail)
        body = QVBoxLayout()
        body.setContentsMargins(30, 28, 30, 22)
        body.setSpacing(14)
        outer.addLayout(body, 1)
        body.addWidget(label("SEU CURSOR. SEU LINUX.", "eyebrow"))
        body.addWidget(label("Um novo lugar para seus cursores.", "title"))
        body.addWidget(label("Importe arquivos do Windows e crie um tema pronto para usar no Linux.", "muted"))
        theme_row = QHBoxLayout()
        theme_row.addWidget(label("Nome do tema"))
        self.name = QLineEdit("Meu tema")
        self.name.setMaxLength(80)
        self.name.setAccessibleName("Nome do tema")
        theme_row.addWidget(self.name, 1)
        body.addLayout(theme_row)
        splitter = QSplitter()
        splitter.setHandleWidth(14)
        collection = QFrame()
        collection.setObjectName("panel")
        left = QVBoxLayout(collection)
        left.setContentsMargins(18, 18, 18, 18)
        heading = QHBoxLayout()
        heading.addWidget(label("Biblioteca", "section"))
        self.count = label("0 arquivos", "muted")
        heading.addStretch()
        heading.addWidget(self.count)
        left.addLayout(heading)
        self.files = QListWidget()
        self.files.setIconSize(QSize(40, 40))
        self.files.setAccessibleName("Cursores importados")
        self.files.currentRowChanged.connect(self.select)
        left.addWidget(self.files, 1)
        self.empty = label("Solte arquivos .cur aqui\nou use o botão abaixo.\n\nPNG e DIB dentro do CUR são aceitos.", "muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.empty, 1)
        buttons = QHBoxLayout()
        self.add = QPushButton("+ Importar .cur")
        self.add.clicked.connect(self.choose_files)
        self.remove = QPushButton("Remover")
        self.remove.clicked.connect(self.remove_current)
        self.remove.setEnabled(False)
        buttons.addWidget(self.add, 1)
        buttons.addWidget(self.remove)
        left.addLayout(buttons)
        splitter.addWidget(collection)
        inspector = QFrame()
        inspector.setObjectName("panel")
        right = QVBoxLayout(inspector)
        right.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        right.setContentsMargins(18, 18, 18, 18)
        right.addWidget(label("Prévia ao vivo", "section"))
        self.preview = Preview()
        right.addWidget(self.preview, 1)
        controls = QHBoxLayout()
        self.zoom = QComboBox()
        self.zoom.setFixedWidth(76)
        self.zoom.addItems(["1×", "2×", "3×", "4×", "6×"])
        self.zoom.setCurrentIndex(2)
        self.zoom.setAccessibleName("Ampliação da prévia")
        self.zoom.currentIndexChanged.connect(self.update_preview)
        self.bg = QCheckBox("Fundo claro")
        self.bg.toggled.connect(self.update_preview)
        self.hot = QCheckBox("Ponto de clique")
        self.hot.setChecked(True)
        self.hot.toggled.connect(self.update_preview)
        controls.addWidget(self.zoom)
        controls.addWidget(self.bg)
        controls.addWidget(self.hot)
        right.addLayout(controls)
        self.metadata = label("Selecione um cursor para inspecionar.", "muted")
        right.addWidget(self.metadata)
        self.sizes = QComboBox()
        self.sizes.setAccessibleName("Resolução do cursor")
        self.sizes.currentIndexChanged.connect(self.update_preview)
        right.addWidget(self.sizes)
        right.addWidget(label("Função no tema", "section"))
        self.role = QComboBox()
        self.role.addItem("Não incluir na exportação", None)
        for key, (title, _) in ROLES.items():
            self.role.addItem(title, key)
        self.role.currentIndexChanged.connect(self.assign_role)
        self.role.setEnabled(False)
        right.addWidget(self.role)
        right.addWidget(label("Passe o mouse sobre a prévia para testar o cursor em tamanho real.", "muted"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setMinimumWidth(340)
        scroll.setWidget(inspector)
        splitter.addWidget(scroll)
        splitter.setSizes([390, 450])
        body.addWidget(splitter, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        body.addWidget(self.progress)
        self.status = label("Tudo pronto para começar. Processamento local, sem uploads.", "muted")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setAccessibleName("Status da operação")
        body.addWidget(self.status)
        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 14, 0, 0)
        footer_layout.addWidget(label("Xcursor · tamanhos e ponto de clique preservados", "muted"), 1)
        self.export = QPushButton("Exportar tema…")
        self.export.clicked.connect(self.choose_export)
        self.install = QPushButton("Instalar no Linux")
        self.install.setObjectName("primary")
        self.install.clicked.connect(self.install_theme)
        self.export.setEnabled(False)
        self.install.setEnabled(False)
        footer_layout.addWidget(self.export)
        footer_layout.addWidget(self.install)
        body.addWidget(footer)
        self.add.setShortcut("Ctrl+O")
        self.remove.setShortcut("Delete")

    def about(self):
        QMessageBox.about(self, "Cursor Studio", f"Cursor Studio {__version__}\n\n"
                          "Criado por Carlos Memória · memoria.pro\nLicença MIT\n\n"
                          "Converte cursores estáticos .cur em temas Xcursor.\n"
                          "Animações .ani ainda não são suportadas.\n\n"
                          "github.com/carlosmemoria/cursor-studio")

    def current(self):
        row = self.files.currentRow()
        return self.cursors[row] if 0 <= row < len(self.cursors) else None

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Importar cursores", "", "Cursores Windows (*.cur *.CUR)")
        self.import_paths(paths)

    def import_paths(self, paths):
        if self.busy:
            return
        existing = {cursor.path for cursor in self.cursors}
        incoming = list(dict.fromkeys(Path(p).resolve() for p in paths))
        incoming = [p for p in incoming if p not in existing]
        used_pixels = sum(f.image.width * f.image.height for c in self.cursors for f in c.images)
        if len(incoming) + len(self.cursors) > 200:
            self.error("Importe até 200 arquivos por projeto.")
            return
        if not incoming:
            return

        def load():
            good, errors = [], []
            pixels = used_pixels
            for path in incoming:
                try:
                    cursor = read_cur(path)
                    count = sum(f.image.width * f.image.height for f in cursor.images)
                    if pixels + count > 64 * 1024 * 1024:
                        raise ValueError("Limite de 256 MiB de imagens por sessão atingido.")
                    good.append(cursor)
                    pixels += count
                except Exception as exc:
                    errors.append(f"{path.name}: {exc}")
            return good, errors

        self.run_task(load, self.imported, "Lendo e validando cursores…")

    def imported(self, result):
        good, errors = result
        for cursor in good:
            role = guess_role(cursor.path)
            if role in self.roles.values():
                role = None
            self.cursors.append(cursor)
            self.roles[cursor.path] = role
            item = QListWidgetItem(QIcon(pixmap(cursor)), cursor.path.name)
            item.setToolTip(str(cursor.path))
            self.files.addItem(item)
        self.empty.setVisible(not self.cursors)
        self.count.setText(f"{len(self.cursors)} arquivos")
        if good:
            self.files.setCurrentRow(len(self.cursors) - len(good))
        self.refresh()
        self.status.setText(f"{len(good)} importado(s). {len(errors)} arquivo(s) recusado(s)."
                            + (" Associe um arquivo à função Ponteiro padrão para exportar."
                               if "left_ptr" not in self.roles.values() else ""))
        if errors:
            self.error("\n".join(errors[:12]))

    def select(self, row):
        cursor = self.current()
        self.role.blockSignals(True)
        self.sizes.blockSignals(True)
        self.sizes.clear()
        if cursor:
            for frame in cursor.images:
                self.sizes.addItem(f"{frame.image.width} × {frame.image.height} px")
            largest = max(range(len(cursor.images)), key=lambda i: cursor.images[i].nominal_size)
            self.sizes.setCurrentIndex(largest)
            self.role.setCurrentIndex(max(0, self.role.findData(self.roles[cursor.path])))
        else:
            self.role.setCurrentIndex(0)
        self.sizes.blockSignals(False)
        self.role.blockSignals(False)
        self.role.setEnabled(cursor is not None and not self.busy)
        self.remove.setEnabled(cursor is not None and not self.busy)
        self.update_preview()

    def update_preview(self, *_):
        cursor = self.current()
        index = self.sizes.currentIndex()
        self.preview.frame = cursor.images[index] if cursor and index >= 0 else None
        self.preview.zoom = [1, 2, 3, 4, 6][self.zoom.currentIndex()]
        self.preview.light = self.bg.isChecked()
        self.preview.hotspot = self.hot.isChecked()
        if self.preview.frame:
            f = self.preview.frame
            self.metadata.setText(f"{f.image.width} × {f.image.height} px  ·  "
                                  f"Ponto de clique: {f.hotspot_x}, {f.hotspot_y}  ·  "
                                  f"{len(cursor.images)} resolução(ões)")
            self.preview.setCursor(QCursor(pixmap(cursor, index), f.hotspot_x, f.hotspot_y))
        else:
            self.metadata.setText("Selecione um cursor para inspecionar.")
            self.preview.unsetCursor()
        self.preview.update()

    def assign_role(self, index):
        cursor = self.current()
        if not cursor:
            return
        role = self.role.currentData()
        conflict = next((p for p, value in self.roles.items() if role and value == role and p != cursor.path), None)
        if conflict:
            answer = self.ask("Transferir função?",
                              f"A função {ROLES[role][0]} está em {conflict.name}.\n\n"
                              f"Transferir para {cursor.path.name}? O arquivo anterior ficará sem função.")
            if not answer:
                self.select(self.files.currentRow())
                return
            self.roles[conflict] = None
        self.roles[cursor.path] = role
        self.refresh()

    def refresh(self):
        for row, cursor in enumerate(self.cursors):
            role = self.roles[cursor.path]
            text = ROLES[role][0] if role else "Sem função"
            self.files.item(row).setText(f"{cursor.path.name}\n{text}")
        ready = "left_ptr" in self.roles.values() and not self.busy
        self.export.setEnabled(ready)
        self.install.setEnabled(ready)

    def remove_current(self):
        row = self.files.currentRow()
        if row < 0 or self.busy:
            return
        cursor = self.cursors.pop(row)
        del self.roles[cursor.path]
        self.files.takeItem(row)
        self.empty.setVisible(not self.cursors)
        self.count.setText(f"{len(self.cursors)} arquivos")
        self.select(self.files.currentRow())
        self.refresh()

    def choose_export(self):
        folder = QFileDialog.getExistingDirectory(self, "Escolha a pasta de destino")
        if folder:
            self.save_theme(Path(folder), False)

    def install_theme(self):
        self.save_theme(user_icons_dir(), True)

    def save_theme(self, parent, installed):
        assignments = {self.roles[c.path]: c for c in self.cursors if self.roles[c.path]}
        name = self.name.text()

        def complete(path):
            self.status.setText(f"Tema {'instalado' if installed else 'exportado'}: {path}")
            if installed:
                self.notify("Tema instalado", f"Tema disponível em:\n{path}\n\n"
                                        "Abra as configurações de aparência do seu ambiente e selecione "
                                        f"“{name.strip()}”. Se não aparecer, reabra as configurações.\n\n"
                                        "Funções não fornecidas usam o tema herdado quando disponível.")
        operation = (lambda: install_user_theme(assignments, name)) if installed else (
            lambda: export_theme(assignments, name, parent))
        self.run_task(operation, complete, "Gerando tema Xcursor…")

    def run_task(self, function, complete, message):
        if self.busy:
            return
        self.busy = True
        self.status.setText(message)
        self.progress.show()
        for widget in [self.add, self.remove, self.role, self.name, self.export, self.install]:
            widget.setEnabled(False)
        self.task = Task(function)

        def finish(result):
            self.unlock()
            complete(result)

        def failed(message):
            self.unlock()
            self.error(message)
        self.task.signals.done.connect(finish)
        self.task.signals.failed.connect(failed)
        QThreadPool.globalInstance().start(self.task)

    def unlock(self):
        self.busy = False
        self.progress.hide()
        self.add.setEnabled(True)
        self.name.setEnabled(True)
        self.select(self.files.currentRow())
        self.refresh()

    def notify(self, title, message):
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setWindowTitle(title)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(message)
        dialog.exec()

    def ask(self, title, message):
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle(title)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        return dialog.exec() == QMessageBox.StandardButton.Yes

    def error(self, message):
        self.status.setText("Não foi possível concluir. Confira os detalhes.")
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Confira os arquivos e as opções")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(message)
        dialog.exec()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.busy:
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self.import_paths(paths)
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self.busy:
            self.status.setText("Aguarde a operação terminar antes de fechar.")
            event.ignore()
        elif self.cursors and QMessageBox.question(
            self, "Fechar projeto", "O projeto fica apenas nesta sessão. Temas já exportados estão salvos.\n\nFechar o aplicativo?"
        ) != QMessageBox.StandardButton.Yes:
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Cursor Studio")
    app.setOrganizationName("Memória")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setFont(QFont("Noto Sans", 10))
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    if len(sys.argv) > 1:
        window.import_paths(sys.argv[1:])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
