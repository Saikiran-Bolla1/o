from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from elftools.elf.elffile import ELFFile
from elftools.dwarf.dwarfinfo import DWARFInfo
from elftools.dwarf.die import DIE
from elftools.dwarf.descriptions import describe_form_class


@dataclass
class SymbolInfo:
    name: str
    address: int
    size: Optional[int] = None
    a2l_datatype: Optional[str] = None


def load_symbols_from_elf(path: Path) -> Dict[str, SymbolInfo]:
    with path.open("rb") as f:
        elf = ELFFile(f)
        syms = _load_from_symtab(elf)
        if elf.has_dwarf_info():
            dwarf = elf.get_dwarf_info()
            syms = _augment_with_dwarf(elf, dwarf, syms)
        return syms


def _load_from_symtab(elf: ELFFile) -> Dict[str, SymbolInfo]:
    symbols: Dict[str, SymbolInfo] = {}
    for section in elf.iter_sections():
        sh_type = section.header.sh_type
        if sh_type in ("SHT_SYMTAB", "SHT_DYNSYM"):
            for sym in section.iter_symbols():
                name = sym.name
                if not name:
                    continue
                addr = int(sym.entry.get("st_value", 0)) or 0
                size = int(sym.entry.get("st_size", 0)) or None
                if name not in symbols:
                    symbols[name] = SymbolInfo(name=name, address=addr, size=size)
    return symbols


def _augment_with_dwarf(elf: ELFFile, dwarf: DWARFInfo, symbols: Dict[str, SymbolInfo]) -> Dict[str, SymbolInfo]:
    for cu in dwarf.iter_CUs():
        top = cu.get_top_DIE()
        for die in top.iter_children():
            _process_die(die, cu, symbols)
    return symbols


def _process_die(die: DIE, cu, symbols: Dict[str, SymbolInfo]) -> None:
    tag = die.tag
    if tag == "DW_TAG_variable":
        name_attr = die.attributes.get("DW_AT_name")
        if not name_attr:
            return
        name = name_attr.value.decode(errors="ignore")
        addr = _addr_from_location(die, cu)
        a2l_type = _a2l_datatype_from_die(die, cu)
        if name in symbols:
            if addr is not None and addr != 0:
                symbols[name].address = addr
            if a2l_type:
                symbols[name].a2l_datatype = a2l_type
        else:
            if addr is not None:
                symbols[name] = SymbolInfo(name=name, address=addr, a2l_datatype=a2l_type)
    for child in die.iter_children():
        _process_die(child, cu, symbols)


def _addr_from_location(die: DIE, cu) -> Optional[int]:
    loc_attr = die.attributes.get("DW_AT_location")
    if not loc_attr:
        return None
    form = describe_form_class(loc_attr.form)
    if form == "exprloc":
        expr = loc_attr.value
        if len(expr) >= 1 and expr[0] == 0x03:
            addr_size = cu['address_size']
            if len(expr) >= 1 + addr_size:
                addr_bytes = expr[1:1 + addr_size]
                addr = int.from_bytes(addr_bytes, byteorder="little")
                return addr
    return None


def _a2l_datatype_from_die(die: DIE, cu) -> Optional[str]:
    type_die = _resolve_type_die(die, cu)
    if not type_die:
        return None
    enc = type_die.attributes.get("DW_AT_encoding")
    size_attr = type_die.attributes.get("DW_AT_byte_size")
    if not enc or not size_attr:
        return None
    enc_val = enc.value
    size = int(size_attr.value)
    if enc_val == 0x07:
        return {1: "UBYTE", 2: "UWORD", 4: "ULONG", 8: "A_UINT64"}.get(size)
    if enc_val == 0x05:
        return {1: "SBYTE", 2: "SWORD", 4: "SLONG", 8: "A_INT64"}.get(size)
    if enc_val == 0x04:
        return {4: "FLOAT32_IEEE", 8: "FLOAT64_IEEE"}.get(size)
    return None


def _resolve_type_die(die: DIE, cu) -> Optional[DIE]:
    visited = set()
    current = die
    while True:
        tattr = current.attributes.get("DW_AT_type")
        if not tattr:
            return None
        offset = tattr.value + cu.cu_offset
        if offset in visited:
            return None
        visited.add(offset)
        td = cu.get_DIE_from_refaddr(offset)
        if td is None:
            return None
        tag = td.tag
        if tag in ("DW_TAG_base_type",):
            return td
        current = td
