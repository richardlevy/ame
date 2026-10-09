// Typed wrapper around the Python Api class (ame/api.py) exposed by pywebview.
// When the UI runs in a normal browser (npm run dev, no pywebview), a mock
// with sample data is used so the UI can be worked on in isolation.

export type Format = "mp3" | "m4a" | "flac";

export interface Column {
  key: string;
  label: string;
}

export interface FileRow {
  file: string;
  tags: Record<string, string>;
  length: number | null;
  error?: string;
}

export interface Table {
  format: Format;
  label: string;
  columns: Column[];
  suggestions: Column[];
  rows: FileRow[];
}

export interface ScanResult {
  directory: string;
  tables: Table[];
  unsupported: string[];
}

export interface SaveChange {
  format: Format;
  file: string;
  tags: Record<string, string>;
  newName?: string;
}

export interface SaveResult {
  file: string;
  ok: boolean;
  error?: string;
  row?: FileRow;
}

export type RenameStatus = "ok" | "same" | "missing" | "conflict" | "error";

export interface RenamePreview {
  file: string;
  newName: string;
  status: RenameStatus;
  message: string;
}

export interface RenameResult {
  file: string;
  newName: string;
  ok: boolean;
  error: string | null;
}

export interface AmeApi {
  get_setting<T>(key: string, fallback: T): Promise<T>;
  set_setting(key: string, value: unknown): Promise<void>;
  initial_directory(): Promise<string | null>;
  choose_directory(): Promise<string | null>;
  scan(directory: string): Promise<ScanResult>;
  normalise_key(format: Format, name: string): Promise<Column>;
  save(directory: string, changes: SaveChange[]): Promise<SaveResult[]>;
  rename_tokens(): Promise<string[]>;
  preview_rename(directory: string, pattern: string, files: { format: Format; file: string }[]): Promise<RenamePreview[]>;
  apply_rename(directory: string, pairs: { file: string; newName: string }[]): Promise<RenameResult[]>;
}

declare global {
  interface Window {
    pywebview?: { api: AmeApi };
  }
}

let apiPromise: Promise<AmeApi> | null = null;

export function getApi(): Promise<AmeApi> {
  if (!apiPromise) {
    apiPromise = new Promise((resolve) => {
      if (window.pywebview?.api) return resolve(window.pywebview.api);
      const timer = window.setTimeout(() => {
        console.warn("pywebview not found - using mock API");
        resolve(mockApi());
      }, 1500);
      window.addEventListener("pywebviewready", () => {
        window.clearTimeout(timer);
        resolve(window.pywebview!.api);
      });
    });
  }
  return apiPromise;
}

// ---------------------------------------------------------------- mock

function mockApi(): AmeApi {
  const mp3Cols: Column[] = [
    { key: "TIT2", label: "Title" }, { key: "TPE1", label: "Artist" }, { key: "TALB", label: "Album" },
    { key: "TPE2", label: "Album Artist" }, { key: "TRCK", label: "Track" }, { key: "TDRC", label: "Date" },
    { key: "TCON", label: "Genre" }, { key: "TXXX:MusicBrainz Album Id", label: "MusicBrainz Album Id" },
  ];
  const tracks = ["Intro", "Northern Line", "Static", "Glasshouse", "Low Tide", "Paper Moon"];
  const db: ScanResult = {
    directory: "/Users/demo/Music/Sample Album",
    unsupported: ["bonus.aac"],
    tables: [
      {
        format: "mp3", label: "MP3", columns: mp3Cols, suggestions: mp3Cols,
        rows: tracks.map((t, i) => ({
          file: `${String(i + 1).padStart(2, "0")} ${t.toLowerCase().replace(/ /g, "_")}.mp3`,
          length: 180 + i * 17,
          tags: {
            TIT2: t, TPE1: "The Example Band", TALB: "Sample Album", TPE2: "The Example Band",
            TRCK: `${i + 1}/${tracks.length}`, TDRC: "2019", TCON: "Indie",
            ...(i < 3 ? { "TXXX:MusicBrainz Album Id": "4f2a9c1e-8d1b-4e6a-9a1f-2b7c0e5d3a91" } : {}),
          },
        })),
      },
      {
        format: "flac", label: "FLAC",
        columns: [{ key: "TITLE", label: "Title" }, { key: "ARTIST", label: "Artist" }, { key: "ALBUM", label: "Album" }, { key: "TRACKNUMBER", label: "Track" }, { key: "DATE", label: "Date" }],
        suggestions: [],
        rows: [
          { file: "live_set_part1.flac", length: 1234, tags: { TITLE: "Live Set (Part 1)", ARTIST: "DJ Demo", ALBUM: "Live", TRACKNUMBER: "1", DATE: "2024" } },
          { file: "live_set_part2.flac", length: 1301, tags: { TITLE: "Live Set (Part 2)", ARTIST: "DJ Demo", TRACKNUMBER: "2" } },
        ],
      },
    ],
  };
  const find = (file: string) => db.tables.flatMap((t) => t.rows).find((r) => r.file === file);
  const delay = <T,>(v: T) => new Promise<T>((r) => setTimeout(() => r(structuredClone(v)), 150));
  const settings: Record<string, unknown> = {};
  return {
    get_setting: <T,>(key: string, fallback: T) => delay((settings[key] ?? fallback) as T),
    set_setting: async (key, value) => void (settings[key] = value),
    initial_directory: () => delay(null),
    choose_directory: () => delay(db.directory),
    scan: () => delay(db),
    normalise_key: (_f, name) => delay({ key: name.toUpperCase(), label: name }),
    save: (_d, changes) =>
      delay(changes.map((c) => {
        const row = find(c.file)!;
        for (const [k, v] of Object.entries(c.tags)) {
          if (v === "") delete row.tags[k];
          else row.tags[k] = v;
        }
        if (c.newName) row.file = c.newName;
        return { file: c.file, ok: true, row };
      })),
    rename_tokens: () => delay(["title", "artist", "albumartist", "album", "track", "disc", "year", "genre", "composer"]),
    preview_rename: (_d, pattern, files) =>
      delay(files.map((f) => {
        const r = find(f.file)!;
        const t = r.tags;
        const name = pattern
          .replace("{track:02}", (t.TRCK ?? t.TRACKNUMBER ?? "").split("/")[0].padStart(2, "0"))
          .replace("{artist}", t.TPE1 ?? t.ARTIST ?? "")
          .replace("{title}", t.TIT2 ?? t.TITLE ?? "") + "." + f.file.split(".").pop();
        return { file: f.file, newName: name, status: name === f.file ? "same" : "ok", message: "" } as RenamePreview;
      })),
    apply_rename: (_d, pairs) =>
      delay(pairs.map((p) => {
        find(p.file)!.file = p.newName;
        return { ...p, ok: true, error: null };
      })),
  };
}
