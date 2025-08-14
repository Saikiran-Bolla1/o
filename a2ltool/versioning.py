from __future__ import annotations

import re
from typing import List

from .a2l import A2LDocument


def change_a2l_version(doc: A2LDocument, target_version: str) -> A2LDocument:
    """Change A2L version and remove incompatible elements."""
    text = doc.to_text()
    
    # Update ASAP2_VERSION declaration
    version_pattern = r'(?im)^(\s*ASAP2_VERSION\s+)\d+\s+\d+(\s*)$'
    major, minor = _parse_version(target_version)
    
    def replace_version(match):
        return f"{match.group(1)}{major} {minor}{match.group(2)}"
    
    text = re.sub(version_pattern, replace_version, text)
    
    # Remove version-incompatible elements
    text = _remove_incompatible_elements(text, target_version)
    
    # Add version annotation
    result_doc = A2LDocument(text)
    return result_doc.annotate_version(target_version)


def _parse_version(version_str: str) -> tuple[int, int]:
    """Parse version string like '1.5.1' into major/minor numbers."""
    parts = version_str.split('.')
    if len(parts) >= 2:
        try:
            major = int(parts[0])
            minor = int(parts[1])
            return major, minor * 10 + (int(parts[2]) if len(parts) > 2 else 0)
        except ValueError:
            pass
    # Default fallback
    return 1, 71


def _remove_incompatible_elements(text: str, target_version: str) -> str:
    """Remove elements that are incompatible with target version."""
    # This is a simplified implementation
    # In practice, you'd have detailed compatibility rules
    
    major, minor = _parse_version(target_version)
    
    if major == 1 and minor < 60:
        # Remove newer A2L 1.6+ features
        incompatible_keywords = [
            'AXIS_PTS_X', 'AXIS_PTS_Y', 'AXIS_PTS_Z',
            'ANNOTATION_LABEL', 'ANNOTATION_ORIGIN',
            'CALIBRATION_ACCESS', 'DISPLAY_IDENTIFIER',
        ]
        
        for keyword in incompatible_keywords:
            # Remove lines containing these keywords
            pattern = rf'(?im)^\s*{re.escape(keyword)}\b.*$'
            text = re.sub(pattern, '', text)
    
    if major == 1 and minor < 51:
        # Remove A2L 1.5.1+ features
        incompatible_keywords = [
            'VIRTUAL_CHARACTERISTIC', 'TYPEDEF_CHARACTERISTIC',
            'TYPEDEF_MEASUREMENT', 'TYPEDEF_AXIS',
        ]
        
        for keyword in incompatible_keywords:
            pattern = rf'(?im)^\s*{re.escape(keyword)}\b.*$'
            text = re.sub(pattern, '', text)
    
    return text