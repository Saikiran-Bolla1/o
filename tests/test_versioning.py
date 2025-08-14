import pytest
from a2ltool.versioning import change_a2l_version, _parse_version
from a2ltool.a2l import A2LDocument


def test_parse_version():
    """Test version string parsing."""
    assert _parse_version("1.5.1") == (1, 51)
    assert _parse_version("1.6.0") == (1, 60)
    assert _parse_version("1.7") == (1, 70)
    assert _parse_version("2.0.1") == (2, 1)
    assert _parse_version("invalid") == (1, 71)  # fallback


def test_change_version():
    """Test changing A2L version."""
    content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/end PROJECT"""
    
    doc = A2LDocument(content)
    changed = change_a2l_version(doc, "1.5.1")
    
    changed_text = changed.to_text()
    assert "ASAP2_VERSION 1 51" in changed_text
    assert "a2ltool-py set version: 1.5.1" in changed_text


def test_version_downgrade_removes_features():
    """Test that version downgrade removes incompatible features."""
    content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/begin MODULE mod "Module"
  AXIS_PTS_X 1.0 2.0 3.0
  ANNOTATION_LABEL "Test"
/end MODULE
/end PROJECT"""
    
    doc = A2LDocument(content)
    changed = change_a2l_version(doc, "1.5.1")
    
    changed_text = changed.to_text()
    # These should be removed for older versions
    assert "AXIS_PTS_X" not in changed_text
    assert "ANNOTATION_LABEL" not in changed_text