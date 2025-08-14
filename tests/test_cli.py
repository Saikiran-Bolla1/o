import pytest
from pathlib import Path
from a2ltool.cli import main


def test_cli_help():
    """Test CLI help command."""
    # Help command raises SystemExit
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_cli_check(tmp_path):
    """Test CLI check command."""
    content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/end PROJECT"""
    
    test_file = tmp_path / "test.a2l"
    test_file.write_text(content)
    
    result = main([str(test_file), "--check"])
    assert result == 0


def test_cli_version_change(tmp_path):
    """Test CLI version change command."""
    content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/end PROJECT"""
    
    test_file = tmp_path / "test.a2l"
    test_file.write_text(content)
    
    output_file = tmp_path / "output.a2l"
    
    result = main([str(test_file), "--a2lversion", "1.5.1", "-o", str(output_file)])
    assert result == 0
    
    output_content = output_file.read_text()
    assert "ASAP2_VERSION 1 51" in output_content
    assert "a2ltool-py set version: 1.5.1" in output_content


def test_cli_create_missing_elffile():
    """Test CLI create command without ELF file."""
    result = main(["--create"])
    assert result == 2  # Should return error code


def test_cli_update_missing_elffile(tmp_path):
    """Test CLI update command without ELF file."""
    content = """ASAP2_VERSION 1 71
/begin PROJECT test "Test"
/end PROJECT"""
    
    test_file = tmp_path / "test.a2l"
    test_file.write_text(content)
    
    result = main([str(test_file), "--update"])
    assert result == 2  # Should return error code


def test_cli_missing_input():
    """Test CLI without input file and without --create."""
    result = main([])
    assert result == 2  # Should return error code