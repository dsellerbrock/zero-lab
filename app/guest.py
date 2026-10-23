"""Talk to the guest over SSH (QEMU user-net forward on 127.0.0.1) to push and run projects.

Dropped-in files are only ever packed into a tar here; they are unpacked, built and run
inside the guest by guest/run-project.sh. Nothing from a project executes on the host.
"""
import io
import subprocess
import tarfile
import threading
from pathlib import Path, PurePosixPath

GUEST = Path(__file__).resolve().parent / "guest"
MAX_UPLOAD = 50 * 1024 * 1024
UNIT = """[Unit]
Description=Zero Lab project
After=graphical.target
[Service]
User={user}
ExecStart=/bin/sh /home/{user}/.zerolab/run-project.sh /home/{user}/zerolab/project
[Install]
WantedBy=graphical.target
"""


def safe_name(rel):
    """Upload path -> a safe relative POSIX path, or None (absolute, '..', empty, hidden tricks)."""
    parts = [p for p in PurePosixPath(rel.replace("\\", "/")).parts if p not in ("", ".")]
    if not parts or parts[0] == "/" or ".." in parts or any(p.startswith("/") for p in parts):
        return None
    return "/".join(parts)


def pack(files):
    """files: list of (relative path, bytes) -> tar bytes. Raises ValueError on bad input."""
    if sum(len(b) for _, b in files) > MAX_UPLOAD:
        raise ValueError("project is larger than 50 MB")
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for rel, data in files:
            name = safe_name(rel)
            if name is None:
                raise ValueError(f"bad file name: {rel!r}")
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o644
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


class Guest:
    def __init__(self, key, port, user):
        self.key, self.port, self.user = key, port, user
        self.proc = None

    def ssh_argv(self, command):
        return ["ssh", "-i", str(self.key), "-p", str(self.port),
                # Loopback forward to our own VM, and the host key changes on every reprovision.
                "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "LogLevel=ERROR",
                f"{self.user}@127.0.0.1", command]

    def sh(self, command, stdin=b"", timeout=60):
        r = subprocess.run(self.ssh_argv(command), input=stdin, capture_output=True, timeout=timeout)
        if r.returncode:
            raise RuntimeError(r.stderr.decode(errors="replace").strip() or f"exit {r.returncode}")
        return r.stdout

    def push(self, tar_bytes):
        runner = (GUEST / "run-project.sh").read_bytes()
        self.sh("mkdir -p ~/.zerolab && cat > ~/.zerolab/run-project.sh", runner)
        self.sh("rm -rf ~/zerolab/project && mkdir -p ~/zerolab/project && "
                "tar -x --no-same-owner -C ~/zerolab/project", tar_bytes)

    def run(self, emit):
        """Build + run in the guest; stream output lines as 'proc' events."""
        if self.proc and self.proc.poll() is None:
            raise RuntimeError("a program is already running")
        self.proc = subprocess.Popen(
            self.ssh_argv("setsid -w sh ~/.zerolab/run-project.sh ~/zerolab/project 2>&1"),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        emit("proc", state="running")

        def pump(proc):
            for raw in proc.stdout:
                emit("proc", line=raw.decode(errors="replace").rstrip("\n"))
            emit("proc", state="exited", code=proc.wait())

        threading.Thread(target=pump, args=(self.proc,), daemon=True).start()

    def stop_program(self):
        self.sh('p=$(cat ~/.zerolab/pid 2>/dev/null) && [ -n "$p" ] && '
                '{ kill -TERM -- -$p 2>/dev/null; sleep 3; kill -KILL -- -$p 2>/dev/null; true; } || true')

    def autostart(self, on):
        if on:
            unit = UNIT.format(user=self.user).encode()
            self.sh("sudo tee /etc/systemd/system/zerolab-app.service >/dev/null && "
                    "sudo systemctl daemon-reload && sudo systemctl enable zerolab-app.service", unit)
        else:
            self.sh("sudo systemctl disable zerolab-app.service 2>/dev/null; true")

    def poweroff(self):
        self.sh("sudo systemctl poweroff --no-block", timeout=15)
