// The list of saved canvases on the left.
export function renderSidebar(listEl, canvases, activeId, { onOpen, onDelete }) {
  listEl.innerHTML = "";
  for (const c of canvases) {
    const li = document.createElement("li");
    li.className = c.id === activeId ? "active" : "";
    const name = document.createElement("span");
    name.textContent = c.title || "Untitled";
    const del = document.createElement("button");
    del.className = "del";
    del.title = "Delete";
    del.textContent = "×";
    li.append(name, del);
    li.onclick = () => onOpen(c.id);
    del.onclick = (e) => { e.stopPropagation(); onDelete(c); };
    listEl.appendChild(li);
  }
}
