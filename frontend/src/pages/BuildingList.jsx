import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiGet, apiSend } from "../api";
import { utilityLabel } from "../format";

function NewBuildingForm() {
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", address: "" });
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    try {
      const building = await apiSend("POST", "/api/buildings/", form);
      navigate(`/buildings/${building.id}`);
    } catch (err) {
      setError(err.body ? JSON.stringify(err.body) : err.message);
    }
  }

  const update = (e) => setForm({ ...form, [e.target.name]: e.target.value });

  return (
    <form className="card inline-form" onSubmit={handleSubmit}>
      <h3>Add a building</h3>
      <div className="field">
        <label htmlFor="new-building-name">Name</label>
        <input id="new-building-name" name="name" value={form.name} onChange={update} required />
      </div>
      <div className="field grow">
        <label htmlFor="new-building-address">Address</label>
        <input id="new-building-address" name="address" value={form.address} onChange={update} required />
      </div>
      <button type="submit">Add</button>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

export default function BuildingList() {
  const [buildings, setBuildings] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    apiGet("/api/buildings/").then(setBuildings).catch((err) => setError(err.message));
  }, []);

  return (
    <>
      <h2>Buildings</h2>
      {error && <p className="error">{error}</p>}
      {!buildings && !error && <p className="muted">Loading…</p>}
      {buildings && buildings.length === 0 && <p className="muted">No buildings yet.</p>}
      {buildings && buildings.length > 0 && (
        <div className="building-grid">
          {buildings.map((building) => (
            <Link key={building.id} to={`/buildings/${building.id}`} className="card building-card">
              <strong>{building.name}</strong>
              <span className="muted">{building.address}</span>
              <ul className="bill-summary">
                {building.bills.map((bill) => (
                  <li key={bill.id}>
                    {bill.name} <span className="muted">· {utilityLabel(bill.utility)} · {bill.entry_count} entries</span>
                    {bill.pending_count > 0 && (
                      <span className="badge badge-needs_review">{bill.pending_count} to review</span>
                    )}
                  </li>
                ))}
                {building.bills.length === 0 && <li className="muted">No bills</li>}
              </ul>
            </Link>
          ))}
        </div>
      )}
      <NewBuildingForm />
    </>
  );
}
