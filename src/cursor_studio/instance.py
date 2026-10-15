"""One GUI instance per user session, with acknowledged local file forwarding."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QObject, QLockFile, QStandardPaths, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    received = Signal(list)

    def __init__(self, endpoint: str | None = None):
        super().__init__()
        runtime = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
        self.endpoint = endpoint or str(Path(runtime) / "memoria-cursor-studio.sock")
        self.lock = QLockFile(self.endpoint + ".lock")
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self.clients = {}
        self.primary = False
        self.activation_token = ""

    def start(self, paths: list[str]) -> bool:
        payload = json.dumps({"paths": paths, "token": os.environ.get("XDG_ACTIVATION_TOKEN", "")}).encode("utf-8") + b"\n"
        if len(paths) > 200 or len(payload) > 65536:
            raise RuntimeError("Abra até 200 arquivos por vez; a lista de caminhos é muito longa.")
        for _ in range(15):
            if self.lock.tryLock(0):
                # Only the lock owner may remove an endpoint left by a crashed process.
                QLocalServer.removeServer(self.endpoint)
                if not self.server.listen(self.endpoint):
                    self.lock.unlock()
                    raise RuntimeError(f"Não foi possível iniciar a comunicação local: {self.server.errorString()}")
                self.primary = True
                return True
            socket = QLocalSocket()
            socket.connectToServer(self.endpoint)
            if socket.waitForConnected(200):
                socket.write(payload)
                if socket.bytesToWrite() and not socket.waitForBytesWritten(2000):
                    raise RuntimeError("Não foi possível avisar a janela já aberta.")
                if ((not socket.bytesAvailable() and not socket.waitForReadyRead(3000))
                        or bytes(socket.readAll()) != b"ok\n"):
                    raise RuntimeError("A janela já aberta não respondeu. Aguarde a operação atual e tente novamente.")
                socket.disconnectFromServer()
                return False
            time.sleep(.1)
        raise RuntimeError("Outra janela está iniciando ou não está respondendo. Tente novamente.")

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.clients[socket] = bytearray()
            socket.readyRead.connect(lambda socket=socket: self._read(socket))
            socket.disconnected.connect(lambda socket=socket: self._remove(socket))
            timer = QTimer(socket)
            timer.setSingleShot(True)
            timer.timeout.connect(socket.disconnectFromServer)
            timer.start(5000)
            self._read(socket)

    def _remove(self, socket):
        self.clients.pop(socket, None)
        socket.deleteLater()

    def _read(self, socket):
        if socket not in self.clients:
            return
        buffer = self.clients[socket]
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > 65536:
            socket.disconnectFromServer()
            return
        if b"\n" not in buffer:
            return
        try:
            request = json.loads(bytes(buffer).split(b"\n", 1)[0])
            if not isinstance(request, dict):
                raise ValueError("Invalid request")
            paths, token = request.get("paths"), request.get("token", "")
            if not isinstance(token, str) or len(token) > 8192 or "\0" in token:
                raise ValueError("Invalid activation token")
            if (not isinstance(paths, list) or len(paths) > 200
                    or any(not isinstance(p, str) or len(p) > 4096 for p in paths)):
                raise ValueError("Invalid request")
        except (ValueError, UnicodeError):
            socket.disconnectFromServer()
            return
        self.clients.pop(socket, None)
        socket.write(b"ok\n")
        socket.flush()
        self.activation_token = token
        self.received.emit(paths)
        self.activation_token = ""
        socket.disconnectFromServer()

    def close(self):
        if self.primary:
            self.server.close()
            self.lock.unlock()
            self.primary = False
