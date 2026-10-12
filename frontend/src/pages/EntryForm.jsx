import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiGet, apiSend } from "../api";
import StatusBadge from "../components/StatusBadge.jsx";
import { periodDays, utilityLabel } from "../format";
import { useBill } from "../hooks";

const EMPTY = {
  start_billing_period: "",
  end_billing_period: "",
  consumption: "",
  billed_power: "",
  bill_cost: "",
};

// API -> form: nulls become empty strings so inputs stay controlled.
function toForm(entry) {
  const form = { ...EMPTY };
  for (const key of Object.keys(EMPTY)) {
    if (entry[key] != null) form[key] = String(entry[key]);
  }
  return form;
}

// Form -> API: empty strings become null.
function toPayload(form) {
  return Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === "" ? null : v]));
}

function Field({ name, label, form, errors, onChange, type = "text", required, hint }) {
  const id = `field-${name}`;
  return (
    <div className="field">
      <label htmlFor={id}>{label}{required && " *"}</label>
      <input
        id={id}
        name={name}
        type={type}
        step={type === "number" ? "0.01" : undefined}
        value={form[name]}
        onChange={onChange}
        required={required}
        aria-invalid={errors[name] ? "true" : undefined}
        aria-describedby={hint ? `${id}-hint` : undefined}
      />
      {hint && <span id={`${id}-hint`} className="muted hint">{hint}</span>}
      {errors[name] && <span className="error">{errors[name].join(" ")}</span>}
    </div>
  );
}

export default function EntryForm() {
  const { entryId, buildingId, billId } = useParams();
  const isNew = !entryId;
  const navigate = useNavigate();
  const newBill = useBill(isNew ? buildingId : null, billId);

  const [entry, setEntry] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [loadError, setLoadError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isNew) return;
    apiGet(`/api/entries/${entryId}/`)
      .then((data) => {
        setEntry(data);
        setForm(toForm(data));
      })
      .catch((err) => setLoadError(err.message));
  }, [entryId, isNew]);

  // Bill context: from the entry itself, or from the building for a new entry.
  const bill = isNew
    ? newBill.bill && { ...newBill.bill, building_id: newBill.building.id, building_name: newBill.building.name }
    : entry?.bill;

  function handleChange(e) {
    setForm({ ...form, [e.target.name]: e.target.value });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    try {
      if (isNew) {
        await apiSend("POST", `/api/bills/${billId}/entries/`, toPayload(form));
      } else {
        await apiSend("PUT", `/api/entries/${entryId}/`, toPayload(form));
      }
      navigate(`/buildings/${bill.building_id}`);
    } catch (err) {
      setErrors(err.body && typeof err.body === "object" ? err.body : { non_field_errors: [err.message] });
      setBusy(false);
    }
  }

  const error = loadError || newBill.error;
  if (error) return <p className="error">{error}</p>;
  if (!bill) return <p className="muted">Loading…</p>;

  const unit = bill.consumption_unit === "m3" ? "m³" : bill.consumption_unit;
  const days = periodDays(form.start_billing_period, form.end_billing_period);
  const fieldProps = { form, errors, onChange: handleChange };

  return (
    <>
      <Link className="back-link" to={`/buildings/${bill.building_id}`}>← {bill.building_name}</Link>
      <h2>
        {isNew ? "Add an entry" : "Billing period"} <span className="muted">· {bill.name}</span>{" "}
        {entry && <StatusBadge status={entry.status} />}
      </h2>
      <p className="muted subtitle">{utilityLabel(bill.utility)}</p>

      {entry && (
        <div className="card meta">
          <div><span className="muted">Source:</span> {entry.source || "—"}</div>
          <div><span className="muted">Parser:</span> {entry.parser_name || "—"}</div>
          <div>
            <span className="muted">Confidence:</span>{" "}
            {entry.confidence == null ? "—" : `${Math.round(entry.confidence * 100)} %`}
          </div>
          {entry.documents.length > 0 && (
            <div>
              <span className="muted">Original:</span>{" "}
              {entry.documents.map((doc) => (
                <a key={doc.id} href={doc.file} target="_blank" rel="noreferrer" className="doc-link">
                  {doc.original_filename}
                </a>
              ))}
            </div>
          )}
        </div>
      )}

      {entry?.review_notes?.length > 0 && entry.status !== "confirmed" && (
        <div className="card review-notes" role="note">
          <strong>Please check:</strong>
          <ul>
            {entry.review_notes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        </div>
      )}

      <form className="card form-grid" onSubmit={handleSubmit}>
        <Field name="start_billing_period" label="Start of billing period" type="date" required {...fieldProps} />
        <Field
          name="end_billing_period"
          label="End of billing period"
          type="date"
          required
          hint={`Exclusive: the day after the last billed day.${days ? ` ${days} days billed.` : ""}`}
          {...fieldProps}
        />
        <Field name="consumption" label={`Consumption (${unit})`} type="number" required {...fieldProps} />
        <Field name="billed_power" label="Billed power (kW)" type="number" hint="Demand-billed accounts only." {...fieldProps} />
        <Field name="bill_cost" label="Cost before taxes ($)" type="number" required {...fieldProps} />

        {errors.non_field_errors && <p className="error full">{errors.non_field_errors.join(" ")}</p>}
        <div className="full">
          <button type="submit" disabled={busy}>
            {busy ? "Saving…" : isNew ? "Save entry" : "Confirm entry"}
          </button>
        </div>
      </form>
    </>
  );
}
