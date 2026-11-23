// Calls to the local Think Canvas server. A 401 (not logged in) sends the browser to the login page.
async function call(url, method = "GET", body) {
  const isForm = body instanceof FormData;
  const res = await fetch(url, {
    method,
    headers: body === undefined || isForm ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !location.pathname.endsWith("login.html") && !url.startsWith("/api/auth/login")) {
    location.href = "/login.html";
    throw new Error("Please log in");
  }
  if (!res.ok) throw new Error(data.error?.message || res.statusText);
  return data;
}

export const api = {
  // account
  register: (name, email, password, organisation) => call("/api/auth/register", "POST", { name, email, password, organisation }),
  login: (email, password) => call("/api/auth/login", "POST", { email, password }),
  logout: () => call("/api/auth/logout", "POST"),
  me: () => call("/api/auth/me"),
  updateMe: (name, organisation) => call("/api/auth/me", "PUT", { name, organisation }),
  // canvases
  config: () => call("/api/config"),
  list: () => call("/api/canvases"),
  get: (id) => call(`/api/canvases/${id}`),
  create: (title) => call("/api/canvases", "POST", { title }),
  save: (id, title, items) => call(`/api/canvases/${id}`, "PUT", { title, items }),
  remove: (id) => call(`/api/canvases/${id}`, "DELETE"),
  // AI
  ask: (image, typed, canvasId, useLibrary) => call("/api/ask", "POST", { image, typed, canvas_id: canvasId, use_library: useLibrary }),
  history: () => call("/api/history"),
  // images and library
  uploadImage: (blob) => { const f = new FormData(); f.append("file", blob, "image.jpg"); return call("/api/assets", "POST", f); },
  documents: () => call("/api/documents"),
  uploadDocument: (file) => { const f = new FormData(); f.append("file", file); return call("/api/documents", "POST", f); },
  setDocumentActive: (id, active) => call(`/api/documents/${id}`, "PUT", { active }),
  deleteDocument: (id) => call(`/api/documents/${id}`, "DELETE"),
};
