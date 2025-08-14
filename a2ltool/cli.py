from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .a2l import A2LDocument
from .merge import merge_a2l_files, merge_includes
from .update import UpdateScope, UpdateMode, update_from_elf, create_from_elf
from .check import check_consistency
from .versioning import change_a2l_version
from .xcp import extract_xcp_info


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="a2ltool",
        description="Edit, merge and update A2L (ASAM MCD-2 MC) files."
    )
    p.add_argument("input", nargs="?", help="Input A2L file (omit when using --create).")

    p.add_argument("--merge", action="append", default=[], help="Merge another A2L file (repeatable).")
    p.add_argument("--merge-includes", action="store_true", help="Merge all included files into the main file.")

    p.add_argument("--create", action="store_true", help="Create a new A2L file from debug info (requires --elffile).")

    p.add_argument("--elffile", help="ELF (or PE/PDB) file with debug info to drive updates/creation.")
    p.add_argument("--update", nargs="?", const="ALL", choices=["ALL", "ADDRESSES"], help="Update mode: ALL (default) or ADDRESSES only.")
    p.add_argument("--update-mode", choices=["PRESERVE", "STRICT"], default="PRESERVE", help="Behavior for invalid/incompatible elements.")
    p.add_argument("--characteristic", help="Add a single characteristic (when using --create).")
    p.add_argument("--measurement-regex", help="Add measurements matching regex (when using --create).")
    p.add_argument("--measurement-range", nargs=2, help="Add measurements in [start, end] address range (when using --create).")

    p.add_argument("--a2lversion", help="Change A2L version (e.g., 1.5.1) and remove incompatible items.")

    p.add_argument("--check", action="store_true", help="Check A2L for consistency.")
    p.add_argument("--strict", action="store_true", help="Use strict checking mode.")

    p.add_argument("--xcp-info", action="store_true", help="Display XCP connection parameters if present.")

    p.add_argument("--output", "-o", required=False, help="Output A2L file path.")
    return p


def load_a2l_or_empty(input_path: Optional[str]) -> A2LDocument:
    if input_path:
        return A2LDocument.read(Path(input_path))
    return A2LDocument.empty()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.create:
        if not args.elffile:
            print("--create requires --elffile", file=sys.stderr)
            return 2
        doc = create_from_elf(
            elf_path=Path(args.elffile),
            characteristic=args.characteristic,
            measurement_regex=args.measurement_regex,
            measurement_range=args.measurement_range,
        )
    else:
        if not args.input:
            print("Missing input A2L file (or use --create).", file=sys.stderr)
            return 2
        doc = load_a2l_or_empty(args.input)

    # Merging operations
    if args.merge:
        doc = merge_a2l_files(primary=doc, others=[Path(p) for p in args.merge], mode=args.update_mode)

    if args.merge_includes:
        base_dir = Path(args.input).parent if args.input else Path(".")
        doc = merge_includes(doc, base_dir=base_dir)

    # Update operations
    if args.update:
        if not args.elffile:
            print("--update requires --elffile", file=sys.stderr)
            return 2
        scope = UpdateScope.ADDRESSES if args.update == "ADDRESSES" else UpdateScope.ALL
        mode = UpdateMode[args.update_mode]
        doc = update_from_elf(doc, elf_path=Path(args.elffile), scope=scope, mode=mode)

    # Version change
    if args.a2lversion:
        doc = change_a2l_version(doc, target_version=args.a2lversion)

    # Checks
    if args.check:
        ok, report = check_consistency(doc, strict=args.strict)
        print(report)
        if not ok and args.strict:
            return 1

    # XCP info
    if args.xcp_info:
        info = extract_xcp_info(doc)
        if info:
            print(info)
        else:
            print("No XCP connection parameters found.")

    # Output
    if args.output:
        doc.write(Path(args.output))
    else:
        # Write to stdout
        sys.stdout.write(doc.to_text())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
