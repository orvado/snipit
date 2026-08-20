import { getCurrentWindow } from "@tauri-apps/api/window";
import { listen } from "@tauri-apps/api/event";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";
import { api, type Snippet, type BackupMeta } from "./api";

const HINT =
  "Enter to copy \u00b7 Double-click or Ctrl+Enter for details \u00b7 Ctrl+N new \u00b7 Ctrl+E edit \u00b7 Ctrl+Del delete \u00b7 Esc hide";

let snippets: Snippet[] = [];
let selectedIdx = 0;
let autoHideTimer: number | null = null;
let noticeTimer: number | null = null;
let searchDebounce: number | null = null;
let config: Awaited<ReturnType<typeof api.getConfig>> | null = null;

function el<T extends HTMLElement>(id: string): T {
  return document.getElementById(id) as T;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function formatRow(idx: number, s: Snippet): string {
  const heading = (s.heading || "").trim() || "(no title)";
  const preview = s.content.split(/\s+/).join(" ").slice(0, 120);
  return `${String(idx + 1).padStart(3, " ")}. ${heading}  \u2502  ${preview}`;
}

function showNotice(text: string, cls: string, ms: number) {
  const status = el("status");
  if (noticeTimer) window.clearTimeout(noticeTimer);
  status.textContent = text;
  status.className = cls;
  noticeTimer = window.setTimeout(() => {
    noticeTimer = null;
    updateStatus();
  }, ms);
}

function updateStatus() {
  if (noticeTimer) return;
  const q = (el<HTMLInputElement>("search").value || "").trim();
  const n = snippets.length;
  const count = el("count");
  const status = el("status");
  if (q) {
    count.textContent = `${n} match${n === 1 ? "" : "es"}`;
  } else {
    count.textContent = `${n} snippet${n === 1 ? "" : "s"}`;
  }
  if (n === 0 && q) {
    status.textContent = "No matches — try fewer terms";
    status.className = "danger";
  } else if (n === 0) {
    status.textContent = "No snippets yet — press Ctrl+N to add one";
    status.className = "";
  } else {
    status.textContent = HINT;
    status.className = "";
  }
}

function renderResults() {
  const ul = el<HTMLUListElement>("results");
  ul.innerHTML = "";
  snippets.forEach((s, i) => {
    const li = document.createElement("li");
    li.textContent = formatRow(i, s);
    li.dataset.id = String(s.id);
    if (i === selectedIdx) li.classList.add("selected");
    li.addEventListener("click", () => {
      selectedIdx = i;
      renderResults();
    });
    li.addEventListener("dblclick", () => openDetail(s));
    ul.appendChild(li);
  });
  if (snippets.length > 0) {
    const sel = ul.children[selectedIdx] as HTMLElement | undefined;
    sel?.scrollIntoView({ block: "nearest" });
  }
  updateStatus();
}

async function doSearch() {
  const q = el<HTMLInputElement>("search").value;
  snippets = await api.search(q);
  selectedIdx = 0;
  renderResults();
}

function scheduleSearch() {
  if (searchDebounce) window.clearTimeout(searchDebounce);
  searchDebounce = window.setTimeout(() => {
    searchDebounce = null;
    void doSearch();
  }, 60);
}

function selectedSnippet(): Snippet | null {
  if (snippets.length === 0) return null;
  return snippets[Math.max(0, Math.min(selectedIdx, snippets.length - 1))] ?? null;
}

function moveSelection(delta: number) {
  if (snippets.length === 0) return;
  selectedIdx = Math.max(0, Math.min(snippets.length - 1, selectedIdx + delta));
  renderResults();
}

function cancelAutoHide() {
  if (autoHideTimer) {
    window.clearTimeout(autoHideTimer);
    autoHideTimer = null;
  }
}

async function copySelected() {
  const row = selectedSnippet();
  if (!row) return;
  await doCopy(row);
}

async function doCopy(row: Snippet) {
  // Prefer Tauri clipboard plugin (works on both platforms and outlives the app).
  // Fall back to Rust copy_text for Windows CRLF handling.
  try {
    await writeText(row.content);
  } catch {
    await api.copyText(row.content);
  }
  await api.markUsed(row.id);
  await doSearch();
  detailDialog.close();
  const secs = config ? `${config.auto_close_ms / 1000}` : "1.5";
  showNotice(`Copied \u2713 — hiding in ${secs}s \u00b7 press Esc to keep open`, "notice", (config?.auto_close_ms ?? 1500) + 900);
  cancelAutoHide();
  autoHideTimer = window.setTimeout(async () => {
    autoHideTimer = null;
    await getCurrentWindow().hide();
  }, config?.auto_close_ms ?? 1500);
}

function handleEscape() {
  if (autoHideTimer) {
    cancelAutoHide();
    showNotice("Auto-close cancelled — window stays open", "ok", 1800);
    return;
  }
  const q = el<HTMLInputElement>("search").value;
  if (q.trim()) {
    el<HTMLInputElement>("search").value = "";
    void doSearch();
    return;
  }
  void getCurrentWindow().hide();
}

// ---- Detail dialog
const detailDialog = el<HTMLDialogElement>("detail-dialog");
function openDetail(row: Snippet) {
  void api.markUsed(row.id).then(() => void doSearch());
  el("detail-heading").textContent = (row.heading || "").trim() || "(no title)";
  const lines = row.content.split("\n").length;
  el("detail-meta").textContent = `${lines} line${lines === 1 ? "" : "s"} \u00b7 ${row.content.length} chars`;
  const contentEl = el("detail-content");
  contentEl.textContent = row.content;
  (detailDialog as unknown as { _row: Snippet })._row = row;
  detailDialog.showModal();
}

// ---- Edit dialog
const editDialog = el<HTMLDialogElement>("edit-dialog");
let editMode: { id: number | null } = { id: null };

function openAdd() {
  editMode.id = null;
  el<HTMLHeadingElement>("edit-title").textContent = "New snippet";
  el<HTMLInputElement>("edit-heading").value = "";
  el<HTMLTextAreaElement>("edit-content").value = "";
  updateEditCounter();
  editDialog.showModal();
  el<HTMLInputElement>("edit-heading").focus();
}

function openEditSelected() {
  const row = selectedSnippet();
  if (row) openEdit(row);
}

function openEdit(row: Snippet) {
  editMode.id = row.id;
  el<HTMLHeadingElement>("edit-title").textContent = "Edit snippet";
  el<HTMLInputElement>("edit-heading").value = row.heading;
  el<HTMLTextAreaElement>("edit-content").value = row.content;
  updateEditCounter();
  detailDialog.close();
  editDialog.showModal();
  el<HTMLInputElement>("edit-heading").focus();
}

function updateEditCounter() {
  if (!config) return;
  const text = el<HTMLTextAreaElement>("edit-content").value;
  const n = text.length;
  const counter = el("edit-counter");
  const over = n > config.max_content_len;
  counter.textContent = `${n.toLocaleString()} / ${config.max_content_len.toLocaleString()}${over ? "  — too long to save" : ""}`;
  counter.className = over ? "counter over" : "counter";
  const saveBtn = el<HTMLButtonElement>("edit-save");
  const empty = !text.trim();
  saveBtn.disabled = over || empty;
}

async function saveEdit() {
  if (!config) return;
  const heading = el<HTMLInputElement>("edit-heading").value.trim().slice(0, config.max_heading_len);
  const content = el<HTMLTextAreaElement>("edit-content").value;
  if (!content.trim()) return;
  if (content.length > config.max_content_len) {
    alert(`This snippet is ${content.length.toLocaleString()} characters; the limit is ${config.max_content_len.toLocaleString()}. Shorten it and save again.`);
    return;
  }
  if (editMode.id == null) {
    const id = await api.addSnippet(heading, content);
    await doSearch();
    const idx = snippets.findIndex((s) => s.id === id);
    if (idx >= 0) {
      selectedIdx = idx;
      renderResults();
    }
    showNotice(`Saved \u201c${heading || "(no title)"}\u201d`, "ok", 1600);
  } else {
    await api.updateSnippet(editMode.id, heading, content);
    await doSearch();
    const idx = snippets.findIndex((s) => s.id === editMode.id);
    if (idx >= 0) {
      selectedIdx = idx;
      renderResults();
    }
    showNotice("Snippet updated", "ok", 1600);
  }
  editDialog.close();
}

async function deleteSelected() {
  const row = selectedSnippet();
  if (!row) return;
  const title = (row.heading || "").trim() || "(no title)";
  if (!confirm(`Delete \u201c${title}\u201d?\n\nThis cannot be undone.`)) return;
  await api.deleteSnippet(row.id);
  detailDialog.close();
  await doSearch();
}

// ---- Cloud dialog
const cloudDialog = el<HTMLDialogElement>("cloud-dialog");
let cloudBusy: string | null = null;
let cloudBackups: BackupMeta[] = [];
let selectedBackupName = "";

function setCloudBusy(op: string | null) {
  cloudBusy = op;
  refreshCloudState();
}

function refreshCloudState() {
  const connected = (el("cloud-status") as unknown as { _connected?: boolean })._connected ?? false;
  const idle = cloudBusy == null;
  const hasSelection = !!selectedBackupName;
  const connectBtn = el<HTMLButtonElement>("cloud-connect");
  const disconnectBtn = el<HTMLButtonElement>("cloud-disconnect");
  const backupBtn = el<HTMLButtonElement>("cloud-backup");
  const restoreBtn = el<HTMLButtonElement>("cloud-restore");
  connectBtn.textContent = cloudBusy === "connect" ? "Connecting\u{2026}" : "Connect\u{2026}";
  connectBtn.disabled = connected || !idle;
  disconnectBtn.disabled = !connected || !idle;
  backupBtn.textContent = cloudBusy === "backup" ? "Backing up\u{2026}" : "Back up now";
  backupBtn.disabled = !connected || !idle;
  restoreBtn.textContent = cloudBusy === "restore" ? "Restoring\u{2026}" : "Restore selected";
  restoreBtn.disabled = !connected || !idle || !hasSelection;
}

async function openCloud() {
  cloudDialog.showModal();
  await refreshCloud();
}

async function refreshCloud() {
  const status = await api.cloudStatus();
  const statusEl = el("cloud-status");
  (statusEl as unknown as { _connected?: boolean })._connected = status.connected;
  statusEl.textContent = status.connected ? "Connected. Cloud backup is ready." : "Not connected. Connect with your Google account.";
  statusEl.className = status.connected ? "ok" : "";
  refreshCloudState();
  if (status.connected) {
    await loadBackups();
  } else {
    cloudBackups = [];
    renderBackups();
  }
}

async function loadBackups() {
  const statusEl = el("cloud-status");
  statusEl.textContent = "Loading backups\u{2026}";
  setCloudBusy("list");
  try {
    cloudBackups = await api.listBackups();
    renderBackups();
    statusEl.textContent = cloudBackups.length ? "Backups ready" : "No cloud backups yet";
    statusEl.className = "";
  } catch (e) {
    statusEl.textContent = `List failed: ${String(e)}`;
    statusEl.className = "danger";
  } finally {
    setCloudBusy(null);
    await refreshCloudStatusOnly();
  }
}

async function refreshCloudStatusOnly() {
  const s = await api.cloudStatus();
  const statusEl = el("cloud-status");
  (statusEl as unknown as { _connected?: boolean })._connected = s.connected;
  refreshCloudState();
}

function renderBackups() {
  const ul = el<HTMLUListElement>("cloud-list");
  ul.innerHTML = "";
  cloudBackups.forEach((m) => {
    const li = document.createElement("li");
    li.textContent = `${m.name}   (${m.size.toLocaleString()} B)`;
    if (m.name === selectedBackupName) li.classList.add("selected");
    li.addEventListener("click", () => {
      selectedBackupName = m.name;
      renderBackups();
      refreshCloudState();
    });
    li.addEventListener("dblclick", () => {
      selectedBackupName = m.name;
      void doRestore();
    });
    ul.appendChild(li);
  });
  refreshCloudState();
}

async function doConnect() {
  if (cloudBusy) {
    showCloudStatus("Another cloud action is already in progress", "notice");
    return;
  }
  setCloudBusy("connect");
  const statusEl = el("cloud-status");
  statusEl.textContent = "Waiting for browser sign-in\u{2026}";
  try {
    await api.cloudConnect();
    statusEl.textContent = "Cloud connected";
    statusEl.className = "ok";
  } catch (e) {
    statusEl.textContent = `Connect failed: ${String(e)}`;
    statusEl.className = "danger";
  } finally {
    setCloudBusy(null);
    await refreshCloud();
  }
}

async function doDisconnect() {
  if (cloudBusy) return;
  await api.cloudDisconnect();
  selectedBackupName = "";
  await refreshCloud();
  const statusEl = el("cloud-status");
  statusEl.textContent = "Cloud disconnected";
  statusEl.className = "";
}

async function doBackup() {
  if (cloudBusy) return;
  setCloudBusy("backup");
  const statusEl = el("cloud-status");
  statusEl.textContent = "Backing up snippets\u{2026}";
  try {
    const name = await api.backupNow();
    statusEl.textContent = `Backup complete: ${name}`;
    statusEl.className = "ok";
    await loadBackups();
  } catch (e) {
    statusEl.textContent = `Backup failed: ${String(e)}`;
    statusEl.className = "danger";
    setCloudBusy(null);
  }
}

async function doRestore() {
  if (cloudBusy) return;
  if (!selectedBackupName) {
    showCloudStatus("Select a backup to restore", "notice");
    return;
  }
  if (!confirm(`Restore \u201c${selectedBackupName}\u201d?\n\nLocal changes made after this backup will be lost.\nA safety snapshot of the current database is kept in the backups folder.`)) {
    return;
  }
  setCloudBusy("restore");
  const statusEl = el("cloud-status");
  statusEl.textContent = `Restoring ${selectedBackupName}\u{2026}`;
  try {
    await api.restoreBackup(selectedBackupName);
    statusEl.textContent = "Restore complete";
    statusEl.className = "ok";
    await doSearch();
    await loadBackups();
  } catch (e) {
    statusEl.textContent = `Restore failed: ${String(e)}`;
    statusEl.className = "danger";
    setCloudBusy(null);
    await doSearch();
  }
}

function showCloudStatus(text: string, cls: string) {
  const statusEl = el("cloud-status");
  statusEl.textContent = text;
  statusEl.className = cls;
}

function buildShell() {
  const app = document.getElementById("app")!;
  app.innerHTML = `
    <div class="top-label">Search snippets</div>
    <div class="top-row">
      <div class="search-wrap">
        <input id="search" type="text" autocomplete="off" spellcheck="false" placeholder="Type a title or phrase" />
      </div>
      <button id="btn-clear" class="btn">Clear</button>
      <button id="btn-cloud" class="btn">Cloud</button>
      <button id="btn-add" class="btn btn-primary">Add snippet</button>
    </div>
    <div class="list-wrap"><ul id="results"></ul></div>
    <div class="status-bar">
      <span id="status" class="hint">${escapeHtml(HINT)}</span>
      <span id="count"></span>
    </div>

    <dialog id="detail-dialog">
      <div class="dialog-body">
        <h3 id="detail-heading" class="dialog-title"></h3>
        <div id="detail-meta" class="dialog-meta"></div>
        <div id="detail-content" class="dialog-content"></div>
        <div class="dialog-actions">
          <button id="detail-copy" class="btn btn-primary">Copy</button>
          <button id="detail-edit" class="btn">Edit\u{2026}</button>
          <button id="detail-delete" class="btn danger">Delete</button>
          <span class="spacer"></span>
          <button id="detail-close" class="btn">Close</button>
        </div>
      </div>
    </dialog>

    <dialog id="edit-dialog">
      <div class="dialog-body">
        <h3 id="edit-title" class="dialog-title">Snippet</h3>
        <label class="field-label" for="edit-heading">Heading (optional)</label>
        <input id="edit-heading" class="field-input" type="text" maxlength="120" />
        <label class="field-label" for="edit-content">Content</label>
        <textarea id="edit-content" class="field-textarea"></textarea>
        <div id="edit-counter" class="counter"></div>
        <div class="dialog-actions">
          <span class="spacer"></span>
          <button id="edit-cancel" class="btn">Cancel (Esc)</button>
          <button id="edit-save" class="btn btn-primary">Save (Ctrl+Enter)</button>
        </div>
      </div>
    </dialog>

    <dialog id="cloud-dialog">
      <div class="dialog-body">
        <div id="cloud-status"></div>
        <div class="dialog-actions" style="margin-top:10px">
          <button id="cloud-connect" class="btn btn-primary">Connect\u{2026}</button>
          <button id="cloud-disconnect" class="btn">Disconnect</button>
          <span class="spacer"></span>
          <button id="cloud-close" class="btn">Close</button>
        </div>
        <div class="dialog-actions">
          <button id="cloud-backup" class="btn">Back up now</button>
          <button id="cloud-restore" class="btn danger">Restore selected</button>
        </div>
        <ul id="cloud-list" class="backup-list"></ul>
      </div>
    </dialog>
  `;
}

async function init() {
  buildShell();
  config = await api.getConfig();

  const searchInput = el<HTMLInputElement>("search");
  searchInput.addEventListener("input", scheduleSearch);
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void copySelected();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      moveSelection(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveSelection(-1);
    } else if (e.key === "Delete" && !searchInput.value) {
      e.preventDefault();
      void deleteSelected();
    }
  });

  el("btn-clear").addEventListener("click", () => {
    searchInput.value = "";
    void doSearch();
    searchInput.focus();
  });
  el("btn-cloud").addEventListener("click", () => void openCloud());
  el("btn-add").addEventListener("click", () => openAdd());

  // Detail dialog
  el("detail-copy").addEventListener("click", () => {
    const row = (detailDialog as unknown as { _row: Snippet })._row;
    if (row) void doCopy(row);
  });
  el("detail-edit").addEventListener("click", () => {
    const row = (detailDialog as unknown as { _row: Snippet })._row;
    if (row) openEdit(row);
  });
  el("detail-delete").addEventListener("click", () => {
    const row = (detailDialog as unknown as { _row: Snippet })._row;
    if (row) {
      const title = (row.heading || "").trim() || "(no title)";
      if (!confirm(`Delete \u201c${title}\u201d?\n\nThis cannot be undone.`)) return;
      void api.deleteSnippet(row.id).then(() => {
        detailDialog.close();
        void doSearch();
      });
    }
  });
  el("detail-close").addEventListener("click", () => detailDialog.close());
  detailDialog.addEventListener("close", () => searchInput.focus());

  // Edit dialog
  el("edit-content").addEventListener("input", updateEditCounter);
  el("edit-save").addEventListener("click", () => void saveEdit());
  el("edit-cancel").addEventListener("click", () => editDialog.close());
  editDialog.addEventListener("close", () => searchInput.focus());

  // Cloud dialog
  el("cloud-connect").addEventListener("click", () => void doConnect());
  el("cloud-disconnect").addEventListener("click", () => void doDisconnect());
  el("cloud-backup").addEventListener("click", () => void doBackup());
  el("cloud-restore").addEventListener("click", () => void doRestore());
  el("cloud-close").addEventListener("click", () => cloudDialog.close());

  // Global keys
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (editDialog.open || detailDialog.open || cloudDialog.open) return;
      e.preventDefault();
      handleEscape();
    } else if (e.key === "n" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      openAdd();
    } else if (e.key === "e" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (!editDialog.open) openEditSelected();
    } else if (e.key === "Delete" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void deleteSelected();
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      const row = selectedSnippet();
      if (row && !detailDialog.open && !editDialog.open) {
        e.preventDefault();
        openDetail(row);
      }
    }
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && editDialog.open) {
      e.preventDefault();
      void saveEdit();
    }
  });

  // Tray events
  await listen("tray-new", () => openAdd());
  await listen("tray-cloud", () => void openCloud());
  await listen("tray-backup", () => {
    void openCloud();
    setTimeout(() => void doBackup(), 300);
  });

  await doSearch();
  searchInput.focus();
}

init().catch((e) => {
  console.error(e);
  const app = document.getElementById("app");
  if (app) app.innerHTML = `<pre style="padding:16px;color:#c0392b;white-space:pre-wrap">${escapeHtml(String(e))}</pre>`;
});
