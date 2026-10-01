import { useState, type FormEvent } from "react";
import { api, ApiError, type Item } from "../lib/api";
import { invalidate } from "../lib/query";
import { FieldError, FormError } from "./ui";

export function ItemEditForm({ item, onDone }: { item: Item; onDone: () => void }) {
  const [name, setName] = useState(item.name);
  const [description, setDescription] = useState(item.description);
  const [unit, setUnit] = useState(item.unit);
  const [threshold, setThreshold] = useState(String(item.reorder_threshold));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (submitting) return;
    const e: Record<string, string> = {};
    if (!name.trim()) e.name = "Name is required.";
    if (!unit.trim()) e.unit = "Unit is required.";
    if (!/^\d+$/.test(threshold.trim())) e.reorder_threshold = "Enter a whole number, 0 or more.";
    setErrors(e);
    setFormError(undefined);
    if (Object.keys(e).length) return;

    setSubmitting(true);
    try {
      await api.updateItem(item.id, {
        name: name.trim(), description: description.trim(), unit: unit.trim(),
        reorder_threshold: Number(threshold),
      });
      // A threshold change can open or resolve an alert, so refresh alerts too.
      invalidate(`item:${item.id}`, "items", "alerts");
      onDone();
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fields);
        setFormError(err.message);
      } else setFormError("Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="form card" onSubmit={submit} noValidate>
      <h2>Edit item</h2>
      <FormError message={formError} />
      <div className="field">
        <span className="label">SKU</span>
        <div className="mono">{item.sku} <span className="muted small">(cannot be changed)</span></div>
      </div>
      <div className="field">
        <label className="label" htmlFor="edit-name">Name</label>
        <input id="edit-name" className={`input${errors.name ? " invalid" : ""}`} value={name} maxLength={200}
               onChange={(ev) => setName(ev.target.value)} />
        <FieldError message={errors.name} />
      </div>
      <div className="field">
        <label className="label" htmlFor="edit-desc">Description</label>
        <textarea id="edit-desc" className="input" rows={3} value={description} maxLength={2000}
                  onChange={(ev) => setDescription(ev.target.value)} />
        <FieldError message={errors.description} />
      </div>
      <div className="field-row">
        <div className="field">
          <label className="label" htmlFor="edit-unit">Unit</label>
          <input id="edit-unit" className={`input${errors.unit ? " invalid" : ""}`} value={unit} maxLength={32}
                 onChange={(ev) => setUnit(ev.target.value)} />
          <FieldError message={errors.unit} />
        </div>
        <div className="field">
          <label className="label" htmlFor="edit-threshold">Reorder threshold</label>
          <input id="edit-threshold" className={`input${errors.reorder_threshold ? " invalid" : ""}`} inputMode="numeric"
                 value={threshold} onChange={(ev) => setThreshold(ev.target.value)} />
          <div className="hint">Alert when stock drops below this. 0 = never alert.</div>
          <FieldError message={errors.reorder_threshold} />
        </div>
      </div>
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? "Saving…" : "Save changes"}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone} disabled={submitting}>Cancel</button>
      </div>
    </form>
  );
}
