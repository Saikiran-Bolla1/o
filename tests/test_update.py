import textwrap
from dataclasses import dataclass
from pathlib import Path

from a2ltool.a2l import A2LDocument
from a2ltool.update import update_from_elf, UpdateScope, UpdateMode


@dataclass
class Sym:
    name: str
    address: int
    a2l_datatype: str | None = None


def test_update_addresses_and_types(monkeypatch, tmp_path: Path):
    a2l = textwrap.dedent("""\
        /begin PROJECT P ""
          /begin MODULE M ""
            /begin MEASUREMENT speed "" SLONG 1 0 0 0
              ECU_ADDRESS 0x0
            /end MEASUREMENT
            /begin MEASUREMENT temp "" SLONG 1 0 0 0
            /end MEASUREMENT
          /end MODULE
        /end PROJECT
    """)
    doc = A2LDocument(a2l)

    def fake_load(path):
        return {
            "speed": Sym("speed", 0x1234, "ULONG"),
            "temp": Sym("temp", 0x2000, "FLOAT32_IEEE"),
        }
    monkeypatch.setattr("a2ltool.update._load_symbols", lambda p: fake_load(p))

    updated = update_from_elf(doc, elf_path=tmp_path / "dummy.elf", scope=UpdateScope.ALL, mode=UpdateMode.PRESERVE)
    out = updated.to_text()
    assert "ECU_ADDRESS 0x1234" in out
    assert "ECU_ADDRESS 0x2000" in out
