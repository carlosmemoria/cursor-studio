"""Strict CUR decoding and a dependency-free Xcursor serializer.

All file reads are bounded. Export builds in a private staging directory; replacement
requires explicit opt-in and keeps the previous theme as a backup. No external command or Windows installer is executed.
"""
from __future__ import annotations

import io
import fcntl
import time
import os
import re
import shutil
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

STANDARD_SIZES = (24, 32, 48, 64, 96, 128)

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
    "pencil": ("Escrita manual", ("draft",)),
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


def resized_images(cursor: Cursor, sizes: tuple[int, ...] | None = None,
                   resampling: str = "smooth") -> tuple[CursorImage, ...]:
    """Keep native images and generate missing nominal sizes from the best source."""
    if resampling not in {"smooth", "pixel"}:
        raise CursorError("Método de redimensionamento inválido.")
    if sizes is None:
        return cursor.images
    if len(sizes) > 32 or any(type(size) is not int or not 1 <= size <= 256 for size in sizes):
        raise CursorError("Use até 32 tamanhos entre 1 e 256 pixels.")
    images = {frame.nominal_size: frame for frame in cursor.images}
    for size in sorted(set(sizes)):
        if size in images:
            continue
        bigger = [frame for frame in cursor.images if frame.nominal_size >= size]
        source = min(bigger, key=lambda f: f.nominal_size) if bigger else cursor.largest
        width, height = source.image.size
        nw, nh = max(1, round(width * size / source.nominal_size)), max(1, round(height * size / source.nominal_size))
        method = Image.Resampling.NEAREST if resampling == "pixel" else Image.Resampling.LANCZOS
        image = source.image.resize((nw, nh), method)
        images[size] = CursorImage(image, min(nw - 1, round(source.hotspot_x * nw / width)),
                                  min(nh - 1, round(source.hotspot_y * nh / height)))
    return tuple(images[size] for size in sorted(images))


def xcursor_bytes(cursor: Cursor, sizes: tuple[int, ...] | None = None,
                  resampling: str = "smooth") -> bytes:
    """Serialize Xcursor image chunks, including premultiplied ARGB pixels."""
    # Duplicate dimensions often represent alternate color depths; prefer the last.
    unique = {item.image.size: item for item in resized_images(cursor, sizes, resampling)}
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


def _commit_theme(stage: Path, destination: Path, overwrite: bool) -> None:
    """Serialize writers and keep the previous complete theme for rollback/recovery."""
    descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
    backup = None
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if destination.exists() or destination.is_symlink():
            if not overwrite:
                raise CursorError(f"Já existe um tema em {destination}.")
            if (destination.is_symlink() or not destination.is_dir()
                    or not (destination / "index.theme").is_file()
                    or not (destination / "cursors").is_dir()):
                raise CursorError("O destino não é uma pasta de tema válida. Nenhum arquivo foi substituído.")
            backups = destination.parent / ".cursor-studio-backups"
            backups.mkdir(exist_ok=True)
            backup = backups / f"{destination.name}-{time.time_ns()}"
            destination.rename(backup)
        try:
            stage.rename(destination)
        except Exception:
            if backup is not None:
                backup.rename(destination)
            raise
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def export_theme(assignments: dict[str, Cursor], name: str, parent: str | Path, *,
                 overwrite: bool = False, sizes: tuple[int, ...] | None = None,
                 resampling: str = "smooth") -> Path:
    """Build privately, then publish; replacing a theme requires explicit opt-in."""
    slug = theme_slug(name)
    if not assignments or "left_ptr" not in assignments:
        raise CursorError("Associe pelo menos um cursor à função Ponteiro padrão.")
    if any(role not in ROLES for role in assignments):
        raise CursorError("Função de cursor desconhecida.")
    parent = Path(parent).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / slug
    if (destination.exists() or destination.is_symlink()) and not overwrite:
        raise CursorError(f"Já existe um tema em {destination}.")
    stage = Path(tempfile.mkdtemp(prefix=".cursor-studio-", dir=parent))
    try:
        cursors = stage / "cursors"
        cursors.mkdir()
        for role, cursor in assignments.items():
            (cursors / role).write_bytes(xcursor_bytes(cursor, sizes, resampling))
            for alias in ROLES[role][1]:
                (cursors / alias).symlink_to(role)
        (stage / "index.theme").write_text(
            f"[Icon Theme]\nName={name.strip()}\nComment=Created with Cursor Studio\n"
            "Inherits=Breeze,Adwaita\nExample=left_ptr\n", encoding="utf-8")
        _commit_theme(stage, destination, overwrite)
        return destination
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def user_icons_dir() -> Path:
    value = os.environ.get("XDG_DATA_HOME")
    base = Path(value) if value and Path(value).is_absolute() else Path.home() / ".local/share"
    return base / "icons"


