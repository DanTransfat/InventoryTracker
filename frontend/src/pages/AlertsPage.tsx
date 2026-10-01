import { useState } from "react";
import { api, ApiError, type Alert } from "../lib/api";
import { invalidate, useQuery } from "../lib/query";
import { Link, useSearchParams } from "../lib/router";
import { formatDateTime, RESOLUTION_LABELS, rememberedName } from "../lib/format";
import { AlertStatusBadge, Empty, ErrorState, Loading, Pagination } from "../components/ui";

export function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "resolved" ? "resolved" : "active";
  const page = Math.max(1, Number(params.get("page")) || 1);
  const status = view === "resolved" ? "resolved" : "open,acknowledged";
  const list = useQuery(`alerts:${status}:${page}`, ["alerts"], (signal) => api.listAlerts(status, page, signal));

  return (
    <section>
      <div className="page-head"><h1>Low-stock alerts</h1></div>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={view === "active"} className={`tab${view === "active" ? " active" : ""}`}
                onClick={() => setParams({ view: null, page: null })}>Open &amp; acknowledged</button>
        <button type="button" role="tab" aria-selected={view === "resolved"} className={`tab${view === "resolved" ? " active" : ""}`}
                onClick={() => setParams({ view: "resolved", page: null })}>Resolved history</button>
      </div>

      {list.error && !list.data ? (
        <ErrorState error={list.error} onRetry={list.refetch} />
      ) : !list.data ? (
        <Loading label="Loading alerts…" />
      ) : list.data.total === 0 ? (
        <Empty title={view === "active" ? "No active alerts. Everything is above its threshold." : "No resolved alerts yet."} />
      ) : (
        <>
          <div className={`table-wrap${list.fetching ? " is-fetching" : ""}`}>
            <table className="table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Status</th>
                  <th className="num" title="Stock / threshold when the alert opened">At trigger</th>
                  <th className="num">{view === "active" ? "Stock now" : "Resolved at"}</th>
                  <th>Opened</th>
                  <th>{view === "active" ? "Acknowledged" : "Resolution"}</th>
                  {view === "active" && <th><span className="sr-only">Actions</span></th>}
                </tr>
              </thead>
              <tbody>
                {list.data.data.map((a) => <AlertRow key={a.id} alert={a} view={view} />)}
              </tbody>
            </table>
          </div>
          <Pagination page={list.data.page} totalPages={list.data.total_pages} total={list.data.total} noun="alert"
                      onPage={(p) => setParams({ page: p === 1 ? null : String(p) })} />
        </>
      )}
    </section>
  );
}

function AlertRow({ alert: a, view }: { alert: Alert; view: "active" | "resolved" }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const acknowledge = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await api.acknowledgeAlert(a.id, rememberedName());
      invalidate("alerts", `item:${a.item_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not acknowledge.");
      if (err instanceof ApiError && err.code === "ALERT_RESOLVED") invalidate("alerts");
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr className={a.status === "open" ? "row-low" : undefined}>
      <td>
        <Link to={`/items/${a.item_id}`} className="mono">{a.item.sku}</Link>
        <div className="small">{a.item.name}</div>
      </td>
      <td><AlertStatusBadge status={a.status} /></td>
      <td className="num">{a.triggered_stock} / {a.threshold_at_trigger}</td>
      <td className="num strong">{view === "active" ? `${a.item.current_stock} ${a.item.unit}` : a.resolved_stock ?? "—"}</td>
      <td className="nowrap">{formatDateTime(a.created_at)}</td>
      <td className="small">
        {view === "active"
          ? a.acknowledged_at ? <>{a.acknowledged_by || "Someone"} · {formatDateTime(a.acknowledged_at)}</> : <span className="muted">Not yet</span>
          : <>{RESOLUTION_LABELS[a.resolution_reason ?? ""] ?? a.resolution_reason} · {formatDateTime(a.resolved_at)}</>}
      </td>
      {view === "active" && (
        <td className="actions">
          {a.status === "open" && (
            <button type="button" className="btn btn-secondary btn-sm" onClick={acknowledge} disabled={busy}>
              {busy ? "…" : "Acknowledge"}
            </button>
          )}
          {error && <div className="field-error">{error}</div>}
        </td>
      )}
    </tr>
  );
}
