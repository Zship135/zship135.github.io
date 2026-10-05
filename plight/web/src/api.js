const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export function liveUrl() {
  const url = new URL(`${API_BASE}/api/v1/live`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export async function api(path, { token, ...options } = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "ngrok-skip-browser-warning": "true",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (response.status === 204) return null;
  const body = await response.json();
  if (!response.ok) {
    const error = new Error(body?.error?.message || "The server could not complete that request.");
    error.status = response.status;
    throw error;
  }
  return body;
}
