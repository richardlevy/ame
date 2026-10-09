import type { Column, FileRow, Format, SaveChange, Table } from "./api";

/** A row as held by the grid: current (editable) values plus what's on disk. */
export interface EditRow {
  id: string; // stable for the lifetime of a scan, survives renames
  file: string;
  tags: Record<string, string>;
  length: number | null;
  error?: string; // couldn't read the file
  saveError?: string; // last save failed
  orig: { file: string; tags: Record<string, string> };
}

export interface TableState {
  format: Format;
  label: string;
  columns: Column[];
  suggestions: Column[];
  rows: EditRow[];
}

export function toTableState(t: Table): TableState {
  return {
    format: t.format,
    label: t.label,
    columns: t.columns,
    suggestions: t.suggestions,
    rows: t.rows.map((r, i) => fromFileRow(`${t.format}:${i}`, r)),
  };
}

function fromFileRow(id: string, r: FileRow): EditRow {
  return {
    id,
    file: r.file,
    tags: { ...r.tags },
    length: r.length,
    error: r.error,
    orig: { file: r.file, tags: { ...r.tags } },
  };
}

/** Replace a row's values with what the backend read back after saving. */
export function applySaved(row: EditRow, saved: FileRow) {
  row.file = saved.file;
  row.tags = { ...saved.tags };
  row.length = saved.length;
  row.error = saved.error;
  row.saveError = undefined;
  row.orig = { file: saved.file, tags: { ...saved.tags } };
}

export function revert(row: EditRow) {
  row.file = row.orig.file;
  row.tags = { ...row.orig.tags };
  row.saveError = undefined;
}

export const val = (tags: Record<string, string>, key: string) => tags[key] ?? "";

export function isCellDirty(row: EditRow, key: string) {
  return val(row.tags, key) !== val(row.orig.tags, key);
}

export function isDirty(row: EditRow) {
  if (row.file !== row.orig.file) return true;
  const keys = new Set([...Object.keys(row.tags), ...Object.keys(row.orig.tags)]);
  for (const k of keys) if (isCellDirty(row, k)) return true;
  return false;
}

export function changeFor(format: Format, row: EditRow): SaveChange {
  const tags: Record<string, string> = {};
  const keys = new Set([...Object.keys(row.tags), ...Object.keys(row.orig.tags)]);
  for (const k of keys) if (isCellDirty(row, k)) tags[k] = val(row.tags, k);
  const change: SaveChange = { format, file: row.orig.file, tags };
  if (row.file !== row.orig.file) change.newName = row.file.trim();
  return change;
}

export const dirtyRows = (t: TableState) => t.rows.filter(isDirty);

export function formatLength(sec: number | null) {
  if (sec == null) return "";
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}
