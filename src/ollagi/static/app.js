// ollagi page behaviour. Every few seconds it asks the server for JSON (/api/...) and redraws.
// Text from the server is always set with textContent (or through renderAnsi, which does the
// same), never innerHTML, so nothing a session prints can run as code in this page.

import { renderAnsi } from "/static/ansi.js";

// ---- helpers -------------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const GiB = 1024 ** 3, MiB = 1024 ** 2;
const gib = (n) => (n / GiB).toFixed(1) + " GiB";
const mib = (n) => (n == null ? "?" : Math.round(n / MiB) + " MiB");

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function age(seconds) {
  if (seconds < 60) return seconds + "s";
  if (seconds < 3600) return Math.round(seconds / 60) + "m";
  if (seconds < 86400) return Math.round(seconds / 3600) + "h";
  return Math.round(seconds / 86400) + "d";
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    // X-Ollagi tells the server this change comes from this page (src/ollagi/access.py).
    headers: { "Content-Type": "application/json", "X-Ollagi": "1" },
    body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || response.statusText);
  return data;
}

// States, most urgent first (src/ollagi/claude_screen.py decides them from the screen).
const STATES = {
  needs_you: "needs you", working: "working", done: "done", idle: "idle",
  frozen: "frozen", exited: "exited", unknown: "unknown",
};

// ---- page state ----------------------------------------------------------------------------
let whoami = null, phoneUrl = null, sessions = [], projects = [], filter = "All", current = null;
let outsideSessions = [];  // Claude sessions started in a terminal window, from Claude's own files
let claudeProcesses = [];  // every Claude process the server sees (from /api/system)

// ---- top bar and tabs ------------------------------------------------------------------------
function showView(name) {
  for (const b of document.querySelectorAll(".tabs button")) b.classList.toggle("on", b.dataset.view === name);
  for (const view of ["sessions", "queue", "system"]) $(`view-${view}`).hidden = name !== view;
  $("new-open").hidden = name !== "sessions";
  if (name === "queue") { refreshQueue(); refreshDrafts(); }
}
for (const b of document.querySelectorAll(".tabs button")) b.onclick = () => showView(b.dataset.view);
$("chip-memory").onclick = () => showView("system");

$("open-qr").onclick = () => {
  if (!phoneUrl) { alert("Tailscale is not running, so there is no phone address."); return; }
  $("qr-big").src = "/qr.svg";
  $("qr-url").textContent = phoneUrl;
  $("qr-sheet").hidden = false;
};
$("qr-close").onclick = () => ($("qr-sheet").hidden = true);

// ---- sessions (home) ------------------------------------------------------------------------
function renderSessions() {
  // Claude processes that are neither ollagi's nor in Claude's own session files (rare). Drawn here,
  // after both lists are loaded: the two requests run at the same time and either may finish first.
  const known = new Set(outsideSessions.map((o) => o.pid));
  const others = claudeProcesses.filter((c) => !c.managed && !known.has(c.pid));
  $("outside").textContent = others.length ? `Also running: ${others.length} other Claude process(es).` : "";

  // Both kinds share one list: ollagi's own sessions, and those started in a terminal window.
  const all = [...sessions, ...outsideSessions.map((o) => ({ ...o, outside: true }))];
  const counts = {};
  for (const s of all) counts[s.state] = (counts[s.state] || 0) + 1;

  $("summary").replaceChildren(...Object.keys(STATES).filter((k) => counts[k]).map((k) => {
    const item = el("span", null, `${k}-count`);
    item.append(el("span", null, `dot ${k}`), `${counts[k]} ${STATES[k]}`);
    return item;
  }));

  // Project filter chips: All, then every project that has a session, marked with its most urgent dot.
  const names = [...new Set(all.map((s) => s.project))];
  $("filters").replaceChildren(...["All", ...names].map((name) => {
    const button = el("button", null, filter === name ? "on" : "");
    const mine = all.filter((s) => s.project === name);
    if (name !== "All" && mine.length) button.append(el("span", null, `dot ${mostUrgent(mine)}`));
    button.append(name);
    button.onclick = () => { filter = name; renderSessions(); };
    return button;
  }));
  $("filters").hidden = names.length < 2;

  const shown = all.filter((s) => filter === "All" || s.project === filter);
  if (!shown.length) {
    $("groups").replaceChildren(el("div", "No sessions yet. Press + New to start Claude in a project.", "empty"));
    return;
  }
  const groups = {};
  for (const s of shown) (groups[s.project] ||= []).push(s);
  const blocks = [];
  for (const [project, list] of Object.entries(groups)) {
    list.sort((a, b) => rank(a.state) - rank(b.state));  // who needs you first
    const head = el("div", null, "group");
    head.append(el("span", null, `dot ${mostUrgent(list)}`), project);
    const tally = el("span", null, "counts");
    for (const state of Object.keys(STATES)) {
      const n = list.filter((s) => s.state === state).length;
      if (n) { const t = el("span"); t.append(el("span", null, `dot ${state}`), " " + n); tally.append(t); }
    }
    head.append(tally);
    const box = el("div", null, "list");
    for (const s of list) box.append(sessionRow(s));
    blocks.push(head, box);
  }
  $("groups").replaceChildren(...blocks);
}

