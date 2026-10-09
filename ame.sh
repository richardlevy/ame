#!/usr/bin/env bash
# Launch ame. Sets up the venv and builds the UI first if needed.
#
#   ./ame.sh                    # asks for a folder
#   ./ame.sh ~/Music/SomeAlbum  # opens that folder
#
# Works from any directory, and via a symlink (e.g. ln -s "$PWD/ame.sh" ~/.local/bin/ame).

set -euo pipefail

SCRIPT="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
cd "$(dirname "$SCRIPT")"

# Python venv. On Linux it needs the system GTK/WebKit bindings (python3-gi, gir1.2-webkit2-*).
if [[ ! -x .venv/bin/python ]]; then
  echo "ame: creating .venv…"
  if [[ "$(uname)" == "Linux" ]]; then
    python3 -m venv --system-site-packages .venv
  else
    python3 -m venv .venv
  fi
  .venv/bin/pip install -q -r requirements.txt
elif [[ requirements.txt -nt .venv/.ame-installed ]]; then
  echo "ame: updating Python packages…"
  .venv/bin/pip install -q -r requirements.txt
fi
touch .venv/.ame-installed

# UI: build when missing or when any UI source is newer than the last build (e.g. after git pull).
if [[ ! -f ui/dist/index.html ]] || [[ -n "$(find ui/src ui/index.html ui/package.json -newer ui/dist/index.html 2>/dev/null | head -1)" ]]; then
  if ! command -v npm >/dev/null; then
    echo "ame: the UI needs building but npm isn't installed (see README)." >&2
    exit 1
  fi
  echo "ame: building the UI…"
  (cd ui && { [[ -d node_modules && node_modules -nt package.json ]] || npm install --no-audit --no-fund; } && npm run build --silent)
fi

exec .venv/bin/python main.py "$@"
