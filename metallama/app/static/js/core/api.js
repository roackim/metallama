import { authHeader } from "./auth.js";

export async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json" };
  const auth = authHeader();
  if (auth) headers["Authorization"] = auth;

  const response = await fetch(path, {
    headers,
    ...options,
  });

  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    const detail = data.detail || `Request failed (${response.status})`;
    throw new Error(detail);
  }

  return data;
}
