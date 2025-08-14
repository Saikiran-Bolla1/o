from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

try:
    import pefile  # type: ignore
except Exception:
    pefile = None

try:
    import pdbparse  # type: ignore
except Exception:
    pdbparse = None


@dataclass
class SymbolInfo:
    name: str
    address: int
    size: Optional[int] = None
    a2l_datatype: Optional[str] = None


def load_symbols_from_pe_or_pdb(path: Path) -> Dict[str, SymbolInfo]:
    symbols: Dict[str, SymbolInfo] = {}
    suffix = path.suffix.lower()
    if suffix == ".pdb" and pdbparse:
        try:
            return symbols
        except Exception:
            return symbols
    if pefile and suffix in (".exe", ".dll", ".sys"):
        try:
            pe = pefile.PE(str(path))
            return symbols
        except Exception:
            return symbols
    return symbols
