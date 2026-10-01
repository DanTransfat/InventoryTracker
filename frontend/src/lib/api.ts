// Typed API client. Every non-2xx response becomes an ApiError carrying the server's
// machine-readable code and per-field messages, so forms can show them inline.

export interface Item {
  id: number;
  sku: string;
  name: string;
  description: string;
  unit: string;
  reorder_threshold: number;
  current_stock: number;
  is_low_stock: boolean;
  is_archived: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  active_alert?: Alert | null;
}

export type TransactionType = "received" | "shipped" | "adjustment" | "returned";

export interface StockTransaction {
  id: number;
  item_id: number;
  type: TransactionType;
  quantity_change: number;
  balance_after: number;
  note: string | null;
  created_by: string;
  created_at: string;
}

export type AlertStatus = "open" | "acknowledged" | "resolved";

export interface Alert {
  id: number;
  item_id: number;
  status: AlertStatus;
  triggered_stock: number;
  threshold_at_trigger: number;
  created_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  resolved_at: string | null;
  resolution_reason: string | null;
  resolved_stock: number | null;
  item: { sku: string; name: string; unit: string; current_stock: number; reorder_threshold: number };
}

export interface Page<T> {
  data: T[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface HistoryPoint {
  at: string;
  stock: number;
  change: number;
  type: TransactionType;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

const BASE: string = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "NETWORK_ERROR", "Can't reach the server. Check that the backend is running.");
  }
  const text = await res.text();
  const body = text ? safeJson(text) : null;
  if (!res.ok) {
    const e = body?.error;
    throw new ApiError(res.status, e?.code ?? "HTTP_ERROR", e?.message ?? `Request failed (${res.status}).`, e?.fields ?? {});
  }
  return body as T;
}

function safeJson(text: string): any {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export interface ItemListQuery {
  search?: string;
  low_stock?: boolean;
  sort?: string;
  page?: number;
  page_size?: number;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "" || v === false) continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  listItems: (q: ItemListQuery, signal?: AbortSignal) =>
    request<Page<Item>>(`/api/items${qs({ ...q })}`, { signal }),
  getItem: (id: number, signal?: AbortSignal) => request<Item>(`/api/items/${id}`, { signal }),
  createItem: (body: Record<string, unknown>) =>
    request<Item>("/api/items", { method: "POST", body: JSON.stringify(body) }),
  updateItem: (id: number, body: Record<string, unknown>) =>
    request<Item>(`/api/items/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  listTransactions: (id: number, page: number, signal?: AbortSignal) =>
    request<Page<StockTransaction>>(`/api/items/${id}/transactions${qs({ page, page_size: 15 })}`, { signal }),
  recordTransaction: (id: number, body: Record<string, unknown>, idempotencyKey: string) =>
    request<{ transaction: StockTransaction; item: Item; alert_change: { action: string; alert_id: number } | null }>(
      `/api/items/${id}/transactions`,
      { method: "POST", body: JSON.stringify(body), headers: { "Idempotency-Key": idempotencyKey } },
    ),
  stockHistory: (id: number, signal?: AbortSignal) =>
    request<{ data: HistoryPoint[] }>(`/api/items/${id}/stock-history`, { signal }),
  listAlerts: (status: string, page: number, signal?: AbortSignal) =>
    request<Page<Alert>>(`/api/alerts${qs({ status, page })}`, { signal }),
  alertSummary: (signal?: AbortSignal) =>
    request<{ open: number; acknowledged: number }>("/api/alerts/summary", { signal }),
  acknowledgeAlert: (id: number, by: string) =>
    request<Alert>(`/api/alerts/${id}/acknowledge`, { method: "POST", body: JSON.stringify({ acknowledged_by: by || null }) }),
};
