import { useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import type {
  CellValueChangedEvent,
  ColDef,
  GridApi,
  GetRowIdParams,
  ICellRendererParams,
  RowSelectionOptions,
  SelectionColumnDef,
  Theme,
} from "ag-grid-community";
import { formatLength, isCellDirty, isDirty, val, type EditRow, type TableState } from "./model";

interface Props {
  table: TableState;
  theme: Theme;
  visible: boolean;
  onGridReady(api: GridApi<EditRow>): void;
  onEdited(): void;
  onSave(rows: EditRow[]): void;
  onRevert(rows: EditRow[]): void;
  onAddColumn(name: string): Promise<boolean>;
}

// Grid options are module constants: if they were recreated on each render, AG Grid
// would treat them as new column config and reset widths the user has dragged.
// Column defs use initialWidth (not width) so adding a column doesn't reset widths either.
const DEFAULT_COL_DEF: ColDef<EditRow> = { sortable: true, resizable: true, filter: false };
const ROW_SELECTION: RowSelectionOptions<EditRow> = { mode: "multiRow", checkboxes: true, headerCheckbox: true, enableClickSelection: false };
const SELECTION_COL_DEF: SelectionColumnDef = { pinned: "left", initialWidth: 44 };
const getRowId = (p: GetRowIdParams<EditRow>) => p.data.id;

const LONG_TEXT = /^(USLT|COMM)|LYRICS|COMMENT|DESCRIPTION|©lyr|©cmt|^desc$/i;

export function FormatTable({ table, theme, visible, onGridReady, onEdited, onSave, onRevert, onAddColumn }: Props) {
  const gridRef = useRef<AgGridReact<EditRow>>(null);
  const [quickFilter, setQuickFilter] = useState("");
  const [newTag, setNewTag] = useState("");
  const [fillOpen, setFillOpen] = useState(false);
  const [fillKey, setFillKey] = useState("");
  const [fillValue, setFillValue] = useState("");
  const [selectedCount, setSelectedCount] = useState(0);

  const dirtyCount = table.rows.filter(isDirty).length;

  // keep column defs stable across renders (so widths/sort survive) while using fresh callbacks
  const handlers = useRef({ onSave, onRevert });
  handlers.current = { onSave, onRevert };

  const columnDefs = useMemo<ColDef<EditRow>[]>(() => {
    const status: ColDef<EditRow> = {
      colId: "_status",
      headerName: "",
      initialWidth: 112,
      pinned: "left",
      editable: false,
      sortable: false,
      resizable: false,
      suppressMovable: true,
      cellRenderer: (p: ICellRendererParams<EditRow>) => {
        const row = p.data!;
        if (row.error) return <span className="badge error" title={row.error}>unreadable</span>;
        const dirty = isDirty(row);
        return (
          <span className="row-actions">
            {row.saveError && <span className="badge error" title={row.saveError}>!</span>}
            {dirty ? (
              <>
                <button className="mini primary" title="Save this file" onClick={() => handlers.current.onSave([row])}>Save</button>
                <button className="mini" title="Revert this file" onClick={() => handlers.current.onRevert([row])}>↺</button>
              </>
            ) : (
              !row.saveError && <span className="saved-dot" title="No unsaved changes" />
            )}
          </span>
        );
      },
    };
    const file: ColDef<EditRow> = {
      colId: "_file",
      headerName: "File name",
      pinned: "left",
      initialWidth: 280,
      editable: (p) => !p.data?.error,
      valueGetter: (p) => p.data?.file,
      valueSetter: (p) => {
        const v = String(p.newValue ?? "").trim();
        if (!v) return false;
        p.data.file = v;
        return true;
      },
      cellClass: "file-cell",
      cellClassRules: { dirty: (p) => !!p.data && p.data.file !== p.data.orig.file },
      tooltipValueGetter: (p) => (p.data && p.data.file !== p.data.orig.file ? `was: ${p.data.orig.file}` : p.data?.file),
    };
    const tags = table.columns.map<ColDef<EditRow>>((c) => ({
      colId: c.key,
      headerName: c.label,
      headerTooltip: c.key === c.label ? c.key : `${c.label}  ·  ${c.key}`,
      initialWidth: Math.min(320, Math.max(110, c.label.length * 9 + 40)),
      editable: (p) => !p.data?.error,
      valueGetter: (p) => (p.data ? val(p.data.tags, c.key) : ""),
      valueFormatter: (p) => (p.value === "" && !p.data?.error ? "[not set]" : p.value),
      valueSetter: (p) => {
        p.data.tags[c.key] = String(p.newValue ?? "");
        return true;
      },
      cellClassRules: {
        dirty: (p) => !!p.data && isCellDirty(p.data, c.key),
        "not-set": (p) => !!p.data && !p.data.error && val(p.data.tags, c.key) === "",
      },
      tooltipValueGetter: (p) =>
        p.data && isCellDirty(p.data, c.key) ? `was: ${val(p.data.orig.tags, c.key) || "(empty)"}` : undefined,
      ...(LONG_TEXT.test(c.key)
        ? { cellEditor: "agLargeTextCellEditor", cellEditorPopup: true, cellEditorParams: { maxLength: 100000, rows: 12, cols: 60 } }
        : {}),
    }));
    const length: ColDef<EditRow> = {
      colId: "_length",
      headerName: "Length",
      initialWidth: 90,
      editable: false,
      valueGetter: (p) => p.data?.length ?? null,
      valueFormatter: (p) => formatLength(p.value),
      cellClass: "muted",
    };
    const art: ColDef<EditRow> = {
      colId: "_art",
      headerName: "Art",
      headerTooltip: "Embedded cover art (use Fetch Cover Art to add it)",
      initialWidth: 80,
      editable: false,
      valueGetter: (p) => (p.data?.hasArt ? "Yes" : ""),
      valueFormatter: (p) => p.value || "[none]",
      cellClassRules: { "not-set": (p) => !p.data?.hasArt },
    };
    return [status, file, ...tags, length, art];
  }, [table.columns]);

  const api = () => gridRef.current?.api;

  const onCellValueChanged = (e: CellValueChangedEvent<EditRow>) => {
    e.api.refreshCells({ rowNodes: [e.node], force: true });
    onEdited();
  };

  const targetRows = (): EditRow[] => {
    const g = api();
    if (!g) return [];
    const selected = g.getSelectedRows();
    if (selected.length) return selected;
    const visibleRows: EditRow[] = [];
    g.forEachNodeAfterFilterAndSort((n) => n.data && visibleRows.push(n.data));
    return visibleRows;
  };

  const applyFill = () => {
    if (!fillKey) return;
    const rows = targetRows().filter((r) => !r.error);
    for (const r of rows) {
      r.tags[fillKey] = fillValue;
    }
    api()?.refreshCells({ force: true });
    onEdited();
    setFillOpen(false);
  };

  const [addOpen, setAddOpen] = useState(false);
  const missingSuggestions = table.suggestions.filter((s) => !table.columns.some((c) => c.key === s.key));
  const addColumn = async (name: string) => {
    if (await onAddColumn(name)) {
      setNewTag("");
      setAddOpen(false);
    }
  };

  const fillTargetLabel = selectedCount ? `${selectedCount} selected` : "all visible";

  return (
    <section className="table-panel" style={{ display: visible ? "flex" : "none" }}>
      <div className="toolbar">
        <input
          className="search"
          placeholder="Filter rows…"
          value={quickFilter}
          onChange={(e) => setQuickFilter(e.target.value)}
        />
        <div className="toolbar-group">
          <button onClick={() => setFillOpen((o) => !o)} title="Set one tag on several files at once">
            Set field…
          </button>
          {fillOpen && (
            <div className="popover">
              <label>
                Field
                <select value={fillKey} onChange={(e) => setFillKey(e.target.value)}>
                  <option value="">Choose…</option>
                  {table.columns.map((c) => (
                    <option key={c.key} value={c.key}>{c.label}</option>
                  ))}
                </select>
              </label>
              <label>
                Value <span className="hint">(empty clears it)</span>
                <input value={fillValue} onChange={(e) => setFillValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && applyFill()} />
              </label>
              <div className="popover-actions">
                <button onClick={() => setFillOpen(false)}>Cancel</button>
                <button className="primary" disabled={!fillKey} onClick={applyFill}>
                  Apply to {fillTargetLabel}
                </button>
              </div>
            </div>
          )}
        </div>
        <div className="toolbar-group">
          <button onClick={() => setAddOpen((o) => !o)} title="Add a tag column to this table">
            + Add tag…
          </button>
          {addOpen && (
            <div className="popover">
              {missingSuggestions.length > 0 && (
                <div className="popover-section">
                  <span className="popover-label">Common tags</span>
                  <div className="tokens">
                    {missingSuggestions.map((s) => (
                      <button key={s.key} className="chip" onClick={() => addColumn(s.label)}>{s.label}</button>
                    ))}
                  </div>
                </div>
              )}
              <label>
                Other tag
                <input
                  autoFocus
                  placeholder="e.g. Mood, REPLAYGAIN_TRACK_GAIN"
                  value={newTag}
                  onChange={(e) => setNewTag(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addColumn(newTag)}
                />
              </label>
              <div className="popover-actions">
                <button onClick={() => setAddOpen(false)}>Cancel</button>
                <button className="primary" disabled={!newTag.trim()} onClick={() => addColumn(newTag)}>Add column</button>
              </div>
            </div>
          )}
        </div>
        <div className="spacer" />
        <button disabled={!dirtyCount} onClick={() => onRevert(table.rows.filter(isDirty))}>Revert table</button>
        <button className="primary" disabled={!dirtyCount} onClick={() => onSave(table.rows.filter(isDirty))}>
          Save table{dirtyCount ? ` (${dirtyCount})` : ""}
        </button>
      </div>
      <div className="grid">
        <AgGridReact<EditRow>
          ref={gridRef}
          theme={theme}
          rowData={table.rows}
          columnDefs={columnDefs}
          getRowId={getRowId}
          defaultColDef={DEFAULT_COL_DEF}
          quickFilterText={quickFilter}
          rowSelection={ROW_SELECTION}
          selectionColumnDef={SELECTION_COL_DEF}
          onSelectionChanged={(e) => setSelectedCount(e.api.getSelectedRows().length)}
          onGridReady={(e) => onGridReady(e.api)}
          onCellValueChanged={onCellValueChanged}
          stopEditingWhenCellsLoseFocus
          undoRedoCellEditing
          undoRedoCellEditingLimit={100}
          enterNavigatesVerticallyAfterEdit
          tooltipShowDelay={400}
        />
      </div>
    </section>
  );
}
