import { Link, Route, Routes } from "react-router-dom";
import UserSwitcher from "./components/UserSwitcher.jsx";
import BuildingDetail from "./pages/BuildingDetail.jsx";
import BuildingList from "./pages/BuildingList.jsx";
import EntryForm from "./pages/EntryForm.jsx";
import UploadBill from "./pages/UploadBill.jsx";

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>
          <Link to="/" style={{ color: "inherit", textDecoration: "none" }}>
            vadiMAP — Utility bills
          </Link>
        </h1>
        <UserSwitcher />
      </header>
      <main>
        <Routes>
          <Route path="/" element={<BuildingList />} />
          <Route path="/buildings/:buildingId" element={<BuildingDetail />} />
          <Route path="/buildings/:buildingId/bills/:billId/upload" element={<UploadBill />} />
          <Route path="/buildings/:buildingId/bills/:billId/entries/new" element={<EntryForm />} />
          <Route path="/entries/:entryId" element={<EntryForm />} />
        </Routes>
      </main>
    </div>
  );
}
