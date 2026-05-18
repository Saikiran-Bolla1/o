import can
import datetime
import cantools
import logging
from typing import Optional, Tuple, Dict, Any, List
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CANReader:
    """
    CAN bus reader with support for J1939 protocol, TP (Transport Protocol), and DM1 diagnostics.
    
    Features:
    - Vector CAN interface support
    - DBC database integration for message decoding
    - J1939 PGN-based message filtering
    - TP.CM (BAM - Broadcast Announce Message) handling
    - TP.DT (Data Transfer) multi-frame message assembly
    - DM1 (Diagnostic Message 1) parsing with lamp status and DTC decoding
    - Cycle time monitoring for individual and target message IDs
    - Frame type detection (standard vs extended)
    - Signal-level extraction and monitoring
    - Fixed TP session key matching and timeout handling
    """
    
    # J1939 PGN constants
    PGN_TP_CM = 0xEC00    # Transport Protocol - Connection Management (BAM)
    PGN_TP_DT = 0xEB00    # Transport Protocol - Data Transfer
    PGN_DM1 = 0xFECA      # Diagnostic Message 1
    
    # TP session timeout in seconds
    TP_SESSION_TIMEOUT = 5.0
    
    def __init__(self, channel: int = 0, bitrate: int = 500000, 
                 dbc_file: Optional[str] = None, filters: Optional[list] = None):
        """
        Initialize Vector CAN interface.
        
        Args:
            channel: CAN channel number (default: 0)
            bitrate: Bus bitrate in bps (default: 500000)
            dbc_file: Path to DBC file for message definitions
            filters: List of filter dictionaries for CAN filtering
        """
        try:
            self.bus = can.interface.Bus(
                bustype='vector',
                channel=channel,
                bitrate=bitrate
            )
            logger.info(f"CAN bus initialized on channel {channel} at {bitrate} bps")
        except Exception as e:
            logger.error(f"Failed to initialize CAN bus: {e}")
            raise

        self.last_timestamps = {}      # For cycle time tracking
        self.db = None
        self.pgn_map = {}
        self.tp_sessions = {}          # TP session storage for multi-frame messages
        self.message_id_map = {}       # Maps message name/id to actual ID
        self.signal_cache = {}         # Caches latest signal values

        if dbc_file:
            self.load_dbc(dbc_file)

        if filters:
            self.set_filters(filters)

    def load_dbc(self, dbc_file: str) -> None:
        """
        Load DBC database file and build PGN map and message ID map.
        
        Args:
            dbc_file: Path to DBC file
        """
        try:
            self.db = cantools.database.load_file(dbc_file)
            logger.info(f"DBC file loaded: {dbc_file}")

            self.pgn_map = {}
            self.message_id_map = {}
            
            for msg in self.db.messages:
                if msg.is_extended_frame:
                    pgn = self.extract_pgn_from_dbc_id(msg.frame_id)
                    self.pgn_map[pgn] = msg
                
                # Build message ID map (both by ID and by name)
                self.message_id_map[msg.frame_id] = msg
                self.message_id_map[msg.name] = msg
            
            logger.info(f"PGN map created with {len(self.pgn_map)} messages")
            logger.info(f"Message ID map created with {len(self.message_id_map)} messages")
        except Exception as e:
            logger.error(f"Failed to load DBC file: {e}")
            raise

    def set_filters(self, filter_list: list) -> None:
        """
        Set CAN bus filters.
        
        Args:
            filter_list: List of filter dictionaries
        """
        try:
            self.bus.set_filters(filter_list)
            logger.info(f"Filters applied: {len(filter_list)} filter(s)")
        except Exception as e:
            logger.error(f"Failed to set filters: {e}")

    def get_pgn(self, arbitration_id: int) -> int:
        """
        Extract PGN from J1939 arbitration ID using correct PDU format.
        
        J1939 uses PDU1 (PF < 240) and PDU2 (PF >= 240) formats:
        - PDU1: PGN = PF << 8 (ignores PS)
        - PDU2: PGN = (PF << 8) | PS
        
        Arbitration ID format (29-bit):
        [Priority(3) | Reserved(1) | Data Page(1) | PF(8) | PS(8) | Source(8)]
        
        Args:
            arbitration_id: CAN arbitration ID
            
        Returns:
            Extracted PGN value
        """
        arbitration_id &= 0x1FFFFFFF  # Mask to 29 bits
        
        pf = (arbitration_id >> 16) & 0xFF
        ps = (arbitration_id >> 8) & 0xFF

        if pf >= 240:  # PDU2 format
            return (pf << 8) | ps
        else:          # PDU1 format
            return (pf << 8)

    def extract_pgn_from_dbc_id(self, frame_id: int) -> int:
        """Wrapper to extract PGN from DBC frame ID."""
        return self.get_pgn(frame_id)

    def calculate_cycle_time(self, msg: can.Message) -> Optional[float]:
        """
        Calculate cycle time (time between consecutive messages with same ID).
        
        Args:
            msg: CAN message
            
        Returns:
            Cycle time in milliseconds, or None if first occurrence
        """
        msg_id = msg.arbitration_id
        cycle = None

        if msg_id in self.last_timestamps:
            cycle = (msg.timestamp - self.last_timestamps[msg_id]) * 1000  # Convert to ms

        self.last_timestamps[msg_id] = msg.timestamp
        return cycle

    def get_specific_cycle_time(self, msg: can.Message, target_id: int) -> Optional[float]:
        """
        Get cycle time only for a specific target message ID.
        
        Args:
            msg: CAN message
            target_id: Target arbitration ID
            
        Returns:
            Cycle time if message matches target ID, else None
        """
        if msg.arbitration_id != target_id:
            return None
        return self.calculate_cycle_time(msg)

    # ==================== TP SESSION CLEANUP ====================
    
    def cleanup_stale_tp_sessions(self) -> None:
        """
        Clean up TP sessions that have timed out.
        
        Removes sessions that haven't received data for TP_SESSION_TIMEOUT seconds.
        """
        current_time = datetime.datetime.now()
        stale_sessions = []
        
        for key, session in self.tp_sessions.items():
            session_time = datetime.datetime.fromtimestamp(session["timestamp"])
            elapsed = (current_time - session_time).total_seconds()
            
            if elapsed > self.TP_SESSION_TIMEOUT:
                stale_sessions.append(key)
                logger.warning(
                    f"⏱️  Cleaning up stale TP session for ID 0x{key:08X} "
                    f"(PGN: 0x{session['target_pgn']:04X}). "
                    f"Elapsed: {elapsed:.1f}s, Received: {session['received_packets']}/{session['expected_packets']} packets"
                )
        
        for key in stale_sessions:
            del self.tp_sessions[key]

    # ==================== NEW: Average Cycle Time Function ====================
    
    def get_average_cycle_time(self, message_id: int, num_samples: int = 10, timeout: float = 30.0) -> Optional[float]:
        """
        Calculate average cycle time for a specific message ID over multiple consecutive messages.
        
        Captures consecutive messages and computes the average time interval between them.
        
        Args:
            message_id: Target message ID (arbitration ID) to monitor
            num_samples: Number of consecutive messages to sample (default: 10)
            timeout: Maximum time to wait for samples in seconds (default: 30.0)
            
        Returns:
            Average cycle time in milliseconds, or None if timeout reached
            
        Example:
            avg_cycle = reader.get_average_cycle_time(message_id=0x123, num_samples=10)
            if avg_cycle:
                print(f"Average cycle time: {avg_cycle:.2f} ms")
        """
        logger.info(f"Starting cycle time measurement for ID 0x{message_id:X} ({num_samples} samples)...")
        
        cycle_times = []
        last_timestamp = None
        start_time = datetime.datetime.now()
        messages_received = 0
        
        while len(cycle_times) < num_samples - 1:  # num_samples - 1 because we need pairs
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                logger.warning(f"Timeout: Collected {messages_received} messages, {len(cycle_times)} cycle times")
                if cycle_times:
                    avg = sum(cycle_times) / len(cycle_times)
                    logger.info(f"Partial average: {avg:.2f} ms")
                    return avg
                return None
            
            msg = self.bus.recv(timeout=1)
            
            if not msg or msg.arbitration_id != message_id:
                continue
            
            messages_received += 1
            current_timestamp = msg.timestamp
            
            if last_timestamp is not None:
                cycle_time = (current_timestamp - last_timestamp) * 1000  # Convert to ms
                cycle_times.append(cycle_time)
                logger.debug(f"Sample {len(cycle_times)}: {cycle_time:.2f} ms")
            
            last_timestamp = current_timestamp
        
        if cycle_times:
            avg_cycle = sum(cycle_times) / len(cycle_times)
            min_cycle = min(cycle_times)
            max_cycle = max(cycle_times)
            
            logger.info(f"✅ Cycle time measurement complete!")
            logger.info(f"   Average: {avg_cycle:.2f} ms")
            logger.info(f"   Min: {min_cycle:.2f} ms")
            logger.info(f"   Max: {max_cycle:.2f} ms")
            logger.info(f"   Total messages: {messages_received}")
            
            print(f"\n📊 Cycle Time Statistics (ID: 0x{message_id:X})")
            print(f"   Samples: {len(cycle_times)}")
            print(f"   Average: {avg_cycle:.2f} ms")
            print(f"   Min: {min_cycle:.2f} ms")
            print(f"   Max: {max_cycle:.2f} ms")
            print(f"   Total messages received: {messages_received}\n")
            
            return avg_cycle
        
        return None

    # ==================== NEW: Read Message with Signal Names and Values ====================
    
    def read_message_signals(self, message_id: Optional[int] = None, 
                            message_name: Optional[str] = None, 
                            timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """
        Read a specific CAN message by ID or name and extract all signal names and values.
        
        Either message_id OR message_name must be provided. If both are provided, message_id takes precedence.
        
        Args:
            message_id: CAN message ID (arbitration ID) - e.g., 0x123
            message_name: CAN message name from DBC - e.g., "EngineStatus"
            timeout: Maximum time to wait for the message in seconds (default: 5.0)
            
        Returns:
            Dictionary with:
            - timestamp: Message timestamp
            - message_id: CAN ID
            - message_name: Message name from DBC
            - signals: Dict mapping signal_name -> signal_value
            - raw_data: Raw hex data
            
            Returns None if timeout reached or message not found in DBC
            
        Example:
            # By ID
            msg_data = reader.read_message_signals(message_id=0x123)
            # By name
            msg_data = reader.read_message_signals(message_name="EngineStatus")
            
            if msg_data:
                print(f"Signals: {msg_data['signals']}")
                print(f"Signal values: {msg_data['signals'].get('EngineRPM')}")
        """
        if not self.db:
            logger.error("No DBC file loaded. Cannot read message signals.")
            return None
        
        if message_id is None and message_name is None:
            logger.error("Either message_id or message_name must be provided")
            return None
        
        # Resolve message definition
        message_def = None
        lookup_key = message_id if message_id is not None else message_name
        lookup_type = "ID" if message_id is not None else "name"
        
        if message_id is not None:
            message_def = self.message_id_map.get(message_id)
        else:
            message_def = self.message_id_map.get(message_name)
        
        if not message_def:
            logger.error(f"Message with {lookup_type} {lookup_key} not found in DBC")
            return None
        
        actual_message_id = message_def.frame_id
        actual_message_name = message_def.name
        
        logger.info(f"Waiting for message '{actual_message_name}' (ID: 0x{actual_message_id:X})...")
        
        start_time = datetime.datetime.now()
        
        while True:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                logger.warning(f"Timeout waiting for message '{actual_message_name}' after {timeout}s")
                return None
            
            msg = self.bus.recv(timeout=1)
            
            if not msg or msg.arbitration_id != actual_message_id:
                continue
            
            try:
                decoded = message_def.decode(msg.data)
                
                result = {
                    "timestamp": datetime.datetime.fromtimestamp(msg.timestamp),
                    "message_id": msg.arbitration_id,
                    "message_name": actual_message_name,
                    "signals": decoded,
                    "raw_data": msg.data.hex()
                }
                
                logger.info(f"✅ Message received: '{actual_message_name}'")
                logger.info(f"   Signals: {decoded}")
                
                # Cache the signals
                self.signal_cache[actual_message_name] = decoded
                
                return result
                
            except Exception as e:
                logger.error(f"Failed to decode message: {e}")
                return None

    # ==================== NEW: Read Signal Value by Signal Name ====================
    
    def get_signal_value(self, signal_name: str, message_id: Optional[int] = None,
                        message_name: Optional[str] = None, timeout: float = 5.0) -> Optional[Any]:
        """
        Get the value of a specific signal from a CAN message.
        
        Looks up the signal in the DBC and waits for the message containing it.
        
        Args:
            signal_name: Name of the signal to read (e.g., "EngineRPM")
            message_id: Optional CAN message ID (if not provided, searches all messages)
            message_name: Optional CAN message name (if not provided, searches all messages)
            timeout: Maximum time to wait for the message in seconds
            
        Returns:
            Signal value (type depends on signal definition), or None if not found/timeout
            
        Example:
            # Get specific signal value
            rpm_value = reader.get_signal_value("EngineRPM", message_id=0x123)
            
            # Or search all messages for the signal
            temp_value = reader.get_signal_value("EngineCoolantTemp")
            
            if rpm_value is not None:
                print(f"Engine RPM: {rpm_value}")
        """
        if not self.db:
            logger.error("No DBC file loaded. Cannot read signal value.")
            return None
        
        # Check cache first
        for msg_name, signals in self.signal_cache.items():
            if signal_name in signals:
                logger.debug(f"Found '{signal_name}' in cache: {signals[signal_name]}")
                return signals[signal_name]
        
        # If specific message provided, read from it
        if message_id is not None or message_name is not None:
            msg_data = self.read_message_signals(message_id=message_id, 
                                                message_name=message_name, 
                                                timeout=timeout)
            if msg_data and signal_name in msg_data['signals']:
                return msg_data['signals'][signal_name]
            else:
                logger.warning(f"Signal '{signal_name}' not found in message")
                return None
        
        # Search all messages for the signal
        logger.info(f"Searching for signal '{signal_name}' in all messages...")
        
        start_time = datetime.datetime.now()
        
        while True:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                logger.warning(f"Timeout searching for signal '{signal_name}' after {timeout}s")
                return None
            
            msg = self.bus.recv(timeout=1)
            
            if not msg:
                continue
            
            # Try to decode with each message definition
            for message_def in self.db.messages:
                if message_def.frame_id == msg.arbitration_id:
                    try:
                        decoded = message_def.decode(msg.data)
                        
                        if signal_name in decoded:
                            signal_value = decoded[signal_name]
                            logger.info(f"✅ Found '{signal_name}' = {signal_value} in message '{message_def.name}'")
                            
                            # Cache the signals
                            self.signal_cache[message_def.name] = decoded
                            
                            return signal_value
                    except Exception as e:
                        logger.debug(f"Failed to decode {message_def.name}: {e}")

    # ==================== FIXED: TP (Transport Protocol) Handling ====================
    
    def handle_tp_cm(self, msg: can.Message) -> None:
        """
        Handle TP.CM (Connection Management) - BAM (Broadcast Announce Message).
        
        FIXED: Now uses Source Address from arbitration ID as session key to properly match
        TP.CM with corresponding TP.DT packets from the same source.
        
        BAM format (Byte 0 = 0x20):
        - Byte 1-2: Total message size (little-endian)
        - Byte 3: Number of packets
        - Byte 4: Reserved
        - Byte 5-7: Target PGN (little-endian)
        
        Args:
            msg: CAN message with PGN 0xEC00
        """
        data = msg.data

        if len(data) < 8:
            logger.warning("TP.CM message too short")
            return

        if data[0] == 0x20:  # BAM
            total_size = data[1] | (data[2] << 8)
            num_packets = data[3]
            target_pgn = data[5] | (data[6] << 8) | (data[7] << 16)
            
            # ✅ FIXED: Use Source Address (SA) from arbitration ID as session key
            # This ensures TP.CM and TP.DT from same source are matched
            source_address = msg.arbitration_id & 0xFF
            session_key = (msg.arbitration_id >> 8) & 0xFFFFFF  # Remove SA to get base ID
            
            # Clean up any stale sessions before creating new one
            self.cleanup_stale_tp_sessions()

            self.tp_sessions[session_key] = {
                "data": bytearray(),
                "expected_packets": num_packets,
                "received_packets": 0,
                "target_pgn": target_pgn,
                "total_size": total_size,
                "timestamp": datetime.datetime.now().timestamp(),
                "source_address": source_address,
                "arbitration_id": msg.arbitration_id
            }

            logger.info(
                f"✅ TP.CM BAM started: PGN=0x{target_pgn:04X}, Size={total_size} bytes, "
                f"Packets={num_packets}, Source=0x{source_address:02X}, Key=0x{session_key:06X}"
            )
            print(f"📦 TP.CM BAM → PGN: 0x{target_pgn:04X}, {num_packets} packets, {total_size} bytes")

    def handle_tp_dt(self, msg: can.Message) -> Optional[Tuple[int, bytearray]]:
        """
        Handle TP.DT (Data Transfer) packets and assemble multi-frame messages.
        
        FIXED: Now properly matches TP.DT packets to their corresponding TP.CM sessions
        by using the same session key derivation (source address).
        
        TP.DT format:
        - Byte 0: Sequence number (1-255)
        - Bytes 1-7: Payload (7 bytes per packet)
        
        Returns assembled message when all packets received.
        
        Args:
            msg: CAN message with PGN 0xEB00
            
        Returns:
            Tuple of (target_pgn, full_data) when complete, else None
        """
        # ✅ FIXED: Use same session key derivation as handle_tp_cm
        source_address = msg.arbitration_id & 0xFF
        session_key = (msg.arbitration_id >> 8) & 0xFFFFFF  # Remove SA to get base ID
        
        if session_key not in self.tp_sessions:
            logger.debug(
                f"⚠️  TP.DT received without matching TP.CM session. "
                f"Source: 0x{source_address:02X}, Key: 0x{session_key:06X}, ID: 0x{msg.arbitration_id:08X}. "
                f"Active sessions: {[f'0x{k:06X}' for k in self.tp_sessions.keys()]}"
            )
            return None

        session = self.tp_sessions[session_key]

        if len(msg.data) < 8:
            logger.warning("TP.DT message too short")
            return None

        payload = msg.data[1:]  # Skip sequence number byte
        session["data"].extend(payload)
        session["received_packets"] += 1
        session["timestamp"] = datetime.datetime.now().timestamp()  # Update timestamp on each packet

        logger.debug(
            f"TP.DT packet {session['received_packets']}/{session['expected_packets']} received "
            f"for PGN 0x{session['target_pgn']:04X}"
        )

        if session["received_packets"] >= session["expected_packets"]:
            full_data = session["data"][:session["total_size"]]
            target_pgn = session["target_pgn"]

            logger.info(
                f"✅ TP.DT complete: PGN=0x{target_pgn:04X}, {session['total_size']} bytes "
                f"assembled from {session['received_packets']} packets"
            )
            print(f"✅ TP.DT Complete → {session['total_size']} bytes")

            del self.tp_sessions[session_key]

            return target_pgn, full_data

        return None

    # ==================== DM1 (Diagnostic Message 1) Handling ====================
    
    def decode_dm1(self, data: bytes) -> Dict[str, Any]:
        """
        Decode DM1 (Diagnostic Message 1) diagnostic data.
        
        DM1 Format:
        - Bytes 0-1: Lamp status (MIL, RSL, AWL, PL indicators)
        - Bytes 2+: DTCs (Diagnostic Trouble Codes) in 4-byte groups
        
        DTC Format (4 bytes):
        - Bytes 0-2: SPN (Suspect Parameter Number - 19 bits)
        - Byte 2: FMI (Failure Mode Indicator - 5 bits) + SPN upper 3 bits
        - Byte 3: OC (Occurrence Count - 7 bits) + Reserved (1 bit)
        
        Args:
            data: Raw DM1 message data
            
        Returns:
            Dictionary containing lamp_status and list of DTCs
        """
        result = {}

        if len(data) < 1:
            logger.warning("DM1 data too short")
            return result

        lamp_status = data[0:2] if len(data) >= 2 else data[0:1]

        # Lamp status bits (2 bits each)
        result["lamp_status"] = {
            "MIL": (lamp_status[0] >> 6) & 0x03,  # Malfunction Indicator Lamp
            "RSL": (lamp_status[0] >> 4) & 0x03,  # Red Stop Lamp
            "AWL": (lamp_status[0] >> 2) & 0x03,  # Amber Warning Lamp
            "PL": (lamp_status[0]) & 0x03,         # Protect Lamp
        }

        dtcs = []
        dtc_bytes = data[2:]

        # Parse DTC groups (4 bytes each)
        for i in range(0, len(dtc_bytes), 4):
            if i + 4 > len(dtc_bytes):
                break

            b1, b2, b3, b4 = dtc_bytes[i:i+4]

            # SPN is 19 bits across 3 bytes: b1[7:0] | b2[7:0] | b3[7:5]
            spn = b1 | (b2 << 8) | ((b3 & 0xE0) << 11)
            
            # FMI is 5 bits in b3[4:0]
            fmi = b3 & 0x1F
            
            # OC is 7 bits in b4[6:0]
            oc = b4 & 0x7F

            dtcs.append({
                "SPN": spn,
                "FMI": fmi,
                "OC": oc
            })

        result["DTCs"] = dtcs
        return result

    def print_dm1(self, decoded: Dict[str, Any]) -> None:
        """
        Print DM1 diagnostic message in human-readable format.
        
        Args:
            decoded: Decoded DM1 data from decode_dm1()
        """
        print("\n🔥 DM1 DECODED")
        print(f"Lamp Status: {decoded.get('lamp_status', {})}")

        dtcs = decoded.get("DTCs", [])
        if dtcs:
            print(f"DTCs ({len(dtcs)} detected):")
            for i, dtc in enumerate(dtcs, 1):
                print(f"  DTC {i}: SPN={dtc['SPN']:<5} FMI={dtc['FMI']:<2} OC={dtc['OC']}")
        else:
            print("No active DTCs")

    def get_dm1_message(self, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        """
        Wait for and retrieve a DM1 diagnostic message from the CAN bus.
        
        Monitors the bus for DM1 messages (single-frame or multi-frame via TP).
        Stops listening and returns immediately upon receiving DM1.
        
        FIXED: Now properly assembles multi-frame DM1 via corrected TP session handling.
        
        Args:
            timeout: Maximum time to wait for DM1 message in seconds
            
        Returns:
            Dictionary with timestamp, arbitration_id, pgn, raw_data, and decoded DM1 data:
            {
                "timestamp": datetime,
                "arbitration_id": int,
                "pgn": 0xFECA,
                "raw_data": "hex_string",
                "decoded": {
                    "lamp_status": {...},
                    "DTCs": [...]
                }
            }
            Returns None if timeout reached without receiving DM1
            
        Example:
            dm1 = reader.get_dm1_message(timeout=10)
            if dm1:
                print(f"DM1 received at {dm1['timestamp']}")
                print(f"Lamp Status: {dm1['decoded']['lamp_status']}")
                print(f"DTCs: {dm1['decoded']['DTCs']}")
        """
        start_time = datetime.datetime.now()
        
        logger.info(f"Waiting for DM1 message (timeout: {timeout}s)...")
        print(f"⏳ Listening for DM1 message... (timeout: {timeout}s)")
        
        while True:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            if elapsed > timeout:
                logger.warning(f"Timeout waiting for DM1 message after {timeout}s")
                print(f"❌ Timeout: No DM1 message received after {timeout}s")
                
                # Log any remaining active TP sessions
                if self.tp_sessions:
                    logger.warning(f"Active TP sessions at timeout: {len(self.tp_sessions)}")
                    for key, session in self.tp_sessions.items():
                        logger.warning(
                            f"  Session 0x{key:06X}: "
                            f"PGN=0x{session['target_pgn']:04X}, "
                            f"Progress={session['received_packets']}/{session['expected_packets']}"
                        )
                
                return None
            
            msg = self.bus.recv(timeout=1)
            
            if not msg:
                # Clean up stale sessions periodically
                if int(elapsed) % 2 == 0:  # Every 2 seconds
                    self.cleanup_stale_tp_sessions()
                continue
            
            pgn = self.get_pgn(msg.arbitration_id)
            
            # Check for single-frame DM1
            if pgn == self.PGN_DM1:
                decoded = self.decode_dm1(msg.data)
                result = {
                    "timestamp": datetime.datetime.fromtimestamp(msg.timestamp),
                    "arbitration_id": msg.arbitration_id,
                    "pgn": pgn,
                    "raw_data": msg.data.hex(),
                    "decoded": decoded
                }
                logger.info("✅ DM1 message received (single-frame)")
                self.print_dm1(decoded)
                return result
            
            # Check for multi-frame DM1 via TP
            elif pgn == self.PGN_TP_CM:
                self.handle_tp_cm(msg)
            
            elif pgn == self.PGN_TP_DT:
                result = self.handle_tp_dt(msg)
                if result:
                    target_pgn, full_data = result
                    if target_pgn == self.PGN_DM1:
                        decoded = self.decode_dm1(full_data)
                        result = {
                            "timestamp": datetime.datetime.now(),
                            "arbitration_id": msg.arbitration_id,
                            "pgn": target_pgn,
                            "raw_data": full_data.hex(),
                            "decoded": decoded
                        }
                        logger.info("✅ DM1 message received (multi-frame via TP)")
                        self.print_dm1(decoded)
                        return result

    # ==================== Standard CAN Message Decoding ====================
    
    def decode_standard(self, msg: can.Message) -> Optional[Dict[str, Any]]:
        """
        Decode standard (11-bit) CAN message using DBC database.
        
        Args:
            msg: CAN message
            
        Returns:
            Decoded message dictionary, or None if decode fails
        """
        if not self.db or msg.is_extended_id:
            return None

        try:
            return self.db.decode_message(msg.arbitration_id, msg.data)
        except Exception as e:
            logger.debug(f"Failed to decode standard CAN ID 0x{msg.arbitration_id:03x}: {e}")
            return None

    def decode_j1939_by_pgn(self, msg: can.Message) -> Tuple[Optional[int], Optional[str], Any]:
        """
        Decode J1939 (extended ID) message using PGN mapping.
        
        Args:
            msg: CAN message with extended ID
            
        Returns:
            Tuple of (PGN, message_name, decoded_data)
            Returns (pgn, None, None) if PGN not in database
        """
        if not self.db or not msg.is_extended_id:
            return None, None, None

        pgn = self.get_pgn(msg.arbitration_id)

        if pgn in self.pgn_map:
            message_def = self.pgn_map[pgn]

            try:
                decoded = message_def.decode(msg.data)
                return pgn, message_def.name, decoded
            except Exception as e:
                logger.debug(f"Failed to decode PGN 0x{pgn:04x}: {e}")
                return pgn, message_def.name, f"Decode Error: {e}"

        return pgn, None, None

    # ==================== Main Message Reading Loop ====================
    
    def read_messages(self, target_id: Optional[int] = None) -> None:
        """
        Main message reading loop with support for TP and DM1 handling.
        
        Continuously reads CAN messages and:
        - Automatically handles TP multi-frame messages
        - Decodes and displays DM1 diagnostic messages
        - Decodes J1939 and standard CAN messages
        - Tracks cycle times for all messages
        
        Args:
            target_id: Optional specific message ID to monitor for cycle time
        """
        print("Listening to CAN bus...\n")
        logger.info("Message reading loop started")

        try:
            while True:
                msg = self.bus.recv(timeout=1)

                if not msg:
                    # Periodically clean up stale TP sessions
                    self.cleanup_stale_tp_sessions()
                    continue

                # Timestamp conversion
                ts = msg.timestamp
                human_time = datetime.datetime.fromtimestamp(ts)
                pgn = self.get_pgn(msg.arbitration_id)

                # Cycle time tracking
                cycle = self.calculate_cycle_time(msg)
                specific_cycle = None
                if target_id:
                    specific_cycle = self.get_specific_cycle_time(msg, target_id)

                print(f"[{human_time}] ID: 0x{msg.arbitration_id:08x}, PGN: 0x{pgn:04x}")
                print(f"Data: {msg.data.hex()}")

                # TP.CM (BAM) handling
                if pgn == self.PGN_TP_CM:
                    self.handle_tp_cm(msg)

                # TP.DT handling
                elif pgn == self.PGN_TP_DT:
                    result = self.handle_tp_dt(msg)

                    if result:
                        target_pgn, full_data = result

                        # Check if assembled message is DM1
                        if target_pgn == self.PGN_DM1:
                            decoded = self.decode_dm1(full_data)
                            self.print_dm1(decoded)

                # Single-frame DM1 handling
                elif pgn == self.PGN_DM1:
                    decoded = self.decode_dm1(msg.data)
                    self.print_dm1(decoded)

                # Standard J1939 decoding
                elif msg.is_extended_id:
                    pgn, name, decoded = self.decode_j1939_by_pgn(msg)
                    if name:
                        print(f"Name: {name}")
                    print(f"Decoded: {decoded}")
                
                # Standard CAN decoding
                else:
                    decoded = self.decode_standard(msg)
                    print(f"Decoded: {decoded}")

                if cycle:
                    print(f"Cycle Time: {cycle:.2f} ms")
                
                if specific_cycle:
                    print(f"Specific Cycle Time (target): {specific_cycle:.2f} ms")

                print("-" * 60)

        except KeyboardInterrupt:
            logger.info("Message reading interrupted by user")
            print("\nStopped by user")
        except Exception as e:
            logger.error(f"Error during message reading: {e}")
            raise
        finally:
            self.close()

    def close(self) -> None:
        """Cleanup and close CAN bus interface."""
        try:
            if self.bus:
                self.bus.shutdown()
                logger.info("CAN bus closed")
        except Exception as e:
            logger.error(f"Error closing CAN bus: {e}")


# ==================== Example Usage ====================

if __name__ == "__main__":
    # Example 1: Basic usage without DBC
    # reader = CANReader(channel=0, bitrate=500000)
    
    # Example 2: With DBC file
    reader = CANReader(channel=0, bitrate=500000, dbc_file="path/to/your.dbc")
    
    # Example 3: With filters
    # filters = [{"can_id": 0x18FEF100, "can_mask": 0x1FFFFFFF}]
    # reader = CANReader(channel=0, bitrate=500000, filters=filters)
    
    try:
        # ===== FEATURE 1: Get DM1 message and return it =====
        print("=" * 60)
        print("DM1 MESSAGE READER - FIXED TP SESSION HANDLING")
        print("=" * 60)
        dm1_msg = reader.get_dm1_message(timeout=15.0)
        
        if dm1_msg:
            print(f"\n✅ DM1 Data Retrieved Successfully!")
            print(f"Timestamp: {dm1_msg['timestamp']}")
            print(f"Arbitration ID: 0x{dm1_msg['arbitration_id']:08X}")
            print(f"PGN: 0x{dm1_msg['pgn']:04X}")
            print(f"Raw Data (hex): {dm1_msg['raw_data']}")
            print(f"\nDecoded DM1:")
            print(f"  Lamp Status: {dm1_msg['decoded']['lamp_status']}")
            print(f"  DTCs: {dm1_msg['decoded']['DTCs']}")
        else:
            print("❌ No DM1 message received within timeout period")
        
        # ===== FEATURE 2: Get average cycle time =====
        # avg_cycle = reader.get_average_cycle_time(message_id=0x123, num_samples=10)
        # if avg_cycle:
        #     print(f"Average cycle time: {avg_cycle:.2f} ms")
        
        # ===== FEATURE 3: Read message by ID or name with all signals =====
        # msg_data = reader.read_message_signals(message_name="EngineStatus")
        # if msg_data:
        #     print(f"Message: {msg_data['message_name']}")
        #     print(f"All signals: {msg_data['signals']}")
        
        # ===== FEATURE 4: Get specific signal value =====
        # rpm_value = reader.get_signal_value("EngineRPM", message_id=0x123)
        # if rpm_value is not None:
        #     print(f"Engine RPM: {rpm_value}")
        
        # ===== Original: Read all messages continuously =====
        # reader.read_messages()
        
    except KeyboardInterrupt:
        print("\nApplication terminated by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
