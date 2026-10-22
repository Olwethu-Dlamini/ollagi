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
  if (name === "system") refreshPush().catch(() => {});
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
  // Project filters: All, then every project that has a session, marked with its most urgent dot.
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
    $("groups").replaceChildren(el("div", "No sessions. Press New to start Claude in a project.", "empty"));
    return;
  }
  const groups = {};
  for (const s of shown) (groups[s.project] ||= []).push(s);
  const blocks = [];
  for (const [project, list] of Object.entries(groups)) {
    list.sort((a, b) => rank(a.state) - rank(b.state));  // who needs you first
    const head = el("div", null, "group");
    const waiting = list.filter((s) => s.state === "needs_you").length;
    head.append(project, el("span", waiting ? `${waiting} waiting for you` : `${list.length} running`, "counts"));
    const box = el("div", null, "list");
    for (const s of list) box.append(sessionRow(s));
    blocks.push(head, box);
  }
  $("groups").replaceChildren(...blocks);
}

// "working · 9h · 1.0 GiB": what a row and the session's header say under the name. The states
// are read from Claude's screen, so a shell session gets none: just its age and memory.
function describe(s) {
  return [isClaude(s) ? STATES[s.state] : null, age(s.age_seconds), size(s.memory_current)].filter(Boolean).join(" · ");
}
function isClaude(s) { return !s.program || s.program === "claude"; }
function size(bytes) {
  if (bytes == null) return "";
  return bytes >= GiB ? (bytes / GiB).toFixed(1) + " GiB" : Math.round(bytes / MiB) + " MiB";
}

function rank(state) { return Object.keys(STATES).indexOf(state); }
function mostUrgent(list) { return list.map((s) => s.state).sort((a, b) => rank(a) - rank(b))[0]; }

function sessionRow(s) {
  if (s.outside) return outsideRow(s);
  const row = el("button", null, `row ${s.state}`);
  const sub = s.state === "needs_you" && s.question ? s.question : describe(s);
  const name = el("span", s.name, "name");
  if (!isClaude(s)) name.append(el("span", s.program, "tag"));  // "bash": a plain terminal, not Claude
  row.append(el("span", null, `dot ${s.state}`), name, el("span", sub, "sub"));
  row.onclick = () => openViewer(s.name);
  return row;
}

// ---- sessions started in a terminal window ------------------------------------------------------
const OUTSIDE_WORD = { busy: "working", waiting: "waiting for you", idle: "idle" };

