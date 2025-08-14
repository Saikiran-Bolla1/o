# a2ltool-py

A Python CLI to edit, merge and update A2L (ASAM MCD-2 MC) files.

This version includes:
- Lossless A2L document model with a tolerant parser and precise printer that preserve whitespace, comments and section order.
- Structure-aware merge with de-duplication and conflict handling inside MODULE blocks.
- Include inlining at the AST layer.
- ELF DWARF-powered symbol/type extraction (pyelftools), with optional PE/PDB symbol reading on Windows.
- Update semantics:
  - Scope: ADDRESSES (only ECU_ADDRESS), ALL (address + data type where possible).
  - Mode: PRESERVE (keep primary content on conflict), STRICT (raise on conflicts or missing symbols).
- Consistency checks (BEGIN/END, duplicates, references) and XCP IF_DATA parsing (basic).
- Tests for round-trip, merging, updates, includes, and XCP parsing.

Install
- Editable: pip install -e .
- Run: a2ltool --help

Examples
- Merge two A2L files:
  a2ltool file1.a2l --merge file2.a2l --output merged.a2l
- Merge multiple files:
  a2ltool file1.a2l --merge file2.a2l --merge file3.a2l --output merged.a2l
- Merge all included files:
  a2ltool file1.a2l --merge-includes --output flat.a2l
- Update from ELF:
  a2ltool input.a2l --elffile input.elf --update --output updated.a2l
- Update addresses only, strict mode:
  a2ltool input.a2l --elffile input.elf --update ADDRESSES --update-mode STRICT --output updated.a2l
- Create with a characteristic:
  a2ltool --create --elffile input.elf --characteristic my_var --output newfile.a2l
- Create with measurement regex:
  a2ltool --create --elffile input.elf --measurement-regex ".*name_pattern\\d\\d+*" --output newfile.a2l
- Create with address range:
  a2ltool --create --elffile input.elf --measurement-range 0x1000 0x3000 --output newfile.a2l
- Change A2L version:
  a2ltool input.a2l --a2lversion 1.5.1 --output downgraded.a2l
- Check:
  a2ltool input.a2l --check --strict

Notes
- The A2L parser is tolerant and lossless: it preserves all text and comments. It recognizes block boundaries (/begin ... /end), include directives, and common object blocks (MEASUREMENT, CHARACTERISTIC, AXIS_PTS, RECORD_LAYOUT, COMPU_METHOD, COMPU_TAB, MODULE, PROJECT).
- Structure-aware merges occur inside MODULE blocks by de-duplicating objects with the same kind+name.
- DWARF-based type mapping supports common base types. Some complex/bitfield types may fall back to preserving existing types in PRESERVE mode.

Run tests:
  pytest -q
