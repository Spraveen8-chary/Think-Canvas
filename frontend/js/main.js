// Think Canvas page logic.
// Flow: you write / type / import an image -> pause -> a dashed box marks it -> the AI reads it ->
// the answer (text, plot, chart, flowchart, drawing or animation) appears on the canvas next to it.
// Everything is saved to your account in MongoDB through the Python backend.
import { Board } from "./board.js";
import { api } from "./api.js";
import { renderSidebar } from "./sidebar.js";
import { union } from "./geometry.js";
import { shrinkImage } from "./imaging.js";
import { library, initLibrary, initHistory, initAccount, initDialogClose } from "./dialogs.js";

const $ = (id) => document.getElementById(id);
const board = new Board($("board"));

// ---- small helpers -------------------------------------------------------------
const store = {
  get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
function setStatus(text, kind = "") {
  $("status").textContent = text;
  $("status").dataset.kind = kind;
}

let canvasId = null;
let dirty = null;          // box around input the AI has not read yet
let timer = null;
let busy = false;
let auto = store.get("tc.auto", "1") === "1";
let delay = Number(store.get("tc.delay", 0)) || 2500;
let sessionTokens = 0;

// ---- auto-detect: wait for a pause, then read what was just added ------------------------
function showCountdown(on) {
  const bar = $("timerBar");
  bar.style.transition = "none";
  bar.style.width = "0%";
  if (!on) return;
  bar.getBoundingClientRect();                       // restart the CSS transition
  bar.style.transition = `width ${delay}ms linear`;
  bar.style.width = "100%";
}

function cancelTimer() {
  clearTimeout(timer);
  timer = null;
  showCountdown(false);
}

function armTimer() {
  cancelTimer();
  if (!auto || !dirty || busy) return;
  board.spot = dirty;
  board.render();
  setStatus("Input detected, reading when you pause…", "wait");
  showCountdown(true);
  timer = setTimeout(() => ask(dirty), delay);
}

board.onStrokeStart = cancelTimer;                   // still writing: hold on
board.onUserInput = (box) => { dirty = union(dirty, box); armTimer(); };

async function ask(seed) {
  cancelTimer();
  const near = board.itemsNear(seed);
  if (!near.length) return;
  const box = board.unionBox(near, seed);
  const typed = near.filter((i) => i.type === "text").map((i) => i.text).join("\n");
  const visual = near.filter((i) => i.type !== "text");

  dirty = null;
  busy = true;
  board.spot = box;
  board.render();
  setStatus("Reading…", "busy");
  $("askNow").disabled = true;
  try {
    const image = visual.length ? board.snapshot(visual, box) : null;   // typed text alone costs no image tokens
    const res = await api.ask(image, typed, canvasId, library.enabled);
    const used = res.tokens.in + res.tokens.out;
    sessionTokens += used;
    $("tokens").textContent = `${sessionTokens.toLocaleString()} tokens this session`;
    if (res.blocks.length && board.addBlocks(res.blocks, box)) {
      setStatus(`Answered · ${used || "?"} tokens${res.sources.length ? " · from " + res.sources.join(", ") : ""}`, "ok");
    } else {
      setStatus("Nothing to answer here", "");
    }
  } catch (e) {
    setStatus(e.message, "error");
  } finally {
    busy = false;
    board.spot = null;
    board.render();
    $("askNow").disabled = false;
    if (dirty) armTimer();                           // more was added while we were busy
  }
}

// ---- typing on the canvas ------------------------------------------------------------
board.onTextClick = (world, screen) => {
  document.querySelector(".typing")?.remove();
  const stage = $("board").parentElement.getBoundingClientRect();
  const box = document.createElement("textarea");
  box.className = "typing";
  box.placeholder = "Type a question…  (Enter to finish)";
  box.style.left = `${screen.x - stage.left}px`;
  box.style.top = `${screen.y - stage.top}px`;
  $("board").parentElement.appendChild(box);
  cancelTimer();
  let done = false;
  const finish = (keep) => {
    if (done) return;
    done = true;
    const text = box.value.trim();
    box.remove();
    if (keep && text) board.addText(text, world.x, world.y);
  };
  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); finish(true); }
    if (e.key === "Escape") finish(false);
  });
  box.addEventListener("blur", () => finish(true));
  setTimeout(() => box.focus());
};

// ---- importing images -----------------------------------------------------------------
async function importImage(file) {
  if (!file || !file.type.startsWith("image/")) return setStatus("That is not an image file", "error");
  setStatus("Adding image…", "busy");
  try {
    const { blob, w, h } = await shrinkImage(file);
    const { id } = await api.uploadImage(blob);
    const k = Math.min(1, 420 / w, 320 / h), v = board.viewBox();
    board.addImage(id, v.x + 60, v.y + 60, w * k, h * k);
    setStatus(auto ? "Image added, explaining when you pause…" : "Image added. Press Answer now to explain it.", "wait");
  } catch (e) {
    setStatus(e.message, "error");
  }
}
$("importImage").onclick = () => $("imageFile").click();
$("imageFile").onchange = () => { importImage($("imageFile").files[0]); $("imageFile").value = ""; };
window.addEventListener("paste", (e) => {
  const file = [...(e.clipboardData?.files || [])].find((f) => f.type.startsWith("image/"));
  if (file) { e.preventDefault(); importImage(file); }
});
const stage = $("board").parentElement;
stage.addEventListener("dragover", (e) => e.preventDefault());
stage.addEventListener("drop", (e) => { e.preventDefault(); importImage(e.dataTransfer.files[0]); });

