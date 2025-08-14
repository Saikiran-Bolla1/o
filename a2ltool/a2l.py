from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


_BEGIN_RE = re.compile(r'(?is)/\s*begin\b')
_END_RE = re.compile(r'(?is)/\s*end\b')
_INCLUDE_RE = re.compile(r'(?im)^\s*(?:/)?include\s+"([^"\r\n]+)"\s*$')
_HEADER_RE = re.compile(r'(?is)^\s*/\s*begin\s+([A-Za-z_][\w\.-]*)\s+([A-Za-z_][\w\.-]*|"[^"]*")')

# Objects we consider as uniquely keyed by kind+name inside MODULEs during merge
MERGE_OBJECT_KINDS = {
    "MEASUREMENT",
    "CHARACTERISTIC",
    "AXIS_PTS",
    "RECORD_LAYOUT",
    "COMPU_METHOD",
    "COMPU_VTAB",
    "COMPU_VTAB_RANGE",
    "COMPU_TAB",
    "FUNCTION",
}


@dataclass
class BlockSpan:
    kind: str
    name: str
    start: int
    end: int
    header_start: int
    header_end: int

    def slice(self, text: str) -> str:
        return text[self.start:self.end]

    def body_slice(self, text: str) -> str:
        return text[self.header_end:self.end]

    def header_slice(self, text: str) -> str:
        return text[self.header_start:self.header_end]


