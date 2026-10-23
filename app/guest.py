"""Talk to the guest over SSH (QEMU user-net forward on 127.0.0.1) to push and run projects.

Dropped-in files are only ever packed into a tar here; they are unpacked, built and run
inside the guest by guest/run-project.sh. Nothing from a project executes on the host.
"""
import io
import json
import os
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


def openssh(tool):
    """Windows' built-in OpenSSH client (System32\\OpenSSH, installed by default since Windows 10 1809), else PATH."""
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH", tool + ".exe")
    return str(exe) if os.name == "nt" and exe.exists() else tool


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
        return [openssh("ssh"), "-i", str(self.key), "-p", str(self.port),
                # Loopback forward to our own VM, and the host key changes on every reprovision.
                "-o", "StrictHostKeyChecking=no", "-o", f"UserKnownHostsFile={os.devnull}",
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


# ---------- file browser (the Files sidebar) ----------
import posixpath  # noqa: E402
import shlex  # noqa: E402

LIST_PY = r"""
import json, os, sys
p, hidden = sys.argv[1], sys.argv[2] == "1"
out = []
try:
    with os.scandir(p) as it:
        for e in it:
            if not hidden and e.name.startswith("."):
                continue
            try:
                st = e.stat(follow_symlinks=False)
                d = e.is_dir(follow_symlinks=True)
            except OSError:
                continue
            out.append({"name": e.name, "dir": d, "link": e.is_symlink(), "size": st.st_size, "mtime": int(st.st_mtime)})
    print(json.dumps({"path": os.path.abspath(p), "entries": out}))
except OSError as e:
    print(json.dumps({"error": e.strerror or str(e)}))
"""


def guest_path(p):
    """A guest path from the UI -> normalised absolute POSIX path. Rejects relative paths and control chars."""
    if not isinstance(p, str) or not p.startswith("/") or any(c in p for c in "\0\n\r"):
        raise ValueError("path must be an absolute path on the Pi")
    return posixpath.normpath(p) if p != "/" else "/"


def download_name(name, folder=False):
    """A guest file/folder name -> a safe single file name for ~/Downloads."""
    base = posixpath.basename(name.rstrip("/")) or "pi-root"
    base = "".join(c for c in base if c not in '/\\\0:*?"<>|').strip(". ") or "download"
    return base + (".tar.gz" if folder else "")


def open_exclusive(folder, name):
    """Create folder/name without following symlinks or overwriting; adds ' (2)', ' (3)'... on clashes."""
    stem, dot, ext = name.partition(".") if not name.startswith(".") else (name, "", "")
    for n in range(1, 1000):
        cand = name if n == 1 else f"{stem} ({n}){dot}{ext}"
        path = os.path.join(folder, cand)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o644)
            return os.fdopen(fd, "wb"), path
        except FileExistsError:
            continue
    raise OSError("too many files with that name in Downloads")


class Files:
    """Guest file operations over the same loopback SSH, as the Pi user."""

    def __init__(self, guest):
        self.g = guest

    def run(self, cmd, stdin=b"", timeout=60):
        return self.g.sh(cmd, stdin, timeout)

    def list(self, path, hidden=False):
        out = json.loads(self.run(f"python3 -c {shlex.quote(LIST_PY)} {shlex.quote(guest_path(path))} {int(hidden)}"))
        if "error" in out:
            raise ValueError(out["error"])
        out["entries"].sort(key=lambda e: (not e["dir"], e["name"].lower()))
        return out

    def home(self):
        return self.run("printf %s \"$HOME\"").decode()

    def exists(self, path):
        return self.run(f"test -e {shlex.quote(guest_path(path))} && echo y || true").strip() == b"y"

    def mkdir(self, path):
        self.run(f"mkdir -p -- {shlex.quote(guest_path(path))}")

    def rename(self, path, new_name):
        if not new_name or "/" in new_name or new_name in (".", ".."):
            raise ValueError("a new name cannot contain /")
        src = guest_path(path)
        dst = posixpath.join(posixpath.dirname(src), new_name)
        self.run(f"test ! -e {shlex.quote(dst)} && mv -- {shlex.quote(src)} {shlex.quote(dst)}")

    def delete(self, path):
        p = guest_path(path)
        if p in ("/", "/home", "/root", "/boot", "/usr", "/etc", "/bin", "/lib", "/var"):
            raise ValueError("refusing to delete a system folder")
        self.run(f"rm -rf -- {shlex.quote(p)}")

    def put(self, path, reader, length, overwrite=False):
        """Stream `length` bytes from reader into a guest file (parent folders created)."""
        p = guest_path(path)
        tmp = p + ".zl-part"
        cmd = (f"mkdir -p -- {shlex.quote(posixpath.dirname(p))} && "
               + ("" if overwrite else f"test ! -e {shlex.quote(p)} && ")
               + f"cat > {shlex.quote(tmp)} && mv -f -- {shlex.quote(tmp)} {shlex.quote(p)}")
        proc = subprocess.Popen(self.g.ssh_argv(cmd), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        left = length
        try:
            while left > 0:
                chunk = reader.read(min(1 << 20, left))
                if not chunk:
                    break
                proc.stdin.write(chunk)
                left -= len(chunk)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        err = proc.stderr.read().decode(errors="replace").strip()
        if proc.wait() or left:
            if not overwrite and not err:
                raise FileExistsError(p)
            raise RuntimeError(err or "upload interrupted")

    def get(self, path, downloads):
        """Stream a guest file (or a folder as .tar.gz) into the downloads folder. -> host path."""
        p = guest_path(path)
        is_dir = self.run(f"test -d {shlex.quote(p)} && echo d || true").strip() == b"d"
        cmd = (f"tar -czf - -C {shlex.quote(posixpath.dirname(p) or '/')} -- {shlex.quote(posixpath.basename(p))}"
               if is_dir else f"cat -- {shlex.quote(p)}")
        os.makedirs(downloads, exist_ok=True)
        out, host_path = open_exclusive(downloads, download_name(p, is_dir))
        with out:
            proc = subprocess.Popen(self.g.ssh_argv(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            while chunk := proc.stdout.read(1 << 20):
                out.write(chunk)
            err = proc.stderr.read().decode(errors="replace").strip()
        if proc.wait():
            os.unlink(host_path)
            raise RuntimeError(err or "download failed")
        return host_path

    def terminal(self, path):
        p = guest_path(path)
        self.run("export XDG_RUNTIME_DIR=/run/user/$(id -u) WAYLAND_DISPLAY=wayland-0 DISPLAY=:0; "
                 f"setsid -f lxterminal --working-directory={shlex.quote(p)} >/dev/null 2>&1 < /dev/null")
