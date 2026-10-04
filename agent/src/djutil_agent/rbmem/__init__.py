"""Read Rekordbox deck state from process memory (Windows, read-only).

Discovery/diagnostic spike — not wired into the live forwarder.
"""

from .pointer import Pointer
from .process import MemoryReadError, UnsupportedPlatform

__all__ = ["MemoryReadError", "Pointer", "UnsupportedPlatform"]
