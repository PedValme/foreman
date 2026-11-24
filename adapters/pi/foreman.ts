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
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const HOOK = join(HERE, "..", "hook.py");
const TIMEOUT_MS = 30_000; // neutral.py: no answer within 30 seconds is no answer (the gate's own budget is 18)
const SHELL_TOOLS = new Set(["bash", "powershell"]);
const READ_TOOLS = new Set(["read", "grep", "find", "ls"]);
const PATH_KEYS = ["path", "file_path", "filePath", "file"];

type Request = Record<string, unknown>;
type Answer = { action?: string; message?: string; reply?: string };

/** Foreman's answer, or an Error saying why there is none (no Python, a failed adapter, no JSON). */
export function ask(request: Request, cwd?: string): Promise<Answer | Error> {
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
				timeout: TIMEOUT_MS,
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
				finish(new Error(err.trim() || `${python} exited with code ${code}`));
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

/** The command may be one Foreman inspects. Used only when Python could not answer: never a decision on its own. */
export function looksGated(command: string): boolean {
	return /\bgit\b[\s\S]*\b(commit|push)\b|\bgh\b[\s\S]*\bpr\b[\s\S]*\b(create|merge)\b/i.test(command);
}

function text(value: unknown): string {
	return typeof value === "string" ? value : "";
}

/** The requests one tool call becomes: none (not Foreman's business), or one per change it makes. */
export function toolRequests(toolName: string, input: Record<string, unknown>, base: Request): Request[] {
	if (SHELL_TOOLS.has(toolName)) {
		return [{ ...base, event: "shell", command: text(input.command) }];
	}
	if (toolName === "write") {
		return [{ ...base, event: "write", path: text(input.path), content: text(input.content) }];
	}
	if (toolName === "edit") {
		const edits: unknown[] = Array.isArray(input.edits) ? [...input.edits] : [];
		if (typeof input.oldText === "string" && typeof input.newText === "string") {
			edits.push({ oldText: input.oldText, newText: input.newText }); // the older single-edit form
		}
		const out = edits
			.filter((e): e is Record<string, unknown> => !!e && typeof e === "object")
			.map((e) => ({ ...base, event: "write", path: text(input.path), old: text(e.oldText), new: text(e.newText) }));
		return out.length ? out : [{ ...base, event: "write", path: text(input.path) }];
	}
	if (READ_TOOLS.has(toolName)) {
		return [];
	}
	// Another tool (an extension's, an MCP server's): if it names a file, Foreman's own files stay out of its reach.
	for (const key of PATH_KEYS) {
		if (typeof input[key] === "string" && input[key]) {
			return [{ ...base, event: "write", path: input[key] }];
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
	} else if (level === "error") {
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

export default function foreman(pi: ExtensionAPI) {
	// pi starts a fresh copy of the extension for each session (startup, /new, /resume, /fork, /reload).
	let errorShown = false;
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
		const answer = await ask({ ...base(ctx), event: "turn_start" }, ctx.cwd);
		if (answer instanceof Error) {
			failed(ctx, "start this turn", answer);
		}
		return undefined;
	});

	// pi's final actionable boundary. Python counts the nudges: the second time in one run it answers {}.
	pi.on("agent_before_settle", async (event, ctx) => {
		const answer = await ask({ ...base(ctx), event: "turn_end" }, ctx.cwd);
		if (answer instanceof Error) {
			failed(ctx, "check the end of this turn", answer);
			return undefined;
		}
		if (answer.action !== "continue") {
			return undefined;
		}
		return {
			entries: [
				...event.entries,
				{ type: "custom_message", customType: "foreman", content: text(answer.message), display: true },
			],
			continue: true,
		};
	});

	pi.registerCommand("foreman", {
		description: "Foreman: status [path], allow [id], help",
		handler: async (args, ctx) => {
			const answer = await ask({ event: "command", args: args ?? "", cwd: ctx.cwd, attended: ctx.hasUI === true }, ctx.cwd);
			if (answer instanceof Error) {
				show(ctx, `Foreman could not run: ${answer.message}`, "error");
			} else {
				show(ctx, text(answer.reply), "info");
			}
		},
	});
}
