from __future__ import annotations

import re
from typing import Optional

from .a2l import A2LDocument


def extract_xcp_info(doc: A2LDocument) -> Optional[str]:
    """Extract XCP connection parameters from A2L document."""
    text = doc.to_text()
    
    # Look for XCP IF_DATA blocks
    xcp_pattern = r'(?is)/begin\s+IF_DATA\s+XCP\s+(.*?)/end\s+IF_DATA'
    matches = re.findall(xcp_pattern, text)
    
    if not matches:
        return None
    
    xcp_info = []
    
    for match in matches:
        # Parse XCP parameters
        info = _parse_xcp_block(match)
        if info:
            xcp_info.append(info)
    
    if xcp_info:
        return "\n".join(xcp_info)
    
    return None


def _parse_xcp_block(xcp_text: str) -> Optional[str]:
    """Parse XCP IF_DATA block content."""
    lines = []
    
    # Extract protocol layer info
    protocol_layer = re.search(r'(?is)PROTOCOL_LAYER\s+(.*?)(?=\w+_LAYER|\Z)', xcp_text)
    if protocol_layer:
        protocol_content = protocol_layer.group(1)
        
        # Extract version
        version_match = re.search(r'(\d+\.\d+)', protocol_content)
        if version_match:
            lines.append(f"XCP Protocol Version: {version_match.group(1)}")
        
        # Extract byte order
        if 'MSB_FIRST' in protocol_content:
            lines.append("Byte Order: MSB_FIRST")
        elif 'MSB_LAST' in protocol_content:
            lines.append("Byte Order: MSB_LAST")
        
        # Extract max CTO
        max_cto_match = re.search(r'MAX_CTO\s+(\d+)', protocol_content)
        if max_cto_match:
            lines.append(f"Max CTO: {max_cto_match.group(1)}")
        
        # Extract max DTO
        max_dto_match = re.search(r'MAX_DTO\s+(\d+)', protocol_content)
        if max_dto_match:
            lines.append(f"Max DTO: {max_dto_match.group(1)}")
    
    # Extract DAQ layer info
    daq_layer = re.search(r'(?is)DAQ\s+(.*?)(?=\w+_LAYER|\Z)', xcp_text)
    if daq_layer:
        daq_content = daq_layer.group(1)
        
        # Extract dynamic mode
        if 'DYNAMIC' in daq_content:
            lines.append("DAQ Mode: DYNAMIC")
        elif 'STATIC' in daq_content:
            lines.append("DAQ Mode: STATIC")
        
        # Extract max DAQ
        max_daq_match = re.search(r'MAX_DAQ\s+(\d+)', daq_content)
        if max_daq_match:
            lines.append(f"Max DAQ: {max_daq_match.group(1)}")
        
        # Extract max event channels
        max_event_match = re.search(r'MAX_EVENT_CHANNEL\s+(\d+)', daq_content)
        if max_event_match:
            lines.append(f"Max Event Channels: {max_event_match.group(1)}")
    
    # Extract transport layer info
    transport_layer = re.search(r'(?is)TRANSPORT_LAYER\s+(.*?)$', xcp_text)
    if transport_layer:
        transport_content = transport_layer.group(1)
        
        # Extract transport type
        if 'CAN' in transport_content:
            lines.append("Transport: CAN")
            
            # Extract CAN ID
            can_id_master = re.search(r'CAN_ID_MASTER\s+0x([0-9A-Fa-f]+)', transport_content)
            if can_id_master:
                lines.append(f"CAN ID Master: 0x{can_id_master.group(1)}")
            
            can_id_slave = re.search(r'CAN_ID_SLAVE\s+0x([0-9A-Fa-f]+)', transport_content)
            if can_id_slave:
                lines.append(f"CAN ID Slave: 0x{can_id_slave.group(1)}")
            
            # Extract baudrate
            baudrate_match = re.search(r'BAUDRATE\s+(\d+)', transport_content)
            if baudrate_match:
                lines.append(f"Baudrate: {baudrate_match.group(1)}")
        
        elif 'ETHERNET' in transport_content:
            lines.append("Transport: ETHERNET")
            
            # Extract IP address
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', transport_content)
            if ip_match:
                lines.append(f"IP Address: {ip_match.group(1)}")
            
            # Extract port
            port_match = re.search(r'PORT\s+(\d+)', transport_content)
            if port_match:
                lines.append(f"Port: {port_match.group(1)}")
    
    return "\n".join(lines) if lines else None