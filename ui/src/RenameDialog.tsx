import { useEffect, useRef, useState } from "react";
import type { AmeApi, Format, RenamePreview } from "./api";
import type { TableState } from "./model";

interface Props {
  api: AmeApi;
  directory: string;
  tables: TableState[];
  activeFormat: Format;
  unsavedCount: number;
  onClose(): void;
  onRenamed(message: string): void;
}

const PATTERN_SETTING = "renamePattern";
const DEFAULT_PATTERN = "{track:02} - {artist} - {title}";

const STATUS_LABEL: Record<RenamePreview["status"], string> = {
  ok: "Rename",
  same: "Unchanged",
  missing: "Missing tags",
  conflict: "Conflict",
  error: "Error",
};

export function RenameDialog({ api, directory, tables, activeFormat, unsavedCount, onClose, onRenamed }: Props) {
  const [pattern, setPattern] = useState(DEFAULT_PATTERN);
  const [scope, setScope] = useState<"table" | "all">("table");
  const [includeMissing, setIncludeMissing] = useState(false);
  const [tokens, setTokens] = useState<string[]>([]);
  const [previews, setPreviews] = useState<RenamePreview[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.rename_tokens().then(setTokens);
    api.get_setting(PATTERN_SETTING, DEFAULT_PATTERN).then(setPattern);
  }, [api]);

  const files = () =>
    tables
      .filter((t) => scope === "all" || t.format === activeFormat)
      .flatMap((t) => t.rows.filter((r) => !r.error).map((r) => ({ format: t.format, file: r.orig.file })));

  // live preview, debounced
  useEffect(() => {
    if (unsavedCount) return;
    const h = window.setTimeout(async () => {
      try {
        setError("");
        setPreviews(await api.preview_rename(directory, pattern, files()));
      } catch (e) {
        setPreviews(null);
        setError(String((e as Error)?.message ?? e));
      }
    }, 250);
    return () => window.clearTimeout(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pattern, scope, directory, unsavedCount]);

  const willRename = (previews ?? []).filter((p) => p.status === "ok" || (includeMissing && p.status === "missing"));

  const insertToken = (token: string) => {
    const el = inputRef.current;
    const text = `{${token}${token === "track" || token === "disc" ? ":02" : ""}}`;
    const start = el?.selectionStart ?? pattern.length;
    const end = el?.selectionEnd ?? pattern.length;
    setPattern(pattern.slice(0, start) + text + pattern.slice(end));
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + text.length, start + text.length);
    });
  };

  const apply = async () => {
    setBusy(true);
    try {
      api.set_setting(PATTERN_SETTING, pattern);
      const results = await api.apply_rename(directory, willRename.map((p) => ({ file: p.file, newName: p.newName })));
      const failed = results.filter((r) => !r.ok);
      onRenamed(
        failed.length
          ? `Renamed ${results.length - failed.length} files; ${failed.length} failed (${failed[0].error})`
          : `Renamed ${results.length} file${results.length === 1 ? "" : "s"}`,
      );
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const counts = (previews ?? []).reduce<Record<string, number>>((acc, p) => ((acc[p.status] = (acc[p.status] ?? 0) + 1), acc), {});

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label="Rename files">
        <header>
          <h2>Rename files from tags</h2>
          <button className="icon" onClick={onClose} aria-label="Close">×</button>
        </header>

        {unsavedCount > 0 ? (
          <p className="warning">
            You have {unsavedCount} unsaved change{unsavedCount === 1 ? "" : "s"}. Save or revert them first; renaming uses
            the tags stored in the files.
          </p>
        ) : (
          <>
            <label className="field">
              Pattern
              <input ref={inputRef} className="mono" value={pattern} onChange={(e) => setPattern(e.target.value)} spellCheck={false} />
            </label>
            <div className="tokens">
              {tokens.map((t) => (
                <button key={t} className="chip" onClick={() => insertToken(t)}>{`{${t}}`}</button>
              ))}
              <span className="hint">Add a width for numbers, e.g. {"{track:02}"}. The extension is kept.</span>
            </div>
            <div className="options">
              <label><input type="radio" checked={scope === "table"} onChange={() => setScope("table")} /> This table</label>
              <label><input type="radio" checked={scope === "all"} onChange={() => setScope("all")} /> All tables</label>
              <label className="push">
                <input type="checkbox" checked={includeMissing} onChange={(e) => setIncludeMissing(e.target.checked)} /> Include files with missing tags
              </label>
            </div>

            {error && <p className="warning">{error}</p>}

            <div className="preview">
              <table>
                <thead>
                  <tr><th>Current name</th><th>New name</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {(previews ?? []).map((p) => (
                    <tr key={p.file} className={`st-${p.status}`}>
                      <td className="mono">{p.file}</td>
                      <td className="mono">{p.newName}</td>
                      <td title={p.message}>
                        <span className={`badge ${p.status}`}>{STATUS_LABEL[p.status]}</span>
                        {p.message && <span className="hint"> {p.message}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint summary">
              {Object.entries(counts).map(([k, n]) => `${n} ${STATUS_LABEL[k as RenamePreview["status"]].toLowerCase()}`).join(" · ")}
            </p>
          </>
        )}

        <footer>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || !!unsavedCount || !willRename.length} onClick={apply}>
            {busy ? "Renaming…" : `Rename ${willRename.length} file${willRename.length === 1 ? "" : "s"}`}
          </button>
        </footer>
      </div>
    </div>
  );
}
