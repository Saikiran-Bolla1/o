import textwrap

from a2ltool.a2l import A2LDocument
from a2ltool.xcp import extract_xcp_info


def test_xcp_info():
    a2l = textwrap.dedent("""\
        /begin PROJECT P ""
          /begin MODULE M ""
            /begin IF_DATA XCP
              TRANSPORT_LAYER CAN
              DAQ_MEM_SIZE 4096
            /end IF_DATA
          /end MODULE
        /end PROJECT
    """)
    doc = A2LDocument(a2l)
    info = extract_xcp_info(doc)
    assert info and "XCP" in info and "DAQ_MEM_SIZE=4096" in info
