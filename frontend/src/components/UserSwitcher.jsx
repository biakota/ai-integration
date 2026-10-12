import { useEffect, useState } from "react";
import {
  SEED_PASSWORD,
  SEED_USERS,
  ensureSession,
  getCurrentUser,
  login,
  setSession,
} from "../api";

export default function UserSwitcher() {
  const [selected, setSelected] = useState(getCurrentUser()?.username || "");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Bootstrap: if no session yet, sign in as the first seed user.
    // No reload here — this is the initial load.
    if (!getCurrentUser()) {
      (async () => {
        setBusy(true);
        try {
          await ensureSession();
          setSelected(getCurrentUser()?.username || "");
        } catch (err) {
          console.error(err);
          setSession(null);
        } finally {
          setBusy(false);
        }
      })();
    }
  }, []);

  async function handleChange(e) {
    const username = e.target.value;
    if (username === selected) return;
    setBusy(true);
    try {
      await login(username, SEED_PASSWORD);
      // Full reload so every page starts with a clean slate as the new user.
      window.location.reload();
    } catch (err) {
      console.error(err);
      setSession(null);
      setBusy(false);
    }
  }

  return (
    <div className="user-switcher">
      <label htmlFor="user-select" className="muted">Acting as:</label>
      <select
        id="user-select"
        value={selected}
        disabled={busy}
        onChange={handleChange}
      >
        {selected === "" && <option value="" disabled>—</option>}
        {SEED_USERS.map((u) => (
          <option key={u.username} value={u.username}>
            {u.username}{u.is_staff ? " (admin)" : ""}
          </option>
        ))}
      </select>
    </div>
  );
}
