import pytest
from pathlib import Path
from a2ltool.a2l import A2LDocument


def test_empty_document():
    """Test creating empty A2L document."""
    doc = A2LDocument.empty()
    assert doc.to_text() == ""


def test_read_write_document(tmp_path):
    """Test reading and writing A2L documents."""
    content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/end PROJECT"""
    
    test_file = tmp_path / "test.a2l"
    test_file.write_text(content)
    
    doc = A2LDocument.read(test_file)
    assert "ASAP2_VERSION 1 71" in doc.to_text()
    
    output_file = tmp_path / "output.a2l"
    doc.write(output_file)
    
    assert output_file.read_text() == content


def test_block_scanning():
    """Test A2L block scanning functionality."""
    content = """ASAP2_VERSION 1 71

/begin PROJECT test_project "Test project"
/begin MODULE test_module "Test module"

/begin MEASUREMENT test_var "Test measurement"
  DATA_TYPE ULONG
  ECU_ADDRESS 0x1000
/end MEASUREMENT

/end MODULE
/end PROJECT"""
    
    doc = A2LDocument(content)
    blocks = doc._scan_blocks()
    
    # Should find PROJECT, MODULE, and MEASUREMENT blocks
    assert len(blocks) >= 3
    
    project_blocks = [b for b in blocks if b.kind == "PROJECT"]
    assert len(project_blocks) == 1
    assert project_blocks[0].name == "test_project"
    
    module_blocks = [b for b in blocks if b.kind == "MODULE"]
    assert len(module_blocks) == 1
    assert module_blocks[0].name == "test_module"
    
    measurement_blocks = [b for b in blocks if b.kind == "MEASUREMENT"]
    assert len(measurement_blocks) == 1
    assert measurement_blocks[0].name == "test_var"


def test_merge_documents():
    """Test merging A2L documents."""
    doc1_content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/begin MODULE mod "Module"
/begin MEASUREMENT var1 "Variable 1"
  DATA_TYPE ULONG
/end MEASUREMENT
/end MODULE
/end PROJECT"""
    
    doc2_content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/begin MODULE mod "Module"
/begin MEASUREMENT var2 "Variable 2"
  DATA_TYPE UWORD
/end MEASUREMENT
/end MODULE
/end PROJECT"""
    
    doc1 = A2LDocument(doc1_content)
    doc2 = A2LDocument(doc2_content)
    
    merged = doc1.merge_with([doc2])
    merged_text = merged.to_text()
    
    # Should contain both measurements
    assert "var1" in merged_text
    assert "var2" in merged_text


def test_version_annotation():
    """Test version annotation functionality."""
    doc = A2LDocument("ASAP2_VERSION 1 71")
    annotated = doc.annotate_version("1.5.1")
    
    assert annotated.to_text().startswith("/* a2ltool-py set version: 1.5.1 */")
    
    # Should not double-annotate
    double_annotated = annotated.annotate_version("1.6.0")
    lines = double_annotated.to_text().split('\n')
    version_comments = [line for line in lines if line.startswith("/* a2ltool-py set version:")]
    assert len(version_comments) == 1