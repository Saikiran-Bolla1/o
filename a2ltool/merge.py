from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .a2l import A2LDocument


def merge_a2l_files(primary: A2LDocument, others: Iterable[Path], mode: str = "PRESERVE") -> A2LDocument:
    doc = primary
    for p in others:
        o = A2LDocument.read(p)
        doc = doc.merge_with([o], mode=mode)
    return doc


def merge_includes(doc: A2LDocument, base_dir: Path) -> A2LDocument:
    return doc.inline_includes(base_dir=base_dir)
