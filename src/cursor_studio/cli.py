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
    args = parser.parse_args(argv)
    try:
        if args.command == "convert":
            data = xcursor_bytes(read_cur(args.input))
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
            print(export_theme(assignments, args.name, args.output))
        return 0
    except (CursorError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