function outsideRow(s) {
  const row = el("button", null, `row ${s.state}`);
  const name = el("span", s.name, "name");
  name.append(el("span", "terminal", "tag"));
  row.append(el("span", null, `dot ${s.state}`), name,
             el("span", [OUTSIDE_WORD[s.status] || s.status, age(s.age_seconds), size(s.memory)].join(" · "), "sub"));
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
  // Which button sent the form: Start Claude, or Start a terminal (a shell in the folder).
  const program = event.submitter && event.submitter.id === "new-shell" ? "shell" : "claude";
  try {
    await api("/api/sessions", { name: $("new-name").value.trim(), directory, force: $("new-force").checked, program });
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

// ---- one session: Claude's own screen (docs/decisions/0021) --------------------------------------
// A session opens as a live terminal (0018): Claude's real screen, redrawn for this screen's width,
// so it shows working, thinking or stopped as it happens. The other way, a copy of the screen as
// drawn on the laptop (read every 1.5 s, lines left as they are), is one tap away in the ⋯ menu and
// is used whenever the live terminal cannot run (a paused session, one that ended).
let screenTimer = null, lastText = "";
let liveEnded = null;  // the session whose live terminal closed by itself: no new one until reopened

function readViewMode() {
  try { return localStorage.getItem("ollagi.view") === "copy" ? "copy" : "live"; } catch { return "live"; }
}
let viewMode = readViewMode();  // remembered on this device only

function openViewer(name) {
  if (name !== current) stopLive();
  current = name;
  lastText = "";
  liveEnded = null;
  lastQuestion = "";
  $("viewer").hidden = false;
  $("v-menu").hidden = true;
  $("switcher").hidden = true;
  $("screen").textContent = "";
  refreshViewer();
  pollViewer();
}

// The copy is read every 1.5 s. A live terminal draws itself, so the screen is then only read every
// 4 s, for the state dot, the laptop item and a question's buttons.
function pollViewer() {
  clearInterval(screenTimer);
  screenTimer = setInterval(refreshViewer, live ? 4000 : 1500);
}

function closeViewer() {
  stopLive();
  clearInterval(screenTimer);
  current = null;
  $("viewer").hidden = true;
  refreshSessions();
}
$("v-back").onclick = closeViewer;
$("v-more").onclick = () => { $("switcher").hidden = true; $("v-menu").hidden = !$("v-menu").hidden; };
$("v-title").onclick = () => { $("v-menu").hidden = true; $("switcher").hidden = !$("switcher").hidden; };

async function refreshViewer() {
  if (!current) return;
  const s = sessions.find((x) => x.name === current);
  $("v-name").textContent = current;
  $("v-sub").textContent = s ? describe(s) : "";
  $("v-live").textContent = live ? "Show a copy of the screen" : "Show the live terminal";

  // Tapping the name lists every session, to hop between them without going back.
  $("switcher").replaceChildren(...sessions.map((x) => {
    const item = el("button", null, x.name === current ? "on" : "");
    item.append(el("span", null, `dot ${x.state}`), x.name);
    item.onclick = () => openViewer(x.name);
    return item;
  }));

  let data;
  try { data = await api(`/api/sessions/${current}/screen?lines=300`); }
  catch (error) { if (!live) $("screen").textContent = error.message; return; }

  $("v-dot").className = `dot ${data.state}`;
  if (s) $("v-sub").textContent = describe({ ...s, state: data.state });  // the list may be a few seconds older
  $("frozen-note").hidden = !data.frozen;
  $("v-pause").hidden = data.frozen;
  showLaptopButton(data.windows);
  if (data.frozen) { stopLive(); return; }  // its tmux is paused too, so keep the last screen

  const wantLive = viewMode === "live" && liveEnded !== current && data.state !== "exited";
  if (wantLive && !live && !starting) {
    startLive().catch((error) => { liveEnded = current; $("screen").textContent = `Live terminal: ${error.message}`; });
  } else if (!live && data.text !== lastText) {
    const pre = $("screen");
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
    renderAnsi(trimLines(data.text), pre);
    if (atBottom || !lastText) pre.scrollTop = pre.scrollHeight;  // follow, unless you scrolled up to read
    lastText = data.text;
  }
  showQuestion(data);
}

// Claude pads its lines with spaces to the window's width; without them, only the lines that are
// really wide (boxes, rules) need sideways scrolling. Colour codes at the end are kept.
function trimLines(text) {
  return text.split("\n").map((line) => line.replace(/[ \t]+((?:\x1b\[[0-9;]*m)*)$/, "$1")).join("\n");
}

// A menu on screen (permission, question, plan) becomes one row of buttons above the keys, one per
// choice; the question itself is on the screen just above.
// Tapping one presses that number key, which is how Claude Code picks a numbered option.
let lastQuestion = "";
function showQuestion(data) {
  const asking = data.state === "needs_you" && data.options && data.options.length;
  const key = asking ? JSON.stringify([data.question, data.options]) : "";
  if (key === lastQuestion) return;
  lastQuestion = key;
  $("term-ask").replaceChildren();
  if (!asking) return;
  const card = el("div", null, "ask-card");
  const options = el("div", null, "options");
  options.append(...data.options.map((o) => {
    const button = el("button");
    button.append(el("b", String(o.number)), el("span", o.label));
    button.onclick = () => press(String(o.number));
    return button;
  }));
  card.append(options);  // the question itself is on the screen just above
  $("term-ask").append(card);
}

// ---- typing and keys ---------------------------------------------------------------------------
async function press(key) {
  await api(`/api/sessions/${current}/send`, { key });
  setTimeout(refreshViewer, 250);
}

$("composer").onsubmit = async (event) => {
  event.preventDefault();
  stopListening();
  const text = $("reply").value;
  if (!text) { await press("Enter"); return; }  // an empty send is an Enter, like a terminal
  await api(`/api/sessions/${current}/send`, { text });
  $("reply").value = "";
  setTimeout(refreshViewer, 300);
};

const KEYS = [["Esc", "Escape"], ["Tab", "Tab"], ["⇧Tab", "BTab"], ["^C", "C-c"], ["↑", "Up"], ["↓", "Down"],
              ["←", "Left"], ["→", "Right"], ["⌫", "BSpace"], ["y", "y"], ["n", "n"], ["⏎", "Enter"]];
const keyButton = ([label, key]) => { const b = el("button", label); b.type = "button"; b.onclick = () => press(key); return b; };
$("keys-row").replaceChildren(...KEYS.map(keyButton));
$("panel-keys").replaceChildren(...KEYS.map(keyButton));

// ---- the + sheet: keys, quick replies, summary ---------------------------------------------------
$("tools-open").onclick = () => { showSummary(); $("tools-sheet").hidden = false; };
$("tools-close").onclick = () => ($("tools-sheet").hidden = true);
$("tools-sheet").onclick = (event) => { if (event.target === $("tools-sheet")) $("tools-sheet").hidden = true; };

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
    $("tools-sheet").hidden = true;
    setTimeout(refreshViewer, 300);
  };
  return button;
}));

