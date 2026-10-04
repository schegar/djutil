"""Read-only process memory access.

``MemoryReader`` is the protocol the pointer/scan code works against (a fake
implements it in tests).  ``WindowsProcess`` opens ``rekordbox.exe`` with
PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ only — it can never
write to the process.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Protocol, runtime_checkable

k32 = ctypes.windll.kernel32 if sys.platform == "win32" else None
ver = ctypes.windll.version if sys.platform == "win32" else None


class MemoryReadError(RuntimeError):
    pass


class UnsupportedPlatform(RuntimeError):
    pass


class ProcessNotFoundError(MemoryReadError):
    pass


@runtime_checkable
class MemoryReader(Protocol):
    @property
    def module_base(self) -> int: ...

    @property
    def module_size(self) -> int: ...

    @property
    def version(self) -> str | None: ...

    def read(self, addr: int, size: int) -> bytes:
        """Return exactly ``size`` bytes or raise ``MemoryReadError``."""
        ...

    def readable_regions(self) -> list[tuple[int, int]]:
        """(base, size) pairs of readable committed memory."""
        ...

    def writable_regions(self) -> list[tuple[int, int]]:
        """(base, size) pairs of committed memory the process may write."""
        ...


def _check_platform() -> None:
    if sys.platform != "win32" or k32 is None:
        raise UnsupportedPlatform(
            "process-memory deck reading is only implemented on Windows"
        )


# -- Windows structs ----------------------------------------------------------

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
WRITABLE = (
    PAGE_READWRITE
    | PAGE_WRITECOPY
    | PAGE_EXECUTE_READWRITE
    | PAGE_EXECUTE_WRITECOPY
)
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.WCHAR * 256),
        ("szExePath", wintypes.WCHAR * MAX_PATH),
    ]


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wintypes.DWORD),
        ("__alignment1", wintypes.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("__alignment2", wintypes.DWORD),
    ]


class VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [
        ("dwSignature", wintypes.DWORD),
        ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD),
        ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD),
        ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD),
        ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD),
        ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD),
        ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    ]


def _file_version(exe_path: str) -> str | None:
    """Product version from the exe's version resource, e.g. '7.2.10.0'."""
    if ver is None:
        return None
    size = ver.GetFileVersionInfoSizeW(exe_path, None)
    if not size:
        return None
    buf = (ctypes.c_byte * size)()
    if not ver.GetFileVersionInfoW(exe_path, 0, size, buf):
        return None
    info = ctypes.POINTER(VS_FIXEDFILEINFO)()
    out_len = wintypes.UINT(0)
    if not ver.VerQueryValueW(
        buf, "\\", ctypes.byref(info), ctypes.byref(out_len)
    ):
        return None
    ms, ls = info.contents.dwFileVersionMS, info.contents.dwFileVersionLS
    v = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    return v.removesuffix(".0")


