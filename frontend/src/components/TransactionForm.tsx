import { useState, type FormEvent } from "react";
import { api, ApiError, type Item, type TransactionType } from "../lib/api";
import { invalidate } from "../lib/query";
import { newIdempotencyKey, rememberName, rememberedName } from "../lib/format";
import { FieldError, FormError } from "./ui";

const TYPES: { value: TransactionType; label: string; hint: string }[] = [
  { value: "received", label: "Received", hint: "Stock arriving from a supplier (adds)." },
  { value: "shipped", label: "Shipped", hint: "Stock leaving to a customer (removes)." },
  { value: "returned", label: "Returned", hint: "A customer return back on the shelf (adds)." },
  { value: "adjustment", label: "Adjustment", hint: "Correct a count or a mistake (adds or removes)." },
];

export function TransactionForm({ item }: { item: Item }) {
  const [type, setType] = useState<TransactionType>("received");
  const [direction, setDirection] = useState<"add" | "remove">("remove");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [createdBy, setCreatedBy] = useState(rememberedName);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string>();
  const [success, setSuccess] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  // One key per intended transaction: if the response is lost and the user clicks again,
  // the server recognises the retry instead of recording the movement twice.
  const [idemKey, setIdemKey] = useState(newIdempotencyKey);

  const touch = () => {
    setSuccess(undefined);
    setIdemKey(newIdempotencyKey()); // changed input = a different intended transaction
  };

  const sign = type === "shipped" || (type === "adjustment" && direction === "remove") ? -1 : 1;

  const validate = (): Record<string, string> => {
    const e: Record<string, string> = {};
    if (!/^\d+$/.test(amount.trim()) || Number(amount) === 0) e.quantity_change = "Enter a whole number greater than 0.";
    else if (sign < 0 && Number(amount) > item.current_stock)
      e.quantity_change = `Only ${item.current_stock} ${item.unit} on hand.`;
    if (!createdBy.trim()) e.created_by = "Enter your name.";
    return e;
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (submitting) return;
    setFormError(undefined);
    setSuccess(undefined);
    const clientErrors = validate();
    setErrors(clientErrors);
    if (Object.keys(clientErrors).length) return;

    setSubmitting(true);
    try {
      const qty = sign * Number(amount);
      const res = await api.recordTransaction(
        item.id,
        { type, quantity_change: qty, note: note.trim() || null, created_by: createdBy.trim() },
        idemKey,
      );
      rememberName(createdBy.trim());
      setAmount("");
      setNote("");
      setIdemKey(newIdempotencyKey());
      const alertMsg =
        res.alert_change?.action === "opened" ? " A low-stock alert was opened." :
        res.alert_change?.action === "resolved" ? " The low-stock alert was resolved." : "";
      setSuccess(`Recorded ${qty > 0 ? "+" : ""}${qty} ${item.unit}. Stock is now ${res.item.current_stock}.${alertMsg}`);
      // Refresh everything that depends on this item's stock, without reloading the page.
      invalidate(`item:${item.id}`, "items", "alerts");
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fields);
        setFormError(err.message);
        if (err.code === "INSUFFICIENT_STOCK") invalidate(`item:${item.id}`); // our view of stock was stale
      } else {
        setFormError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (item.is_archived) {
    return <p className="muted">This item is archived. Restore it to record stock movements.</p>;
  }

  return (
    <form className="form" onSubmit={submit} noValidate>
      <FormError message={formError} />
      {success && <div className="form-success" role="status">{success}</div>}

      <div className="field">
        <span className="label">Type</span>
        <div className="segmented" role="radiogroup" aria-label="Transaction type">
          {TYPES.map((t) => (
            <label key={t.value} className={`segment${type === t.value ? " selected" : ""}`}>
              <input type="radio" name="type" value={t.value} checked={type === t.value}
                     onChange={() => { setType(t.value); touch(); }} />
              {t.label}
            </label>
          ))}
        </div>
        <div className="hint">{TYPES.find((t) => t.value === type)?.hint}</div>
        <FieldError message={errors.type} />
      </div>

      <div className="field-row">
        {type === "adjustment" && (
          <div className="field">
            <label className="label" htmlFor="txn-direction">Direction</label>
            <select id="txn-direction" className="input" value={direction}
                    onChange={(e) => { setDirection(e.target.value as "add" | "remove"); touch(); }}>
              <option value="remove">Remove stock (−)</option>
              <option value="add">Add stock (+)</option>
            </select>
          </div>
        )}
        <div className="field">
          <label className="label" htmlFor="txn-qty">Quantity ({item.unit})</label>
          <input id="txn-qty" className={`input${errors.quantity_change ? " invalid" : ""}`} inputMode="numeric"
                 value={amount} aria-invalid={!!errors.quantity_change} aria-describedby="txn-qty-err"
                 onChange={(e) => { setAmount(e.target.value); touch(); }} placeholder="e.g. 12" />
          <FieldError id="txn-qty-err" message={errors.quantity_change} />
        </div>
        <div className="field">
          <label className="label" htmlFor="txn-by">Recorded by</label>
          <input id="txn-by" className={`input${errors.created_by ? " invalid" : ""}`} value={createdBy}
                 aria-invalid={!!errors.created_by} maxLength={100}
                 onChange={(e) => { setCreatedBy(e.target.value); touch(); }} placeholder="Your name" />
          <FieldError message={errors.created_by} />
        </div>
      </div>

      <div className="field">
        <label className="label" htmlFor="txn-note">Note <span className="muted">(optional)</span></label>
        <input id="txn-note" className="input" value={note} maxLength={500}
               onChange={(e) => { setNote(e.target.value); touch(); }} placeholder="PO number, reason for adjustment…" />
        <FieldError message={errors.note} />
      </div>

      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? "Recording…" : "Record transaction"}
        </button>
      </div>
    </form>
  );
}
