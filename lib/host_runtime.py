# pimux-managed: portable filesystem, locking and bounded-process primitives.
"""Standard-library helpers; no environment or credential discovery."""

import ctypes
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys


def process_cwd(pid):
    pid = int(pid)
    if not 0 < pid < 2**31:
        raise ValueError("Invalid process ID")
    if sys.platform != "darwin":
        return str(Path(f"/proc/{pid}/cwd").readlink())
    # Public Darwin proc_info.h ABI: vnode_info is 152 bytes, followed by
    # MAXPATHLEN (1024). Use the kernel path, not lsof's ambiguous caret escapes.
    class VnodePath(ctypes.Structure):
        _fields_ = [("info", ctypes.c_uint64 * 19), ("path", ctypes.c_char * 1024)]
    class VnodePaths(ctypes.Structure):
        _fields_ = [("cwd", VnodePath), ("root", VnodePath)]
    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    query = libproc.proc_pidinfo
    query.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    query.restype = ctypes.c_int
    paths = VnodePaths()
    size = ctypes.sizeof(paths)
    if query(pid, 9, 0, ctypes.byref(paths), size) != size or not paths.cwd.path:
        raise OSError(ctypes.get_errno(), "Working directory unavailable")
    return os.fsdecode(paths.cwd.path)


def timed_command(seconds, command):
    seconds = float(seconds)
    if not 0 < seconds < 86400 or not command:
        raise ValueError("Invalid timeout or empty command")
    class Cancelled(Exception):
        def __init__(self, signum):
            self.signum = signum

    def cancelled(signum, _frame):
        raise Cancelled(signum)

    handlers = {sig: signal.signal(sig, cancelled) for sig in
                (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    process = None
    try:
        process = subprocess.Popen(command, start_new_session=True)
        try:
            result = process.wait(timeout=seconds)
            return result if result >= 0 else 128 - result
        except (subprocess.TimeoutExpired, Cancelled) as error:
            signum = error.signum if isinstance(error, Cancelled) else signal.SIGTERM
            # Ignore repeated cancellation while reaping the entire command group.
            for sig in handlers:
                signal.signal(sig, signal.SIG_IGN)
            try:
                os.killpg(process.pid, signum)
                process.wait(timeout=1)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            # A leader may exit while a descendant ignores termination.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            return 128 + signum if isinstance(error, Cancelled) else 124
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def main(args):
    action, *values = args
    if action == "realpath" and len(values) == 1:
        print(os.path.realpath(values[0]))
    elif action == "signature" and len(values) == 1:
        info = os.stat(values[0])
        print(f"{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}")
    elif action == "lock" and len(values) == 1:
        # The shell keeps the inherited open file description alive after this
        # helper exits, just as util-linux flock FD does.
        fcntl.flock(int(values[0]), fcntl.LOCK_EX)
    elif action == "cwd" and len(values) == 1:
        print(process_cwd(values[0]))
    elif action == "timeout" and len(values) >= 2:
        return timed_command(values[0], values[1:])
    else:
        raise ValueError("Invalid host-runtime arguments")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError) as error:
        print(f"PiMux host runtime: {error}", file=sys.stderr)
        raise SystemExit(1) from None
