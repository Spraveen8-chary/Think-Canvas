// The three pop-up dialogs: Library (textbooks/PDFs for RAG), History, Account.
import { api } from "./api.js";

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };

export const library = {
  get enabled() { try { return localStorage.getItem("tc.rag") !== "0"; } catch { return true; } },
  set enabled(v) { try { localStorage.setItem("tc.rag", v ? "1" : "0"); } catch { /* ignore */ } },
};

// ---- Library -------------------------------------------------------------------------
async function renderLibrary() {
  const docs = await api.documents();
  const list = $("docList");
  list.innerHTML = "";
  if (!docs.length) list.append(el("li", { className: "empty", textContent: "No books yet. Add a PDF, TXT or MD file." }));
  for (const d of docs) {
    const use = el("input", { type: "checkbox", checked: d.active, title: "Use this book when answering" });
    use.onchange = () => api.setDocumentActive(d.id, use.checked);
    const del = el("button", { className: "del", title: "Delete", textContent: "×" });
    del.onclick = async () => { if (confirm(`Remove "${d.name}" from your library?`)) { await api.deleteDocument(d.id); renderLibrary(); } };
    list.append(el("li", {}, use, el("span", { className: "grow" }, el("b", { textContent: d.name }), el("small", { textContent: `${d.pages} pages · ${d.chunks} passages` })), del));
  }
}

export function initLibrary() {
  const dlg = $("libraryDialog"), status = $("libStatus");
  $("openLibrary").onclick = () => { status.textContent = ""; renderLibrary(); dlg.showModal(); };
  $("useLibrary").checked = library.enabled;
  $("useLibrary").onchange = () => { library.enabled = $("useLibrary").checked; };
  $("docFile").onchange = async () => {
    const files = [...$("docFile").files];
    for (const f of files) {
      status.textContent = `Reading ${f.name}…`;
      try { await api.uploadDocument(f); status.textContent = `Added ${f.name}`; } catch (e) { status.textContent = `${f.name}: ${e.message}`; break; }
    }
    $("docFile").value = "";
    renderLibrary();
  };
}

// ---- Warning pop-up (inappropriate language) --------------------------------------------
// v = { title, message, strikes, limit, suspended }. After a suspension the student is signed out.
export function showViolation(v) {
  const dlg = $("violationDialog");
  $("violTitle").textContent = v.title || "Warning";
  $("violMessage").textContent = v.message || "";
  $("violStrikes").textContent = v.limit ? `Strike ${Math.min(v.strikes, v.limit)} of ${v.limit}` : "";
  dlg.onclose = async () => {
    if (v.suspended) { try { await api.logout(); } catch { /* ignore */ } location.href = "/login.html"; }
  };
  if (!dlg.open) dlg.showModal();
}
window.addEventListener("tc:suspended", (e) => showViolation({ title: "Account suspended", message: e.detail, suspended: true }));

// ---- History -------------------------------------------------------------------------
export function initHistory() {
  const dlg = $("historyDialog");
  $("openHistory").onclick = async () => {
    const rows = await api.history();
    const list = $("historyList");
    list.innerHTML = "";
    if (!rows.length) list.append(el("li", { className: "empty", textContent: "Nothing asked yet." }));
    for (const r of rows) {
      const when = new Date(r.ts).toLocaleString();
      const tok = r.tokens ? ` · ${r.tokens.in + r.tokens.out} tokens` : "";
      list.append(el("li", {}, el("span", { className: "grow" },
        el("b", { textContent: r.read || "(unread)" }),
        el("small", { textContent: r.answer || r.kinds.join(", ") || "no answer" }),
        el("small", { className: "meta", textContent: `${when}${tok}${r.sources.length ? " · " + r.sources.join(", ") : ""}` }))));
    }
    dlg.showModal();
  };
}

// ---- Account -------------------------------------------------------------------------
export function initAccount(user, onName) {
  const dlg = $("accountDialog");
  $("openAccount").onclick = () => {
    $("accName").value = user.name; $("accOrg").value = user.organisation || ""; $("accEmail").value = user.email;
    $("accSince").textContent = user.created_at ? `Member since ${new Date(user.created_at).toLocaleDateString()}` : "";
    $("accStatus").textContent = "";
    dlg.showModal();
  };
  $("accSave").onclick = async (e) => {
    e.preventDefault();
    const u = await api.updateMe($("accName").value, $("accOrg").value);
    Object.assign(user, u);
    onName(u.name);
    $("accStatus").textContent = "Saved";
  };
  $("accLogout").onclick = async () => { await api.logout(); location.href = "/login.html"; };
}

// Close buttons on every dialog
export function initDialogClose() {
  document.querySelectorAll("dialog [data-close]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); b.closest("dialog").close(); }));
}
