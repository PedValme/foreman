/**
 * Foreman for pi: a green check the agent did not rig.
 *
 * As thin as pi allows. For each thing pi tells it, it runs `python3 -I <clone>/adapters/hook.py pi` with one
 * request on standard input (the protocol is `adapters/foreman_hosts/neutral.py`) and does what the one answer
 * says. All of Foreman's judgment is in Python, where it is tested; nothing here decides what is rigged.
 *
 *   tool_call (bash, powershell)     -> {"event": "shell"}   block, or ask the person
 *   tool_call (write, edit)          -> {"event": "write"}   block, or ask the person
 *   tool_call (another tool, a path) -> {"event": "write"}   guards only
 *   before_agent_start               -> {"event": "turn_start"}
 *   agent_before_settle              -> {"event": "turn_end"}  continue, once per run (Python counts)
 *   /foreman <args>                  -> {"event": "command"} the reply, shown to the person
 *
 * Try it: `pi -e /path/to/foreman/adapters/pi/foreman.ts`. Needs Python 3.9+ as `python3` (or FOREMAN_PYTHON) and git.
 */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, posix, win32 } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const HOOK = join(HERE, "..", "hook.py");
const TIMEOUT_MS = 30_000; // neutral.py: no answer within 30 seconds is no answer (the gate's own budget is 18)
// /foreman review waits for a model (seven minutes at most), and /foreman merge then for gh (three): neutral.py
// gives a `command` twelve minutes where it can merge, so Foreman is never stopped while gh may still be merging
export const COMMAND_TIMEOUT_MS = 720_000;
const SHELL_TOOLS =new Set(["bash", "powershell"]);
const READ_TOOLS = new Set(["read", "grep", "find", "ls"]);
const PATH_KEYS = ["path", "file_path", "filePath", "file"];

const MAX_QUESTIONS = 3; // neutral.py: at most three questions for one command
const MAX_SENT_BACK = 3; // neutral.py: a run is sent back at most three times (the gate once, the review's bounces)

type Request = Record<string, unknown>;
type Option = { value: string; label: string };
type Question = { id: string; question: string; options: Option[] };
type Answer = { action?: string; message?: string; reply?: string; question?: Question };

/** Foreman's answer, or an Error saying why there is none (no Python, a failed adapter, no JSON). */
export function ask(request: Request, cwd?: string, timeoutMs: number = TIMEOUT_MS): Promise<Answer | Error> {
	const python = process.env.FOREMAN_PYTHON || "python3";
	return new Promise((resolve) => {
		let out = "";
		let err = "";
		let done = false;
		const finish = (value: Answer | Error) => {
			if (!done) {
				done = true;
				resolve(value);
			}
		};
		let child;
		try {
			child = spawn(python, ["-I", HOOK, "pi"], {
				cwd: cwd && existsSync(cwd) ? cwd : HERE,
				stdio: ["pipe", "pipe", "pipe"],
				timeout: timeoutMs,
				windowsHide: true,
			});
		} catch (e) {
			finish(new Error(`cannot run ${python}: ${(e as Error).message}`));
			return;
		}
		child.stdout.on("data", (d: Buffer) => (out += d.toString("utf8")));
		child.stderr.on("data", (d: Buffer) => (err += d.toString("utf8")));
		child.on("error", (e: Error) => finish(new Error(`cannot run ${python}: ${e.message}`)));
		child.on("close", (code: number | null) => {
			if (code !== 0) {
				const why = code === null ? `no answer within ${timeoutMs / 1000} seconds` : `${python} exited with code ${code}`;
				finish(new Error(code === null ? why : err.trim() || why));
				return;
			}
			try {
				const parsed = JSON.parse(out);
				finish(parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : new Error("not a JSON object"));
			} catch {
				finish(new Error(`no answer (${err.trim() || "empty output"})`));
			}
		});
		child.stdin.on("error", () => {}); // a child that died before reading: its exit code says why
		child.stdin.end(JSON.stringify(request));
	});
}

/** The gate's own quick filter (`gate._quick`, copied exactly): a git or gh word and a commit, push, pr or config
 * word, anywhere. Used only when Python could not answer: never a decision on its own. */
export function looksGated(command: string): boolean {
	return /\b(?:git|gh)(?:\.exe)?\b/i.test(command) && /\b(?:commit|push|pr|config|api)\b/i.test(command);
}

const UNICODE_SPACES = /[\u00A0\u2000-\u200A\u202F\u205F\u3000]/g;

/** pi's `normalizeWindowsShellPath`: `/c/x`, `/mnt/c/x` and `/cygdrive/c/x` are `C:\x` on Windows. */
function windowsShellPath(p: string): string {
	if (!p.startsWith("/") || p.startsWith("//") || p.includes("\\")) {
		return p;
	}
	const match = p.match(/^\/(?:mnt\/|cygdrive\/)?([a-z])(?:\/(.*))?$/i);
	if (!match) {
		return p;
	}
	return `${match[1].toUpperCase()}:\\${(match[2] ?? "").split("/").join("\\")}`;
}