// ---- toolbar -------------------------------------------------------------------
const toolButtons = { pen: $("toolPen"), text: $("toolText"), eraser: $("toolEraser"), hand: $("toolHand") };
function selectTool(name) {
  board.setTool(name);
  for (const [n, b] of Object.entries(toolButtons)) b.classList.toggle("on", n === name);
}
for (const [name, button] of Object.entries(toolButtons)) button.onclick = () => selectTool(name);
selectTool("pen");

const resetPending = () => { dirty = null; cancelTimer(); board.spot = null; };
$("undo").onclick = () => { resetPending(); board.undo(); };
$("clear").onclick = () => { if (board.items.length && confirm("Clear this whole canvas?")) { resetPending(); board.clear(); } };

const GRIDS = ["lines", "dots", "none"];
board.grid = store.get("tc.grid", "lines");
$("grid").textContent = `Grid: ${board.grid}`;
$("grid").onclick = () => {
  board.grid = GRIDS[(GRIDS.indexOf(board.grid) + 1) % GRIDS.length];
  store.set("tc.grid", board.grid);
  $("grid").textContent = `Grid: ${board.grid}`;
  board.render();
};

$("auto").checked = auto;
$("auto").onchange = () => {
  auto = $("auto").checked;
  store.set("tc.auto", auto ? "1" : "0");
  if (auto) armTimer(); else { cancelTimer(); board.spot = null; board.render(); setStatus(""); }
};
$("delay").onchange = () => { delay = Number($("delay").value); store.set("tc.delay", delay); };

$("askNow").onclick = () => {
  const seed = dirty || board.inkBounds();
  if (!seed) return setStatus("Write, type or import something first", "");
  ask(seed);
};

// ---- finding your work ---------------------------------------------------------------
// "Find my work" jumps to your most recent spot; press again to visit the next one.
function findWork() {
  const r = board.contentVisible() ? board.nextSpot() : board.goToSpot(0);
  setStatus(r ? (r.total > 1 ? `Work spot ${r.index + 1} of ${r.total}` : "Here is your work") : "Nothing drawn yet", "");
}
$("find").onclick = findWork;
$("backPill").onclick = () => board.goToSpot(0);
board.onView = () => { $("backPill").hidden = board.contentVisible(); };

window.addEventListener("keydown", (e) => {
  if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  if (e.code === "Space") { board.spaceDown = true; e.preventDefault(); }
  if (e.key === "Home") { e.preventDefault(); findWork(); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); $("undo").click(); }
});
window.addEventListener("keyup", (e) => { if (e.code === "Space") board.spaceDown = false; });

// ---- saving (your account in MongoDB, through the Python backend) ----------------------------
let saveTimer = null;
async function saveNow() {
  clearTimeout(saveTimer);
  if (canvasId) await api.save(canvasId, $("title").value, board.items);
}
function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => { try { await saveNow(); refreshList(); } catch (e) { setStatus(`Not saved: ${e.message}`, "error"); } }, 500);
}
board.onChange = () => {
  $("hint").hidden = board.items.length > 0;
  scheduleSave();
};
$("title").oninput = scheduleSave;

async function refreshList() {
  const list = await api.list();
  renderSidebar($("canvasList"), list, canvasId, { onOpen: openCanvas, onDelete: deleteCanvas });
  return list;
}

async function openCanvas(id) {
  board.locked = true;                               // ignore the pen until the canvas has loaded
  try {
    await saveNow();
    resetPending();
    const c = await api.get(id);
    canvasId = id;
    $("title").value = c.title;
    board.setItems(c.items);
    $("hint").hidden = board.items.length > 0;
    setStatus("");
    refreshList();
  } finally {
    board.locked = false;
  }
}

async function newCanvas() {
  const { id } = await api.create("Untitled");
  await openCanvas(id);
}

async function deleteCanvas(c) {
  if (!confirm(`Delete "${c.title}"?`)) return;
  await api.remove(c.id);
  if (c.id === canvasId) canvasId = null;
  const list = await refreshList();
  if (!canvasId) list.length ? openCanvas(list[0].id) : newCanvas();
}
$("newCanvas").onclick = newCanvas;

// ---- start -----------------------------------------------------------------------
(async function init() {
  const [user, cfg] = await Promise.all([api.me(), api.config()]);     // not logged in -> login page
  $("userName").textContent = user.name;
  $("provider").textContent = `AI: ${cfg.provider}`;
  if (!store.get("tc.delay", 0)) delay = cfg.autoAskDelayMs;
  $("delay").value = String(delay);
  if (!$("delay").value) { $("delay").add(new Option(`${(delay / 1000).toFixed(1)} s`, String(delay))); $("delay").value = String(delay); }
  initDialogClose();
  initLibrary();
  initHistory();
  initAccount(user, (name) => { $("userName").textContent = name; });
  const list = await refreshList();
  list.length ? openCanvas(list[0].id) : newCanvas();
})().catch((e) => setStatus(e.message, "error"));
