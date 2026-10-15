"""Headless conversion entry point; importing this module does not load Qt."""
import argparse
import sys
from pathlib import Path

from .core import ROLES, CursorError, export_theme, read_cur, xcursor_bytes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert Windows CUR files into Linux Xcursor themes.")
    sub = parser.add_subparsers(dest="command", required=True)
    convert = sub.add_parser("convert", help="Convert one .cur into a raw Xcursor file")
    convert.add_argument("input", type=Path)
    convert.add_argument("output", type=Path)
    theme = sub.add_parser("theme", help="Build a theme from ROLE=FILE assignments")
    theme.add_argument("--name", required=True)
    theme.add_argument("--output", type=Path, required=True, help="Parent output directory")
    theme.add_argument("assignments", nargs="+", metavar="ROLE=FILE")
    for command in [convert, theme]:
        command.add_argument("--sizes", help="Additional nominal sizes, e.g. 24,32,48,64,96,128")
        command.add_argument("--pixel-art", action="store_true", help="Use nearest-neighbor resizing")
    theme.add_argument("--overwrite", action="store_true", help="Replace an existing theme and keep a backup")
    args = parser.parse_args(argv)
    try:
        try:
            sizes = tuple(int(value) for value in args.sizes.split(",")) if args.sizes else None
        except ValueError as exc:
            raise CursorError("Sizes must be comma-separated integers.") from exc
        method = "pixel" if args.pixel_art else "smooth"
        if args.command == "convert":
            data = xcursor_bytes(read_cur(args.input), sizes=sizes, resampling=method)
            with args.output.open("xb") as stream:
                stream.write(data)
            print(args.output)
        else:
            assignments = {}
            for entry in args.assignments:
                role, separator, path = entry.partition("=")
                if not separator or role not in ROLES or role in assignments:
                    raise CursorError(f"Invalid or duplicate role: {entry}. Valid roles: {', '.join(ROLES)}")
                assignments[role] = read_cur(path)
            print(export_theme(assignments, args.name, args.output, overwrite=args.overwrite, sizes=sizes, resampling=method))
        return 0
    except (CursorError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
