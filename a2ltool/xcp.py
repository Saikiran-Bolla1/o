from __future__ import annotations

import re
from typing import Dict, Optional

from .a2l import A2LDocument


def extract_xcp_info(doc: A2LDocument) -> Optional[str]:
    text = doc.to_text()
    blocks = A2LDocument(text)._scan_blocks()
    out = []
    for b in blocks:
        if b.kind.upper() == "IF_DATA":
            body = text[b.start:b.end]
            if re.search(r'(?im)^\s*XCP\b', body) or re.search(r'(?i)\bXCP\b', body):
                info = _extract_key_values(body)
                if info:
                    out.append("; ".join(f"{k}={v}" for k, v in info.items()))
    if out:
        return "XCP IF_DATA: " + " | ".join(out)
    return None


def _extract_key_values(body: str) -> Dict[str, str]:
    kvs: Dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("/*"):
            continue
        m = re.match(r'^([A-Za-z_][\w\.\-]*)\s+(?:"([^"]+)"|([^\s/][^\s]*))', line)
        if m:
            key = m.group(1)
            val = m.group(2) or m.group(3) or ""
            kvs[key] = val
    return kvs