class WindowsProcess:
    """Read-only view of a running process's memory (Windows only)."""

    def __init__(self, name: str = "rekordbox.exe") -> None:
        _check_platform()
        self.name = name.lower()
        self.pid = self._find_pid()
        if self.pid is None:
            raise ProcessNotFoundError(
                f"{name} is not running (Rekordbox must be running with "
                "tracks loaded on the decks)"
            )
        self._handle = k32.OpenProcess(  # type: ignore[union-attr]
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ,
            False,
            self.pid,
        )
        if not self._handle:
            err = ctypes.get_last_error()
            raise MemoryReadError(
                f"OpenProcess failed for pid {self.pid} (error {err}); "
                "try running the agent elevated"
            )
        self._exe_path: str | None = None
        self._module_base, self._module_size = self._find_module()
        self._regions: list[tuple[int, int, int]] | None = None
        self._version = _file_version(self._exe_path) if self._exe_path else None
        if self._version is None:
            try:
                from ..platform.paths import rekordbox_version

                self._version = rekordbox_version()
            except Exception:
                self._version = None

    # -- discovery ------------------------------------------------------------

    def _find_pid(self) -> int | None:
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)  # type: ignore[union-attr]
        if snap == -1:
            raise MemoryReadError("CreateToolhelp32Snapshot(process) failed")
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = k32.Process32FirstW(snap, ctypes.byref(entry))  # type: ignore[union-attr]
            while ok:
                if entry.szExeFile.lower() == self.name:
                    return int(entry.th32ProcessID)
                ok = k32.Process32NextW(snap, ctypes.byref(entry))  # type: ignore[union-attr]
            return None
        finally:
            k32.CloseHandle(snap)  # type: ignore[union-attr]

    def _find_module(self) -> tuple[int, int]:
        snap = k32.CreateToolhelp32Snapshot(  # type: ignore[union-attr]
            TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, self.pid
        )
        if snap == -1:
            raise MemoryReadError("CreateToolhelp32Snapshot(module) failed")
        try:
            entry = MODULEENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = k32.Module32FirstW(snap, ctypes.byref(entry))  # type: ignore[union-attr]
            while ok:
                if entry.szModule.lower() == self.name:
                    self._exe_path = entry.szExePath
                    return (
                        ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value
                        or 0,
                        int(entry.modBaseSize),
                    )
                ok = k32.Module32NextW(snap, ctypes.byref(entry))  # type: ignore[union-attr]
            raise MemoryReadError(
                f"module {self.name!r} not found in pid {self.pid}"
            )
        finally:
            k32.CloseHandle(snap)  # type: ignore[union-attr]

    # -- MemoryReader protocol -------------------------------------------------

    @property
    def module_base(self) -> int:
        return self._module_base

    @property
    def module_size(self) -> int:
        return self._module_size

    @property
    def version(self) -> str | None:
        return self._version

    def read(self, addr: int, size: int) -> bytes:
        buf = (ctypes.c_byte * size)()
        read = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(  # type: ignore[union-attr]
            self._handle,
            ctypes.c_void_p(addr),
            buf,
            size,
            ctypes.byref(read),
        )
        if not ok or read.value != size:
            err = ctypes.get_last_error()
            raise MemoryReadError(
                f"read {size:#x} bytes @ {addr:#x} failed "
                f"(error {err}, got {read.value})"
            )
        return bytes(buf)

    def _query_regions(self) -> list[tuple[int, int, int]]:
        """(base, size, protect) of committed, accessible regions (cached)."""
        if self._regions is not None:
            return self._regions
        regions: list[tuple[int, int, int]] = []
        mbi = MEMORY_BASIC_INFORMATION64()
        addr = 0
        limit = 0x7FFFFFFFFFFF  # user-mode space on x64
        while addr < limit:
            n = k32.VirtualQueryEx(  # type: ignore[union-attr]
                self._handle,
                ctypes.c_void_p(addr),
                ctypes.byref(mbi),
                ctypes.sizeof(mbi),
            )
            if n == 0:
                break
            if (
                mbi.State == MEM_COMMIT
                and not (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))
                and mbi.RegionSize > 0
            ):
                regions.append(
                    (
                        int(mbi.BaseAddress),
                        int(mbi.RegionSize),
                        int(mbi.Protect),
                    )
                )
            nxt = mbi.BaseAddress + mbi.RegionSize
            if nxt <= addr:
                break
            addr = nxt
        regions.sort()
        self._regions = regions
        return regions

    def readable_regions(self) -> list[tuple[int, int]]:
        return [(b, s) for b, s, _p in self._query_regions()]

    def writable_regions(self) -> list[tuple[int, int]]:
        return [
            (b, s) for b, s, p in self._query_regions() if p & WRITABLE
        ]

    def is_readable(self, addr: int) -> bool:
        import bisect

        regions = [(b, s) for b, s, _p in self._query_regions()]
        bases = [b for b, _ in regions]
        i = bisect.bisect_right(bases, addr) - 1
        return i >= 0 and addr < regions[i][0] + regions[i][1]

    def close(self) -> None:
        if getattr(self, "_handle", None):
            k32.CloseHandle(self._handle)  # type: ignore[union-attr]
            self._handle = None

    def __enter__(self) -> WindowsProcess:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
