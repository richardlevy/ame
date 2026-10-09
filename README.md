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

## Run

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