function rank(state) { return Object.keys(STATES).indexOf(state); }
function mostUrgent(list) { return list.map((s) => s.state).sort((a, b) => rank(a) - rank(b))[0]; }

function sessionRow(s) {
  if (s.outside) return outsideRow(s);
  const row = el("button", null, `row ${s.state}`);
  const sub = s.state === "needs_you" && s.question ? s.question : `${STATES[s.state]} · ${s.directory}`;
  const meta = el("span", null, "meta");
  meta.append(age(s.age_seconds), el("br"), mib(s.memory_current));
  row.append(el("span", null, `dot ${s.state}`), el("span", s.name, "name"), meta, el("span", sub, "sub"));
  row.onclick = () => openViewer(s.name);
  return row;
}

// ---- sessions started in a terminal window ------------------------------------------------------
const OUTSIDE_WORD = { busy: "working", waiting: "waiting for you", idle: "idle" };

function outsideRow(s) {
  const row = el("button", null, `row ${s.state}`);
  const name = el("span", s.name, "name");
  name.append(el("span", "terminal", "tag"));
  const meta = el("span", null, "meta");
  meta.append(age(s.age_seconds), el("br"), mib(s.memory));
  row.append(el("span", null, `dot ${s.state}`), name, meta,
             el("span", `${OUTSIDE_WORD[s.status] || s.status} · ${s.cwd}`, "sub"));
  row.onclick = () => openOutside(s.pid);
  return row;
}

async function openOutside(pid) {
  const s = outsideSessions.find((x) => x.pid === pid);
  if (!s) return;
  $("outside-error").textContent = "";
  $("outside-sheet").hidden = false;
  $("outside-sub").textContent = `${s.name} · ${OUTSIDE_WORD[s.status] || s.status} · ${s.cwd}`;
  $("outside-takeover").hidden = s.status !== "idle";  // idle only: never cut off work in progress
  $("outside-takeover").onclick = () => takeOver(s);
  const c = await api(`/api/outside/${pid}/conversation`);
  $("outside-title").textContent = c.title || s.name;
  $("outside-items").replaceChildren(...c.items.map((i) => el("div", i.text, `msg ${i.role}`)));
  $("outside-items").scrollTop = $("outside-items").scrollHeight;
}
$("outside-close").onclick = () => ($("outside-sheet").hidden = true);

async function takeOver(s) {
  const typed = prompt(
    `Take over ${s.name}?\n\nClaude in its terminal window ends, and the same conversation reopens in ollagi.\n` +
    `If this is the window you are typing in right now, that window's session ends.\n\nType the name to confirm:`);
  if (typed === null) return;
  try {
    const r = await api(`/api/outside/${s.pid}/takeover`, { confirm_name: typed.trim() });
    $("outside-sheet").hidden = true;
    await refreshSessions();
    alert(`Reopened as ${r.session}. To see it in a terminal window again: ${r.attach}`);
  } catch (error) { $("outside-error").textContent = error.message; }
}

// ---- new session sheet ------------------------------------------------------------------------
$("new-open").onclick = () => { $("new-error").textContent = ""; $("new-sheet").hidden = false; $("new-name").focus(); };
$("new-cancel").onclick = () => ($("new-sheet").hidden = true);
$("new-form").onsubmit = async (event) => {
  event.preventDefault();
  $("new-error").textContent = "";
  const directory = $("new-dir").value.trim() || $("new-project").value;
  if (!directory) { $("new-error").textContent = "Choose a project or type a folder."; return; }
  try {
    await api("/api/sessions", { name: $("new-name").value.trim(), directory, force: $("new-force").checked });
    $("new-sheet").hidden = true;
    $("new-name").value = "";
    await refreshSessions();
  } catch (error) { $("new-error").textContent = error.message; }
};

