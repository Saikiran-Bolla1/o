import can
import datetime
import cantools
import logging
from typing import Optional, Tuple, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CANReader:
    """
    CAN bus reader with support for J1939 protocol and standard CAN messages.
    
    Features:
    - Vector CAN interface support
    - DBC database integration for message decoding
    - J1939 PGN-based message filtering
    - Cycle time monitoring for individual and target message IDs
    - Frame type detection (standard vs extended)
    """
    
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

        self.last_timestamps = {}  # For cycle time tracking
        self.db = None
        self.pgn_map = {}

        if dbc_file:
            self.load_dbc(dbc_file)

        if filters:
            self.set_filters(filters)

    def load_dbc(self, dbc_file: str) -> None:
        """
        Load DBC database file and build PGN map.
        
        Args:
            dbc_file: Path to DBC file
        """
        try:
            self.db = cantools.database.load_file(dbc_file)
            logger.info(f"DBC file loaded: {dbc_file}")

            self.pgn_map = {}
            for msg in self.db.messages:
                if msg.is_extended_frame:
                    pgn = self.extract_pgn_from_dbc_id(msg.frame_id)
                    self.pgn_map[pgn] = msg
            
            logger.info(f"PGN map created with {len(self.pgn_map)} messages")
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
        
        Args:
            arbitration_id: CAN arbitration ID
            
        Returns:
            Extracted PGN value
        """
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

    def read_messages(self, target_id: Optional[int] = None) -> None:
        """
        Main message reading loop.
        
        Continuously reads CAN messages and prints them with decoding information.
        Supports monitoring specific message IDs for cycle time analysis.
        
        Args:
            target_id: Optional specific message ID to monitor for cycle time
        """
        print("Listening to CAN bus...\n")
        logger.info("Message reading loop started")

        try:
            while True:
                msg = self.bus.recv(timeout=1)

                if not msg:
                    continue

                # Timestamp conversion
                ts = msg.timestamp
                human_time = datetime.datetime.fromtimestamp(ts)

                # Cycle time tracking
                cycle = self.calculate_cycle_time(msg)
                specific_cycle = None
                if target_id:
                    specific_cycle = self.get_specific_cycle_time(msg, target_id)

                # Decode and print based on frame type
                if msg.is_extended_id:
                    pgn, name, decoded = self.decode_j1939_by_pgn(msg)
                    print(f"[{human_time}] J1939 - ID: 0x{msg.arbitration_id:08x}, PGN: 0x{pgn:04x}, Name: {name}")
                    print(f"    Data: {msg.data.hex()}")
                    print(f"    Decoded: {decoded}")
                    if cycle:
                        print(f"    Cycle Time: {cycle:.2f} ms")
                    if specific_cycle:
                        print(f"    Specific Cycle Time (target): {specific_cycle:.2f} ms")
                else:
                    decoded = self.decode_standard(msg)
                    print(f"[{human_time}] Standard - ID: 0x{msg.arbitration_id:03x}")
                    print(f"    Data: {msg.data.hex()}")
                    print(f"    Decoded: {decoded}")
                    if cycle:
                        print(f"    Cycle Time: {cycle:.2f} ms")
                    if specific_cycle:
                        print(f"    Specific Cycle Time (target): {specific_cycle:.2f} ms")
                
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


# Example usage
if __name__ == "__main__":
    # Without DBC file
    reader = CANReader(channel=0, bitrate=500000)
    
    # With DBC file (uncomment and provide path)
    # reader = CANReader(channel=0, bitrate=500000, dbc_file="path/to/your.dbc")
    
    # With filters (example)
    # filters = [{"can_id": 0x123, "can_mask": 0x7FF}]
    # reader = CANReader(channel=0, bitrate=500000, filters=filters)
    
    try:
        # Read all messages
        reader.read_messages()
        
        # Or read with specific target ID for cycle time monitoring
        # reader.read_messages(target_id=0x123)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
