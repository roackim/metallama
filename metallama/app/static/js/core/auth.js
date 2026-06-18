const TOKEN_KEY = "metallama_admin_token";

let _authEnabled = null; // null = unknown, true/false once checked
let _onChangeCallbacks = [];

/** Check if auth is enabled on the backend. */
export async function checkAuthEnabled() {
  try {
    const r = await fetch("/api/auth/status");
    const data = await r.json();
    _authEnabled = data.auth_enabled === true;
  } catch {
    _authEnabled = false;
  }
  return _authEnabled;
}

/** Return cached auth-enabled state. */
export function isAuthEnabled() {
  return _authEnabled === true;
}

/** Return whether we currently hold a valid admin token. */
export function isAdmin() {
  if (!_authEnabled) return true; // auth off → always admin
  return !!getToken();
}

/** Get the stored token (or null). */
export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

/** Return an Authorization header value (empty string if no token). */
export function authHeader() {
  const t = getToken();
  return t ? `Bearer ${t}` : "";
}

/** Attempt login with the given password. Returns true on success. */
export async function login(password) {
  const resp = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  const data = await resp.json();
  if (!resp.ok || !data.token) {
    throw new Error(data.detail || "Login failed");
  }
  sessionStorage.setItem(TOKEN_KEY, data.token);
  notifyChange();
  return true;
}

/** Logout: revoke server-side session and clear local token. */
export async function logout() {
  const token = getToken();
  if (token) {
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
    } catch { /* ignore */ }
  }
  sessionStorage.removeItem(TOKEN_KEY);
  notifyChange();
}

/** Subscribe to admin state changes. */
export function onAdminChange(cb) {
  _onChangeCallbacks.push(cb);
}

function notifyChange() {
  for (const cb of _onChangeCallbacks) {
    try { cb(isAdmin()); } catch { /* ignore */ }
  }
}