class A2LDocument:
    def __init__(self, text: str):
        self._text = text

    @classmethod
    def read(cls, path):
        from pathlib import Path
        return cls(Path(path).read_text(encoding="utf-8", errors="ignore"))

    @classmethod
    def empty(cls) -> "A2LDocument":
        return cls("")

    def to_text(self) -> str:
        return self._text

    def write(self, path):
        from pathlib import Path
        Path(path).write_text(self._text, encoding="utf-8")

    # ---------- Parsing primitives (lossless scanning) ----------

    def _scan_blocks(self, text: Optional[str] = None, region: Optional[Tuple[int, int]] = None) -> List[BlockSpan]:
        s = self._text if text is None else text
        start_pos = 0 if region is None else region[0]
        end_pos = len(s) if region is None else region[1]
        
        if region:
            s = s[start_pos:end_pos]
        
        # Use simpler regex approach
        begin_pattern = re.compile(r'/begin\s+(\w+)\s+(\w+|"[^"]*")')
        end_pattern = re.compile(r'/end\s+(\w+)')
        
        begins = [(m.start(), m.group(1), m.group(2)) for m in begin_pattern.finditer(s)]
        ends = [(m.start(), m.group(1)) for m in end_pattern.finditer(s)]
        
        # Stack to match begins with ends
        stack = []
        blocks = []
        
        # Create combined list of events
        events = []
        for pos, kind, name in begins:
            events.append((pos, 'begin', kind, name))
        for pos, kind in ends:
            events.append((pos, 'end', kind, None))
        
        # Sort by position
        events.sort()
        
        for pos, event_type, kind, name in events:
            if event_type == 'begin':
                # Remove quotes from name
                clean_name = name.strip('"')
                header_start = pos + start_pos
                header_end = s.find('\n', pos)
                if header_end == -1:
                    header_end = len(s)
                else:
                    header_end += 1
                header_end += start_pos
                stack.append((kind.upper(), clean_name, pos + start_pos, header_start, header_end))
            elif event_type == 'end' and stack:
                expected_kind, block_name, block_start, header_start, header_end = stack.pop()
                if expected_kind == kind.upper():
                    blocks.append(BlockSpan(
                        kind=expected_kind,
                        name=block_name,
                        start=block_start,
                        end=pos + start_pos + len(f"/end {kind}"),
                        header_start=header_start,
                        header_end=header_end
                    ))
        
        blocks.sort(key=lambda b: b.start)
        return blocks

    def _find_header_end(self, s: str, begin_start: int, end_lim: int) -> int:
        line_end = s.find("\n", begin_start)
        if line_end == -1 or line_end > end_lim:
            return end_lim
        return line_end + 1

    def _extract_name_from_header(self, s: str, header_start: int) -> str:
        line_end = s.find("\n", header_start)
        if line_end == -1:
            line_end = len(s)
        hm = _HEADER_RE.match(s, header_start)
        if hm:
            name = hm.group(2)
            # Remove quotes if present
            if name.startswith('"') and name.endswith('"'):
                name = name[1:-1]
            return name
        return ""

    # ---------- Include inlining ----------

    def inline_includes(self, base_dir) -> "A2LDocument":
        from pathlib import Path
        base_dir = Path(base_dir)
        s = self._text
        n = len(s)
        out: List[str] = []
        i = 0

        STATE_NORMAL, STATE_STRING, STATE_COMMENT = 0, 1, 2
        state = STATE_NORMAL

        while i < n:
            if state == STATE_NORMAL:
                line_start = s.rfind("\n", 0, i) + 1
                m = _INCLUDE_RE.match(s, line_start)
                if m and line_start == i:
                    rel = m.group(1)
                    inc_path = (base_dir / rel).resolve()
                    try:
                        inc_text = inc_path.read_text(encoding="utf-8", errors="ignore")
                        out.append(f"/* begin include: {rel} */\n")
                        out.append(inc_text)
                        if not inc_text.endswith("\n"):
                            out.append("\n")
                        out.append(f"/* end include: {rel} */\n")
                    except Exception:
                        out.append(s[line_start:m.end()])
                    i = m.end()
                    continue
                ch = s[i]
                if ch == '"':
                    state = STATE_STRING
                elif ch == '/' and i + 1 < n and s[i + 1] == '*':
                    state = STATE_COMMENT
                    i += 1
                out.append(ch)
                i += 1
            elif state == STATE_STRING:
                ch = s[i]
                out.append(ch)
                if ch == '\\' and i + 1 < n:
                    out.append(s[i + 1])
                    i += 2
                    continue
                if ch == '"':
                    state = STATE_NORMAL
                i += 1
            elif state == STATE_COMMENT:
                out.append(s[i])
                if s[i] == '*' and i + 1 < n and s[i + 1] == '/':
                    out.append(s[i + 1])
                    i += 2
                    state = STATE_NORMAL
                    continue
                i += 1
        return A2LDocument("".join(out))

    # ---------- Structure-aware merge ----------

    def _index_module_objects(self, module_span: BlockSpan, kinds: Iterable[str]) -> Dict[Tuple[str, str], Tuple[int, BlockSpan]]:
        inner_blocks = self._scan_blocks(text=self._text, region=(module_span.header_end, module_span.end))
        index: Dict[Tuple[str, str], Tuple[int, BlockSpan]] = {}
        for idx, b in enumerate(inner_blocks):
            if b.kind.upper() in kinds:
                index[(b.kind.upper(), b.name)] = (idx, b)
        return index

    def _find_modules(self) -> List[BlockSpan]:
        return [b for b in self._scan_blocks() if b.kind.upper() == "MODULE"]

    def merge_with(self, others: Sequence["A2LDocument"], mode: str = "PRESERVE") -> "A2LDocument":
        base_text = self._text
        for other in others:
            other_text = other._text
            base_modules = {b.name: b for b in A2LDocument(base_text)._find_modules()}
            other_modules = {b.name: b for b in A2LDocument(other_text)._find_modules()}

            if not base_modules:
                if base_text and not base_text.endswith("\n"):
                    base_text += "\n"
                base_text += f"\n/* merge appended */\n" + other_text
                continue

            for mod_name, ospan in other_modules.items():
                if mod_name in base_modules:
                    bspan = base_modules[mod_name]
                    base_text = self._merge_module_text(
                        base_text, bspan, other_text[ospan.start:ospan.end], mode=mode
                    )
                    base_modules = {b.name: b for b in A2LDocument(base_text)._find_modules()}
                else:
                    proj_blocks = [b for b in A2LDocument(base_text)._scan_blocks() if b.kind.upper() == "PROJECT"]
                    insert_pos = len(base_text)
                    if proj_blocks:
                        insert_pos = proj_blocks[-1].end
                    insertion = other_text[ospan.start:ospan.end]
                    base_text = base_text[:insert_pos] + "\n/* merge appended MODULE */\n" + insertion + base_text[insert_pos:]
        return A2LDocument(base_text)

    def _merge_module_text(self, base_text: str, base_mod: BlockSpan, other_mod_text: str, mode: str) -> str:
        base_inner = A2LDocument(base_text)
        base_index = base_inner._index_module_objects(base_mod, MERGE_OBJECT_KINDS)
        other_inner_blocks = A2LDocument(other_mod_text)._scan_blocks()
        segments_to_insert: List[str] = []
        for ob in other_inner_blocks:
            key = (ob.kind.upper(), ob.name)
            if ob.kind.upper() not in MERGE_OBJECT_KINDS:
                continue
            if key in base_index:
                existing_span = base_index[key][1]
                existing_text = base_text[existing_span.start:existing_span.end]
                other_text = other_mod_text[ob.start:ob.end]
                if _normalize_ws(existing_text) != _normalize_ws(other_text):
                    if mode.upper() == "STRICT":
                        raise ValueError(f"Merge conflict in MODULE {self._extract_name_from_header(base_text, base_mod.header_start)} for {key[0]} {key[1]}")
                    segments_to_insert.append(f"\n/* merge skipped duplicate {key[0]} {key[1]} */\n")
                continue
            seg = other_mod_text[ob.start:ob.end]
            segments_to_insert.append("\n" + seg + "\n")
        if not segments_to_insert:
            return base_text
        insertion_block = "".join(segments_to_insert)
        return base_text[:base_mod.end] + insertion_block + base_text[base_mod.end:]

    # ---------- Update operations ----------

    def update_addresses_and_types(
        self,
        symbols: Dict[str, "SymbolInfoLike"],
        scope: str = "ALL",
        mode: str = "PRESERVE",
    ) -> "A2LDocument":
        text = self._text
        modules = self._find_modules()
        for mspan in reversed(modules):
            mod_text = text[mspan.start:mspan.end]
            updated_mod_text = _update_module_objects(mod_text, symbols, scope=scope, mode=mode)
            if updated_mod_text != mod_text:
                text = text[:mspan.start] + updated_mod_text + text[mspan.end:]
        return A2LDocument(text)

    # ---------- Versioning annotation (placeholder) ----------

    def annotate_version(self, target_version: str) -> "A2LDocument":
        if self._text.startswith("/* a2ltool-py set version:"):
            return self
        return A2LDocument(f"/* a2ltool-py set version: {target_version} */\n" + self._text)


