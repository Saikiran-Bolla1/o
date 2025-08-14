from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple

from .a2l import A2LDocument
from .elf import load_symbols_from_elf
from .pe import load_symbols_from_pe_or_pdb


class UpdateScope(Enum):
    ALL = "ALL"
    ADDRESSES = "ADDRESSES"


class UpdateMode(Enum):
    PRESERVE = "PRESERVE"
    STRICT = "STRICT"


@dataclass
class CreateFilters:
    characteristic: Optional[str] = None
    measurement_regex: Optional[str] = None
    measurement_range: Optional[Tuple[int, int]] = None


def _load_symbols(elf_or_pe_path: Path) -> Dict[str, object]:
    suf = elf_or_pe_path.suffix.lower()
    if suf in (".elf", ".axf", ".out", ".o"):
        return load_symbols_from_elf(elf_or_pe_path)
    if suf in (".exe", ".dll", ".sys", ".pdb"):
        return load_symbols_from_pe_or_pdb(elf_or_pe_path)
    return load_symbols_from_elf(elf_or_pe_path)


def update_from_elf(doc: A2LDocument, elf_path: Path, scope: UpdateScope, mode: UpdateMode) -> A2LDocument:
    symbols = _load_symbols(elf_path)
    norm_syms: Dict[str, object] = {}
    for name, si in symbols.items():
        norm_syms[name] = si
    return doc.update_addresses_and_types(norm_syms, scope=scope.value, mode=mode.value)


def create_from_elf(
    elf_path: Path,
    characteristic: Optional[str],
    measurement_regex: Optional[str],
    measurement_range: Optional[Tuple[str, str]],
) -> A2LDocument:
    symbols = _load_symbols(elf_path)
    selected = set()

    if characteristic:
        if characteristic in symbols:
            selected.add(characteristic)
    if measurement_regex:
        rx = re.compile(measurement_regex)
        for n in symbols.keys():
            if rx.search(n):
                selected.add(n)
    if measurement_range:
        try:
            start = int(measurement_range[0], 0)
            end = int(measurement_range[1], 0)
            for n, si in symbols.items():
                addr = getattr(si, "address", 0)
                if start <= addr <= end:
                    selected.add(n)
        except Exception:
            pass

    lines = []
    lines.append('/begin PROJECT AutoProject ""\n')
    lines.append('  /begin MODULE AutoModule ""\n')
    for n in sorted(selected):
        si = symbols[n]
        addr = getattr(si, "address", 0)
        dtype = getattr(si, "a2l_datatype", None) or "SLONG"
        lines.append(f'    /begin MEASUREMENT {n} "" {dtype} 1.0 0 0 0\n')
        lines.append(f'      ECU_ADDRESS 0x{addr:X}\n')
        lines.append(f'    /end MEASUREMENT\n')
    lines.append("  /end MODULE\n")
    lines.append("/end PROJECT\n")
    return A2LDocument("".join(lines))
