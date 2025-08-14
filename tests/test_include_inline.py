import textwrap
from pathlib import Path

from a2ltool.a2l import A2LDocument


def test_inline_includes(tmp_path: Path):
    inc = tmp_path / "inc.a2l"
    inc.write_text('/begin COMPU_METHOD CM "" RAT_FUNC_32 1 0 0\n/end COMPU_METHOD\n')
    src = textwrap.dedent(f"""\
        /begin PROJECT P ""
          /begin MODULE M ""
          /end MODULE
        /end PROJECT

        include "{inc.name}"
    """)
    doc = A2LDocument(src).inline_includes(tmp_path)
    out = doc.to_text()
    assert "begin include" in out and "end include" in out
    assert "COMPU_METHOD CM" in out
