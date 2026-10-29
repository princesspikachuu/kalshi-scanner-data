"""Return temporary report allocations after a completed processor work unit."""
import gc
import sys
import ctypes

try:
    _trim=ctypes.CDLL(None).malloc_trim if sys.platform.startswith('linux') else None
    if _trim is not None:_trim.argtypes=[ctypes.c_size_t];_trim.restype=ctypes.c_int
except (OSError,AttributeError):_trim=None


def release_report_memory():
    gc.collect()
    if _trim is not None:_trim(0)
