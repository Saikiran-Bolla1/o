import pytest
from a2ltool.check import check_consistency
from a2ltool.a2l import A2LDocument


def test_check_valid_document():
    """Test consistency check on valid document."""
    content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/begin MODULE mod "Module"
/begin MEASUREMENT var "Variable"
  DATA_TYPE ULONG
/end MEASUREMENT
/end MODULE
/end PROJECT"""
    
    doc = A2LDocument(content)
    ok, report = check_consistency(doc)
    
    assert ok is True
    assert "passed" in report.lower()


def test_check_unbalanced_blocks():
    """Test consistency check on document with unbalanced blocks."""
    content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/begin MODULE mod "Module"
/begin MEASUREMENT var "Variable"
  DATA_TYPE ULONG
/end MEASUREMENT
/end MODULE
/* Missing /end PROJECT */"""
    
    doc = A2LDocument(content)
    ok, report = check_consistency(doc)
    
    assert ok is False
    assert "Unmatched" in report


def test_check_mismatched_blocks():
    """Test consistency check on document with mismatched blocks."""
    content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/begin MODULE mod "Module"
/end PROJECT
/end MODULE"""
    
    doc = A2LDocument(content)
    ok, report = check_consistency(doc)
    
    assert ok is False
    assert "Mismatched" in report


def test_check_duplicate_objects():
    """Test consistency check for duplicate objects."""
    content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/begin MODULE mod "Module"
/begin MEASUREMENT var "Variable 1"
  DATA_TYPE ULONG
/end MEASUREMENT
/begin MEASUREMENT var "Variable 2"
  DATA_TYPE ULONG
/end MEASUREMENT
/end MODULE
/end PROJECT"""
    
    doc = A2LDocument(content)
    ok, report = check_consistency(doc)
    
    assert ok is False
    assert "Duplicate" in report