"""Sample CPU, memory, process births, and disk bytes. Works on Windows and on Linux."""

from __future__ import annotations

import platform
import time

import psutil

from .samples import Sample


class Collector:
    def __init__(self) -> None:
        psutil.cpu_percent(interval=None)
        self._pids = set(psutil.pids())
        self._io = psutil.disk_io_counters()
        self._t0 = time.perf_counter()

    def sample(self) -> Sample:
        cpu = float(psutil.cpu_percent(interval=None))
        mem = float(psutil.virtual_memory().percent)
        pids = set(psutil.pids())
        born = len(pids - self._pids)
        self._pids = pids
        io = psutil.disk_io_counters()
        read = write = 0
        if io is not None and self._io is not None:
            read = max(0, int(io.read_bytes - self._io.read_bytes))
            write = max(0, int(io.write_bytes - self._io.write_bytes))
        self._io = io
        return Sample(
            t=time.perf_counter() - self._t0,
            cpu_percent=cpu,
            mem_percent=mem,
            proc_count=len(pids),
            proc_born=born,
            read_bytes=read,
            write_bytes=write,
            running=_running(),
        )


def host_meta() -> dict:
    return {
        "platform": platform.platform(),
        "cpu_count": psutil.cpu_count(logical=True) or 1,
        "memory_gb": round(psutil.virtual_memory().total / 2**30, 2),
    }


def collect_seconds(seconds: int, interval: float = 1.0) -> list[Sample]:
    if seconds < 1:
        raise ValueError("seconds must be >= 1")
    collector = Collector()
    samples: list[Sample] = []
    for _ in range(seconds):
        time.sleep(interval)
        samples.append(collector.sample())
    return samples


def _running() -> int:
    """Tasks currently executing, without opening a handle to every process.

    On Windows, psutil's status means "not suspended" and opens every process.
    That walk takes seconds on the UI thread. One system snapshot counts
    threads in the Running state, excluding the idle process.
    """
    system = platform.system()
    if system == "Linux":
        try:
            return max(0, _linux_procs_running())
        except (OSError, ValueError, IndexError):
            return 0
    if system == "Windows":
        try:
            return _windows_executing()
        except (OSError, ValueError, IndexError, OverflowError):
            return 0
    try:
        return max(0, int(round(psutil.getloadavg()[0])))
    except (OSError, AttributeError):
        return 0


def _linux_procs_running(path: str = "/proc/stat") -> int:
    with open(path, encoding="ascii") as handle:
        for line in handle:
            if line.startswith("procs_running "):
                return int(line.split()[1])
    raise OSError("procs_running missing")


def _windows_executing() -> int:
    import ctypes

    ntdll = ctypes.WinDLL("ntdll")
    query = ntdll.NtQuerySystemInformation
    query.argtypes = [
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    query.restype = ctypes.c_long
    proc_type, thread_type = _windows_structs()
    proc_size = ctypes.sizeof(proc_type)
    thread_size = ctypes.sizeof(thread_type)
    state_offset = thread_type.ThreadState.offset
    mismatch = ctypes.c_long(0xC0000004).value
    size = 0x20000
    while True:
        buf = ctypes.create_string_buffer(size)
        returned = ctypes.c_ulong(0)
        status = query(5, buf, size, ctypes.byref(returned))
        if status == mismatch:
            size = max(size * 2, int(returned.value) + 0x1000)
            continue
        if status != 0:
            raise OSError(status)
        data = buf.raw
        break
    offset = 0
    executing = 0
    limit = len(data)
    while offset + proc_size <= limit:
        entry = proc_type.from_buffer_copy(data, offset)
        pid = int(entry.UniqueProcessId or 0)
        if entry.NextEntryOffset:
            region_end = min(limit, offset + int(entry.NextEntryOffset))
        else:
            region_end = limit
        thread_at = offset + proc_size
        room = max(0, (region_end - thread_at) // thread_size)
        for index in range(min(int(entry.NumberOfThreads), room)):
            at = thread_at + index * thread_size + state_offset
            state = int.from_bytes(data[at : at + 4], "little")
            if state == 2 and pid != 0:
                executing += 1
        if not entry.NextEntryOffset:
            break
        offset += int(entry.NextEntryOffset)
    return executing


def _windows_structs():
    import ctypes
    from ctypes import wintypes

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", ctypes.c_void_p),
        ]

    class CLIENT_ID(ctypes.Structure):
        _fields_ = [
            ("UniqueProcess", ctypes.c_void_p),
            ("UniqueThread", ctypes.c_void_p),
        ]

    class SYSTEM_THREAD_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("KernelTime", ctypes.c_longlong),
            ("UserTime", ctypes.c_longlong),
            ("CreateTime", ctypes.c_longlong),
            ("WaitTime", wintypes.ULONG),
            ("StartAddress", ctypes.c_void_p),
            ("ClientId", CLIENT_ID),
            ("Priority", wintypes.LONG),
            ("BasePriority", wintypes.LONG),
            ("ContextSwitches", wintypes.ULONG),
            ("ThreadState", wintypes.ULONG),
            ("WaitReason", wintypes.ULONG),
        ]

    class SYSTEM_PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("NextEntryOffset", wintypes.ULONG),
            ("NumberOfThreads", wintypes.ULONG),
            ("WorkingSetPrivateSize", ctypes.c_longlong),
            ("HardFaultCount", wintypes.ULONG),
            ("NumberOfThreadsHighWatermark", wintypes.ULONG),
            ("CycleTime", ctypes.c_ulonglong),
            ("CreateTime", ctypes.c_longlong),
            ("UserTime", ctypes.c_longlong),
            ("KernelTime", ctypes.c_longlong),
            ("ImageName", UNICODE_STRING),
            ("BasePriority", wintypes.LONG),
            ("UniqueProcessId", ctypes.c_void_p),
            ("InheritedFromUniqueProcessId", ctypes.c_void_p),
            ("HandleCount", wintypes.ULONG),
            ("SessionId", wintypes.ULONG),
            ("UniqueProcessKey", ctypes.c_void_p),
            ("PeakVirtualSize", ctypes.c_size_t),
            ("VirtualSize", ctypes.c_size_t),
            ("PageFaultCount", wintypes.ULONG),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivatePageCount", ctypes.c_size_t),
            ("ReadOperationCount", ctypes.c_longlong),
            ("WriteOperationCount", ctypes.c_longlong),
            ("OtherOperationCount", ctypes.c_longlong),
            ("ReadTransferCount", ctypes.c_longlong),
            ("WriteTransferCount", ctypes.c_longlong),
            ("OtherTransferCount", ctypes.c_longlong),
        ]

    return SYSTEM_PROCESS_INFORMATION, SYSTEM_THREAD_INFORMATION
