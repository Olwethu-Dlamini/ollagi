// Turn terminal text with colour codes into coloured HTML elements.
//
// A terminal colours text with "SGR" escape codes: ESC [ <numbers> m. For example ESC[1;31m means
// "bold, red" and ESC[0m means "back to normal". tmux keeps them when asked (`capture-pane -e`).
//
// This reads the codes one by one, keeps the current style, and wraps each run of text in a <span>
// with that style. The text itself is always set with textContent, never innerHTML, so whatever a
// session prints can only ever appear as text.

const PALETTE = [  // the 16 basic terminal colours: 0-7 normal, 8-15 bright
  "#3b3b40", "#ff6b6b", "#5fd38d", "#f5c451", "#6aa7ff", "#d58cf0", "#4fd1d9", "#d0d0d6",
  "#6c6c74", "#ff8f8f", "#7fe3a6", "#ffd879", "#8fbcff", "#e3a9f7", "#7fe4ea", "#ffffff",
];

function colour256(n) {
  if (n < 16) return PALETTE[n];
  if (n >= 232) { const v = 8 + (n - 232) * 10; return `rgb(${v},${v},${v})`; }  // 24 greys
  const i = n - 16, steps = [0, 95, 135, 175, 215, 255];  // a 6x6x6 colour cube
  return `rgb(${steps[Math.floor(i / 36)]},${steps[Math.floor(i / 6) % 6]},${steps[i % 6]})`;
}

// Apply one SGR code list (already split on ";") to a style object.
function applySgr(style, codes) {
  for (let i = 0; i < codes.length; i++) {
    const c = codes[i] === "" ? 0 : Number(codes[i]);
    if (c === 0) { for (const k of Object.keys(style)) delete style[k]; }
    else if (c === 1) style.bold = true;
    else if (c === 2) style.dim = true;
    else if (c === 3) style.italic = true;
    else if (c === 4) style.underline = true;
    else if (c === 7) style.inverse = true;
    else if (c === 22) { delete style.bold; delete style.dim; }
    else if (c === 23) delete style.italic;
    else if (c === 24) delete style.underline;
    else if (c === 27) delete style.inverse;
    else if (c >= 30 && c <= 37) style.fg = PALETTE[c - 30];
    else if (c >= 90 && c <= 97) style.fg = PALETTE[c - 90 + 8];
    else if (c >= 40 && c <= 47) style.bg = PALETTE[c - 40];
    else if (c >= 100 && c <= 107) style.bg = PALETTE[c - 100 + 8];
    else if (c === 39) delete style.fg;
    else if (c === 49) delete style.bg;
    else if (c === 38 || c === 48) {  // extended colour: 38;5;n (256 colours) or 38;2;r;g;b
      const key = c === 38 ? "fg" : "bg";
      if (codes[i + 1] === "5") { style[key] = colour256(Number(codes[i + 2])); i += 2; }
      else if (codes[i + 1] === "2") { style[key] = `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`; i += 4; }
    }
  }
}

function spanFor(text, style) {
  const span = document.createElement("span");
  span.textContent = text;
  let fg = style.fg, bg = style.bg;
  if (style.inverse) [fg, bg] = [bg || "var(--screen-bg)", fg || "var(--screen-text)"];
  if (fg) span.style.color = fg;
  if (bg) span.style.backgroundColor = bg;
  if (style.bold) span.style.fontWeight = "700";
  if (style.dim) span.style.opacity = "0.6";
  if (style.italic) span.style.fontStyle = "italic";
  if (style.underline) span.style.textDecoration = "underline";
  return span;
}

// Claude draws rule lines as wide as its window (200 columns here). On a phone they would wrap
// into several lines, so long runs of rule characters are shortened to RULE_MAX.
const RULE_MAX = 40;
const longRule = new RegExp(`[─━╌═]{${RULE_MAX},}`, "g");

// Fill `container` with the coloured version of `text`.
export function renderAnsi(text, container) {
  text = text.replace(longRule, "─".repeat(RULE_MAX));
  const pieces = [];
  const style = {};
  // Matches any escape sequence; only SGR ones (ending in "m") change the style, others are dropped.
  const escape = /\x1b\[([0-9;:?]*)([A-Za-z])/g;
  let last = 0, match;
  while ((match = escape.exec(text)) !== null) {
    if (match.index > last) pieces.push(spanFor(text.slice(last, match.index), style));
    if (match[2] === "m") applySgr(style, match[1].replaceAll(":", ";").split(";"));
    last = escape.lastIndex;
  }
  if (last < text.length) pieces.push(spanFor(text.slice(last), style));
  container.replaceChildren(...pieces);
}
