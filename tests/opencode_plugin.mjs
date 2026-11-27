// Drives adapters/opencode/foreman.ts with a stand-in for OpenCode's plugin context, against the real Python side.
// Run by tests/test_hosts_opencode.py with node or bun: `<runtime> tests/opencode_plugin.mjs <repo> <scenario>`.
// Prints one JSON object with what the plugin did; the Python test judges it.
import { readFileSync, writeFileSync } from "node:fs"
import { pathToFileURL } from "node:url"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const [repo, scenario, ...rest] = process.argv.slice(2)
const here = dirname(fileURLToPath(import.meta.url))
const module = await import(pathToFileURL(join(here, "..", "adapters", "opencode", "foreman.ts")).href)
const plugin = module.default
const { toolRequests } = module
const running = new Set()

// The time limit each request to the Python side was given: `ask` sets one timer per request.
const delays = []
const realSetTimeout = globalThis.setTimeout
globalThis.setTimeout = (fn, ms, ...more) => { delays.push(ms); return realSetTimeout(fn, ms, ...more) }
let sessionModel // what OpenCode's record of the session says about its model, when it does
let answerModel // the model of the session's latest answer, in its messages (`opencode run` states only this one)

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
    // OpenCode's record of the session it is asked about: mid-run while its id is in `running`.
    get: async ({ sessionID }) => ({ id: sessionID, ...(sessionModel ? { model: sessionModel } : {}),
                                     time: running.has(sessionID) ? { busy: 2000, idle: 1000 }
                                                                  : { busy: 1000, idle: 2000 } }),
    context: async () => [{ type: "user", text: "go" },
                          ...(answerModel ? [{ type: "assistant", model: { providerID: "old", id: "x" } },
                                             { type: "assistant", model: answerModel }] : []),
                          { type: "synthetic", text: "note" }],
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
  out.write = await tool("write", { path: "tests/test_cart.py", content: rest[2] })
  // A file whose own content holds the end line must not hide the hunk after it.
  out.patch = await tool("patch", { patchText: "*** Begin Patch\n*** Add File: notes.txt\n+*** End Patch\n"
                                    + "*** Update File: tests/test_cart.py\n@@\n-" + rest[0] + "\n+" + rest[1]
                                    .split("\n").join("\n+") + "\n*** End Patch\n" })
  out.plainPatch = await tool("patch", { patchText: "*** Begin Patch\n*** Add File: notes.txt\n+hi\n*** End Patch\n" })
  // A shell call without a command string (OpenCode's own check refuses it): Foreman cannot answer it, the call
  // is not held up, and the error reaches the person at the end of the run.
  out.misspelt = await tool("shell", { cmd: "git commit -m x" })
  out.misspeltIdle = await idle()
  const event = { action: "foreman", effect: "allow", metadata: { message: "why" } }
  await hooks["permission.evaluate"](event)
  out.evaluated = event
} else if (scenario === "requests") {
  out.relative = toolRequests("shell", { command: "ls", workdir: "sub/dir" }, repo, "s1", "t1")[0].cwd
  out.home = toolRequests("shell", { command: "ls", workdir: "~/work" }, repo, "s1", "t1")[0].cwd
  out.absolute = toolRequests("shell", { command: "ls", workdir: join(dirname(repo), "elsewhere") }, repo, "s1",
                              "t1")[0].cwd
  out.none = toolRequests("shell", { command: "ls" }, repo, "s1", "t1")[0].cwd
  out.todo = toolRequests("todowrite", { path: "x" }, repo, "s1", "t1")
  out.mcp = toolRequests("mcp_writer", { filePath: "y.txt" }, repo, "s1", "t1")
} else if (scenario === "steer") {
  await prompt("s1", "m1")
  out.shell = await tool("shell", { command: "perl -pi -e s/x/y/ " + rest[0] })
  writeFileSync(join(repo, rest[0]), rest[1])
  running.add("s2")                                          // another session's run says nothing about this one
  out.other = await outcome(prompt("s1", "m1b"))             // a prompt to s1 at rest: s1's run starts again
  await tool("shell", { command: "perl -pi -e s/x/y/ " + rest[0] })
  writeFileSync(join(repo, rest[0]), rest[1])
  running.add("s1")                                          // OpenCode's record: s1's run is still going
  await prompt("s1", "m2")                                   // the person writes while the agent works
  running.delete("s1")
  out.first = await idle()
  out.second = await idle()
  out.synthetic = seen.synthetic
} else if (scenario === "ask") {
  const gone = { command: "git commit -m x", workdir: join(repo, "gone") }
  out.unattended = await tool("shell", gone)                 // `opencode run`: OpenCode rejects the question
  approve = async () => {}                                   // `opencode run --auto`: a yes within milliseconds
  out.automatic = await tool("shell", gone)
  approve = async () => { await sleep(1100) }                // a person
  out.person = await tool("shell", gone)
  out.asked = seen.asked.map((a) => ({ action: a.action, message: a.metadata?.message ?? "" }))
  out.idle = await idle()                                    // Foreman ran fine: nothing to show at the end
} else if (scenario === "broken-git") {
  process.env.PATH = join(repo, "no-python-here")            // no python3: the Python side cannot answer
  out.commit = await tool("shell", { command: "git commit -m x" }) // the first failed call is a gated one
  out.asked = seen.asked.length
  out.first = await idle()                                   // its error still reaches the person, once
  out.second = await idle()
} else if (scenario === "turn") {
  await prompt()
  out.shell = await tool("shell", { command: "perl -pi -e s/x/y/ " + rest[0] })
  if (rest[1] !== undefined) writeFileSync(join(repo, rest[0]), rest[1]) // what that command did
  const before = delays.length
  out.first = await idle()
  out.idleDelay = delays[before]                             // the end of a turn may wait for a review
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
  // the board and its read commands: `/foreman` alone, a pin kept for this conversation, nothing asked
  out.board = await command("")
  out.use = await command("use")
  out.pin = await command("use .")
  out.askedAfterBoard = seen.asked.length
} else if (scenario === "server-writes") {
  // Merge and reject through the server command (the apps, the HTTP API, the SDK, `opencode api`): nobody is
  // attending there, whatever the person or a script answers; only `allow <id>` asks OpenCode's question.
  approve = async () => { await sleep(1100) }                // even a person's yes to a question, were one asked
  out.merge = await command("merge 7")
  out.mergeYes = await command("merge 7 --yes")
  out.reject = await command("reject 7 --close --yes note")
  out.askedForWrites = seen.asked.length
  out.allowNamedMerge = await command("allow merge 7")         // `allow` asks, and allows a finding: never a merge
  out.asked = seen.asked.map((a) => a.resources)
} else if (scenario === "review") {
  // The review's own command: a longer time, and the session's model as OpenCode's record states it.
  out.shellDelays = delays.length
  await tool("shell", { command: "ls" })
  out.shellDelay = delays[delays.length - 1]
  out.unknown = await command("reviewer p/m")                  // the person's choice, saved in the state directory
  out.unknownDelay = delays[delays.length - 1]
  out.unknownShown = (await command("reviewer")).error
  sessionModel = { providerID: "p", id: "m" }
  out.sameShown = (await command("reviewer")).error
  sessionModel = { providerID: "p", id: "m", variant: "high" }
  out.variantShown = (await command("reviewer p/m#high")).error
  out.variantAgain = (await command("reviewer")).error
  sessionModel = undefined                                     // the record says nothing: the latest answer does
  answerModel = { providerID: "p", id: "m", variant: "high" }
  out.fromAnswer = (await command("reviewer")).error
  out.modelOf = [module.modelOf({ model: { providerID: "a", id: "b", variant: "max" } }),
                 module.modelOf({ model: { providerID: "a", id: "b" } }), module.modelOf({}), module.modelOf(null),
                 module.modelOf({ model: { providerID: "a" } })]
} else if (scenario === "turn-cap") {
  // The end of a turn carries the session's model, and the plugin sends a run back at most three times whatever
  // the Python side answers (here a stand-in on PATH that always sends the agent back and logs each request).
  answerModel = { providerID: "p", id: "m", variant: "high" } // as in `opencode run`: only the messages state it
  await prompt()
  out.failedCall = await tool("shell", { command: "ls fail-here" }) // the stand-in fails this one request
  out.idles = []
  for (let i = 0; i < 4; i++) out.idles.push(await idle())   // the fourth end is not sent back: the run is over
  out.synthetic = seen.synthetic.length
  await prompt("s1", "m9")                                   // a new run starts its own count
  await idle()
  out.afterNewRun = seen.synthetic.length
  out.ends = readFileSync(rest[0], "utf-8").trim().split("\n").map((line) => JSON.parse(line))
    .filter((r) => r.event === "turn_end")
} else if (scenario === "reviewer-env") {
  out.registered = Object.keys(hooks)
  out.commands = Object.keys(commands)
  out.asked = seen.asked.length
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
