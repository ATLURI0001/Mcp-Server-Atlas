"""
Mcp-Server-Atlas: Multi-Transport Session Multiplexer & Framing Protocol Guard.
Provides length-delimited and newline-delimited framing validation, session multiplexing,
and idle watchdog connection management.
"""

from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class FramingType(str, Enum):
    LENGTH_PREFIXED = "length_prefixed"
    NEWLINE_DELIMITED = "newline_delimited"


class FramingError(Exception):
    """Raised when incoming byte streams violate MCP transport framing boundaries."""
    pass


class PayloadTooLargeError(FramingError):
    """Raised when frame length exceeds configured safety budget."""
    pass


@dataclass
class SessionState:
    session_id: str
    transport_name: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    message_count: int = 0
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class FramingProtocolGuard:
    """
    Parses and sanitizes framed messages from raw transport byte streams.
    """

    def __init__(self, max_frame_size_bytes: int = 16 * 1024 * 1024):  # 16 MB max
        self.max_frame_size_bytes = max_frame_size_bytes

    def encode_length_prefixed(self, payload: bytes) -> bytes:
        """Encodes payload with 4-byte big-endian unsigned length header."""
        if len(payload) > self.max_frame_size_bytes:
            raise PayloadTooLargeError(
                f"Payload size {len(payload)} exceeds maximum {self.max_frame_size_bytes}"
            )
        return struct.pack(">I", len(payload)) + payload

    def decode_length_prefixed(self, stream_buffer: bytearray) -> Tuple[Optional[bytes], int]:
        """
        Extracts the first valid length-prefixed frame from stream_buffer.
        Returns (frame_bytes, bytes_consumed) or (None, 0) if incomplete.
        """
        if len(stream_buffer) < 4:
            return None, 0

        (length,) = struct.unpack(">I", stream_buffer[:4])
        if length > self.max_frame_size_bytes:
            raise PayloadTooLargeError(
                f"Frame declared size {length} bytes exceeds limit {self.max_frame_size_bytes}"
            )

        total_frame_size = 4 + length
        if len(stream_buffer) < total_frame_size:
            return None, 0  # Incomplete frame, wait for more chunks

        frame_data = bytes(stream_buffer[4:total_frame_size])
        return frame_data, total_frame_size

    def decode_newline_delimited(self, stream_buffer: bytearray) -> Tuple[Optional[str], int]:
        """
        Extracts the first newline-delimited JSON frame from stream_buffer.
        Returns (message_str, bytes_consumed) or (None, 0) if incomplete.
        """
        newline_idx = stream_buffer.find(b"\n")
        if newline_idx == -1:
            if len(stream_buffer) > self.max_frame_size_bytes:
                raise PayloadTooLargeError(
                    f"Buffer length {len(stream_buffer)} without newline exceeds limit"
                )
            return None, 0

        line_bytes = stream_buffer[:newline_idx]
        consumed = newline_idx + 1

        if len(line_bytes) > self.max_frame_size_bytes:
            raise PayloadTooLargeError(f"Line size {len(line_bytes)} exceeds frame limit")

        decoded = line_bytes.decode("utf-8", errors="replace").strip()
        return decoded, consumed


class SessionMultiplexer:
    """
    Multiplexes concurrent client sessions across a shared transport channel.
    """

    def __init__(self, idle_timeout_sec: float = 300.0, max_sessions: int = 100):
        self.idle_timeout_sec = idle_timeout_sec
        self.max_sessions = max_sessions
        self.sessions: Dict[str, SessionState] = {}
        self.guard = FramingProtocolGuard()

    def create_session(
        self, session_id: str, transport_name: str, metadata: Optional[Dict[str, Any]] = None
    ) -> SessionState:
        if not session_id:
            raise ValueError("session_id cannot be empty")
        if len(self.sessions) >= self.max_sessions:
            raise RuntimeError(f"Session capacity {self.max_sessions} reached")

        session = SessionState(
            session_id=session_id,
            transport_name=transport_name,
            metadata=metadata or {},
        )
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[SessionState]:
        return self.sessions.get(session_id)

    def route_message(self, session_id: str, payload: Dict[str, Any]) -> bool:
        """Records ingress message delivery for session and updates activity timestamp."""
        session = self.sessions.get(session_id)
        if not session or not session.is_active:
            return False

        session.last_activity = time.time()
        session.message_count += 1
        return True

    def evict_idle_sessions(self, now: Optional[float] = None) -> List[str]:
        """Closes and removes sessions that have exceeded the idle timeout threshold."""
        ts = now if now is not None else time.time()
        evicted = []

        for sid, sess in list(self.sessions.items()):
            if ts - sess.last_activity > self.idle_timeout_sec:
                sess.is_active = False
                evicted.append(sid)
                del self.sessions[sid]

        return evicted

    def close_session(self, session_id: str) -> bool:
        sess = self.sessions.pop(session_id, None)
        if sess:
            sess.is_active = False
            return True
        return False
