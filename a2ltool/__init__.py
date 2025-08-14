
"""
a2ltool-py: Function-first API for working with A2L (ASAM MCD-2 MC) files.

Core building-block functions are imported from .api.
High-level convenience functions (path-in/path-out) are imported from .simple_api.
"""

from .api import (
    load,
    from_text,
    to_text,
    save,
    inline_includes,
    merge,
    update,
    create,
    check,
    extract_xcp_info,
    change_version,
)

# Convenience, file-oriented wrappers
try:
    from .simple_api import (
        update_a2l_from_elf,
        merge_a2l_files,
        create_a2l_from_elf,
        inline_includes_file,
        check_a2l,
        extract_xcp_info_from_a2l,
        change_a2l_version_file,
    )
except Exception:  # simple_api is optional in some minimal builds
    update_a2l_from_elf = None
    merge_a2l_files = None
    create_a2l_from_elf = None
    inline_includes_file = None
    check_a2l = None
    extract_xcp_info_from_a2l = None
    change_a2l_version_file = None

__all__ = [
    # Core API
    "load",
    "from_text",
    "to_text",
    "save",
    "inline_includes",
    "merge",
    "update",
    "create",
    "check",
    "extract_xcp_info",
    "change_version",
    # Convenience wrappers
    "update_a2l_from_elf",
    "merge_a2l_files",
    "create_a2l_from_elf",
    "inline_includes_file",
    "check_a2l",
    "extract_xcp_info_from_a2l",
    "change_a2l_version_file",
]

__version__ = "0.2.1"
