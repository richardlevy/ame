import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { colorSchemeDarkBlue, colorSchemeLight, themeQuartz, type GridApi } from "ag-grid-community";
import { getApi, type AmeApi, type Format } from "./api";
import { FormatTable } from "./FormatTable";
import { RenameDialog } from "./RenameDialog";
import { applySaved, changeFor, dirtyRows, isDirty, revert, toTableState, type EditRow, type TableState } from "./model";

interface Toast {
  id: number;
  text: string;
  kind: "info" | "error";
}

function useDarkMode() {
  const query = "(prefers-color-scheme: dark)";
  const [dark, setDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return dark;
}

export default function App() {
  const [api, setApi] = useState<AmeApi | null>(null);
  const [directory, setDirectory] = useState<string | null>(null);
  const [tables, setTables] = useState<TableState[]>([]);
  const [unsupported, setUnsupported] = useState<string[]>([]);
  const [active, setActive] = useState<Format | null>(null);
  const [loading, setLoading] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [, setVersion] = useState(0); // bumped after in-place edits to re-render counts
  const grids = useRef<Partial<Record<Format, GridApi<EditRow>>>>({});
  const dark = useDarkMode();

  const theme = useMemo(
    () =>
      themeQuartz.withPart(dark ? colorSchemeDarkBlue : colorSchemeLight).withParams({
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        fontSize: 13,
        spacing: 5,
        accentColor: dark ? "#6ea8fe" : "#2f6fde",
        headerFontWeight: 600,
        wrapperBorderRadius: 0,
      }),
    [dark],
  );

  const bump = useCallback(() => setVersion((v) => v + 1), []);

  const toast = useCallback((text: string, kind: Toast["kind"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, kind }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 8000 : 3500);
  }, []);

  const unsavedCount = tables.reduce((n, t) => n + dirtyRows(t).length, 0);

  const load = useCallback(
    async (dir: string, a: AmeApi | null = api) => {
      if (!a) return;
      setLoading(true);
      try {
        const res = await a.scan(dir);
        grids.current = {};
        setDirectory(res.directory);
        setTables(res.tables.map(toTableState));
        setUnsupported(res.unsupported);
        setActive((cur) => (res.tables.some((t) => t.format === cur) ? cur : res.tables[0]?.format ?? null));
      } catch (e) {
        toast(String((e as Error)?.message ?? e), "error");
      } finally {
        setLoading(false);
      }
    },
    [api, toast],
  );

  const chooseFolder = useCallback(
    async (a: AmeApi | null = api) => {
      if (!a) return;
      if (unsavedCount && !window.confirm(`Discard ${unsavedCount} unsaved change(s)?`)) return;
      const dir = await a.choose_directory();
      if (dir) await load(dir, a);
    },
    [api, load, unsavedCount],
  );

  // start-up: open the folder given on the command line, or ask for one
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // StrictMode runs effects twice in dev
    started.current = true;
    getApi().then(async (a) => {
      setApi(a);
      const initial = await a.initial_directory();
      if (initial) await load(initial, a);
      else await chooseFolder(a);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // warn before closing / reloading with unsaved edits (where the webview supports it)
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => {
      if (unsavedCount) e.preventDefault();
    };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [unsavedCount]);

  const save = useCallback(
    async (format: Format, rows: EditRow[]) => {
      if (!api || !directory) return 0;
      const dirty = rows.filter(isDirty);
      if (!dirty.length) return 0;
      const results = await api.save(directory, dirty.map((r) => changeFor(format, r)));
      let failed = 0;
      results.forEach((res, i) => {
        const row = dirty[i];
        if (res.ok && res.row) applySaved(row, res.row);
        else {
          row.saveError = res.error ?? "Save failed";
          failed++;
        }
      });
      grids.current[format]?.refreshCells({ force: true });
      bump();
      if (failed) {
        const first = results.find((r) => !r.ok);
        toast(`${failed} file(s) not saved — ${first?.file}: ${first?.error}`, "error");
      }
      return dirty.length - failed;
    },
    [api, directory, bump, toast],
  );

  const saveAndReport = async (format: Format, rows: EditRow[]) => {
    const n = await save(format, rows);
    if (n) toast(`Saved ${n} file${n === 1 ? "" : "s"}`);
  };

  const saveAll = async () => {
    let n = 0;
    for (const t of tables) n += await save(t.format, dirtyRows(t));
    if (n) toast(`Saved ${n} file${n === 1 ? "" : "s"}`);
  };

  const revertRows = (format: Format, rows: EditRow[]) => {
    rows.forEach(revert);
    grids.current[format]?.refreshCells({ force: true });
    bump();
  };

  const addColumn = async (format: Format, name: string) => {
    if (!api || !name.trim()) return false;
    try {
      const col = await api.normalise_key(format, name);
      setTables((ts) =>
        ts.map((t) => {
          if (t.format !== format) return t;
          if (t.columns.some((c) => c.key === col.key)) {
            toast(`"${col.label}" is already a column`);
            return t;
          }
          return { ...t, columns: [...t.columns, col] };
        }),
      );
      window.setTimeout(() => grids.current[format]?.ensureColumnVisible(col.key, "end"), 50);
      return true;
    } catch (e) {
      toast(String((e as Error)?.message ?? e), "error");
      return false;
    }
  };

  // Cmd/Ctrl+S saves everything
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        saveAll();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  const activeTable = tables.find((t) => t.format === active);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">ame</div>
        <div className="path" title={directory ?? ""}>
          <bdi>{directory ?? (api ? "No folder open" : "Starting…")}</bdi>
        </div>
        <button onClick={() => chooseFolder()} disabled={!api}>Open folder…</button>
        <button
          onClick={() => directory && (!unsavedCount || window.confirm(`Discard ${unsavedCount} unsaved change(s)?`)) && load(directory)}
          disabled={!directory}
          title="Re-read the folder from disk"
        >
          Reload
        </button>
        <button onClick={() => setRenameOpen(true)} disabled={!activeTable}>Rename files…</button>
        <button className="primary" onClick={saveAll} disabled={!unsavedCount} title="Save every table (⌘S)">
          Save all{unsavedCount ? ` (${unsavedCount})` : ""}
        </button>
      </header>

      {tables.length > 0 && (
        <nav className="tabs">
          {tables.map((t) => {
            const d = dirtyRows(t).length;
            return (
              <button key={t.format} className={`tab ${t.format === active ? "active" : ""}`} onClick={() => setActive(t.format)}>
                {t.label}
                <span className="count">{t.rows.length}</span>
                {d > 0 && <span className="dirty-count" title={`${d} unsaved`}>{d}</span>}
              </button>
            );
          })}
          {unsupported.length > 0 && (
            <span className="note" title={unsupported.join("\n")}>
              {unsupported.length} raw .aac file{unsupported.length === 1 ? "" : "s"} skipped (no tag container)
            </span>
          )}
        </nav>
      )}

      <main className="content">
        {loading && <div className="empty">Reading tags…</div>}
        {!loading && directory && tables.length === 0 && (
          <div className="empty">
            <p>No mp3, m4a or flac files in this folder.</p>
            <button onClick={() => chooseFolder()}>Choose another folder…</button>
          </div>
        )}
        {!loading && !directory && api && (
          <div className="empty">
            <p>Choose a folder of audio files to edit their tags.</p>
            <button className="primary" onClick={() => chooseFolder()}>Open folder…</button>
          </div>
        )}
        {!loading &&
          tables.map((t) => (
            <FormatTable
              key={`${directory}:${t.format}`}
              table={t}
              theme={theme}
              visible={t.format === active}
              onGridReady={(g) => (grids.current[t.format] = g)}
              onEdited={bump}
              onSave={(rows) => saveAndReport(t.format, rows)}
              onRevert={(rows) => revertRows(t.format, rows)}
              onAddColumn={(name) => addColumn(t.format, name)}
            />
          ))}
      </main>

      {renameOpen && api && directory && active && (
        <RenameDialog
          api={api}
          directory={directory}
          tables={tables}
          activeFormat={active}
          unsavedCount={unsavedCount}
          onClose={() => setRenameOpen(false)}
          onRenamed={async (msg) => {
            setRenameOpen(false);
            await load(directory);
            toast(msg, msg.includes("failed") ? "error" : "info");
          }}
        />
      )}

      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>
        ))}
      </div>
    </div>
  );
}