function fillProjects() {
  for (const id of ["new-project", "task-project", "jira-project"]) {
    const select = $(id);
    if (select.dataset.filled) continue;
    select.append(Object.assign(el("option", "choose a project…"), { value: "" }));
    for (const p of projects) select.append(Object.assign(el("option", `${p.name}  (${p.directory})`), { value: p.directory }));
    select.dataset.filled = "1";
  }
}

// ---- one session ------------------------------------------------------------------------------
let screenTimer = null, lastText = "";

function openViewer(name) {
  current = name;
  lastText = "";
  $("viewer").hidden = false;
  $("v-menu").hidden = true;
  $("screen").textContent = "";
  refreshViewer();
  clearInterval(screenTimer);
  screenTimer = setInterval(refreshViewer, 1500);
}

function closeViewer() {
  clearInterval(screenTimer);
  current = null;
  $("viewer").hidden = true;
  refreshSessions();
}
$("v-back").onclick = closeViewer;
$("v-more").onclick = () => ($("v-menu").hidden = !$("v-menu").hidden);

async function refreshViewer() {
  if (!current) return;
  const s = sessions.find((x) => x.name === current);
  $("v-name").textContent = current;
  $("v-sub").textContent = s ? `${s.project} · ${age(s.age_seconds)} · ${mib(s.memory_current)}` : "";

  // The switcher: every session as a chip, so you can hop between them without going back.
  $("switcher").replaceChildren(...sessions.map((x) => {
    const chip = el("button", null, x.name === current ? "on" : "");
    chip.append(el("span", null, `dot ${x.state}`), x.name);
    chip.onclick = () => openViewer(x.name);
    return chip;
  }));
  $("switcher").hidden = sessions.length < 2;

  let data;
  try { data = await api(`/api/sessions/${current}/screen?lines=300`); }
  catch (error) { $("screen").textContent = error.message; return; }

  $("v-dot").className = `dot ${data.state}`;
  $("frozen-note").hidden = !data.frozen;
  $("v-pause").hidden = data.frozen;
  if (data.frozen) return;  // its tmux is paused too, so keep the last screen

  if (data.text !== lastText) {
    const pre = $("screen");
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
    renderAnsi(data.text, pre);
    if (atBottom || !lastText) pre.scrollTop = pre.scrollHeight;  // follow, unless you scrolled up to read
    lastText = data.text;
  }

  // A menu on screen (permission, question, plan): show its choices as big buttons.
  // Tapping one presses that number key, which is how Claude Code picks a numbered option.
  const wasHidden = $("ask").hidden;
  $("ask").hidden = data.state !== "needs_you";
  // The card takes room from the screen above it, so keep the screen's last lines in view.
  if (wasHidden && !$("ask").hidden) $("screen").scrollTop = $("screen").scrollHeight;
  if (data.state === "needs_you") {
    $("ask-question").textContent = data.question || "";
    $("ask-options").replaceChildren(...data.options.map((o) => {
      const button = el("button");
      button.append(el("b", String(o.number)), el("span", o.label));
      button.onclick = () => press(String(o.number));
      return button;
    }));
  }
}

async function press(key) {
  await api(`/api/sessions/${current}/send`, { key });
  setTimeout(refreshViewer, 250);
}

$("composer").onsubmit = async (event) => {
  event.preventDefault();
  const text = $("reply").value;
  if (!text) { await press("Enter"); return; }  // an empty send is an Enter, like a terminal
  await api(`/api/sessions/${current}/send`, { text });
  $("reply").value = "";
  setTimeout(refreshViewer, 300);
};

// The dock: Keys (a small keyboard for keys a phone lacks) and Quick (one-tap replies).
const KEYS = [["Esc", "Escape"], ["Tab", "Tab"], ["⇧Tab", "BTab"], ["^C", "C-c"], ["↑", "Up"], ["↓", "Down"],
              ["←", "Left"], ["→", "Right"], ["⌫", "BSpace"], ["y", "y"], ["n", "n"], ["⏎", "Enter"]];
$("panel-keys").replaceChildren(...KEYS.map(([label, key]) => {
  const button = el("button", label);
  button.onclick = () => press(key);
  return button;
}));

