import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiUpload } from "../api";
import { useBill } from "../hooks";
import { utilityLabel } from "../format";

export default function UploadBill() {
  const { buildingId, billId } = useParams();
  const { building, bill, error: loadError } = useBill(buildingId, billId);
  const navigate = useNavigate();
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const entry = await apiUpload(`/api/bills/${billId}/upload/`, files);
      navigate(`/entries/${entry.id}`);
    } catch (err) {
      setError(err.body ? JSON.stringify(err.body) : err.message);
      setBusy(false);
    }
  }

  if (loadError) return <p className="error">{loadError}</p>;
  if (!bill) return <p className="muted">Loading…</p>;

  return (
    <>
      <Link className="back-link" to={`/buildings/${buildingId}`}>← {building.name}</Link>
      <h2>Upload a bill</h2>
      <p className="muted subtitle">
        Adds one billing period to <strong>{bill.name}</strong> ({utilityLabel(bill.utility)}).
      </p>
      <form className="card" onSubmit={handleSubmit}>
        <label htmlFor="bill-files">One PDF, or one photo per page (PNG / JPEG)</label>
        <input
          id="bill-files"
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          onChange={(e) => setFiles(Array.from(e.target.files))}
        />
        {files.length > 0 && (
          <ul className="file-list">
            {files.map((f) => (
              <li key={f.name}>{f.name} <span className="muted">({Math.round(f.size / 1024)} KB)</span></li>
            ))}
          </ul>
        )}
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy || files.length === 0}>
          {busy ? "Reading bill…" : "Upload"}
        </button>
      </form>
    </>
  );
}