// Summary (docs/decisions/0019): Haiku reads the end of the screen and answers in a few lines.
// Only the button spends tokens; opening the sheet shows the last summary of this session, if any.
const summaries = {};  // session name -> { text, model, input_tokens, output_tokens, seconds, at }

function showSummary() {
  const last = summaries[current];
  $("summary-text").textContent = last ? last.text : "What is this session doing? Press the button to ask Haiku.";
  $("summary-meta").textContent = last
    ? `${last.model.replace("claude-", "").replace(/-\d{8}$/, "")} · ${last.input_tokens} in, ${last.output_tokens} out · ${last.seconds} s · ${age(Math.round((Date.now() - last.at) / 1000))} ago`
    : "about 600 tokens per press";
}

$("summary-go").onclick = async () => {
  const name = current, button = $("summary-go");
  button.disabled = true;
  button.textContent = "Asking…";
  try {
    summaries[name] = { ...(await api(`/api/sessions/${name}/summary`, {})), at: Date.now() };
    if (current === name) showSummary();
  } catch (error) {
    if (current === name) { $("summary-text").textContent = error.message; $("summary-meta").textContent = "no summary"; }
  } finally {
    button.disabled = false;
    button.textContent = "Summarise";
  }
};

// ---- voice: speak a message into the box (docs/decisions/0020) ---------------------------------
// The browser turns speech into text (Chrome does it with Google's speech service). The words land
// in the box to be read and sent with the send button; nothing is sent by voice alone. Browsers only
// allow the microphone on https:// pages (and on the laptop itself), so over plain http it explains.
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let listener = null;

function stopListening() {
  if (listener) listener.stop();
}

$("mic").onclick = () => {
  if (listener) { stopListening(); return; }
  if (!window.isSecureContext) {
    alert("Voice needs the page on https://, which is not switched on yet. Until then, use the microphone key on your phone's keyboard.");
    return;
  }
  if (!Recognition) { alert("This browser cannot turn speech into text. Use the microphone key on your phone's keyboard."); return; }
  const before = $("reply").value ? $("reply").value.trimEnd() + " " : "";
  listener = new Recognition();
  listener.lang = navigator.language || "en-US";
  listener.interimResults = true;  // words appear while you speak
  listener.onresult = (event) => {
    $("reply").value = before + [...event.results].map((r) => r[0].transcript).join("");
  };
  listener.onerror = (event) => {
    if (event.error === "not-allowed") alert("The microphone is blocked for this page. Allow it in the browser's site settings.");
  };
  listener.onend = () => { listener = null; $("mic").classList.remove("on"); };
  listener.start();
  $("mic").classList.add("on");
};

// ---- fitting above the phone keyboard ----------------------------------------------------------
// The viewport setting asks the browser to shrink the page when the keyboard opens; where a browser
// does not, the visible area (visualViewport) is followed by hand.
function fitToKeyboard() {
  const view = window.visualViewport;
  $("viewer").style.height = `${view.height}px`;
  $("viewer").style.top = `${view.offsetTop}px`;
}
if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", fitToKeyboard);
  window.visualViewport.addEventListener("scroll", fitToKeyboard);
  fitToKeyboard();
}

