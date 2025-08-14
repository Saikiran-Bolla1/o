from __future__ import annotations

from pathlib import Path
from typing import Iterable, Literal, Optional, Tuple, Union

# Import the function-first API from the package
from .api import (
    load,
    save,
    to_text,
    inline_includes as _inline_includes,
    merge as _merge,
    update as _update,
    create as _create,
    check as _check,
    extract_xcp_info as _extract_xcp_info,
    change_version as _change_version,
)

PathLike = Union[str, Path]


def update_a2l_from_elf(
    a2l_path: PathLike,
    elf_path: PathLike,
    *,
    scope: Literal["ALL", "ADDRESSES"] = "ALL",
    mode: Literal["PRESERVE", "STRICT"] = "PRESERVE",
    inline: bool = True,
    output: Optional[PathLike] = None,
) -> str:
    """
    Update an A2L file using an ELF image.

    - scope: "ALL" updates ECU_ADDRESS and data types where possible; "ADDRESSES" updates addresses only.
    - mode: "PRESERVE" keeps existing content on conflicts; "STRICT" raises on missing symbols/conflicts.
    - inline: if True, inlines include directives before updating (recommended).
    - output: if provided, writes the updated A2L to this path.

    Returns the updated A2L text.
    """
    a2l_path = Path(a2l_path)
    doc = load(a2l_path)
    if inline:
        doc = _inline_includes(doc, base_dir=a2l_path.parent)
    doc = _update(doc, image_path=elf_path, scope=scope, mode=mode)
    if output:
        save(doc, output)
    return to_text(doc)


def merge_a2l_files(
    primary: PathLike,
    others: Iterable[PathLike],
    *,
    mode: Literal["PRESERVE", "STRICT"] = "PRESERVE",
    inline_primary: bool = False,
    output: Optional[PathLike] = None,
) -> str:
    """
    Merge multiple A2L files into a primary file (structure-aware within MODULE).

    - mode: "PRESERVE" keeps primary's objects on conflicts; "STRICT" raises on conflicts.
    - inline_primary: if True, inlines includes in the primary before merging (optional).
    - output: if provided, writes the merged A2L to this path.

    Returns the merged A2L text.
    """
    primary = Path(primary)
    doc = load(primary)
    if inline_primary:
        doc = _inline_includes(doc, base_dir=primary.parent)
    doc = _merge(doc, [Path(p) for p in others], mode=mode)
    if output:
        save(doc, output)
    return to_text(doc)


def create_a2l_from_elf(
    elf_path: PathLike,
    *,
    characteristic: Optional[str] = None,
    measurement_regex: Optional[str] = None,
    measurement_range: Optional[Tuple[Union[int, str], Union[int, str]]] = None,
    output: Optional[PathLike] = None,
) -> str:
    """
    Create a minimal A2L from an ELF image.

    - characteristic: exact variable name to include as a characteristic.
    - measurement_regex: regex to select variables (e.g., r"(speed|rpm)").
    - measurement_range: address range (lo, hi) as ints or strings (e.g., (0x1000, 0x3000)).
    - output: if provided, writes the generated A2L to this path.

    Returns the generated A2L text.
    """
    doc = _create(
        image_path=elf_path,
        characteristic=characteristic,
        measurement_regex=measurement_regex,
        measurement_range=measurement_range,
    )
    if output:
        save(doc, output)
    return to_text(doc)


def inline_includes_file(
    a2l_path: PathLike,
    *,
    base_dir: Optional[PathLike] = None,
    output: Optional[PathLike] = None,
) -> str:
    """
    Inline include directives inside an A2L file.

    - base_dir: root directory to resolve includes; defaults to the A2L's directory.
    - output: if provided, writes the inlined A2L to this path.

    Returns the inlined A2L text.
    """
    a2l_path = Path(a2l_path)
    doc = load(a2l_path)
    base = Path(base_dir) if base_dir is not None else a2l_path.parent
    doc = _inline_includes(doc, base_dir=base)
    if output:
        save(doc, output)
    return to_text(doc)


def check_a2l(
    a2l_path: PathLike,
    *,
    strict: bool = False,
) -> tuple[bool, str]:
    """
    Run best-effort consistency checks on an A2L file.

    - strict: if True, the boolean indicates whether it would pass in strict mode.

    Returns (ok, report_text).
    """
    doc = load(a2l_path)
    return _check(doc, strict=strict)


def extract_xcp_info_from_a2l(a2l_path: PathLike) -> Optional[str]:
    """
    Extract XCP IF_DATA parameters from an A2L file (best-effort).

    Returns a summary string or None if not found.
    """
    doc = load(a2l_path)
    return _extract_xcp_info(doc)


def change_a2l_version_file(
    a2l_path: PathLike,
    *,
    target_version: str,
    output: Optional[PathLike] = None,
) -> str:
    """
    Annotate/adapt an A2L file to a target A2L version (best-effort placeholder).

    - target_version: e.g., "1.5.1"
    - output: if provided, writes the modified A2L to this path.

    Returns the modified A2L text.
    """
    doc = load(a2l_path)
    doc = _change_version(doc, target_version=target_version)
    if output:
        save(doc, output)
    return to_text(doc)
