"""Windows: Zero Lab in its own window, and nothing left running once that window closes.

The UI opens in Microsoft Edge's app mode (part of Windows 10/11; Chrome if Edge was removed): a window with no
tabs or address bar, in a private profile under the data folder. The engine waits for that window; closing it
powers the Pi off and ends QEMU and the engine. A job object also ends QEMU and ssh if the engine itself dies.
"""
import os
import subprocess
from pathlib import Path


def find_browser():
    """Edge, else Chrome: both have an app mode (--app). None if neither is installed."""
    roots = [os.environ.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
        for root in filter(None, roots):
            if (Path(root) / rel).is_file():
                return Path(root) / rel
    return None


def open_window(url, data):
    """Start the app window -> its process (it exits when the window closes), or None without Edge/Chrome.
    A second call for the same data folder opens another window in the running browser and returns at once."""
    browser = find_browser()
    if not browser:
        return None
    return subprocess.Popen([str(browser), f"--app={url}", f"--user-data-dir={Path(data) / 'window'}",
                             "--start-maximized", "--no-first-run", "--no-default-browser-check"])


def message(text):
    import ctypes  # noqa: PLC0415
    ctypes.windll.user32.MessageBoxW(None, text, "Zero Lab", 0x10)  # MB_ICONERROR


def end_children_with_me():
    """Put this process in a job that ends every process it starts (QEMU, ssh, the window) when it exits,
    even if it is killed or crashes."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class Basic(ctypes.Structure):
        _fields_ = [("user_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", wintypes.DWORD),
                    ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t), ("procs", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("sched", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6), ("proc_mem", ctypes.c_size_t),
                    ("job_mem", ctypes.c_size_t), ("peak_proc_mem", ctypes.c_size_t), ("peak_job_mem", ctypes.c_size_t)]

    k = ctypes.windll.kernel32
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k.CreateJobObjectW(None, None)  # held (never closed) until this process exits
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # JobObjectExtendedLimitInformation
    return bool(k.AssignProcessToJobObject(job, k.GetCurrentProcess()))