// The laptop item in ⋯: "Open on laptop" when no terminal window shows this session, "Close on
// laptop" when one does. Closing detaches the windows; the session keeps running. Hidden while
// paused, because a paused tmux cannot say how many windows it has (windows is then null).
function showLaptopButton(windows) {
  const button = $("v-laptop");
  button.hidden = windows === null || windows === undefined;
  button.dataset.open = windows > 0 ? "1" : "";
  button.textContent = windows > 0 ? "Close on laptop" : "Open on laptop";
}

$("v-laptop").onclick = async () => {
  const button = $("v-laptop");
  $("v-menu").hidden = true;
  try {
    const action = button.dataset.open ? "desktop/close" : "desktop";
    await api(`/api/sessions/${current}/${action}`, {});
  } catch (error) {
    alert(error.message);  // e.g. no desktop is running on the laptop
  } finally {
    setTimeout(refreshViewer, 700);  // the window needs a moment to attach or close
  }
};

// ---- the live terminal (docs/decisions/0018) -------------------------------------------------
// xterm.js draws a real terminal in #live. Its bytes come from `tmux attach` for this session,
// which the server runs in a pty and relays over a WebSocket (src/ollagi/terminal.py). xterm.js is
// about 350 KB, so it is only loaded the first time a session opens.
let live = null;  // { term, socket, observer } while a live terminal is open
let starting = false;

async function loadXterm() {
  if (!document.querySelector('link[href="/static/xterm.css"]')) {
    document.head.append(Object.assign(document.createElement("link"), { rel: "stylesheet", href: "/static/xterm.css" }));
  }
  const [{ Terminal }, { FitAddon }, { WebglAddon }] = await Promise.all([
    import("/static/xterm.mjs"), import("/static/xterm-addon-fit.mjs"), import("/static/xterm-addon-webgl.mjs")]);
  return { Terminal, FitAddon, WebglAddon };
}

// xterm.js draws with DOM elements unless told otherwise, which is slow on a phone when Claude
// redraws nine times a second. The WebGL add-on draws on the graphics chip instead. Where WebGL is
// not available the DOM renderer stays; if the browser takes the graphics context away later, the
// add-on is dropped and xterm.js falls back on its own.
function drawWithWebgl(term, WebglAddon) {
  try {
    const webgl = new WebglAddon();
    webgl.onContextLoss(() => webgl.dispose());
    term.loadAddon(webgl);
    return true;
  } catch (error) {
    console.warn("live terminal: no WebGL, drawing with the DOM:", error.message);
    return false;
  }
}

async function startLive() {
  const name = current;
  starting = true;
  try {
    const { Terminal, FitAddon, WebglAddon } = await loadXterm();
    if (current !== name || live) return;  // the viewer moved on while xterm.js was loading
    const styles = getComputedStyle(document.documentElement);
    const term = new Terminal({
      fontFamily: styles.getPropertyValue("--mono") || "monospace",
      fontSize: window.innerWidth < 600 ? 11 : 13,
      cursorBlink: true,
      theme: { background: styles.getPropertyValue("--screen-bg").trim(), foreground: styles.getPropertyValue("--screen-text").trim() },
    });
    const fitter = new FitAddon();
    term.loadAddon(fitter);
    $("screen").hidden = true;
    $("live").hidden = false;
    term.open($("live"));
    drawWithWebgl(term, WebglAddon);  // after open: the add-on needs the element to draw in
    fitter.fit();

    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${scheme}://${location.host}/api/sessions/${name}/terminal?rows=${term.rows}&cols=${term.cols}`);
    socket.binaryType = "arraybuffer";
    const send = (message) => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message)); };
    socket.onmessage = (event) => term.write(new Uint8Array(event.data));
    socket.onclose = () => {
      // Closed by the other side (the session ended, or the server restarted): show the copy instead.
      if (live && live.socket === socket) { liveEnded = name; stopLive(); }
    };
    const scroll = swipeToScroll(term);
    term.onData((data) => {
      // Scrolled back, tmux would read this key as a scroll command: go back to the live screen first.
      // Mouse reports (the wheel events a swipe makes, "ESC [ < b;x;y M") travel here too; they are
      // not typing and must not undo the scroll.
      if (scroll.back && !MOUSE_REPORT.test(data)) { send({ type: "bottom" }); scroll.back = false; }
      send({ type: "input", data });
    });
    term.onResize(({ rows, cols }) => send({ type: "resize", rows, cols }));

    // Rotating the phone or opening the keyboard changes the box; fit the terminal to it again.
    // The keyboard slides over several frames and the box changes with each. Every fit resizes
    // the session and makes Claude redraw the whole screen, so wait until the box has held still.
    const fit = whenStill(() => fitter.fit(), 150);
    const observer = new ResizeObserver(fit);
    observer.observe($("live"));
    live = { term, socket, observer, fit };
    $("v-live").textContent = "Show a copy of the screen";
    pollViewer();
  } finally {
    starting = false;
  }
}

