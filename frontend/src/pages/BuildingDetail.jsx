import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiDelete, apiGet, apiSend } from "../api";
import StatusBadge from "../components/StatusBadge.jsx";
import { formatMoney, formatNumber, formatPeriod, UTILITIES, utilityLabel } from "../format";

function BillCard({ buildingId, bill, onDeleted }) {
  const [error, setError] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const unit = bill.consumption_unit;
  const counted = bill.entries.filter((e) => e.consumption != null);
  const totalConsumption = counted.reduce((sum, e) => sum + Number(e.consumption), 0);
  const totalCost = counted.reduce((sum, e) => sum + Number(e.bill_cost || 0), 0);
  const hasBilledPower = bill.entries.some((e) => e.billed_power != null);

  // Entries deleted since they were ticked no longer count.
  const selected = bill.entries.filter((e) => selectedIds.includes(e.id));
  const deleteLabel = selected.length === 1 ? "Delete bill" : `Delete ${selected.length} bills`;

  function toggle(entryId, checked) {
    setSelectedIds((ids) => (checked ? [...ids, entryId] : ids.filter((id) => id !== entryId)));
  }

  async function handleDelete() {
    const what = selected.length === 1
      ? `the bill for ${formatPeriod(selected[0].start_billing_period, selected[0].end_billing_period)}`
      : `these ${selected.length} bills`;
    if (!window.confirm(`Delete ${what} from "${bill.name}"? This cannot be undone.`)) return;
    setError(null);
    try {
      await Promise.all(selected.map((entry) => apiDelete(`/api/entries/${entry.id}/`)));
      setSelectedIds([]);
    } catch (err) {
      setError(err.message);
    }
    // Even after a failure: some of them may be gone.
    onDeleted();
  }

  return (
    <section className="card bill-card">
      <div className="toolbar">
        <div>
          <h3>{bill.name}</h3>
          <span className="muted">
            {utilityLabel(bill.utility)}
            {bill.rate_code && ` · Rate ${bill.rate_code}`}
            {bill.account_number && ` · Account ${bill.account_number}`}
          </span>
        </div>
        <div className="actions">
          <Link className="button" to={`/buildings/${buildingId}/bills/${bill.id}/upload`}>
            Upload a bill
          </Link>
          <Link className="button secondary" to={`/buildings/${buildingId}/bills/${bill.id}/entries/new`}>
            Add entry manually
          </Link>
          {selected.length > 0 && (
            <button type="button" className="danger" onClick={handleDelete}>
              {deleteLabel}
            </button>
          )}
        </div>
      </div>
      {error && <p className="error">{error}</p>}

      {bill.entries.length === 0 ? (
        <p className="muted">No entries yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th />
              <th>Billing period</th>
              <th>Consumption</th>
              {hasBilledPower && <th>Billed power</th>}
              <th>Cost before taxes</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {bill.entries.map((entry) => (
              <tr key={entry.id} className={selectedIds.includes(entry.id) ? "selected" : undefined}>
                <td>
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(entry.id)}
                    onChange={(e) => toggle(entry.id, e.target.checked)}
                    aria-label={`Select the bill for ${formatPeriod(entry.start_billing_period, entry.end_billing_period)}`}
                  />
                </td>
                <td>
                  <Link to={`/entries/${entry.id}`}>
                    {formatPeriod(entry.start_billing_period, entry.end_billing_period)}
                  </Link>
                </td>
                <td>{formatNumber(entry.consumption, unit)}</td>
                {hasBilledPower && <td>{formatNumber(entry.billed_power, "kW")}</td>}
                <td>{formatMoney(entry.bill_cost)}</td>
                <td>
                  <StatusBadge status={entry.status} />
                  {entry.source && <span className="muted source"> {entry.source}</span>}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td />
              <th scope="row">Total ({counted.length} periods)</th>
              <td>{formatNumber(totalConsumption, unit)}</td>
              {hasBilledPower && <td />}
              <td>{formatMoney(totalCost)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      )}
    </section>
  );
}

function NewBillForm({ buildingId, onCreated }) {
  const [form, setForm] = useState({ name: "", utility: "hydro_quebec", consumption_unit: "kWh" });
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    try {
      await apiSend("POST", `/api/buildings/${buildingId}/bills/`, form);
      setForm({ ...form, name: "" });
      onCreated();
    } catch (err) {
      setError(err.body ? JSON.stringify(err.body) : err.message);
    }
  }

  const update = (e) => setForm({ ...form, [e.target.name]: e.target.value });

  return (
    <form className="card inline-form" onSubmit={handleSubmit}>
      <h3>Add a bill</h3>
      <div className="field">
        <label htmlFor="new-bill-name">Name</label>
        <input id="new-bill-name" name="name" value={form.name} onChange={update} required placeholder="Électricité" />
      </div>
      <div className="field">
        <label htmlFor="new-bill-utility">Utility</label>
        <select id="new-bill-utility" name="utility" value={form.utility} onChange={update}>
          {UTILITIES.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
        </select>
      </div>
      <div className="field">
        <label htmlFor="new-bill-unit">Unit</label>
        <select id="new-bill-unit" name="consumption_unit" value={form.consumption_unit} onChange={update}>
          <option value="kWh">kWh</option>
          <option value="m3">m³</option>
        </select>
      </div>
      <button type="submit">Add</button>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

export default function BuildingDetail() {
  const { buildingId } = useParams();
  const [building, setBuilding] = useState(null);
  const [error, setError] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const navigate = useNavigate();

  function load() {
    apiGet(`/api/buildings/${buildingId}/`).then(setBuilding).catch((err) => setError(err.message));
  }

  useEffect(load, [buildingId]);

  async function handleDelete() {
    const count = building.bills.length;
    const what = count > 0 ? ` and its ${count} ${count === 1 ? "bill" : "bills"}` : "";
    if (!window.confirm(`Delete the building "${building.name}"${what}? This cannot be undone.`)) return;
    setDeleteError(null);
    try {
      await apiDelete(`/api/buildings/${building.id}/`);
      navigate("/");
    } catch (err) {
      setDeleteError(err.message);
    }
  }

  if (error) return <p className="error">{error}</p>;
  if (!building) return <p className="muted">Loading…</p>;

  return (
    <>
      <Link className="back-link" to="/">← All buildings</Link>
      <div className="toolbar">
        <h2>{building.name}</h2>
        <button type="button" className="danger" onClick={handleDelete}>
          Delete building
        </button>
      </div>
      <p className="muted subtitle">{building.address}</p>
      {deleteError && <p className="error">{deleteError}</p>}
      {building.bills.map((bill) => (
        <BillCard key={bill.id} buildingId={building.id} bill={bill} onDeleted={load} />
      ))}
      <NewBillForm buildingId={building.id} onCreated={load} />
    </>
  );
}
