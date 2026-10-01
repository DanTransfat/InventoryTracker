import type { ReactNode } from "react";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state state-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state state-empty">
      <strong>{title}</strong>
      {children && <div className="muted">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <strong>Couldn't load this.</strong>
      <span>{error.message}</span>
      {onRetry && (
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Pagination({ page, totalPages, total, onPage, noun }: {
  page: number; totalPages: number; total: number; onPage: (p: number) => void; noun: string;
}) {
  if (total === 0) return null;
  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="muted">
        {total} {noun}
        {total === 1 ? "" : "s"} · page {page} of {totalPages}
      </span>
      <div className="pagination-buttons">
        <button type="button" className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          ← Previous
        </button>
        <button type="button" className="btn btn-secondary btn-sm" disabled={page >= totalPages} onClick={() => onPage(page + 1)}>
          Next →
        </button>
      </div>
    </nav>
  );
}

export function FieldError({ message, id }: { message?: string; id?: string }) {
  if (!message) return null;
  return (
    <div className="field-error" id={id} role="alert">
      {message}
    </div>
  );
}

export function FormError({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <div className="form-error" role="alert">
      {message}
    </div>
  );
}

export function StockBadge({ low, archived }: { low: boolean; archived?: boolean }) {
  if (archived) return <span className="badge badge-muted">Archived</span>;
  return low ? <span className="badge badge-danger">Low stock</span> : <span className="badge badge-ok">OK</span>;
}

export function AlertStatusBadge({ status }: { status: string }) {
  const cls = status === "open" ? "badge-danger" : status === "acknowledged" ? "badge-warn" : "badge-muted";
  return <span className={`badge ${cls}`}>{status[0].toUpperCase() + status.slice(1)}</span>;
}
