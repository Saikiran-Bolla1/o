from __future__ import annotations

import re
from typing import List, Tuple

from .a2l import A2LDocument


def check_consistency(doc: A2LDocument, strict: bool = False) -> Tuple[bool, str]:
    """Check A2L document for consistency issues."""
    issues: List[str] = []
    
    text = doc.to_text()
    
    # Check BEGIN/END balance
    begin_end_issues = _check_begin_end_balance(text)
    issues.extend(begin_end_issues)
    
    # Check for duplicate objects
    duplicate_issues = _check_duplicates(doc)
    issues.extend(duplicate_issues)
    
    # Check basic reference validation
    if strict:
        ref_issues = _check_references(text)
        issues.extend(ref_issues)
    
    # Generate report
    if issues:
        report = "Consistency check failed:\n" + "\n".join(f"  - {issue}" for issue in issues)
        return False, report
    else:
        return True, "Consistency check passed."


def _check_begin_end_balance(text: str) -> List[str]:
    """Check if BEGIN and END blocks are properly balanced."""
    issues = []
    
    begin_pattern = re.compile(r'(?im)^\s*/\s*begin\s+([A-Za-z_][\w\.-]*)')
    end_pattern = re.compile(r'(?im)^\s*/\s*end\s+([A-Za-z_][\w\.-]*)')
    
    stack = []
    
    for line_num, line in enumerate(text.split('\n'), 1):
        begin_match = begin_pattern.match(line)
        if begin_match:
            block_type = begin_match.group(1).upper()
            stack.append((block_type, line_num))
            continue
        
        end_match = end_pattern.match(line)
        if end_match:
            block_type = end_match.group(1).upper()
            if not stack:
                issues.append(f"Unmatched /end {block_type} at line {line_num}")
            else:
                expected_type, begin_line = stack.pop()
                if expected_type != block_type:
                    issues.append(f"Mismatched /end {block_type} at line {line_num}, expected {expected_type} from line {begin_line}")
    
    # Check for unmatched begins
    for block_type, line_num in stack:
        issues.append(f"Unmatched /begin {block_type} at line {line_num}")
    
    return issues


def _check_duplicates(doc: A2LDocument) -> List[str]:
    """Check for duplicate object definitions within modules."""
    issues = []
    
    modules = doc._find_modules()
    for module in modules:
        module_text = doc.to_text()[module.start:module.end]
        inner_blocks = doc._scan_blocks(text=doc.to_text(), region=(module.header_end, module.end))
        
        seen_objects = {}
        for block in inner_blocks:
            key = (block.kind.upper(), block.name)
            if key in seen_objects:
                issues.append(f"Duplicate {block.kind} '{block.name}' in MODULE '{module.name}'")
            else:
                seen_objects[key] = block
    
    return issues


def _check_references(text: str) -> List[str]:
    """Basic reference validation (strict mode only)."""
    issues = []
    
    # This is a placeholder for more sophisticated reference checking
    # In a full implementation, this would check:
    # - COMPU_METHOD references
    # - RECORD_LAYOUT references  
    # - Function parameter references
    # etc.
    
    return issues