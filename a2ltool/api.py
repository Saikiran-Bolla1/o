from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple, Union

from .a2l import A2LDocument
from .merge import merge_a2l_files
from .update import UpdateMode, UpdateScope, update_from_elf, create_from_elf
from .check import check_consistency
from .versioning import change_a2l_version
from .xcp import extract_xcp_info as _extract_xcp_info


PathLike = Union[str, Path]


def load(path: PathLike) -> A2LDocument:
    """Load an A2L file into a lossless A2LDocument."""
    return A2LDocument.read(Path(path))


def from_text(text: str) -> A2LDocument:
    """Create an A2LDocument from raw A2L text."""
    return A2LDocument(text)


def to_text(doc: A2LDocument) -> str:
    """Serialize an A2LDocument back to text."""
    return doc.to_text()


def save(doc: A2LDocument, path: PathLike) -> None:
    """Write an A2LDocument to disk."""
    doc.write(Path(path))


def inline_includes(doc: A2LDocument, base_dir: PathLike) -> A2LDocument:
    """Inline include directives found in the document using base_dir as resolution root."""
    return doc.inline_includes(base_dir=Path(base_dir))


def merge(
    primary: A2LDocument,
    others: Union[Iterable[PathLike], Iterable[A2LDocument]],
    mode: str = "PRESERVE",
) -> A2LDocument:
    """Structure-aware merge of multiple A2L sources into primary.

    - mode: "PRESERVE" keeps primary content on conflicts, "STRICT" raises on conflicts.
    - others may be paths or already-loaded A2LDocument instances.
    """
    # If others are paths, delegate to merge_a2l_files that loads them; otherwise merge documents directly.
    if not others:
        return primary
    first = next(iter(others))
    if isinstance(first, (str, Path)):
        return merge_a2l_files(primary, [Path(p) for p in others], mode=mode)  # type: ignore[arg-type]
    # Already documents
    doc = primary.merge_with([o for o in others if isinstance(o, A2LDocument)], mode=mode)  # type: ignore[list-item]
    return doc


def update(
    doc: A2LDocument,
    image_path: PathLike,
    scope: Union[str, UpdateScope] = "ALL",
    mode: Union[str, UpdateMode] = "PRESERVE",
) -> A2LDocument:
    """Update addresses (and optionally types) using an ELF/PE image.

    - scope: "ALL" or UpdateScope.ALL to update addresses + types, or "ADDRESSES" for addresses only.
    - mode: "PRESERVE" to keep unknowns, "STRICT" to raise on missing symbols or conflicts.
    """
    scope_enum = UpdateScope[scope] if isinstance(scope, str) else scope
    mode_enum = UpdateMode[mode] if isinstance(mode, str) else mode
    return update_from_elf(doc, elf_path=Path(image_path), scope=scope_enum, mode=mode_enum)


def create(
    image_path: PathLike,
    *,
    characteristic: Optional[str] = None,
    measurement_regex: Optional[str] = None,
    measurement_range: Optional[Tuple[Union[int, str], Union[int, str]]] = None,
) -> A2LDocument:
    """Create a minimal A2L document from an ELF image with optional filters."""
    # Normalize range to strings accepted by underlying function
    rng: Optional[Tuple[str, str]] = None
    if measurement_range is not None:
        lo, hi = measurement_range
        rng = (str(lo), str(hi))
    return create_from_elf(
        elf_path=Path(image_path),
        characteristic=characteristic,
        measurement_regex=measurement_regex,
        measurement_range=rng,
    )


def check(doc: A2LDocument, strict: bool = False) -> tuple[bool, str]:
    """Run best-effort consistency checks. Returns (ok, report)."""
    return check_consistency(doc, strict=strict)


def extract_xcp_info(doc: A2LDocument) -> Optional[str]:
    """Extract XCP IF_DATA parameters if present (best-effort)."""
    return _extract_xcp_info(doc)


def change_version(doc: A2LDocument, target_version: str) -> A2LDocument:
    """Annotate or adapt document to a target A2L version (best-effort placeholder)."""
    return change_a2l_version(doc, target_version=target_version)
