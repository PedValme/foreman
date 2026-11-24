// Drives Foreman's pi extension (adapters/pi/foreman.ts) without pi: a stand-in for pi's ExtensionAPI collects the
// handlers, and each step calls one as pi would. The extension runs the real `python3 -I adapters/hook.py pi`.
// Usage: node tests/pi_extension_driver.mjs <repository> <scenario>. Prints one JSON object of results.
// Run by tests/test_hosts_pi.py, which builds the repository and checks the results.
import { appendFileSync } from "node:fs";
import { join } from "node:path";

const [repo, scenario] = process.argv.slice(2);
const mod = await import(new URL("../adapters/pi/foreman.ts", import.meta.url).href);

const handlers = {};
const commands = {};
mod.default({
	on: (name, fn) => (handlers[name] = fn),
	registerCommand: (name, options) => (commands[name] = options),
});

const shown = [];
function context(hasUI, confirmAnswer = false, cwd = repo) {
	return {
		cwd,
		hasUI,
		ui: {
			notify: (message, level) => shown.push([level, message]),
			confirm: async (_title, message) => {
				shown.push(["confirm", message]);
				return confirmAnswer;
			},
		},
		sessionManager: { getSessionId: () => "pi-test-session" },
	};
}

const tool = (name, input, ctx = context(false)) => handlers.tool_call({ type: "tool_call", toolName: name, toolCallId: "c1", input }, ctx);

async function command(args, hasUI) {
	const printed = [];
	const write = process.stdout.write;
	process.stdout.write = (chunk) => (printed.push(String(chunk)), true);
	try {
		await commands.foreman.handler(args, context(hasUI));
	} finally {
		process.stdout.write = write;
	}
	return { printed: printed.join(""), shown: shown.splice(0) };
}

const out = { registered: { events: Object.keys(handlers).sort(), commands: Object.keys(commands) } };
const SKIP = "@pytest.mark." + "skip";

if (scenario === "gate") {
	out.commit = await tool("bash", { command: "git commit -m green" });
	out.merge = await tool("bash", { command: "gh pr merge 7" });
	out.powershell_merge = await tool("powershell", { command: "gh pr merge 7" });
	out.edit = await tool("edit", { path: "tests/test_cart.py", edits: [{ oldText: "def test_total():", newText: `${SKIP}\ndef test_total():` }] });
	out.legacy_edit = await tool("edit", { path: "tests/test_cart.py", oldText: "def test_total():", newText: `${SKIP}\ndef test_total():` });
	out.write = await tool("write", { path: "tests/test_new.py", content: `import pytest\n\n${SKIP}\ndef test_new():\n    pass\n` });
	out.ordinary_write = await tool("write", { path: "cart.py", content: "x = 1\n" });
	out.ls = await tool("bash", { command: "ls" });
	out.read = await tool("read", { path: "tests/test_cart.py" });
	out.other_tool_on_state = await tool("my_tool", { path: join(process.env.HOME, ".foreman", "grants.json") });
	out.help = await command("help", false);
	out.status = await command("status", false);
} else if (scenario === "turn") {
	const settle = () => handlers.agent_before_settle({ type: "agent_before_settle", entries: [], continue: false }, context(false));
	await handlers.before_agent_start({ type: "before_agent_start", messageType: "user", prompt: "hi" }, context(false));
	out.talk_only = await settle();
	await handlers.before_agent_start({ type: "before_agent_start", messageType: "user", prompt: "fix" }, context(false));
	out.shell = await tool("bash", { command: "make fix" });
	appendFileSync(join(repo, "tests", "test_cart.py"), `\n\n${SKIP}\ndef test_more():\n    pass\n`);
	out.first = await settle();
	out.second = await settle();
} else if (scenario === "ask") {
	const gone = join(repo, "gone");
	out.nobody = await tool("bash", { command: "git commit -m x" }, context(false, false, gone));
	out.declined = await tool("bash", { command: "git commit -m x" }, context(true, false, gone));
	out.approved = await tool("bash", { command: "git commit -m x" }, context(true, true, gone));
	out.shown = shown.splice(0);
} else if (scenario === "allow") {
	out.blocked = await tool("bash", { command: "git commit -m green" });
	out.list = await command("allow", false); // listing what waits needs nobody
	const id = /^\s+([0-9a-f]{4,})\s+\[/m.exec(out.list.printed)?.[1] ?? "";
	out.id = id;
	out.unattended = await command(`allow ${id}`, false);
	out.still_blocked = await tool("bash", { command: "git commit -m green" });
	out.attended = await command(`allow ${id}`, true);
	out.passes = await tool("bash", { command: "git commit -m green" });
} else if (scenario === "no-python") {
	process.env.FOREMAN_PYTHON = join(repo, "no-such-python");
	const errors = [];
	const write = process.stderr.write;
	process.stderr.write = (chunk) => (errors.push(String(chunk)), true);
	try {
		out.gated_nobody = await tool("bash", { command: "git push" });
		out.gated_person = await tool("bash", { command: "git push" }, context(true, false));
		out.ordinary = await tool("bash", { command: "ls" });
		out.write = await tool("write", { path: "cart.py", content: "x\n" });
		out.settle = await handlers.agent_before_settle({ type: "agent_before_settle", entries: [], continue: false }, context(false));
		out.help = await command("help", false);
	} finally {
		process.stderr.write = write;
	}
	out.stderr = errors.join("");
	out.shown = shown.splice(0);
} else {
	throw new Error(`unknown scenario ${scenario}`);
}

process.stdout.write(JSON.stringify(out, (_k, v) => (v === undefined ? null : v)));
