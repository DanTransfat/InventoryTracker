import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { invalidate, useQuery } from "../lib/query";
import { Link } from "../lib/router";
import { formatChange, formatDateTime, TYPE_LABELS } from "../lib/format";
import { AlertStatusBadge, Empty, ErrorState, FormError, Loading, Pagination, StockBadge } from "../components/ui";
import { TransactionForm } from "../components/TransactionForm";
import { ItemEditForm } from "../components/ItemEditForm";
import { StockChart } from "../components/StockChart";

export function ItemDetailPage({ id }: { id: number }) {
  const item = useQuery(`item:${id}`, [`item:${id}`, "items"], (signal) => api.getItem(id, signal));
  const [editing, setEditing] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [archiveError, setArchiveError] = useState<string>();

  if (item.error && !item.data) {
    if (item.error instanceof ApiError && item.error.status === 404) {
      return <Empty title="Item not found."><Link to="/">Back to inventory</Link></Empty>;
    }
    return <ErrorState error={item.error} onRetry={item.refetch} />;
  }
  if (!item.data) return <Loading label="Loading item…" />;
  const it = item.data;

  const toggleArchive = async () => {
    const archive = !it.is_archived;
    if (archive && !window.confirm(`Archive ${it.sku}? It will be hidden from the inventory list. Its history is kept and you can restore it.`)) return;
    setArchiving(true);
    setArchiveError(undefined);
    try {
      await api.updateItem(it.id, { is_archived: archive });
      invalidate(`item:${it.id}`, "items", "alerts");
    } catch (err) {
      setArchiveError(err instanceof Error ? err.message : "Could not update the item.");
    } finally {
      setArchiving(false);
    }
  };

  const alert = it.active_alert;
  return (
    <section>
      <div className="breadcrumb"><Link to="/">← Inventory</Link></div>
      <div className="page-head">
        <div>
          <div className="mono muted">{it.sku}</div>
          <h1>{it.name}</h1>
        </div>
        <div className="head-actions">
          {!editing && (
            <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>Edit</button>
          )}
          <button type="button" className={`btn ${it.is_archived ? "btn-secondary" : "btn-danger-outline"}`}
                  onClick={toggleArchive} disabled={archiving}>
            {archiving ? "Saving…" : it.is_archived ? "Restore" : "Archive"}
          </button>
        </div>
      </div>
      <FormError message={archiveError} />

      {it.is_archived && (
        <div className="banner banner-muted">Archived {formatDateTime(it.archived_at)}. Hidden from the inventory list.</div>
      )}
      {alert && (
        <div className={`banner ${alert.status === "open" ? "banner-danger" : "banner-warn"}`}>
          <AlertStatusBadge status={alert.status} /> Low-stock alert since {formatDateTime(alert.created_at)}
          {alert.status === "acknowledged" && alert.acknowledged_by ? ` · acknowledged by ${alert.acknowledged_by}` : ""}
          {" · "}<Link to="/alerts">View alerts</Link>
        </div>
      )}

      <div className="stats">
        <div className="stat">
          <div className="stat-label">Current stock</div>
          <div className={`stat-value${it.is_low_stock ? " danger" : ""}`}>{it.current_stock} <span className="stat-unit">{it.unit}</span></div>
        </div>
        <div className="stat">
          <div className="stat-label">Reorder threshold</div>
          <div className="stat-value">{it.reorder_threshold}</div>
        </div>
        <div className="stat">
          <div className="stat-label">Status</div>
          <div className="stat-value small-value"><StockBadge low={it.is_low_stock} archived={it.is_archived} /></div>
        </div>
      </div>

      {editing ? (
        <ItemEditForm item={it} onDone={() => setEditing(false)} />
      ) : (
        <div className="card">
          <h2>Details</h2>
          <dl className="details">
            <dt>Description</dt><dd>{it.description || <span className="muted">—</span>}</dd>
            <dt>Unit</dt><dd>{it.unit}</dd>
            <dt>Created</dt><dd>{formatDateTime(it.created_at)}</dd>
            <dt>Updated</dt><dd>{formatDateTime(it.updated_at)}</dd>
          </dl>
        </div>
      )}

      <div className="card">
        <h2>Record a stock movement</h2>
        <TransactionForm item={it} />
      </div>

      <div className="card">
        <h2>Stock over time</h2>
        <HistoryChart id={it.id} threshold={it.reorder_threshold} />
      </div>

      <div className="card">
        <h2>Transaction history</h2>
        <TransactionHistory id={it.id} unit={it.unit} />
      </div>
    </section>
  );
}

function HistoryChart({ id, threshold }: { id: number; threshold: number }) {
  const q = useQuery(`history:${id}`, [`item:${id}`], (signal) => api.stockHistory(id, signal));
  if (q.error && !q.data) return <ErrorState error={q.error} onRetry={q.refetch} />;
  if (!q.data) return <Loading label="Loading chart…" />;
  return <StockChart points={q.data.data} threshold={threshold} />;
}

function TransactionHistory({ id, unit }: { id: number; unit: string }) {
  const [page, setPage] = useState(1);
  const q = useQuery(`txns:${id}:${page}`, [`item:${id}`], (signal) => api.listTransactions(id, page, signal));
  if (q.error && !q.data) return <ErrorState error={q.error} onRetry={q.refetch} />;
  if (!q.data) return <Loading label="Loading history…" />;
  if (q.data.total === 0) return <Empty title="No transactions yet.">Record a movement above to start the ledger.</Empty>;
  return (
    <>
      <div className={`table-wrap${q.fetching ? " is-fetching" : ""}`}>
        <table className="table">
          <thead>
            <tr>
              <th>When</th><th>Type</th><th className="num">Change</th><th className="num">Balance</th><th>By</th><th>Note</th>
            </tr>
          </thead>
          <tbody>
            {q.data.data.map((t) => (
              <tr key={t.id}>
                <td className="nowrap">{formatDateTime(t.created_at)}</td>
                <td><span className={`type type-${t.type}`}>{TYPE_LABELS[t.type]}</span></td>
                <td className={`num strong ${t.quantity_change > 0 ? "pos" : "neg"}`}>{formatChange(t.quantity_change)}</td>
                <td className="num">{t.balance_after} <span className="muted small">{unit}</span></td>
                <td>{t.created_by}</td>
                <td className="muted">{t.note ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={q.data.page} totalPages={q.data.total_pages} total={q.data.total} noun="transaction" onPage={setPage} />
    </>
  );
}
