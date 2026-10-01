import { useState, type FormEvent, type InputHTMLAttributes } from "react";
import { api, ApiError } from "../lib/api";
import { invalidate } from "../lib/query";
import { Link, navigate } from "../lib/router";
import { rememberName, rememberedName } from "../lib/format";
import { FieldError, FormError } from "../components/ui";

const SKU_RE = /^[A-Z0-9][A-Z0-9._-]{0,63}$/;

interface Values {
  sku: string; name: string; description: string; unit: string; reorder_threshold: string;
  initial_stock: string; created_by: string;
}

function validate(v: Values): Record<string, string> {
  const e: Record<string, string> = {};
  const sku = v.sku.trim().toUpperCase();
  if (!sku) e.sku = "SKU is required.";
  else if (!SKU_RE.test(sku)) e.sku = "Use letters, digits, '.', '_' or '-' (max 64), starting with a letter or digit.";
  if (!v.name.trim()) e.name = "Name is required.";
  if (!v.unit.trim()) e.unit = "Unit is required, e.g. each, box, kg.";
  if (!/^\d+$/.test(v.reorder_threshold.trim())) e.reorder_threshold = "Enter a whole number, 0 or more.";
  if (v.initial_stock.trim() && !/^\d+$/.test(v.initial_stock.trim())) e.initial_stock = "Enter a whole number, 0 or more.";
  if (Number(v.initial_stock || 0) > 0 && !v.created_by.trim()) e.created_by = "Who is recording the opening stock?";
  return e;
}

export function NewItemPage() {
  const [values, setValues] = useState<Values>({
    sku: "", name: "", description: "", unit: "each", reorder_threshold: "10", initial_stock: "", created_by: rememberedName(),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [formError, setFormError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  const set = (field: keyof Values) => (ev: { target: { value: string } }) => {
    const next = { ...values, [field]: ev.target.value };
    setValues(next);
    setDirty((d) => (d[field] ? d : { ...d, [field]: true }));
    // Inline validation: re-check fields the user has already visited.
    if (touched[field]) setErrors((prev) => ({ ...prev, [field]: validate(next)[field] }));
  };
  // Validate on blur only once the user has typed in the field. Flagging an untouched
  // empty field the moment focus leaves it is noisy, and the message shifting the layout
  // can make the user's click on "Create item" miss.
  const blur = (field: keyof Values) => () => {
    if (!dirty[field]) return;
    setTouched((t) => ({ ...t, [field]: true }));
    setErrors((prev) => ({ ...prev, [field]: validate(values)[field] }));
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (submitting) return;
    const e = validate(values);
    setErrors(e);
    setTouched({ sku: true, name: true, unit: true, reorder_threshold: true, initial_stock: true, created_by: true });
    setFormError(undefined);
    if (Object.values(e).some(Boolean)) return;

    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        sku: values.sku.trim(), name: values.name.trim(), description: values.description.trim(),
        unit: values.unit.trim(), reorder_threshold: Number(values.reorder_threshold),
        initial_stock: Number(values.initial_stock || 0),
      };
      if (values.created_by.trim()) {
        body.created_by = values.created_by.trim();
        rememberName(values.created_by.trim());
      }
      const item = await api.createItem(body);
      invalidate("items", "alerts");
      navigate(`/items/${item.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fields); // e.g. {sku: "This SKU is already in use."} shown under the SKU box
        setFormError(err.message);
      } else setFormError("Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const field = (name: keyof Values, label: string, props: InputHTMLAttributes<HTMLInputElement> = {}, hint?: string) => (
    <div className="field">
      <label className="label" htmlFor={`new-${name}`}>{label}</label>
      <input id={`new-${name}`} className={`input${errors[name] ? " invalid" : ""}`} value={values[name]}
             onChange={set(name)} onBlur={blur(name)} aria-invalid={!!errors[name]} {...props} />
      {hint && <div className="hint">{hint}</div>}
      <FieldError message={errors[name]} />
    </div>
  );

  return (
    <section className="narrow">
      <div className="breadcrumb"><Link to="/">← Inventory</Link></div>
      <h1>New item</h1>
      <form className="form card" onSubmit={submit} noValidate>
        <FormError message={formError} />
        {field("sku", "SKU", { maxLength: 64, autoFocus: true, className: `input mono${errors.sku ? " invalid" : ""}` },
          "Unique and permanent. Stored in upper case.")}
        {field("name", "Name", { maxLength: 200 })}
        <div className="field">
          <label className="label" htmlFor="new-description">Description <span className="muted">(optional)</span></label>
          <textarea id="new-description" className="input" rows={3} maxLength={2000} value={values.description}
                    onChange={set("description")} />
        </div>
        <div className="field-row">
          {field("unit", "Unit of measure", { maxLength: 32 })}
          {field("reorder_threshold", "Reorder threshold", { inputMode: "numeric" }, "Alert when stock falls below this. 0 = never.")}
        </div>
        <div className="field-row">
          {field("initial_stock", "Opening stock (optional)", { inputMode: "numeric", placeholder: "0" },
            "Recorded as a 'received' transaction.")}
          {field("created_by", "Recorded by", { maxLength: 100, placeholder: "Your name" })}
        </div>
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? "Creating…" : "Create item"}
          </button>
          <Link to="/" className="btn btn-secondary">Cancel</Link>
        </div>
      </form>
    </section>
  );
}
