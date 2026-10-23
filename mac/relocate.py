#!/usr/bin/env python3
"""Make a QEMU tree self-contained: copy every non-system dylib it links into DIR/lib and
point all references at @loader_path. Libraries in PREFER (our macOS-26 rebuilds) win over
same-named Homebrew ones. Then check: no absolute non-system paths left, minos <= 26.

usage: relocate.py QEMU_DIR PREFER_LIBDIR
"""
import re
import subprocess
import sys
from pathlib import Path

SYSTEM = ("/usr/lib/", "/System/")
MAX_MINOS = (26, 0)


def deps(f):
    out = subprocess.run(["otool", "-L", str(f)], capture_output=True, text=True, check=True).stdout
    return [line.split(" (")[0].strip() for line in out.splitlines()[1:] if line.strip()]


def rpaths(f):
    out = subprocess.run(["otool", "-l", str(f)], capture_output=True, text=True, check=True).stdout
    return re.findall(r"cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (\S+)", out)


def minos(f):
    out = subprocess.run(["vtool", "-show-build", str(f)], capture_output=True, text=True).stdout
    m = re.search(r"minos (\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def resolve(ref, prefer, origin):
    name = Path(ref).name
    if (prefer / name).exists():
        return (prefer / name).resolve()
    if ref.startswith("@"):
        for rp in rpaths(origin):
            cand = Path(rp.replace("@loader_path", str(origin.parent))) / name
            if cand.exists():
                return cand.resolve()
        raise SystemExit(f"cannot resolve {ref} for {origin}")
    return Path(ref).resolve()


def main():
    qdir, prefer = Path(sys.argv[1]), Path(sys.argv[2])
    lib = qdir / "lib"
    roots = [p for p in (qdir / "bin").iterdir()] + [p for p in (qdir / "libexec").iterdir()]
    todo, seen = list(roots) + list(lib.glob("*.dylib")), set()
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        subprocess.run(["chmod", "u+w", str(f)], check=True)
        own_id = deps(f)[0] if f.suffix == ".dylib" else None
        if own_id:
            subprocess.run(["install_name_tool", "-id", f"@rpath/{f.name}", str(f)], check=True, capture_output=True)
        for ref in deps(f):
            if ref.startswith(SYSTEM) or ref == own_id or Path(ref).name == f.name:
                continue
            src = resolve(ref, prefer, f)
            dest = lib / Path(ref).name
            if not dest.exists():
                dest.write_bytes(src.read_bytes())
                todo.append(dest)
            new = f"@loader_path/{dest.name}" if f.parent == lib else f"@loader_path/../lib/{dest.name}"
            subprocess.run(["install_name_tool", "-change", ref, new, str(f)], check=True, capture_output=True)
        for rp in rpaths(f):
            if not rp.startswith("@"):
                subprocess.run(["install_name_tool", "-delete_rpath", rp, str(f)], check=True, capture_output=True)
    # verification
    bad = []
    for f in seen:
        for ref in deps(f):
            if ref.startswith("/") and not ref.startswith(SYSTEM):
                bad.append(f"{f.name} -> {ref}")
        if minos(f) > MAX_MINOS:
            bad.append(f"{f.name}: minos {minos(f)} > {MAX_MINOS}")
    if bad:
        raise SystemExit("relocation check failed:\n  " + "\n  ".join(sorted(bad)))
    print(f"relocated {len(seen)} Mach-O files; all minos <= {MAX_MINOS[0]}.{MAX_MINOS[1]}")


if __name__ == "__main__":
    main()
