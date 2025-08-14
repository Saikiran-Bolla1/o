from __future__ import annotations

from .a2l import A2LDocument


def change_a2l_version(doc: A2LDocument, target_version: str) -> A2LDocument:
    return doc.annotate_version(target_version)
