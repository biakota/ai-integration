const TOKEN_KEY = "takehome.token";
const USER_KEY = "takehome.user";

export function getCurrentUser() {
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setSession(session) {
  if (session && session.token) {
    localStorage.setItem(TOKEN_KEY, session.token);
    localStorage.setItem(
      USER_KEY,
      JSON.stringify({
        id: session.user_id,
        username: session.username,
        is_staff: session.is_staff,
      })
    );
  } else {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }
}

function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class ApiError extends Error {
  constructor(path, status, body) {
    super(`Request to ${path} failed: ${status}`);
    this.status = status;
    this.body = body;
  }
}

// Seeded users — fixed, matches `backend/core/management/commands/seed.py`.
// All share the same password. First entry is the bootstrap default.
export const SEED_USERS = [
  { username: "alice", is_staff: false },
  { username: "admin", is_staff: true },
  { username: "bob",   is_staff: false },
];
export const SEED_PASSWORD = "takehome";

let bootstrap = null;

// If no session yet, sign in as the first seed user. Concurrent callers
// share one login so pages mounting at the same time all wait for the token.
export function ensureSession() {
  if (getToken()) return Promise.resolve();
  if (!bootstrap) {
    bootstrap = login(SEED_USERS[0].username, SEED_PASSWORD).finally(() => {
      bootstrap = null;
    });
  }
  return bootstrap;
}

async function request(path, options = {}) {
  await ensureSession();
  const res = await fetch(path, {
    ...options,
    headers: { ...authHeaders(), ...options.headers },
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(path, res.status, body);
  return body;
}

export function apiGet(path) {
  return request(path);
}

export function apiSend(method, path, body) {
  return request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function apiDelete(path) {
  return request(path, { method: "DELETE" });
}

export function apiUpload(path, files) {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  // No Content-Type header: the browser sets the multipart boundary.
  return request(path, { method: "POST", body: form });
}

export async function login(username, password) {
  // Login itself must not send a stale token.
  const res = await fetch("/api/auth/login/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new ApiError("/api/auth/login/", res.status, await res.text());
  const session = await res.json();
  setSession(session);
  return session;
}