/** The file a pi tool will touch, resolved as pi's own tools do (`resolveToCwd`, `normalizePath`): Unicode spaces
 * made plain, a leading `@` dropped, on Windows a shell-style `/c/…` read as `C:\…`, `~` and `~/` expanded, a
 * `file://` URL read as a path, the rest resolved against the session's directory. A path pi itself could not
 * resolve is sent as it was given, never an error. */
export function resolvePiPath(path: string, cwd: string, platform: string = process.platform): string {
	const win = platform === "win32";
	const paths = win ? win32 : posix;
	try {
		let p = path.replace(UNICODE_SPACES, " ");
		if (p.startsWith("@")) {
			p = p.slice(1);
		}
		if (win) {
			p = windowsShellPath(p);
		}
		if (p === "~") {
			p = homedir();
		} else if (p.startsWith("~/") || (win && p.startsWith("~\\"))) {
			p = paths.join(homedir(), p.slice(2));
		} else if (/^file:\/\//.test(p)) {
			p = fileURLToPath(p, { windows: win });
		}
		if (!p) {
			return "";
		}
		return paths.isAbsolute(p) ? paths.resolve(p) : paths.resolve(cwd || process.cwd(), p);
	} catch {
		return path;
	}
}

function text(value: unknown): string {
	return typeof value === "string" ? value : "";
}

/** The requests one tool call becomes: none (not Foreman's business), or one per change it makes. */
export function toolRequests(toolName: string, input: Record<string, unknown>, base: Request): Request[] {
	const where = (value: unknown) => resolvePiPath(text(value), text(base.cwd));
	if (SHELL_TOOLS.has(toolName)) {
		return [{ ...base, event: "shell", command: text(input.command) }];
	}
	if (toolName === "write") {
		return [{ ...base, event: "write", path: where(input.path), content: text(input.content) }];
	}
	if (toolName === "edit") {
		const edits: unknown[] = Array.isArray(input.edits) ? [...input.edits] : [];
		if (typeof input.oldText === "string" && typeof input.newText === "string") {
			edits.push({ oldText: input.oldText, newText: input.newText }); // the older single-edit form
		}
		const out = edits
			.filter((e): e is Record<string, unknown> => !!e && typeof e === "object")
			.map((e) => ({ ...base, event: "write", path: where(input.path), old: text(e.oldText), new: text(e.newText) }));
		return out.length ? out : [{ ...base, event: "write", path: where(input.path) }];
	}
	if (READ_TOOLS.has(toolName)) {
		return [];
	}
	// Another tool (an extension's, an MCP server's): if it names a file, Foreman's own files stay out of its reach.
	for (const key of PATH_KEYS) {
		if (typeof input[key] === "string" && input[key]) {
			return [{ ...base, event: "write", path: where(input[key]) }];
		}
	}
	return [];
}

function cannotRun(error: Error): string {
	return `Foreman could not run: ${error.message}. Approve only if you have checked the change yourself.`;
}

function show(ctx: ExtensionContext, message: string, level: "info" | "error"): void {
	if (ctx.hasUI) {
		ctx.ui.notify(message, level);
	} else if (level === "error" || ctx.mode !== "print") {
		// `--mode json` and RPC own standard output (their event stream): Foreman never writes into it
		process.stderr.write(`${message}\n`);
	} else {
		process.stdout.write(`${message}\n`);
	}
}

/** "ask": the person decides through pi's own dialog; with nobody there, refuse with the message. */
async function personDecides(ctx: ExtensionContext, message: string) {
	if (!ctx.hasUI) {
		return { block: true, reason: message };
	}
	const ok = await ctx.ui.confirm("Foreman", `${message}\n\nLet the agent run it?`);
	return ok ? undefined : { block: true, reason: `${message}\n(The user declined.)` };
}

/** The session's model (`provider/id`, which `pi --model` takes as it is) and thinking level, as pi's context states
 * them; a key is left out when pi does not state it. They only decide what the review says about its reviewer. */
export function sessionOf(ctx: ExtensionContext): Request {
	const out: Request = {};
	const model = ctx.model as { id?: unknown; provider?: unknown } | undefined;
	if (model && typeof model.id === "string" && model.id) {
		out.model = typeof model.provider === "string" && model.provider ? `${model.provider}/${model.id}` : model.id;
	}
	const level = (ctx as { thinkingLevel?: unknown }).thinkingLevel;
	if (typeof level === "string" && level) {
		out.effort = level;
	}
	return out;
}

/** A question as Python sent it, or undefined when it is not shaped as the protocol says. */
export function questionOf(answer: Answer): Question | undefined {
	const q = answer.question;
	if (!q || typeof q !== "object" || typeof q.id !== "string" || typeof q.question !== "string" || !Array.isArray(q.options)) {
		return undefined;
	}
	const options = q.options.filter((o) => o && typeof o.value === "string" && typeof o.label === "string" && o.label);
	return options.length ? { id: q.id, question: q.question, options } : undefined;
}

/** The lines pi's selector shows, one per option and each different (the pick is found by its line): when two
 * options share a label, every line gets its number. */
