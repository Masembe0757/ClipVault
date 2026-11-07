#!/usr/bin/env bash
# Clipvault launcher for macOS, Linux and Git Bash / MSYS2 on Windows.
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1; then
    PY="$c"; break
  fi
done

# Windows Python installed without PATH (common in Git Bash / MSYS2)
if [ -z "$PY" ]; then
  for p in /c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe /c/Python3*/python.exe "/c/Program Files/Python3"*/python.exe; do
    [ -x "$p" ] && PY="$p"
  done
fi

if [ -z "$PY" ]; then
  echo "Python 3.9+ was not found. Install it from https://www.python.org/downloads/"
  exit 1
fi

exec "$PY" app.py "$@"
