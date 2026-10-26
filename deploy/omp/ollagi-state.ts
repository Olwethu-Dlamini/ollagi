// ollagi-state: an omp hook that tells ollagi what an omp session is doing (docs/decisions/0036).
//
// ollagi reads a Claude session's state from its screen. omp has hooks instead, so this file writes the
// state to a small JSON file that ollagi reads:
//
//   $XDG_RUNTIME_DIR/ollagi/<session>.json   {"state", "question", "options", "updated", "pid"}
//
// The states are ollagi's own (src/ollagi/claude_screen.py):
//   idle       the session opened, nothing has happened yet
//   working    a turn is running
//   needs_you  omp is asking something (the ask tool, or a tool waiting for approval)
//   done       the turn finished; omp waits for the next message
//
// It only acts in sessions ollagi started: ollagi sets OLLAGI_SESSION=<name> on the tmux session, so an
// omp run anywhere else is left alone. Subagents are ignored: their tool calls are not the session's.
// Install: link this file into ~/.omp/agent/hooks/post/ (omp loads hooks from hooks/pre and hooks/post).
import { mkdirSync, renameSync, unlinkSync, writeFileSync, appendFileSync } from "node:fs";
import { join } from "node:path";

const SESSION = process.env.OLLAGI_SESSION ?? "";
const NAME_OK = /^[a-z0-9][a-z0-9-]{0,31}$/; // the same rule as ollagi's session names
const DIR = join(process.env.XDG_RUNTIME_DIR ?? `/tmp/ollagi-${process.getuid?.() ?? "user"}`, "ollagi");
const FILE = join(DIR, `${SESSION}.json`);
const TRACE = process.env.OLLAGI_STATE_TRACE; // optional: append every change to this file (debugging, tests)

type State = "idle" | "working" | "needs_you" | "done";

function write(state: State, question: string | null = null, options: string[] = []): void {
	const record = { state, question, options, updated: Date.now() / 1000, pid: process.pid };
	const text = JSON.stringify(record);
	try {
		mkdirSync(DIR, { recursive: true, mode: 0o700 });
		// Write then rename: ollagi never reads a half-written file.
		const tmp = `${FILE}.${process.pid}.tmp`;
		writeFileSync(tmp, text, { mode: 0o600 });
		renameSync(tmp, FILE);
		if (TRACE) appendFileSync(TRACE, `${text}\n`);
	} catch {
		// Never let a state report break the session it reports on.
	}
}

// The ask tool's input: { questions: [{ question, options: [{ label }] }] }. Only the first question is shown.
function askOf(input: unknown): { question: string | null; options: string[] } {
	if (!input || typeof input !== "object" || !("questions" in input) || !Array.isArray(input.questions)) {
		return { question: null, options: [] };
	}
	const first: unknown = input.questions[0];
	if (!first || typeof first !== "object") return { question: null, options: [] };
	const question = "question" in first && typeof first.question === "string" ? first.question : null;
	const options =
		"options" in first && Array.isArray(first.options)
			? first.options.flatMap(o => (o && typeof o === "object" && "label" in o && typeof o.label === "string" ? [o.label] : []))
			: [];
	return { question, options };
}

interface Ctx {
	agent?: { kind?: string };
}
interface ToolEvent {
	toolName: string;
	input?: unknown;
}
interface HookApi {
	on(event: "session_start" | "agent_start" | "agent_end" | "session_shutdown", handler: (event: unknown, ctx: Ctx) => void): void;
	on(event: "tool_call" | "tool_result", handler: (event: ToolEvent, ctx: Ctx) => void): void;
	on(event: "tool_approval_requested" | "tool_approval_resolved", handler: (event: { toolName?: string }, ctx: Ctx) => void): void;
}

const isSub = (ctx: Ctx) => ctx?.agent?.kind === "sub";

export default function (pi: HookApi): void {
	if (!NAME_OK.test(SESSION)) return; // not an ollagi session, or a name that could escape the folder
	pi.on("session_start", (_e, ctx) => { if (!isSub(ctx)) write("idle"); });
	pi.on("agent_start", (_e, ctx) => { if (!isSub(ctx)) write("working"); });
	pi.on("agent_end", (_e, ctx) => { if (!isSub(ctx)) write("done"); });
	pi.on("tool_call", (event, ctx) => {
		if (isSub(ctx) || event.toolName !== "ask") return;
		const { question, options } = askOf(event.input);
		write("needs_you", question, options);
	});
	pi.on("tool_result", (event, ctx) => { if (!isSub(ctx) && event.toolName === "ask") write("working"); });
	pi.on("tool_approval_requested", (event, ctx) => {
		if (!isSub(ctx)) write("needs_you", `Allow ${event.toolName ?? "a tool"}?`, []);
	});
	pi.on("tool_approval_resolved", (_e, ctx) => { if (!isSub(ctx)) write("working"); });
	pi.on("session_shutdown", (_e, ctx) => {
		if (isSub(ctx)) return;
		try { unlinkSync(FILE); } catch { /* already gone */ }
	});
}
