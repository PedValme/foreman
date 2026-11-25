// Drives adapters/opencode/tui.ts (Foreman's TUI part for OpenCode) with a stand-in for OpenCode's TUI plugin
// context that records every dialog and toast and lets the scenario pick in the select dialog.
// Run by tests/test_hosts_opencode_tui.py with node or bun:
//   `<runtime> tests/opencode_tui.mjs <repo> <scenario> [<hook> <python>]`
// With a hook and a python, the person's command runs that entry point instead of adapters/hook.py (the test's own,
// which puts a fake gh and a fake reviewer in front of the real Python side). Prints one JSON object.
import { dirname, join } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const [repo, scenario, hook, python] = process.argv.slice(2)
const here = dirname(fileURLToPath(import.meta.url))
const tui = await import(pathToFileURL(join(here, "..", "adapters", "opencode", "tui.ts")).href)
const server = await import(pathToFileURL(join(here, "..", "adapters", "opencode", "foreman.ts")).href)

const layers = []
let shown = []
let pick = () => undefined          // the select dialog: the value picked, or undefined when it is closed
let confirmAnswer = false            // the confirm dialog
let route = { type: "session", sessionID: "s1" }
let sessionModel

const ctx = {
  location: { directory: repo },
  keymap: { layer: (factory) => layers.push(factory()) },
  data: { session: { get: (id) => ({ id, ...(sessionModel ? { model: sessionModel } : {}) }) } },
  ui: {
    router: { current: () => route },
    toast: { show: (o) => shown.push(["toast", o.message]) },
    dialog: {
      alert: async (o) => { shown.push(["alert", o.title, o.message]) },
      set: (o) => shown.push(["set", o]),
      confirm: async (o) => { shown.push(["confirm", o.message]); return confirmAnswer },
      select: async (o) => { shown.push(["select", o.title, o.options]); return pick(o.options) },
    },
  },
}
await tui.default.setup(ctx)
const command = layers.flatMap((l) => l.commands ?? []).find((c) => c.slash?.name === "foreman")

// The person types `/foreman <text>`: what the TUI shows, in order, once the command has finished. With a hook,
// through that entry point. (The registered command starts this same `run` without waiting for it: "registered".)
const type = async (text) => {
  await (hook ? tui.run(ctx, text, hook, python) : tui.run(ctx, text))
  return shown.splice(0)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const out = {}
if (scenario === "reads") {
  out.layer = layers.map((l) => ({ mode: l.mode, commands: (l.commands ?? []).map((c) => ({ id: c.id, slash: c.slash })) }))
  // The registered command returns at once (the TUI keeps its prompt) and the reply's dialog comes after.
  const started = Date.now()
  out.returned = command.run("help")
  out.returnedAt = Date.now() - started
  out.immediately = shown.length
  for (let i = 0; i < 300 && !shown.some((e) => e[0] === "alert"); i++) await sleep(100)
  out.registered = shown.splice(0)
  out.board = await type("")
  out.help = await type("help")
  route = { type: "home" }
  out.home = await type("status")              // no session open: the command still answers
  pick = (options) => options.find((o) => o.title.includes("other"))?.value
  out.homePin = await type("use")              // pinned on the home screen: for this TUI's run, not for session s1
  route = { type: "session", sessionID: "s1" }
  out.sessionAfterHomePin = await type("status")
  pick = () => undefined
  out.dismissed = await type("use")
  pick = (options) => options.find((o) => o.title.includes("other"))?.value
  out.picked = await type("use")
  out.status = await type("status")             // the pinned repository's verdict
  out.limit = tui.COMMAND_MS
  out.options = tui.selectOptions([{ value: "a", label: "x" }, { value: "b", label: "x" }, { value: "c", label: "y" }])
} else if (scenario === "allow") {
  const blocked = await server.ask({ event: "shell", command: "git commit -m green", cwd: repo, session: "s1", turn: "" })
  out.id = (/id ([0-9a-f]+)\)/.exec(blocked.message ?? "") ?? [])[1] ?? ""
  confirmAnswer = false
  out.cancelled = await type("allow " + out.id)
  out.still = await server.ask({ event: "shell", command: "git commit -m green", cwd: repo, session: "s1", turn: "" })
  confirmAnswer = true
  out.allowed = await type("allow " + out.id)
  out.after = await server.ask({ event: "shell", command: "git commit -m green", cwd: repo, session: "s1", turn: "" })
} else if (scenario === "writes") {
  sessionModel = { providerID: "p", id: "m-1" }
  pick = () => undefined
  out.dismissed = await type("merge 7")
  pick = (options) => options.find((o) => o.value === "cancel")?.value
  out.cancelled = await type("merge 7")
  pick = (options) => options.find((o) => o.value === "merge")?.value
  out.merged = await type("merge 7")
} else if (scenario === "reject") {
  pick = () => undefined
  out.dismissed = await type("reject 7 --close")
  pick = (options) => options.find((o) => o.value === "close")?.value
  out.closed = await type("reject 7 --close")
} else if (scenario === "slow") {
  out.slow = await type("status")               // an answer slower than 1.5 s: a notice that Foreman is working
} else if (scenario === "endless") {
  pick = (options) => options[0].value
  out.endless = await type("use")
} else if (scenario === "broken") {
  process.env.PATH = join(repo, "no-python-here")  // no python3: the Python side cannot answer
  out.broken = await type("status")
}
process.stdout.write(JSON.stringify(out))