export function optionLines(options: Option[]): string[] {
	const labels = options.map((o) => o.label);
	return new Set(labels).size === labels.length ? labels : labels.map((label, i) => `${i + 1}. ${label}`);
}

export default function foreman(pi: ExtensionAPI) {
	// pi starts a fresh copy of the extension for each session (startup, /new, /resume, /fork, /reload).
	let errorShown = false;
	let sentBack = 0; // how many times this run was already sent back
	const failed = (ctx: ExtensionContext, what: string, error: Error) => {
		if (!errorShown) {
			errorShown = true; // once per session: the person sees it, the agent is not held up by Foreman's fault
			show(ctx, `Foreman could not ${what}: ${error.message}. Until this is fixed Foreman is not checking this session.`, "error");
		}
	};

	const base = (ctx: ExtensionContext): Request => ({
		cwd: ctx.cwd,
		session: ctx.sessionManager.getSessionId() || "",
		turn: "", // pi has no id for one run of the agent; turn_start marks where one begins
	});

	pi.on("tool_call", async (event, ctx) => {
		const input = (event.input ?? {}) as Record<string, unknown>;
		for (const request of toolRequests(event.toolName, input, base(ctx))) {
			const answer = await ask(request, ctx.cwd);
			if (answer instanceof Error) {
				if (request.event === "shell" && looksGated(text(request.command))) {
					// a call the gate would inspect never passes unseen: the person decides, or nobody does
					return personDecides(ctx, cannotRun(answer));
				}
				failed(ctx, `inspect a ${event.toolName} call`, answer);
				continue;
			}
			if (!answer.action) {
				continue;
			}
			const message = text(answer.message) || "Foreman needs a person to decide this call.";
			if (answer.action === "block") {
				return { block: true, reason: message };
			}
			return personDecides(ctx, message); // "ask", and anything this extension does not know
		}
		return undefined;
	});

	// A prompt starts a run (before_agent_start fires once per prompt; a continuation asked below does not fire it).
	pi.on("before_agent_start", async (_event, ctx) => {
		sentBack = 0;
		const answer = await ask({ ...base(ctx), event: "turn_start" }, ctx.cwd);
		if (answer instanceof Error) {
			failed(ctx, "start this turn", answer);
		}
		return undefined;
	});

	// pi's final actionable boundary. Python counts the nudges: one for what the gate finds, and, where the person
	// turned on the review at the end of every turn, one per review that sends the change back (three in all at
	// most). This side also stops at three per run, so a Python side that cannot save its count never loops. That
	// review starts a session of pi and waits for it, so the answer gets a command's time; the session's model and
	// thinking level go with the request, for the review's default reviewer.
	pi.on("agent_before_settle", async (event, ctx) => {
		if (sentBack >= MAX_SENT_BACK) {
			return undefined;
		}
		const answer = await ask({ ...base(ctx), event: "turn_end", ...sessionOf(ctx) }, ctx.cwd, COMMAND_TIMEOUT_MS);
		if (answer instanceof Error) {
			failed(ctx, "check the end of this turn", answer);
			return undefined;
		}
		if (answer.action !== "continue") {
			return undefined;
		}
		sentBack += 1;
		return {
			entries: [
				...event.entries,
				{ type: "custom_message", customType: "foreman", content: text(answer.message), display: true },
			],
			continue: true,
		};
	});

	pi.registerCommand("foreman", {
		description: "Foreman: the board, verdict [pr|branch], merge <pr>, reject <pr>, pipeline, prs, issues, use, status, allow [id], review, reviewer, help",
		handler: async (args, ctx) => {
			// the review starts a session of pi and waits for it: ten minutes, not thirty seconds
			const request: Request = {
				event: "command",
				args: args ?? "",
				cwd: ctx.cwd,
				session: ctx.sessionManager.getSessionId() || "",
				attended: ctx.hasUI === true,
				...sessionOf(ctx),
			};
			// A command that needs the person to choose answers with a question: pi's own selector asks it, here and
			// nowhere else, and the command runs again with what they picked (null when they closed the selector).
			for (let asked = 0; ; asked++) {
				const answer = await ask(request, ctx.cwd, COMMAND_TIMEOUT_MS);
				if (answer instanceof Error) {
					show(ctx, `Foreman could not run: ${answer.message}`, "error");
					return;
				}
				const question = questionOf(answer);
				if (!question) {
					show(ctx, text(answer.reply), "info");
					return;
				}
				if (!ctx.hasUI || asked >= MAX_QUESTIONS) {
					const why = ctx.hasUI ? "the question kept changing" : "nobody is attending this session to answer";
					show(ctx, `${question.question}\n\nForeman: nothing was done (${why}).`, "info");
					return;
				}
				const lines = optionLines(question.options);
				const picked = await ctx.ui.select(question.question, lines);
				const at = picked === undefined ? -1 : lines.indexOf(picked);
				request.answer = { id: question.id, value: at >= 0 ? question.options[at].value : null };
			}
		},
	});
}
