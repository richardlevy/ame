import { useEffect, useRef, useState } from "react";
import type { AmeApi, ArtAlbum, ArtApplyResult, ArtCandidate } from "./api";
import type { TableState } from "./model";

interface Props {
  api: AmeApi;
  directory: string;
  tables: TableState[];
  unsavedCount: number;
  onClose(): void;
  onApplied(files: string[], message: string, isError: boolean): void;
}

interface Options {
  embed: boolean;
  saveFolder: boolean;
  folderName: string;
  limitSize: boolean;
  maxSize: number;
  replace: boolean;
}

const DEFAULT_OPTIONS: Options = {
  embed: true,
  saveFolder: true,
  folderName: "cover.jpg",
  limitSize: true,
  maxSize: 500,
  replace: false,
};
const OPTIONS_SETTING = "coverArt";

interface AlbumState {
  album: ArtAlbum;
  query: { album: string; artist: string };
  loading: boolean;
  searched: boolean;
  candidates: ArtCandidate[];
  errors: string[];
  broken: Set<string>; // candidate urls whose thumbnail failed (no art at source)
  selected: ArtCandidate | null;
  current: string | null; // existing embedded art thumbnail
  result?: { ok: boolean; text: string };
}

export function CoverArtDialog({ api, directory, tables, unsavedCount, onClose, onApplied }: Props) {
  const [albums, setAlbums] = useState<AlbumState[] | null>(null);
  const [options, setOptions] = useState<Options>(DEFAULT_OPTIONS);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const albumsRef = useRef<AlbumState[]>([]);

  const update = (id: string, patch: Partial<AlbumState> | ((a: AlbumState) => Partial<AlbumState>)) => {
    albumsRef.current = albumsRef.current.map((a) =>
      a.album.id === id ? { ...a, ...(typeof patch === "function" ? patch(a) : patch) } : a,
    );
    setAlbums(albumsRef.current);
  };

  const search = async (id: string) => {
    const a = albumsRef.current.find((x) => x.album.id === id);
    if (!a) return;
    update(id, { loading: true, errors: [] });
    try {
      const mbid = a.query.album === a.album.album && a.query.artist === a.album.artist ? a.album.mbid : "";
      const res = await api.art_search(a.query.album, a.query.artist, mbid);
      update(id, (cur) => ({
        loading: false,
        searched: true,
        candidates: res.candidates,
        errors: res.errors,
        broken: new Set(),
        selected: cur.selected && !cur.selected.url.startsWith("file://") ? null : cur.selected,
      }));
    } catch (e) {
      update(id, { loading: false, searched: true, candidates: [], errors: [String((e as Error)?.message ?? e)] });
    }
  };

  // load albums, existing art and saved options, then search each album in turn
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const saved = await api.get_setting<Partial<Options>>(OPTIONS_SETTING, {});
        setOptions({ ...DEFAULT_OPTIONS, ...saved });
        const files = tables.flatMap((t) => t.rows.filter((r) => !r.error).map((r) => ({ format: t.format, file: r.orig.file })));
        const list = await api.art_albums(directory, files);
        albumsRef.current = list.map((album) => ({
          album,
          query: { album: album.album, artist: album.artist },
          loading: false,
          searched: false,
          candidates: [],
          errors: [],
          broken: new Set(),
          selected: null,
          current: null,
        }));
        setAlbums(albumsRef.current);
        for (const a of list) {
          const withArt = a.files.find((f) => f.hasArt);
          if (withArt) api.art_current(directory, withArt.format, withArt.file).then((c) => !cancelled && update(a.id, { current: c }));
        }
        for (const a of list) {
          if (cancelled) return;
          if (a.album) await search(a.id); // sequential: MusicBrainz allows ~1 request/second
        }
      } catch (e) {
        setLoadError(String((e as Error)?.message ?? e));
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setOpt = <K extends keyof Options>(k: K, v: Options[K]) => setOptions((o) => ({ ...o, [k]: v }));

  const chooseFile = async (id: string) => {
    const pick = await api.art_choose_file();
    if (!pick) return;
    const local: ArtCandidate = {
      source: "Local file", title: pick.url.split("/").pop() ?? "", artist: "", year: "",
      detail: `${pick.width}×${pick.height}`, thumb: pick.thumb, url: pick.url,
    };
    update(id, (a) => ({ candidates: [local, ...a.candidates.filter((c) => !c.url.startsWith("file://"))], selected: local }));
  };

  const chosen = (albums ?? []).filter((a) => a.selected);
  const folderAllowed = chosen.length <= 1;
  const nothingToDo = !options.embed && !(options.saveFolder && folderAllowed);

  const apply = async () => {
    setBusy(true);
    api.set_setting(OPTIONS_SETTING, options);
    const updatedFiles: string[] = [];
    let failures = 0;
    let embedded = 0;
    for (const a of chosen) {
      try {
        const res: ArtApplyResult = await api.art_apply(directory, {
          url: a.selected!.url,
          original: a.selected!.original,
          files: a.album.files.map(({ format, file }) => ({ format, file })),
          embed: options.embed,
          folderFile: options.saveFolder && folderAllowed ? options.folderName : "",
          maxSize: options.limitSize ? options.maxSize : 0,
          replace: options.replace,
        });
        embedded += res.embedded;
        if (options.embed) {
          // files that now have art: newly embedded, or skipped because they already had some
          updatedFiles.push(...a.album.files.map((f) => f.file));
        }
        const parts = [`${res.width}×${res.height}`];
        if (options.embed) parts.push(`embedded in ${res.embedded} file${res.embedded === 1 ? "" : "s"}`);
        if (res.skipped) parts.push(`${res.skipped} skipped (already had art)`);
        if (res.folderFile) parts.push(`saved ${res.folderFile}`);
        if (res.errors.length) failures++;
        update(a.album.id, { result: { ok: !res.errors.length, text: [parts.join(", "), ...res.errors].join(" · ") } });
      } catch (e) {
        failures++;
        update(a.album.id, { result: { ok: false, text: String((e as Error)?.message ?? e) } });
      }
    }
    setBusy(false);
    onApplied(
      updatedFiles,
      failures ? `Cover art: ${failures} album(s) had problems — see the dialog` : `Cover art applied${embedded ? ` to ${embedded} file${embedded === 1 ? "" : "s"}` : ""}`,
      failures > 0,
    );
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal art-modal" role="dialog" aria-label="Fetch cover art">
        <header>
          <h2>Fetch cover art</h2>
          <button className="icon" onClick={onClose} disabled={busy} aria-label="Close">×</button>
        </header>

        {unsavedCount > 0 && (
          <p className="warning">
            Albums are grouped using the tags saved in the files. Save your {unsavedCount} pending change
            {unsavedCount === 1 ? "" : "s"} first if you've edited album or artist names.
          </p>
        )}
        {loadError && <p className="warning">{loadError}</p>}

        <div className="art-albums">
          {albums === null && !loadError && <p className="hint">Reading albums…</p>}
          {albums?.length === 0 && <p className="hint">No readable files.</p>}
          {albums?.map((a) => {
            const visible = a.candidates.filter((c) => !a.broken.has(c.url));
            const missing = a.album.files.filter((f) => !f.hasArt).length;
            return (
              <section key={a.album.id} className="art-album">
                <div className="art-album-head">
                  <div className="art-current" title={a.current ? "Current embedded art" : "No embedded art"}>
                    {a.current ? <img src={a.current} alt="" /> : <span>no art</span>}
                  </div>
                  <div className="art-album-info">
                    <div className="art-album-title">{a.album.album || <em>No album tag</em>}</div>
                    <div className="hint">
                      {a.album.artist || "Unknown artist"} · {a.album.files.length} file{a.album.files.length === 1 ? "" : "s"}
                      {missing ? ` · ${missing} without art` : " · all have art"}
                    </div>
                    <div className="art-query">
                      <input
                        value={a.query.album}
                        placeholder="Album"
                        onChange={(e) => update(a.album.id, (s) => ({ query: { ...s.query, album: e.target.value } }))}
                        onKeyDown={(e) => e.key === "Enter" && search(a.album.id)}
                      />
                      <input
                        value={a.query.artist}
                        placeholder="Artist"
                        onChange={(e) => update(a.album.id, (s) => ({ query: { ...s.query, artist: e.target.value } }))}
                        onKeyDown={(e) => e.key === "Enter" && search(a.album.id)}
                      />
                      <button onClick={() => search(a.album.id)} disabled={a.loading || busy || !a.query.album.trim()}>Search</button>
                      <button onClick={() => chooseFile(a.album.id)} disabled={busy}>Choose image…</button>
                    </div>
                  </div>
                  {a.result && <div className={`art-result ${a.result.ok ? "ok" : "error"}`}>{a.result.text}</div>}
                </div>

                <div className="art-candidates">
                  {a.loading && <span className="hint">Searching…</span>}
                  {!a.loading && a.searched && visible.length === 0 && (
                    <span className="hint">No covers found. Try different search terms or choose an image file.</span>
                  )}
                  {!a.loading && !a.searched && !a.album.album && (
                    <span className="hint">These files have no album tag. Type a search above, or choose an image file.</span>
                  )}
                  {visible.map((c) => (
                    <button
                      key={c.url}
                      className={`art-candidate ${a.selected?.url === c.url ? "selected" : ""}`}
                      onClick={() => update(a.album.id, (s) => ({ selected: s.selected?.url === c.url ? null : c, result: undefined }))}
                      title={`${c.title} — ${c.artist}\n${c.source}${c.detail ? ` · ${c.detail}` : ""}`}
                    >
                      <img
                        src={c.thumb}
                        alt=""
                        loading="lazy"
                        onError={() => update(a.album.id, (s) => ({ broken: new Set(s.broken).add(c.url), selected: s.selected?.url === c.url ? null : s.selected }))}
                      />
                      <span className="art-cap">
                        <strong>{c.source}</strong>
                        <span>{[c.year, c.detail].filter(Boolean).join(" · ")}</span>
                        <span className="art-cap-title">{c.title}</span>
                      </span>
                    </button>
                  ))}
                  {a.errors.map((e) => (
                    <span key={e} className="hint art-error">{e}</span>
                  ))}
                </div>
              </section>
            );
          })}
        </div>

        <div className="art-options">
          <label><input type="checkbox" checked={options.embed} onChange={(e) => setOpt("embed", e.target.checked)} /> Embed in audio files</label>
          <label title={folderAllowed ? "" : "Only one image file can live in the folder — select a cover for just one album to use this"}>
            <input type="checkbox" checked={options.saveFolder} onChange={(e) => setOpt("saveFolder", e.target.checked)} disabled={!folderAllowed} />
            Save in folder as
            <input className="mono small" value={options.folderName} onChange={(e) => setOpt("folderName", e.target.value)} disabled={!options.saveFolder || !folderAllowed} />
          </label>
          <label>
            <input type="checkbox" checked={options.limitSize} onChange={(e) => setOpt("limitSize", e.target.checked)} /> Resize to at most
            <input
              className="small"
              type="number"
              min={100}
              max={5000}
              step={50}
              value={options.maxSize}
              onChange={(e) => setOpt("maxSize", Math.max(50, Number(e.target.value) || DEFAULT_OPTIONS.maxSize))}
              disabled={!options.limitSize}
            />
            × {options.limitSize ? options.maxSize : "…"} px
          </label>
          <label><input type="checkbox" checked={options.replace} onChange={(e) => setOpt("replace", e.target.checked)} /> Replace existing art</label>
        </div>
        {!folderAllowed && options.saveFolder && (
          <p className="hint">Folder image skipped: covers are selected for {chosen.length} albums, but the folder can only hold one {options.folderName}.</p>
        )}

        <footer>
          <span className="hint push-left">
            {options.limitSize ? `Larger images are scaled down to fit ${options.maxSize}×${options.maxSize}; smaller ones are kept as they are.` : "Images are kept at their original size."}
          </span>
          <button onClick={onClose} disabled={busy}>Close</button>
          <button className="primary" disabled={busy || !chosen.length || nothingToDo} onClick={apply}>
            {busy ? "Applying…" : `Apply to ${chosen.length} album${chosen.length === 1 ? "" : "s"}`}
          </button>
        </footer>
      </div>
    </div>
  );
}
