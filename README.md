# ame — audio metadata editor

Edit the tags of every mp3, m4a (AAC) and flac file in a folder in editable tables, then save one file, one table or everything. Files can also be renamed from their tags.

- **Backend:** Python + [mutagen](https://mutagen.readthedocs.io/)
- **UI:** React + TypeScript + [AG Grid](https://www.ag-grid.com/) (community), in a native window via [pywebview](https://pywebview.flowrl.com/)

## Setup

```bash
cd ~/Development/python/ame
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd ui
npm install
npm run build        # outputs ui/dist, which main.py loads
cd ..
```

### Raspberry Pi (Raspberry Pi OS)

ame opens a window, so it needs the Pi desktop rather than a headless/Lite install.

**Node and npm:** the NodeSource packages are newer than Raspberry Pi OS's own. They work on 64-bit Raspberry Pi OS and on 32-bit Pi 2 or newer, but not on the original Pi Zero or Pi 1 (ARMv6).

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node -v && npm -v
```

`sudo apt install -y nodejs npm` (Node 18 on Bookworm) also works if you'd rather stick to the distro packages.

**pywebview's GUI libraries:** on Linux, pywebview uses the system's GTK and WebKit, which come from apt, not pip. Install them, then create the venv with `--system-site-packages` so it can see them:

```bash
sudo apt install -y python3-gi gir1.2-webkit2-4.1    # gir1.2-webkit2-4.0 on older releases

cd ~/Development/python/ame
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c "import gi; print('ok')"                    # should print ok
```

If you already made `.venv` without the flag, either delete it and recreate it as above (`deactivate && rm -rf .venv`), or set `include-system-site-packages = true` in `.venv/pyvenv.cfg` and re-activate.

**Display corruption:** with WebKitGTK's default DMA-BUF renderer, the window shows a corrupted screen on the Pi once a folder loads. The fix is `WEBKIT_DISABLE_DMABUF_RENDERER=1`, and `main.py` sets it automatically when it detects a Raspberry Pi, so a plain `python main.py` works.

- On other Linux machines with the same symptom, set it yourself: `WEBKIT_DISABLE_DMABUF_RENDERER=1 python main.py`.
- If that alone doesn't fix it, also try `WEBKIT_DISABLE_COMPOSITING_MODE=1`. This turns off GPU compositing entirely.
- To turn the Pi default off, run `WEBKIT_DISABLE_DMABUF_RENDERER=0 python main.py`.

Then build the UI as normal (`cd ui && npm install && npm run build`). If that's slow on an older Pi, build `ui/dist` on another machine and copy the folder across.

## Run

The simplest way, on the Pi or the Mac:

```bash
./ame.sh                       # asks for a folder
./ame.sh ~/Music/SomeAlbum     # opens that folder
```

`ame.sh` works from any directory and doesn't need the venv activated. Before launching, it:
- creates `.venv` if it's missing (with `--system-site-packages` on Linux), and reinstalls Python packages when `requirements.txt` changes
- rebuilds the UI when `ui/dist` is missing or older than the UI source, so `git pull` then `./ame.sh` is all an update needs

To run it as `ame` from anywhere: `ln -s ~/Development/python/ame/ame.sh ~/.local/bin/ame` (with `~/.local/bin` on your `PATH`).

Or run it by hand:

```bash
source .venv/bin/activate
python main.py                       # asks for a folder
python main.py ~/Music/SomeAlbum     # opens that folder straight away
```

### UI development with hot reload

```bash
cd ui && npm run dev                 # terminal 1: Vite on http://localhost:5173
python main.py --dev                 # terminal 2: app window loads the dev server
```

`npm run dev` also works in a normal browser. Without pywebview it falls back to a mock API with sample data (see `ui/src/api.ts`), which is useful for styling work. `--debug` enables the web inspector (right-click → Inspect).

## Using it

- **One tab per format:** MP3, AAC / M4A, FLAC. Raw `.aac` (ADTS) files have no tag container, so they're listed as skipped.
- **Every cell is editable,** including the file name. Changed cells are highlighted, and hovering one shows the old value. ⌘Z / ⌘⇧Z undo and redo edits.
- **Saving:** use **Save** on a row, **Save table**, or **Save all** (⌘S). Each row and table can also be reverted.
- **Multiple values** are shown joined with `; `. Typing `A; B` writes two values. *Note:* ID3v2.3 mp3s can't store true multi-values, so mutagen writes `A/B`. Files keep their ID3 version (2.3 or 2.4).
- **Emptying a cell** deletes that tag.
- **Set field…** writes one value into a column for the selected rows. If no rows are selected, it fills every visible row (the filter box narrows that).
- **Add column** adds any tag: type a common name (`Composer`, `BPM`, `Album Artist`) or a native key. Unknown names become `TXXX:<name>` (mp3), `----:com.apple.iTunes:<name>` (m4a) or an upper-cased Vorbis field (flac).
- **Rename files…** builds names from a pattern, e.g. `{track:02} - {artist} - {title}`. You get a live preview with conflict detection, and the extension is always kept. Save any edits first, because renaming reads the tags stored on disk. The last pattern is remembered in `~/.config/ame/settings.json`.

Artwork and other binary frames (APIC, covr, PRIV…) are left untouched and aren't shown.

## Layout

```
main.py              entry point: argument parsing, pywebview window
ame/api.py           Api class exposed to JS as window.pywebview.api
ame/tags.py          mutagen read/write per format, column labels, key normalising
ame/rename.py        pattern → filename, safe batch rename (handles swaps)
ui/src/App.tsx       folder loading, tabs, save/revert orchestration
ui/src/FormatTable.tsx   AG Grid table for one format
ui/src/RenameDialog.tsx  rename-from-tags dialog
ui/src/model.ts      edit/dirty tracking
ui/src/api.ts        typed bridge to Python + browser mock
```
