#!/bin/sh
# Build and run a dropped-in project. Runs as the Zero Lab user INSIDE the guest, never on the host.
# Usage: run-project.sh DIR   (started under setsid, so $$ is the process group to stop)
set -e
echo $$ > "$HOME/.zerolab/pid"
cd "$1"
for z in *.zip; do [ -f "$z" ] && python3 -m zipfile -e "$z" . && rm -f "$z"; done
# A single dropped folder: work inside it.
if [ "$(ls -A | wc -l)" = 1 ] && [ -d "$(ls -A)" ]; then cd "$(ls -A)"; fi
export PYTHONUNBUFFERED=1

need() { command -v "$1" >/dev/null || { echo "ZL: installing $2 (needs networking on)"; sudo apt-get install -y "$2"; }; }
json() { python3 -c "import json,sys; print(json.load(open('pi-run.json')).get('$1', ''))"; }
first_elf() { for f in $(find . -maxdepth 2 -type f | sort); do [ "$(head -c4 "$f" | od -An -c | tr -d ' ')" = '177ELF' ] && { echo "$f"; return; }; done; }
first_py() { [ -f main.py ] && echo main.py || ls *.py 2>/dev/null | head -n1; }

build= run=
if [ -f pi-run.json ]; then build=$(json build); run=$(json run)
elif [ -f Makefile ] || [ -f makefile ]; then need make make; need cc gcc; build=make; run=${run:-./app}
elif [ -f CMakeLists.txt ]; then need cc gcc; need cmake cmake; build='cmake -B build && cmake --build build'
elif [ -f Cargo.toml ]; then need cargo cargo; build='cargo build --release'
elif [ -f go.mod ]; then need go golang; build='go build -o app .'; run=./app
elif [ -n "$(first_py)" ]; then run="python3 $(first_py)"
elif [ -n "$(first_elf)" ]; then run=$(first_elf); chmod +x "$run"
fi
# Guess the run target for compiled projects when pi-run.json did not say.
if [ -z "$run" ]; then
  [ -f Cargo.toml ] && run=$(ls target/release/* 2>/dev/null | head -n1)
  [ -d build ] && run=$(find build -maxdepth 1 -type f -perm -u+x | head -n1)
fi
if [ -n "$build" ]; then echo "ZL_BUILD: $build"; sh -c "$build"; fi
[ -z "$run" ] && run=$(first_elf)
[ -n "$run" ] || { echo "ZL: nothing to run (add pi-run.json with a \"run\" command)"; exit 2; }
case "$run" in */*|python3*) ;; *) [ -x "$run" ] && run="./$run" ;; esac
echo "ZL_RUN: $run"
exec stdbuf -oL -eL sh -c "$run"
