const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? dateTime.format(new Date(iso)) : "—";
}

export function formatChange(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}

export const TYPE_LABELS: Record<string, string> = {
  received: "Received",
  shipped: "Shipped",
  adjustment: "Adjustment",
  returned: "Returned",
};

export const RESOLUTION_LABELS: Record<string, string> = {
  stock_recovered: "Stock recovered",
  threshold_changed: "Threshold changed",
  item_archived: "Item archived",
};

/** Remember the operator's name between visits. Storage can be unavailable, so never throw. */
export function rememberedName(): string {
  try {
    return localStorage.getItem("inventory.operator") ?? "";
  } catch {
    return "";
  }
}

export function rememberName(name: string): void {
  try {
    localStorage.setItem("inventory.operator", name);
  } catch {
    /* ignore */
  }
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
