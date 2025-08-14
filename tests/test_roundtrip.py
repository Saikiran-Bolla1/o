import textwrap

from a2ltool.a2l import A2LDocument


def test_roundtrip_preserves_text():
    src = textwrap.dedent("""\
        /* comment */
        /begin PROJECT P ""
          /begin MODULE M ""
            /* inner comment */
            /begin MEASUREMENT speed "" SLONG 1 0 0 0
              ECU_ADDRESS 0x1000
            /end MEASUREMENT
          /end MODULE
        /end PROJECT
    """)
    doc = A2LDocument(src)
    assert doc.to_text() == src
