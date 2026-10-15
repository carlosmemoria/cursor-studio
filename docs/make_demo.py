"""Generate original sample cursors and an offscreen UI screenshot."""
import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw


def generate(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name, color in [("arrow", "#b6a7ff"), ("link", "#7ee2c3"), ("precision", "#ffb6c7")]:
        entries, chunks = [], []
        offset = 6 + 16 * 3
        for size in (24, 48, 64):
            image = Image.new("RGBA", (size, size))
            draw = ImageDraw.Draw(image)
            if name == "precision":
                c = size // 2
                draw.ellipse((c - size // 4, c - size // 4, c + size // 4, c + size // 4), outline=color, width=max(1, size // 16))
                draw.line((c, 2, c, size - 3), fill=color, width=max(1, size // 16))
                draw.line((2, c, size - 3, c), fill=color, width=max(1, size // 16))
                hx = hy = c
            else:
                draw.polygon([(2, 2), (size - 5, int(size * .61)), (int(size * .56), int(size * .65)), (int(size * .38), size - 4)], fill=color, outline="#ffffff", width=max(1, size // 24))
                hx = hy = 2
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            payload = buffer.getvalue()
            entries.append(struct.pack("<BBBBHHII", size, size, 0, 0, hx, hy, len(payload), offset))
            chunks.append(payload)
            offset += len(payload)
        (destination / f"{name}.cur").write_bytes(struct.pack("<HHH", 0, 2, 3) + b"".join(entries + chunks))


if __name__ == "__main__":
    generate(Path(__file__).parent / "examples")