// Commands that throw work away need a second tap within 3 seconds.
const QUICK = [["continue", false], ["yes", false], ["no", false], ["/compact", false], ["/clear", true]];
$("panel-quick").replaceChildren(...QUICK.map(([text, destructive]) => {
  const button = el("button", text);
  button.onclick = async () => {
    if (destructive && !button.classList.contains("armed")) {
      button.classList.add("armed");
      button.textContent = text + " (tap again)";
      setTimeout(() => { button.classList.remove("armed"); button.textContent = text; }, 3000);
      return;
    }
    button.classList.remove("armed");
    button.textContent = text;
    await api(`/api/sessions/${current}/send`, { text });
    setTimeout(refreshViewer, 300);
  };
  return button;
}));

for (const tab of document.querySelectorAll(".dock-tabs button")) {
  tab.onclick = () => {
    const open = !tab.classList.contains("on");
    for (const t of document.querySelectorAll(".dock-tabs button")) t.classList.remove("on");
    $("panel-keys").hidden = !(open && tab.dataset.panel === "keys");
    $("panel-quick").hidden = !(open && tab.dataset.panel === "quick");
    if (open) tab.classList.add("on");
  };
}

$("v-pause").onclick = async () => { $("v-menu").hidden = true; await api(`/api/sessions/${current}/freeze`, {}); refreshViewer(); };
$("v-resume").onclick = async () => { await api(`/api/sessions/${current}/thaw`, {}); lastText = ""; setTimeout(refreshViewer, 300); };
$("v-stop").onclick = async () => {
  $("v-menu").hidden = true;
  if (!confirm(`Stop ${current}? The Claude session ends; work saved to disk stays.`)) return;
  await api(`/api/sessions/${current}/stop`, {});
  closeViewer();
};

// ---- queue -----------------------------------------------------------------------------------
// A task's status, shown with the same dots as sessions where the meaning matches.
const TASK = {
  queued: ["idle", "queued"], running: ["working", "running"], waiting: ["needs_you", "waiting for you"],
  done: ["done", "done"], failed: ["failed", "failed"], limited: ["limited", "usage limit"], cancelled: ["cancelled", "cancelled"],
};

async function refreshQueue() {
  const q = await api("/api/queue");
  const active = q.tasks.find((t) => t.status === "running" || t.status === "waiting");
  const waiting = q.tasks.filter((t) => t.status === "queued").length;
  $("queue-status").textContent = q.paused ? `Paused · ${waiting} queued`
    : active ? `Running task ${active.id} · ${waiting} queued` : `Ready · ${waiting} queued`;
  $("queue-reason").textContent = q.paused ? q.pause_reason : "";
  $("queue-toggle").textContent = q.paused ? "Resume" : "Pause";
  $("queue-toggle").onclick = async () => { await api(`/api/queue/${q.paused ? "resume" : "pause"}`, {}); refreshQueue(); };

  $("tasks").replaceChildren(...(q.tasks.length ? [taskList(q.tasks)] : [el("div", "No tasks yet. Add one above.", "empty")]));
  $("queue-events").replaceChildren(...q.events.slice(-5).reverse().map((e) =>
    el("li", new Date(e.time * 1000).toLocaleTimeString() + "  " + e.text)));
}

function taskList(tasks) {
  const box = el("div", null, "list");
  for (const t of tasks) {
    const [dot, word] = TASK[t.status] || ["unknown", t.status];
    const row = el("div", null, "row task");
    const when = t.finished || t.started || t.created;
    const meta = el("span", null, "meta");
    meta.append(`#${t.id}`, el("br"), age(Math.max(0, Math.round(Date.now() / 1000 - when))));
    const sub = `${word} · ${t.project}` + (t.note ? ` · ${t.note}` : "");
    row.append(el("span", null, `dot ${dot}`), el("span", t.prompt, "name"), meta, el("span", sub, "sub"));
    const actions = el("div", null, "actions");
    if (t.status === "queued") actions.append(button("Cancel", async () => { await api(`/api/queue/${t.id}/cancel`, {}); refreshQueue(); }));
    if (t.status === "running" || t.status === "waiting") actions.append(button("Open session", () => openViewer(t.session)));
    if (t.status === "done") actions.append(button("Result", () => showResult(t.id)));
    if (actions.children.length) row.append(actions);
    box.append(row);
  }
  return box;
}

function button(text, onclick) {
  const b = el("button", text);
  b.type = "button";
  b.onclick = onclick;
  return b;
}

