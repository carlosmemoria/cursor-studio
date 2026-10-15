import ctypes
import ctypes.util
import io
import struct

import pytest
from PIL import Image

from cursor_studio.cli import main
from cursor_studio.core import CursorError, export_theme, read_cur, theme_slug, xcursor_bytes


def make_cur(path, sizes=(24, 48), png=True):
    entries, chunks = [], []
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        image = Image.new("RGBA", (size, size), (200, 100, 50, 128))
        buf = io.BytesIO()
        if png:
            image.save(buf, format="PNG")
            payload = buf.getvalue()
        else:
            image.save(buf, format="ICO", sizes=[(size, size)], bitmap_format="bmp")
            ico = buf.getvalue()
            payload_size, pos = struct.unpack_from("<II", ico, 14)
            payload = ico[pos:pos + payload_size]
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 2, 3, len(payload), offset))
        chunks.append(payload)
        offset += len(payload)
    path.write_bytes(struct.pack("<HHH", 0, 2, len(sizes)) + b"".join(entries + chunks))
    return path


@pytest.mark.parametrize("png", [True, False])
def test_decode_png_and_dib(tmp_path, png):
    cursor = read_cur(make_cur(tmp_path / "arrow.cur", png=png))
    assert [frame.image.size for frame in cursor.images] == [(24, 24), (48, 48)]
    assert (cursor.largest.hotspot_x, cursor.largest.hotspot_y) == (2, 3)
    assert cursor.largest.image.getpixel((0, 0)) == (200, 100, 50, 128)


def test_xcursor_header_pixels_and_hotspot(tmp_path):
    data = xcursor_bytes(read_cur(make_cur(tmp_path / "arrow.cur")))
    assert struct.unpack_from("<4I", data) == (0x72756358, 16, 0x10000, 2)
    position = struct.unpack_from("<I", data, 24)[0]
    assert struct.unpack_from("<9I", data, position) == (36, 0xFFFD0002, 24, 1, 24, 24, 2, 3, 0)
    assert struct.unpack_from("<I", data, position + 36)[0] == 0x80643219


def test_system_libxcursor_reads_output(tmp_path):
    library = ctypes.util.find_library("Xcursor")
    if not library:
        pytest.skip("libXcursor is not installed")
    cursor = read_cur(make_cur(tmp_path / "arrow.cur"))
    output = tmp_path / "left_ptr"
    output.write_bytes(xcursor_bytes(cursor))

    class XcursorImage(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint) for name in ["version", "size", "width", "height", "xhot", "yhot", "delay"]] + [("pixels", ctypes.POINTER(ctypes.c_uint32))]

    class XcursorImages(ctypes.Structure):
        _fields_ = [("nimage", ctypes.c_int), ("images", ctypes.POINTER(ctypes.POINTER(XcursorImage))), ("name", ctypes.c_char_p)]

    lib = ctypes.CDLL(library)
    lib.XcursorFilenameLoadAllImages.argtypes = [ctypes.c_char_p]
    lib.XcursorFilenameLoadAllImages.restype = ctypes.POINTER(XcursorImages)
    lib.XcursorImagesDestroy.argtypes = [ctypes.POINTER(XcursorImages)]
    result = lib.XcursorFilenameLoadAllImages(bytes(output))
    assert result
    try:
        assert result.contents.nimage == 2
        frame = result.contents.images[1].contents
        assert (frame.width, frame.height, frame.xhot, frame.yhot) == (48, 48, 2, 3)
        assert frame.pixels[0] == 0x80643219
    finally:
        lib.XcursorImagesDestroy(result)


@pytest.mark.parametrize("payload", [b"", b"\0" * 12, struct.pack("<HHH", 0, 2, 200), struct.pack("<HHH", 0, 2, 1)])
def test_reject_invalid_headers(tmp_path, payload):
    path = tmp_path / "bad.cur"
    path.write_bytes(payload)
    with pytest.raises(CursorError):
        read_cur(path)


def test_reject_bad_hotspot_and_offset(tmp_path):
    path = make_cur(tmp_path / "bad.cur")
    original = path.read_bytes()
    for position, value in [(10, 999), (18, 0)]:
        data = bytearray(original)
        struct.pack_into("<H" if position == 10 else "<I", data, position, value)
        path.write_bytes(data)
        with pytest.raises(CursorError):
            read_cur(path)


def test_theme_aliases_and_refuse_overwrite(tmp_path):
    cursor = read_cur(make_cur(tmp_path / "arrow.cur"))
    destination = export_theme({"left_ptr": cursor}, "My Theme", tmp_path / "out")
    assert destination.name == "my-theme"
    assert (destination / "cursors/default").is_symlink()
    assert (destination / "cursors/default").read_bytes().startswith(b"Xcur")
    assert "Name=My Theme" in (destination / "index.theme").read_text()
    with pytest.raises(CursorError):
        export_theme({"left_ptr": cursor}, "My Theme", tmp_path / "out")


def test_theme_validation_and_path_safety(tmp_path):
    with pytest.raises(CursorError):
        export_theme({}, "Test", tmp_path)
    for name in ["", "\nInjected=true", "...", "a" * 81]:
        with pytest.raises(CursorError):
            theme_slug(name)
    assert theme_slug("../../Escape") == "escape"


def test_cli_does_not_overwrite(tmp_path):
    source = make_cur(tmp_path / "arrow.cur")
    output = tmp_path / "out"
    assert main(["convert", str(source), str(output)]) == 0
    before = output.read_bytes()
    assert main(["convert", str(source), str(output)]) == 1
    assert output.read_bytes() == before


def test_maximum_dimension(tmp_path):
    cursor = read_cur(make_cur(tmp_path / "large.cur", sizes=(256,)))
    assert cursor.largest.image.size == (256, 256)


def test_user_install_respects_xdg(tmp_path, monkeypatch):
    from cursor_studio.core import user_icons_dir
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert user_icons_dir() == tmp_path / "icons"
    monkeypatch.setenv("XDG_DATA_HOME", "relative-is-invalid")
    assert user_icons_dir().is_absolute()


@pytest.mark.parametrize("name,role", [("Normal Select.cur", "left_ptr"), ("Alternate Select.cur", "up_arrow"), ("Precision Select.cur", "crosshair"), ("Text Select.cur", "xterm"), ("Working In Background.cur", "left_ptr_watch")])
def test_windows_scheme_names(name, role):
    from pathlib import Path
    from cursor_studio.core import guess_role
    assert guess_role(Path(name)) == role


def test_install_registers_legacy_lookup_and_is_idempotent(tmp_path, monkeypatch):
    from pathlib import Path
    from cursor_studio.core import install_user_theme, register_user_theme
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    cursor = read_cur(make_cur(tmp_path / "arrow.cur"))
    theme = install_user_theme({"left_ptr": cursor}, "Compatible")
    link = tmp_path / ".icons/compatible"
    assert link.is_symlink()
    assert link.resolve() == theme
    assert register_user_theme(theme) == theme
    assert (link / "cursors/left_ptr").read_bytes().startswith(b"Xcur")


def test_install_preserves_legacy_conflicts(tmp_path, monkeypatch):
    from pathlib import Path
    from cursor_studio.core import install_user_theme
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    existing = tmp_path / ".icons/compatible"
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("existing theme")
    cursor = read_cur(make_cur(tmp_path / "arrow.cur"))
    with pytest.raises(CursorError):
        install_user_theme({"left_ptr": cursor}, "Compatible")
    assert (existing / "keep.txt").read_text() == "existing theme"
    assert not (tmp_path / "data/icons/compatible").exists()
