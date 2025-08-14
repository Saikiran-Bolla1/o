import textwrap
from a2ltool.a2l import A2LDocument
from a2ltool.merge import merge_a2l_files


def test_merge_dedup():
    a = textwrap.dedent("""\
        /begin PROJECT P ""
          /begin MODULE M ""
            /begin MEASUREMENT speed "" SLONG 1 0 0 0
              ECU_ADDRESS 0x1000
            /end MEASUREMENT
          /end MODULE
        /end PROJECT
    """)
    b = textwrap.dedent("""\
        /begin PROJECT P ""
          /begin MODULE M ""
            /begin MEASUREMENT speed "" SLONG 1 0 0 0
              ECU_ADDRESS 0x2000
            /end MEASUREMENT
            /begin MEASUREMENT rpm "" SLONG 1 0 0 0
              ECU_ADDRESS 0x2004
            /end MEASUREMENT
          /end MODULE
        /end PROJECT
    """)
    merged = A2LDocument(a).merge_with([A2LDocument(b)], mode="PRESERVE")
    out = merged.to_text()
    assert "ECU_ADDRESS 0x1000" in out
    assert "MEASUREMENT rpm" in out