async function showResult(id) {
  const r = await api(`/api/queue/${id}/result`);
  $("result-title").textContent = `Task ${id}`;
  $("result-text").textContent = r.text;
  $("result-sheet").hidden = false;
}
$("result-close").onclick = () => ($("result-sheet").hidden = true);

$("task-form").onsubmit = async (event) => {
  event.preventDefault();
  $("task-error").textContent = "";
  const directory = $("task-dir").value.trim() || $("task-project").value;
  if (!directory) { $("task-error").textContent = "Choose a project or type a folder."; return; }
  try {
    await api("/api/queue", { directory, prompt: $("task-prompt").value });
    $("task-prompt").value = "";
    refreshQueue();
  } catch (error) { $("task-error").textContent = error.message; }
};

// ---- Jira groups (read only) -------------------------------------------------------------------
const PRESELECT = 5;  // tick at most this many per group by default: a big group is too much for one session
// Finished work waiting for a reviewer stays visible but is not ticked by default, and sorts last.
const WAITING_FOR_REVIEW = new Set(["To Be Checked"]);

$("jira-load").onclick = () => loadJira(true);

async function loadJira(refresh) {
  $("jira-load").textContent = "Loading…";
  try {
    const data = await api(`/api/jira/groups${refresh ? "?refresh=true" : ""}`);
    const read = new Date(data.read_at * 1000).toLocaleTimeString();
    $("jira-note").textContent = `${data.tickets} open tickets, ${data.groups.length} groups, read from Jira at ${read}. ` +
      "Read only: nothing here changes a ticket.";
    $("jira-project").hidden = false;
    $("jira-groups").replaceChildren(...data.groups.map(groupCard));
  } catch (error) {
    $("jira-note").textContent = error.message;
  }
  $("jira-load").textContent = "Reload";
}

function groupCard(g) {
  const card = el("div", null, "jgroup");
  card.append(el("p", `${g.tickets.length} tickets · ${g.reason}`, "why"));
  const ordered = [...g.tickets].sort((a, b) => WAITING_FOR_REVIEW.has(a.status) - WAITING_FOR_REVIEW.has(b.status));
  let ticked = 0;
  const boxes = ordered.map((t) => {
    const label = el("label");
    const tick = !WAITING_FOR_REVIEW.has(t.status) && ticked < PRESELECT;
    if (tick) ticked++;
    const box = Object.assign(document.createElement("input"), { type: "checkbox", checked: tick, value: t.key });
    const text = el("span");
    const link = Object.assign(el("a", t.key, "key"), { href: t.url, target: "_blank", rel: "noopener" });
    text.append(link, ` ${t.summary} `, el("span", `(${t.status})`, "muted"));
    label.append(box, text);
    card.append(label);
    return box;
  });
  const actions = el("div", null, "actions");
  const result = el("span", null, "muted");
  actions.append(button("Queue ticked as one task", async () => {
    const keys = boxes.filter((b) => b.checked).map((b) => b.value);
    const directory = $("jira-project").value;
    if (!keys.length) { result.textContent = "Tick at least one ticket."; return; }
    if (!directory) { result.textContent = "Choose a project above first."; return; }
    try {
      const task = await api("/api/jira/queue", { keys, directory });
      result.textContent = `Queued as task ${task.id}.`;
      refreshQueue();
    } catch (error) { result.textContent = error.message; }
  }), result);
  card.append(actions);
  return card;
}

// ---- Slack outbox: drafts only; one Send per message, after seeing its exact text --------------
async function refreshDrafts() {
  const data = await api("/api/slack/drafts");
  $("drafts").replaceChildren(...data.drafts.filter((d) => d.status !== "discarded").slice(0, 20).map(draftCard));
}

function draftCard(d) {
  const card = el("div", null, "draft");
  const where = d.thread_ts ? `${d.channel}, reply in thread ${d.thread_ts}` : d.channel;
  card.append(el("div", `#${d.id} · ${where} · ${d.status}${d.source !== "me" ? " · from " + d.source : ""}`, "meta-line"),
              el("pre", d.text));
  if (d.status !== "draft") {
    if (d.result) card.append(el("div", d.result, "meta-line"));
    return card;
  }
  const actions = el("div", null, "actions");
  const said = el("span", null, "muted");
  actions.append(
    button("Preview", async () => {
      said.textContent = "asking slack.sh…";
      try { said.textContent = (await api(`/api/slack/drafts/${d.id}/preview`, {})).notifies; }
      catch (error) { said.textContent = error.message; }
    }),
    Object.assign(button("Send", async () => {
      // The approval: the exact text, shown once more, and an explicit OK for this one message.
      if (!confirm(`Post this to ${where}?\n\n${d.text}`)) return;
      try { await api(`/api/slack/drafts/${d.id}/send`, { confirmed_text: d.text }); refreshDrafts(); }
      catch (error) { said.textContent = error.message; }
    }), { className: "send-draft" }),
    button("Discard", async () => { await api(`/api/slack/drafts/${d.id}/discard`, {}); refreshDrafts(); }),
    said,
  );
  card.append(actions);
  return card;
}

