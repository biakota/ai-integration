import { useEffect, useState } from "react";
import { apiGet } from "./api";

// Loads a building and picks one of its bills — enough context for pages
// that act on a bill (upload, manual entry).
export function useBill(buildingId, billId) {
  const [state, setState] = useState({ building: null, bill: null, error: null });

  useEffect(() => {
    if (!buildingId) return;
    apiGet(`/api/buildings/${buildingId}/`)
      .then((building) => {
        const bill = building.bills.find((b) => String(b.id) === String(billId));
        setState({ building, bill, error: bill ? null : "Bill not found." });
      })
      .catch((err) => setState({ building: null, bill: null, error: err.message }));
  }, [buildingId, billId]);

  return state;
}
