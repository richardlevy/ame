"""ame - audio metadata editor.

    python main.py [directory]          # run the built UI (ui/dist)
    python main.py --dev [directory]    # load the Vite dev server for hot reload
"""

from __future__ import annotations

import argparse
import os
import sys

import webview

from ame.api import Api

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "ui", "dist", "index.html")
DEV_URL = "http://localhost:5173"


def main() -> None:
    parser = argparse.ArgumentParser(prog="ame", description="Edit audio file tags in a folder.")
    parser.add_argument("directory", nargs="?", help="folder to open (otherwise you're asked)")
    parser.add_argument("--dev", action="store_true", help=f"load the Vite dev server at {DEV_URL}")
    parser.add_argument("--debug", action="store_true", help="enable the web inspector")
    args = parser.parse_args()

    if args.dev:
        url = DEV_URL
    else:
        if not os.path.exists(DIST):
            sys.exit("UI not built yet. Run:  cd ui && npm install && npm run build")
        url = DIST

    api = Api(args.directory)
    window = webview.create_window("ame", url, js_api=api, width=1400, height=850, min_size=(800, 500))
    api._window = window
    webview.start(debug=args.dev or args.debug, http_server=not args.dev)


if __name__ == "__main__":
    main()