$("draft-form").onsubmit = async (event) => {
  event.preventDefault();
  await api("/api/slack/drafts", { channel: $("draft-channel").value, thread_ts: $("draft-thread").value || null,
                                   text: $("draft-text").value });
  $("draft-text").value = "";
  refreshDrafts();
};

// ---- system ----------------------------------------------------------------------------------
const LEVEL_WORD = { green: "green", amber: "amber", red: "red" };

async function refreshSystem() {
  const s = await api("/api/system");
  projects = s.projects;
  fillProjects();
  const used = 1 - s.memory.available / s.memory.total;
  $("chip-memory-text").textContent = `MEM ${(s.memory.available / GiB).toFixed(1)}G free`;
  $("chip-cpu").textContent = `CPU ${s.load.one_minute.toFixed(1)}/${s.load.cpus}`;
  $("mem-text").textContent = `${gib(s.memory.available)} of ${gib(s.memory.total)}`;
  $("mem-bar").style.width = (used * 100).toFixed(0) + "%";
  $("pressure").textContent = s.pressure ? s.pressure.some_avg10.toFixed(1) + "%" : "not available";
  $("swap").textContent = `${gib(s.swap.used)} of ${gib(s.swap.total)}`;
  $("load").textContent = `${s.load.one_minute.toFixed(2)} on ${s.load.cpus} threads`;
  $("verdict").textContent = (s.can_start ? `Room for ${s.can_start} more session(s). ` : "No room for another session. ") + s.reason;

  claudeProcesses = s.claude_sessions;

  $("disks").replaceChildren(...s.disks.map((d) => {
    const row = el("tr");
    row.append(el("td", d.mount), el("td", `${gib(d.free)} free of ${gib(d.total)}`));
    return row;
  }));
  $("processes").replaceChildren(...s.top_processes.map((p) => {
    const row = el("tr");
    row.append(el("td", p.name), el("td", `pid ${p.pid}`, "muted"), el("td", mib(p.rss)));
    return row;
  }));
}

async function refreshWatcher() {
  const w = await api("/api/watcher");
  phoneUrl = w.phone_url;
  $("chip-level").className = `dot ${w.level}`;
  $("watch-level").replaceChildren(el("span", null, `dot ${w.level}`), " " + LEVEL_WORD[w.level]);
  $("watch-action").textContent = `${w.action} the heaviest session` +
    (w.frozen_by_watcher.length ? ` (frozen now: ${w.frozen_by_watcher.join(", ")})` : "");
  const events = w.events.slice(-5).reverse();
  $("watch-events").replaceChildren(...(events.length ? events : [{ time: null, text: "no events yet" }]).map((e) =>
    el("li", (e.time ? new Date(e.time * 1000).toLocaleTimeString() + "  " : "") + e.text)));

  // On the laptop itself, show the phone QR code at the top of the System tab.
  if (phoneUrl && whoami === "this machine" && $("qr-card").hidden) {
    $("qr-inline").src = "/qr.svg";
    $("qr-url-inline").textContent = phoneUrl;
    $("qr-card").hidden = false;
  }
}

async function refreshSessions() {
  [sessions, outsideSessions] = await Promise.all([api("/api/sessions"), api("/api/outside")]);
  renderSessions();
}

// ---- keep everything fresh -----------------------------------------------------------------------
async function tick() {
  try {
    if (!whoami) whoami = (await api("/api/whoami")).login;
    const jobs = [refreshSystem(), refreshSessions(), refreshWatcher()];
    if (!$("view-queue").hidden) jobs.push(refreshQueue());
    await Promise.all(jobs);
    renderSessions();  // once more, now that every list is in
  } catch (error) {
    $("chip-memory-text").textContent = "offline";
  }
}
tick();
setInterval(tick, 4000);
