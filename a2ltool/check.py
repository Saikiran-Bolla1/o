from __future__ import annotations

import re
from typing import Tuple

from .a2l import A2LDocument, MERGE_OBJECT_KINDS


def check_consistency(doc: A2LDocument, strict: bool) -> Tuple[bool, str]:
    text = doc.to_text()
    ok = True
    report_lines = []

    begin_kinds = re.findall(r'(?im)^\s*/\s*begin\s+([A-Za-z_][\w\.\-]*)\b', text)
    end_kinds = re.findall(r'(?im)^\s*/\s*end\s+([A-Za-z_][\w\.\-]*)\b', text)
    from collections import Counter
    cb = Counter(k.upper() for k in begin_kinds)
    ce = Counter(k.upper() for k in end_kinds)
    allk = set(cb) | set(ce)
    for k in sorted(allk):
        if cb[k] != ce[k]:
            ok = False
            report_lines.append(f"Mismatch for {k}: /begin={cb[k]} /end={ce[k]}")

    modules = A2LDocument(text)._find_modules()
    for m in modules:
        mod_text = text[m.start:m.end]
        inner = A2LDocument(mod_text)._scan_blocks()
        seen = set()
        for b in inner:
            if b.kind.upper() in MERGE_OBJECT_KINDS:
                key = (b.kind.upper(), b.name)
                if key in seen:
                    ok = False
                    report_lines.append(f"Duplicate {key[0]} {key[1]} in MODULE {m.name}")
                else:
                    seen.add(key)

    compu_methods = set(b.name for b in A2LDocument(text)._scan_blocks() if b.kind.upper() == "COMPU_METHOD")
    meas_blocks = [b for b in A2LDocument(text)._scan_blocks() if b.kind.upper() == "MEASUREMENT"]
    for b in meas_blocks:
        body = text[b.start:b.end]
        m = re.search(r'(?im)^\s*COMPU_METHOD\s+([A-Za-z_][\w\.\-]*)\b', body)
        if m:
            cm = m.group(1)
            if cm not in compu_methods:
                ok = False
                report_lines.append(f"MEASUREMENT {b.name} references missing COMPU_METHOD {cm}")

    report = "OK" if ok else "\n".join(report_lines) if report_lines else "Inconsistencies found."
    return (ok or not strict), report
