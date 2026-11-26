import { useEffect, useRef, useState } from "react";
import type { AmeApi, ConvertInfo, ConvertOptions, ConvertResult } from "./api";
import { isDirty, type EditRow } from "./model";

interface Props {
  api: AmeApi;
  directory: string;
  rows: EditRow[]; // every FLAC row
  initiallySelected: string[]; // orig file names; empty = all
  onClose(converted: number, sameFolder: boolean): void;
}

const DEFAULT_OPTIONS: ConvertOptions = { quality: "v0", destination: "same", subfolder: "MP3", overwrite: false };
const OPTIONS_SETTING = "convertMp3";

type Status = "pending" | "running" | ConvertResult["status"] | "cancelled";

const STATUS_LABEL: Record<Status, string> = {
  pending: "Waiting",
  running: "Converting…",
  converted: "Done",
  exists: "Skipped",
  error: "Failed",
  cancelled: "Cancelled",
};

export function ConvertDialog({ api, directory, rows, initiallySelected, onClose }: Props) {
  const usable = rows.filter((r) => !r.error);
  const [info, setInfo] = useState<ConvertInfo | null>(null);
  const [options, setOptions] = useState<ConvertOptions>(DEFAULT_OPTIONS);
  const [checked, setChecked] = useState<Set<string>>(
    () => new Set(initiallySelected.length ? initiallySelected : usable.map((r) => r.orig.file)),
  );
  const [results, setResults] = useState<Record<string, { status: Status; detail: string }>>({});
  const [running, setRunning] = useState(false);
  const [finished, setFinished] = useState(false);
  const cancelRef = useRef(false);

  useEffect(() => {
    api.convert_info().then(setInfo);
    api.get_setting<Partial<ConvertOptions>>(OPTIONS_SETTING, {}).then((o) => setOptions({ ...DEFAULT_OPTIONS, ...o }));
  }, [api]);

  const setOpt = <K extends keyof ConvertOptions>(k: K, v: ConvertOptions[K]) => setOptions((o) => ({ ...o, [k]: v }));
  const toggle = (file: string) =>
    setChecked((c) => {
      const n = new Set(c);
      if (n.has(file)) n.delete(file);
      else n.add(file);
      return n;
    });

  const queue = usable.filter((r) => checked.has(r.orig.file));
  const dirtyChecked = queue.filter(isDirty).length;
  const done = Object.values(results).filter((r) => !["pending", "running"].includes(r.status)).length;
  const counts = Object.values(results).reduce<Record<string, number>>((a, r) => ((a[r.status] = (a[r.status] ?? 0) + 1), a), {});
  const outName = (file: string) => {
    const base = file.replace(/\.[^.]+$/, "") + ".mp3";
    return options.destination === "subfolder" ? `${options.subfolder || "MP3"}/${base}` : base;
  };

  const start = async () => {
    cancelRef.current = false;
    setRunning(true);
    setFinished(false);
    api.set_setting(OPTIONS_SETTING, options);
    const initial: typeof results = {};
    for (const r of queue) initial[r.orig.file] = { status: "pending", detail: "" };
    setResults(initial);
    for (const r of queue) {
      const file = r.orig.file;
      if (cancelRef.current) {
        setResults((s) => ({ ...s, [file]: { status: "cancelled", detail: "" } }));
        continue;
      }
      setResults((s) => ({ ...s, [file]: { status: "running", detail: "" } }));
      const res = await api.convert_flac(directory, file, options);
      const detail =
        res.status === "converted"
          ? `${res.output}${res.seconds != null ? ` · ${res.seconds}s` : ""}`
          : res.status === "exists"
            ? `${res.output} already exists`
            : res.message;
      setResults((s) => ({ ...s, [file]: { status: res.status, detail } }));
    }
    setRunning(false);
    setFinished(true);
  };

  const close = () => {
    if (running) return;
    onClose(counts.converted ?? 0, options.destination === "same");
  };

  const unavailable = info && !info.available;

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="modal convert-modal" role="dialog" aria-label="Convert to MP3">
        <header>
          <h2>Convert FLAC to MP3</h2>
          <button className="icon" onClick={close} disabled={running} aria-label="Close">×</button>
        </header>

        {unavailable && <p className="warning">{info.message}</p>}
        {dirtyChecked > 0 && !running && !finished && (
          <p className="warning">
            {dirtyChecked} selected file{dirtyChecked === 1 ? " has" : "s have"} unsaved changes. Conversion copies the tags saved in
            the FLAC, so save first if you want your edits in the MP3s.
          </p>
        )}

        <div className="convert-options">
          <label>
            Quality
            <select value={options.quality} onChange={(e) => setOpt("quality", e.target.value)} disabled={running}>
              {(info?.qualities ?? []).map((q) => (
                <option key={q.id} value={q.id}>{q.label}</option>
              ))}
            </select>
          </label>
          <label>
            <input type="radio" checked={options.destination === "same"} onChange={() => setOpt("destination", "same")} disabled={running} />
            Same folder
          </label>
          <label>
            <input type="radio" checked={options.destination === "subfolder"} onChange={() => setOpt("destination", "subfolder")} disabled={running} />
            Subfolder
            <input
              className="small mono"
              value={options.subfolder}
              onChange={(e) => setOpt("subfolder", e.target.value)}
              disabled={running || options.destination !== "subfolder"}
            />
          </label>
          <label>
            <input type="checkbox" checked={options.overwrite} onChange={(e) => setOpt("overwrite", e.target.checked)} disabled={running} />
            Overwrite existing MP3s
          </label>
        </div>

        <div className="preview">
          <table>
            <thead>
              <tr>
                <th className="check-col">
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={checked.size === usable.length && usable.length > 0}
                    ref={(el) => el && (el.indeterminate = checked.size > 0 && checked.size < usable.length)}
                    onChange={(e) => setChecked(e.target.checked ? new Set(usable.map((r) => r.orig.file)) : new Set())}
                    disabled={running}
                  />
                </th>
                <th>FLAC file</th>
                <th>MP3</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {usable.map((r) => {
                const res = results[r.orig.file];
                return (
                  <tr key={r.id} className={checked.has(r.orig.file) ? "" : "st-same"}>
                    <td className="check-col">
                      <input type="checkbox" checked={checked.has(r.orig.file)} onChange={() => toggle(r.orig.file)} disabled={running} />
                    </td>
                    <td className="mono">{r.orig.file}</td>
                    <td className="mono">{checked.has(r.orig.file) ? outName(r.orig.file) : ""}</td>
                    <td>
                      {res && (
                        <span title={res.detail} className={`badge ${{ converted: "ok", exists: "missing", error: "error" }[res.status as string] ?? ""}`}>
                          {STATUS_LABEL[res.status]}
                        </span>
                      )}
                      {res?.detail && res.status !== "converted" && <span className="hint"> {res.detail}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {(running || finished) && (
          <div className="progress">
            <div className="progress-bar"><div style={{ width: `${queue.length ? (done / queue.length) * 100 : 0}%` }} /></div>
            <span className="hint">
              {done} of {queue.length}
              {counts.converted ? ` · ${counts.converted} converted` : ""}
              {counts.exists ? ` · ${counts.exists} skipped (MP3 already exists)` : ""}
              {counts.error ? ` · ${counts.error} failed` : ""}
            </span>
          </div>
        )}

        <footer>
          {info?.version && <span className="hint push-left">ffmpeg {info.version} · tags and cover art are copied</span>}
          {running ? (
            <button onClick={() => (cancelRef.current = true)}>Stop after this file</button>
          ) : (
            <button onClick={close}>{finished ? "Close" : "Cancel"}</button>
          )}
          {!finished && (
            <button className="primary" disabled={running || !queue.length || !info?.available} onClick={start}>
              {running ? "Converting…" : `Convert ${queue.length} file${queue.length === 1 ? "" : "s"}`}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