// Swipe to scroll back (docs/decisions/0025). The history is not in this terminal but in tmux on the
// laptop, which scrolls it when it gets mouse-wheel events (tmux.conf: mouse on). xterm.js sends a
// wheel on to tmux, but not a finger, so a vertical swipe becomes wheel events here: one per five
// lines of finger travel, which is how far tmux scrolls for each. Swiping back down to the bottom
// returns to the live screen. Taps and sideways moves are left to xterm.js and the page.
const MOUSE_REPORT = /^\x1b\[<\d+;\d+;\d+[Mm]$/;

function swipeToScroll(term) {
  const surface = $("live");
  const state = { back: false };
  let lastY = null, travelled = 0, vertical = false;
  const step = () => 5 * (surface.clientHeight / term.rows);
  surface.addEventListener("touchstart", (event) => {
    lastY = event.touches.length === 1 ? event.touches[0].clientY : null;
    travelled = 0;
    vertical = false;
  }, { capture: true, passive: true });
  surface.addEventListener("touchmove", (event) => {
    if (lastY === null) return;
    const touch = event.touches[0];
    travelled += touch.clientY - lastY;
    lastY = touch.clientY;
    if (!vertical && Math.abs(travelled) < 8) return;  // not a swipe yet: could be a tap
    vertical = true;
    event.preventDefault();   // no page bounce, no pull-to-refresh
    event.stopPropagation();  // and no scrolling of xterm.js's own (empty) history
    while (Math.abs(travelled) >= step()) {
      const up = travelled > 0;  // finger moving down = older lines, like any phone list
      term.element.dispatchEvent(new WheelEvent("wheel", {
        deltaY: up ? -100 : 100, deltaMode: 0, clientX: touch.clientX, clientY: touch.clientY,
        bubbles: true, cancelable: true,
      }));
      if (up) state.back = true;
      travelled += up ? -step() : step();
    }
  }, { capture: true, passive: false });
  return state;
}

// Runs `action` once `ms` have passed with no new call (a fit after the last resize, not each one).
function whenStill(action, ms) {
  let timer = null;
  const call = () => { clearTimeout(timer); timer = setTimeout(action, ms); };
  call.cancel = () => clearTimeout(timer);
  return call;
}

function stopLive() {
  if (!live) return;
  const was = live;
  live = null;
  was.observer.disconnect();
  was.fit.cancel();  // a fit still pending would reach a terminal that is gone
  was.socket.close();  // the server hangs up `tmux attach`; the session keeps running
  was.term.dispose();
  $("live").hidden = true;
  $("screen").hidden = false;
  lastText = "";  // draw the copy at once
  if (current) { refreshViewer(); pollViewer(); }
}

$("v-live").onclick = () => {
  $("v-menu").hidden = true;
  viewMode = live ? "copy" : "live";
  try { localStorage.setItem("ollagi.view", viewMode); } catch { /* private window: not remembered */ }
  liveEnded = null;
  if (live) stopLive(); else refreshViewer();
};

$("v-pause").onclick = async () => { $("v-menu").hidden = true; await api(`/api/sessions/${current}/freeze`, {}); refreshViewer(); };
$("v-resume").onclick = async () => {
  await api(`/api/sessions/${current}/thaw`, {});
  lastText = "";
  liveEnded = null;
  setTimeout(refreshViewer, 300);
};
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
  $("chip-memory-text").textContent = `${(s.memory.available / GiB).toFixed(1)} GiB free`;
  $("chip-cpu").textContent = ` · load ${s.load.one_minute.toFixed(1)}`;
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

// ---- notifications on this device (docs/decisions/0024) ------------------------------------------
// The browser subscribes at its push service with the server's public key; the server keeps the
// subscription and sends to it (src/ollagi/notify.py). Asking for permission needs a tap, so
// nothing happens until "Turn on" is pressed.
const canPush = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
let pushKey = null;

function fromBase64Url(text) {
  const plain = atob(text.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(plain, (c) => c.charCodeAt(0));
}

// This browser's subscription, if it was made with the server's current key.
async function currentSubscription() {
  const sub = await (await navigator.serviceWorker.ready).pushManager.getSubscription();
  if (!sub || !pushKey) return null;
  const made = new Uint8Array(sub.options.applicationServerKey || []);
  const wanted = fromBase64Url(pushKey);
  return made.length === wanted.length && made.every((b, i) => b === wanted[i]) ? sub : null;
}

async function refreshPush(firstTime = false) {
  const state = await api("/api/push");
  pushKey = state.public_key;
  const toggle = $("push-toggle");
  toggle.hidden = true;
  if (!isSecureContext) {
    $("push-status").textContent = "Needs the https address";
  } else if (!canPush) {
    $("push-status").textContent = "This browser cannot show them";
  } else if (Notification.permission === "denied") {
    $("push-status").textContent = "Blocked in this browser's site settings";
  } else {
    const sub = await currentSubscription();
    // The server may have lost it (a new database, a phone dropped after an error): give it again.
    if (sub && firstTime) await api("/api/push/subscribe", sub.toJSON());
    $("push-status").textContent = sub ? "On for this device" : "Off for this device";
    toggle.textContent = sub ? "Turn off" : "Turn on";
    toggle.hidden = false;
  }
  $("push-test-row").hidden = state.phones === 0;
  $("push-phones").textContent = `${state.phones} device${state.phones === 1 ? "" : "s"} on`;
  $("push-events").replaceChildren(...state.events.slice(-5).reverse().map((e) =>
    el("li", new Date(e.time * 1000).toLocaleTimeString() + "  " + e.text)));
}

$("push-toggle").onclick = async () => {
  const toggle = $("push-toggle");
  toggle.disabled = true;
  try {
    const sub = await currentSubscription();
    if (sub) {
      await api("/api/push/unsubscribe", { endpoint: sub.endpoint });
      await sub.unsubscribe();
    } else if (await Notification.requestPermission() === "granted") {
      const registration = await navigator.serviceWorker.ready;
      // One made with an older key would be refused by the push service: replace it.
      await (await registration.pushManager.getSubscription())?.unsubscribe();
      const fresh = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: fromBase64Url(pushKey) });
      // If the server refuses it, undo the browser's half too, or this device would say "On" for nothing.
      await api("/api/push/subscribe", fresh.toJSON()).catch(async (error) => { await fresh.unsubscribe(); throw error; });
    }
  } catch (error) {
    alert("Notifications: " + error.message);
  } finally {
    toggle.disabled = false;
    refreshPush();
  }
};