def register_user_theme(theme: Path) -> Path:
    """Expose XDG-installed themes to libXcursor builds using the legacy search path.

    Keep the actual theme in XDG_DATA_HOME; only add a per-theme compatibility link.
    Never replace an unrelated directory or link.
    """
    theme = theme.resolve()
    legacy = Path.home() / ".icons"
    if legacy.resolve() == theme.parent:
        return theme
    legacy.mkdir(parents=True, exist_ok=True)
    link = legacy / theme.name
    if link.exists() or link.is_symlink():
        if link.is_symlink() and link.resolve() == theme:
            return theme
        raise CursorError(f"O caminho de compatibilidade já existe: {link}. Nenhum arquivo foi substituído.")
    link.symlink_to(theme, target_is_directory=True)
    return theme


def install_user_theme(assignments: dict[str, Cursor], name: str, *,
                       overwrite: bool = False, sizes: tuple[int, ...] | None = None,
                       resampling: str = "smooth") -> Path:
    slug = theme_slug(name)
    target = user_icons_dir().resolve() / slug
    legacy = Path.home() / ".icons" / slug
    if (legacy.exists() or legacy.is_symlink()) and legacy != target:
        if not (legacy.is_symlink() and legacy.resolve() == target):
            raise CursorError(f"Já existe um tema em {legacy}. Escolha outro nome.")
    theme = export_theme(assignments, name, user_icons_dir(), overwrite=overwrite, sizes=sizes, resampling=resampling)
    try:
        return register_user_theme(theme)
    except OSError as exc:
        raise CursorError(f"Tema salvo em {theme}, mas não foi possível registrar a compatibilidade: {exc}") from exc


def guess_role(path: Path) -> str | None:
    name = re.sub(r"[^a-z0-9]", "", path.stem.lower())
    for role in ROLES:
        if name == re.sub(r"[^a-z0-9]", "", role):
            return role
    guesses = {
        "normalselect": "left_ptr", "alternateselect": "up_arrow",
        "helpselect": "question_arrow", "linkselect": "hand2", "precisionselect": "crosshair", "textselect": "xterm",
        "handwriting": "pencil", "workinginbackground": "left_ptr_watch",
        "horizontalresize": "sb_h_double_arrow", "verticalresize": "sb_v_double_arrow",
        "diagonalresize1": "size_fdiag", "diagonalresize2": "size_bdiag",
        "arrow": "left_ptr", "normal": "left_ptr", "pointer": "left_ptr",
        "link": "hand2", "hand": "hand2", "ibeam": "xterm", "text": "xterm",
        "busy": "watch", "wait": "watch", "working": "left_ptr_watch",
        "unavailable": "not-allowed", "no": "not-allowed", "move": "fleur",
        "help": "question_arrow", "precision": "crosshair",
        "horiz": "sb_h_double_arrow", "vert": "sb_v_double_arrow",
        "diagonal1": "size_fdiag", "diagonal2": "size_bdiag",
    }
    return guesses.get(name)
