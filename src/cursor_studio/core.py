"""Strict CUR decoding and a dependency-free Xcursor serializer.

All file reads are bounded. Export builds in a private staging directory and refuses
existing destinations. No external command or Windows installer is executed.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_FILE_SIZE = 32 * 1024 * 1024
MAX_IMAGES = 128
MAX_DIMENSION = 256  # CUR uses one byte: zero represents 256.


class CursorError(ValueError):
    """An invalid cursor or theme request, suitable for display to the user."""


@dataclass(frozen=True)
class CursorImage:
    image: Image.Image
    hotspot_x: int
    hotspot_y: int

    @property
    def nominal_size(self) -> int:
        return max(self.image.size)


@dataclass(frozen=True)
class Cursor:
    path: Path
    images: tuple[CursorImage, ...]

    @property
    def largest(self) -> CursorImage:
        return max(self.images, key=lambda item: item.nominal_size)


# Canonical Xcursor names, standard CSS names and commonly used legacy aliases.
ROLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "left_ptr": ("Ponteiro padrão", ("default", "arrow", "top_left_arrow")),
    "hand2": ("Link / mão", ("pointer", "hand", "hand1", "pointing_hand")),
    "xterm": ("Seleção de texto", ("text", "ibeam")),
    "watch": ("Ocupado", ("wait",)),
    "left_ptr_watch": ("Trabalhando em segundo plano", ("progress", "half-busy")),
    "crosshair": ("Precisão", ("cross", "tcross")),
    "fleur": ("Mover", ("move", "all-scroll", "size_all")),
    "not-allowed": ("Não permitido", ("forbidden", "crossed_circle", "no-drop")),
    "question_arrow": ("Ajuda", ("help", "whats_this")),
    "sb_h_double_arrow": ("Redimensionar na horizontal", ("ew-resize", "size_hor", "h_double_arrow")),
    "sb_v_double_arrow": ("Redimensionar na vertical", ("ns-resize", "size_ver", "v_double_arrow")),
    "size_fdiag": ("Diagonal ↖ ↘", ("nwse-resize", "bd_double_arrow")),
    "size_bdiag": ("Diagonal ↗ ↙", ("nesw-resize", "fd_double_arrow")),
    "openhand": ("Mão aberta", ("grab",)),
    "closedhand": ("Mão fechada", ("grabbing",)),
    "up_arrow": ("Seta para cima", ("center_ptr",)),
    "vertical-text": ("Texto vertical", ()),
    "zoom-in": ("Ampliar", ()),
    "zoom-out": ("Reduzir", ()),
}


def read_cur(path: str | Path) -> Cursor:
    path = Path(path)
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_SIZE + 1)
    if len(data) > MAX_FILE_SIZE:
        raise CursorError("O arquivo excede o limite de 32 MiB.")
    if len(data) < 6:
        raise CursorError("Cabeçalho CUR incompleto.")
    reserved, kind, count = struct.unpack_from("<HHH", data)
    if reserved != 0 or kind != 2:
        raise CursorError("Este arquivo não é um cursor .cur válido (ICO e ANI não são CUR).")
    if not 1 <= count <= MAX_IMAGES:
        raise CursorError("Quantidade de imagens inválida (máximo: 128).")
    directory_end = 6 + count * 16
    if len(data) < directory_end:
        raise CursorError("Diretório de imagens incompleto.")
    images = []
    for index in range(count):
        entry = data[6 + index * 16:22 + index * 16]
        width, height, colors, unused, hx, hy, size, offset = struct.unpack("<BBBBHHII", entry)
        width, height = width or 256, height or 256
        if unused or not size or offset < directory_end or offset + size > len(data):
            raise CursorError(f"Imagem {index + 1}: intervalo de dados inválido.")
        if hx >= width or hy >= height:
            raise CursorError(f"Imagem {index + 1}: ponto de clique fora da imagem.")
        payload = data[offset:offset + size]
        # Rebuild a one-image ICO container: Pillow handles PNG and DIB/AND masks.
        ico = struct.pack("<HHH", 0, 1, 1)
        ico += struct.pack("<BBBBHHII", width % 256, height % 256, colors, 0, 1, 32, size, 22)
        try:
            with Image.open(io.BytesIO(ico + payload)) as decoded:
                if decoded.size != (width, height):
                    raise CursorError(f"Imagem {index + 1}: dimensões inconsistentes.")
                image = decoded.convert("RGBA")
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError, struct.error, Image.DecompressionBombError) as exc:
            raise CursorError(f"Imagem {index + 1}: dados PNG/DIB inválidos.") from exc
        images.append(CursorImage(image, hx, hy))
    return Cursor(path.resolve(), tuple(images))


def xcursor_bytes(cursor: Cursor) -> bytes:
    """Serialize Xcursor image chunks, including premultiplied ARGB pixels."""
    # Duplicate dimensions often represent alternate color depths; prefer the last.
    unique = {item.image.size: item for item in cursor.images}
    images = sorted(unique.values(), key=lambda item: item.nominal_size)
    position = 16 + 12 * len(images)
    toc, chunks = [], []
    for item in images:
        width, height = item.image.size
        pixels = bytearray()
        rgba = item.image.tobytes()
        for index in range(0, len(rgba), 4):
            red, green, blue, alpha = rgba[index:index + 4]
            pixels.extend(struct.pack("<I", (alpha << 24) | (((red * alpha + 127) // 255) << 16)
                                      | (((green * alpha + 127) // 255) << 8)
                                      | ((blue * alpha + 127) // 255)))
        chunk = struct.pack("<9I", 36, 0xFFFD0002, item.nominal_size, 1,
                            width, height, item.hotspot_x, item.hotspot_y, 0) + pixels
        toc.append(struct.pack("<3I", 0xFFFD0002, item.nominal_size, position))
        chunks.append(chunk)
        position += len(chunk)
    return struct.pack("<4I", 0x72756358, 16, 0x00010000, len(images)) + b"".join(toc + chunks)


def theme_slug(name: str) -> str:
    if any(ord(c) < 32 for c in name):
        raise CursorError("O nome não pode conter caracteres de controle.")
    name = name.strip()
    if not name or len(name) > 80:
        raise CursorError("Use um nome de tema com 1 a 80 caracteres, sem quebras de linha.")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-_").lower()
    if not slug:
        raise CursorError("O nome deve conter pelo menos uma letra ou número ASCII.")
    return slug


def export_theme(assignments: dict[str, Cursor], name: str, parent: str | Path) -> Path:
    """Create a complete theme without overwriting an existing file or directory."""
    slug = theme_slug(name)
    if not assignments or "left_ptr" not in assignments:
        raise CursorError("Associe pelo menos um cursor à função Ponteiro padrão.")
    if any(role not in ROLES for role in assignments):
        raise CursorError("Função de cursor desconhecida.")
    parent = Path(parent).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / slug
    if destination.exists() or destination.is_symlink():
        raise CursorError(f"Já existe um tema em {destination}. Escolha outro nome ou pasta.")
    stage = Path(tempfile.mkdtemp(prefix=".cursor-studio-", dir=parent))
    try:
        cursors = stage / "cursors"
        cursors.mkdir()
        for role, cursor in assignments.items():
            (cursors / role).write_bytes(xcursor_bytes(cursor))
            for alias in ROLES[role][1]:
                (cursors / alias).symlink_to(role)
        (stage / "index.theme").write_text(
            f"[Icon Theme]\nName={name.strip()}\nComment=Created with Cursor Studio\n"
            "Inherits=Adwaita\nExample=left_ptr\n", encoding="utf-8")
        # Reserve the destination first, then move staged contents. Refuse races.
        destination.mkdir()
        try:
            for item in stage.iterdir():
                shutil.move(str(item), str(destination / item.name))
        except Exception:
            shutil.rmtree(destination)
            raise
        return destination
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def user_icons_dir() -> Path:
    value = os.environ.get("XDG_DATA_HOME")
    base = Path(value) if value and Path(value).is_absolute() else Path.home() / ".local/share"
    return base / "icons"


def guess_role(path: Path) -> str | None:
    name = re.sub(r"[^a-z0-9]", "", path.stem.lower())
    for role in ROLES:
        if name == re.sub(r"[^a-z0-9]", "", role):
            return role
    guesses = {
        "arrow": "left_ptr", "normal": "left_ptr", "pointer": "left_ptr",
        "link": "hand2", "hand": "hand2", "ibeam": "xterm", "text": "xterm",
        "busy": "watch", "wait": "watch", "working": "left_ptr_watch",
        "unavailable": "not-allowed", "no": "not-allowed", "move": "fleur",
        "help": "question_arrow", "precision": "crosshair",
        "horiz": "sb_h_double_arrow", "vert": "sb_v_double_arrow",
        "diagonal1": "size_fdiag", "diagonal2": "size_bdiag",
    }
    return guesses.get(name)