$("push-test").onclick = async () => {
  try {
    const result = await api("/api/push/test", {});
    if (result.failed.length) alert("Not sent: " + result.failed.join("; "));
  } catch (error) {
    alert(error.message);
  }
  refreshPush();
};

// A notification's address says what to show: /?session=NAME or /?view=queue. It arrives as the
// page's address when the page was closed, or as a message from the service worker when it was open.
function follow(url) {
  const params = new URL(url, location.origin).searchParams;
  if (params.get("session")) openViewer(params.get("session"));
  else if (params.get("view")) { if (current) closeViewer(); showView(params.get("view")); }
}
if (location.search) {
  follow(location.href);
  history.replaceState(null, "", "/");
}
navigator.serviceWorker?.addEventListener("message", (event) => {
  if (event.data?.type === "open") follow(event.data.url);
});

// ---- keep everything fresh -----------------------------------------------------------------------
async function tick() {
  try {
    if (!whoami) whoami = (await api("/api/whoami")).login;
    const jobs = [refreshSystem(), refreshSessions(), refreshWatcher()];
    if (!$("view-queue").hidden) jobs.push(refreshQueue());
    if (!$("view-system").hidden) jobs.push(refreshPush());
    await Promise.all(jobs);
    renderSessions();  // once more, now that every list is in
  } catch (error) {
    $("chip-memory-text").textContent = "offline";
  }
}
tick();
setInterval(tick, 4000);

// ---- the service worker: lets the phone install this page as an app (docs/decisions/0023) ----
// Browsers only allow one on a secure page (https, or 127.0.0.1 on the laptop).
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js")
    .then(() => refreshPush(true))
    .catch((error) => console.warn("service worker:", error));
}