def _normalize_ws(s: str) -> str:
    return re.sub(r'\s+', ' ', s.strip())


def _update_module_objects(
    module_text: str,
    symbols: Dict[str, "SymbolInfoLike"],
    scope: str,
    mode: str,
) -> str:
    inner_blocks = A2LDocument(module_text)._scan_blocks()
    out = module_text
    for b in reversed(inner_blocks):
        kind = b.kind.upper()
        if kind not in MERGE_OBJECT_KINDS:
            continue
        name = b.name
        sym = symbols.get(name)
        if sym is None:
            if mode.upper() == "STRICT":
                raise ValueError(f"Symbol for {kind} {name} not found")
            continue
        block_text = module_text[b.start:b.end]
        new_block = _set_or_insert_ecu_address(block_text, getattr(sym, "address", 0))
        if scope.upper() == "ALL":
            if getattr(sym, "a2l_datatype", None):
                new_block = _set_or_insert_datatype(new_block, getattr(sym, "a2l_datatype"))
        out = out[:b.start] + new_block + out[b.end:]
        module_text = out
    return out


def _set_or_insert_ecu_address(block_text: str, address: int) -> str:
    hex_addr = f"0x{address:X}"
    patterns = [
        r'(?im)^(\s*ECU_ADDRESS\s+)(?:0x[0-9A-Fa-f]+|\d+)(\s*)$',
        r'(?im)^(\s*ADDRESS\s+)(?:0x[0-9A-Fa-f]+|\d+)(\s*)$',
    ]
    for pat in patterns:
        def repl(m: re.Match) -> str:
            return f"{m.group(1)}{hex_addr}{m.group(2)}"
        new_text, n = re.subn(pat, repl, block_text)
        if n > 0:
            return new_text
    indent = _detect_indent(block_text)
    insertion_line = f"{indent}ECU_ADDRESS {hex_addr}\n"
    end_idx = _find_last_end_index(block_text)
    if end_idx is None:
        return block_text + ("\n" if not block_text.endswith("\n") else "") + insertion_line
    return block_text[:end_idx] + insertion_line + block_text[end_idx:]


def _set_or_insert_datatype(block_text: str, a2l_datatype: str) -> str:
    pat = r'(?im)^(\s*DATA_TYPE\s+)([A-Za-z0-9_]+)(\s*)$'
    def repl(m: re.Match) -> str:
        return f"{m.group(1)}{a2l_datatype}{m.group(3)}"
    new_text, n = re.subn(pat, repl, block_text)
    if n > 0:
        return new_text
    return block_text


def _detect_indent(block_text: str) -> str:
    for line in block_text.splitlines():
        m = re.match(r'^(\s+)\S', line)
        if m:
            return m.group(1)
    return "  "


def _find_last_end_index(block_text: str) -> Optional[int]:
    m = list(re.finditer(r'(?im)^\s*/\s*end\b.*$', block_text))
    if not m:
        return None
    return m[-1].start()


class SymbolInfoLike:
    name: str
    address: int
    a2l_datatype: Optional[str] = None