// Drives adapters/opencode/foreman.ts with a stand-in for OpenCode's plugin context, against the real Python side.
// Run by tests/test_hosts_opencode.py with node or bun: `<runtime> tests/opencode_plugin.mjs <repo> <scenario>`.
// Prints one JSON object with what the plugin did; the Python test judges it.
import { writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const [repo, scenario, ...rest] = process.argv.slice(2)
const here = dirname(fileURLToPath(import.meta.url))
const plugin = (await import(pathToFileURL(join(here, "..", "adapters", "opencode", "foreman.ts")).href)).default

const hooks = {}
const commands = {}
const seen = { asked: [], synthetic: [] }
let approve = async () => { throw new Error("rejected: nobody answered") }

const ctx = {
  location: { directory: repo },
  tool: { hook: async (name, fn) => { hooks["tool." + name] = fn } },
  session: {
    hook: async (name, fn) => { hooks["session." + name] = fn },
    synthetic: async (input) => { seen.synthetic.push(input) },
  },
  permission: {
    hook: async (name, fn) => { hooks["permission." + name] = fn },
    assert: async (input) => { seen.asked.push(input); return approve(input) },
  },
  command: { transform: async (fn) => fn({ add: (d) => { commands[d.name] = d } }) },
}
await plugin.setup(ctx)

const outcome = async (promise) => {
  try {
    await promise
    return { ok: true }
  } catch (e) {
    return { ok: false, error: String(e?.message ?? e) }
  }
}
const tool = (name, input, session = "s1") =>
  outcome(hooks["tool.execute.before"]({ tool: name, sessionID: session, messageID: "m2", id: "c1", input }))
const idle = (session = "s1") => outcome(hooks["session.experimental.idle"]({ sessionID: session, background: [] }))
const prompt = (session = "s1", messageID = "m1") =>
  hooks["session.prompt"]({ sessionID: session, messageID, prompt: { text: "go" }, delivery: "steer" })
const command = (text) => outcome(commands.foreman.execute({ sessionID: "s1", prompt: { text }, delivery: "steer" }))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const out = {}
if (scenario === "gate") {
  out.registered = Object.keys(hooks).sort()
  out.merge = await tool("shell", { command: "gh pr merge 7" })
  out.ls = await tool("shell", { command: "ls" })
  out.edit = await tool("edit", { path: "tests/test_cart.py", oldString: rest[0], newString: rest[1] })
  out.read = await tool("read", { path: join(process.env.HOME, ".foreman", "x") })
  out.misspelt = await tool("shell", { cmd: "git commit -m x" })
  const event = { action: "foreman", effect: "allow", metadata: { message: "why" } }
  await hooks["permission.evaluate"](event)
  out.evaluated = event
} else if (scenario === "ask") {
  const gone = { command: "git commit -m x", workdir: join(repo, "gone") }
  out.unattended = await tool("shell", gone)                 // `opencode run`: OpenCode rejects the question
  approve = async () => {}                                   // `opencode run --auto`: a yes within milliseconds
  out.automatic = await tool("shell", gone)
  approve = async () => { await sleep(1100) }                // a person
  out.person = await tool("shell", gone)
  out.asked = seen.asked.map((a) => ({ action: a.action, message: a.metadata?.message ?? "" }))
} else if (scenario === "turn") {
  await prompt()
  out.shell = await tool("shell", { command: "perl -pi -e s/x/y/ " + rest[0] })
  if (rest[1] !== undefined) writeFileSync(join(repo, rest[0]), rest[1]) // what that command did
  out.first = await idle()
  out.second = await idle()
  out.synthetic = seen.synthetic
} else if (scenario === "talk") {
  await prompt()
  out.first = await idle()
  out.synthetic = seen.synthetic
} else if (scenario === "command") {
  out.commit = await tool("shell", { command: "git commit -m green" })
  out.id = (/id ([0-9a-f]+)\)/.exec(out.commit.error ?? "") ?? [])[1] ?? ""
  out.status = await command("status")
  out.help = await command("help")
  out.refused = await command("allow " + out.id)               // nobody answered OpenCode's question
  approve = async () => { await sleep(1100) }
  out.allowed = await command("allow " + out.id)
  out.asked = seen.asked.length
  out.after = await tool("shell", { command: "git commit -m green" })
} else if (scenario === "broken") {
  process.env.PATH = join(repo, "no-python-here")            // no python3: the Python side cannot answer
  out.ls = await tool("shell", { command: "ls" })
  out.write = await tool("write", { path: "a.txt", content: "x" })
  out.first = await idle()
  out.second = await idle()
  out.commit = await tool("shell", { command: "git commit -m x" })
  out.asked = seen.asked.map((a) => a.metadata?.message ?? "")
  out.command = await command("status")
}
process.stdout.write(JSON.stringify(out))
