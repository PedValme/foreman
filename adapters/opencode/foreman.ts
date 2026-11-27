// Foreman for OpenCode (its v2 plugin API, checked on OpenCode 2.3.2).
//
// As thin as OpenCode allows: for each thing OpenCode tells it, this plugin runs
// `python3 -I <this clone>/adapters/hook.py opencode` with one request on standard input (the protocol in
// `adapters/foreman_hosts/neutral.py`) and does what the one answer says. Every judgment is Foreman's Python.
//
// No import from OpenCode or anywhere else beyond Node's built-ins: OpenCode accepts a default export shaped
// `{ id, setup }` and gives `setup` its context.

import { spawn } from "node:child_process"
import { realpathSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, isAbsolute, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

export type Request = Record<string, unknown> & { event: string }
export type Option = { value: string; label: string }
export type Question = { id: string; question: string; options: Option[] }
export type Answer = { action?: string; message?: string; reply?: string; question?: Question }

const TIMEOUT_MS = 30_000 // the protocol's limit; the gate's own budget is 18 s
export const COMMAND_MS = 600_000 // a `command` or `turn_end` request: the review starts a session of OpenCode
const MAX_SENT_BACK = 3 // neutral.py: a run is sent back at most three times (the gate once, the review's bounces)
const PERMISSION = "foreman" // the action Foreman's questions carry in OpenCode's permission mechanism
const PERSON_MS = 1_000 // a yes sooner than this after the question was not typed by a person
const SHELL_TOOL = "shell"
const READ_ONLY_TOOLS = new Set(["read", "glob", "grep", "webfetch", "websearch", "skill", "question", "todowrite"])

// Where Foreman is: next to this file, resolved through a symlink (the plugin is usually linked into a
// `.opencode/plugins` folder), never a path from the agent's working directory.
function hookPath(): string {
  let here = fileURLToPath(import.meta.url)
  try {
    here = realpathSync(here)
  } catch {}
  return join(dirname(here), "..", "hook.py")
}

export const HOOK = hookPath()

/** Run the Python side with one request. Resolves to its answer, or throws an Error saying why there is none. */
export function ask(request: Request, hook = HOOK, python = "python3", limit = TIMEOUT_MS): Promise<Answer> {
  return new Promise((done, fail) => {
    let child
    try {
      child = spawn(python, ["-I", hook, "opencode"], { stdio: ["pipe", "pipe", "pipe"] })
    } catch (e) {
      return fail(new Error(`cannot start ${python}: ${(e as Error).message}`))
    }
    const out: Buffer[] = []
    const err: Buffer[] = []
    const timer = setTimeout(() => {
      child.kill("SIGKILL")
      fail(new Error(`no answer within ${limit / 1000} s`))
    }, limit)
    child.stdout.on("data", (b: Buffer) => out.push(b))
    child.stderr.on("data", (b: Buffer) => err.push(b))
    child.on("error", (e: Error) => {
      clearTimeout(timer)
      fail(new Error(`cannot start ${python}: ${e.message}`))
    })
    child.on("close", (code: number | null) => {
      clearTimeout(timer)
      const stderr = Buffer.concat(err).toString("utf8").trim().slice(-500)
      if (code !== 0) return fail(new Error(`exit code ${code}${stderr ? `: ${stderr}` : ""}`))
      try {
        const answer = JSON.parse(Buffer.concat(out).toString("utf8"))
        if (answer && typeof answer === "object" && !Array.isArray(answer)) return done(answer as Answer)
      } catch {}
      fail(new Error(`no JSON answer${stderr ? `: ${stderr}` : ""}`))
    })
    child.stdin.on("error", () => {}) // a Python that exits early closes the pipe: the close above reports it
    child.stdin.end(JSON.stringify(request))
  })
}

// The gate's own quick filter (`gate._quick` in plugin/foreman/gate.py, `core.looks_gated`): the one check this
// plugin repeats, for when the Python side cannot answer. Keep the two in step.
const QUICK_TOOL = /\b(?:git|gh)(?:\.exe)?\b/i
const QUICK_VERB = /\b(?:commit|push|pr|config)\b/i

export function looksGated(command: unknown): boolean {
  return typeof command === "string" && QUICK_TOOL.test(command) && QUICK_VERB.test(command)
}

function str(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined
}

/** The directory a shell call runs in: OpenCode resolves the tool's `workdir` against the session's directory. */
export function shellCwd(base: string, workdir: unknown): string {
  let dir = str(workdir)
  if (!dir) return base
  if (dir === "~" || dir.startsWith("~/")) dir = join(homedir(), dir.slice(1))
  return isAbsolute(dir) ? dir : resolve(base, dir)
}

const PATCH_PATHS = /^\*\*\* (?:(?:Update|Add|Delete) File|Move to):\s*(.+?)\s*$/gm

/** The requests for one tool call before it runs: [] for a tool Foreman does not look at. */
export function toolRequests(tool: string, input: unknown, base: string, session: string, turn: string): Request[] {
  const args = (input && typeof input === "object" ? input : {}) as Record<string, unknown>
  const where = { cwd: base, session, turn }
  if (tool === SHELL_TOOL) {
    // A shell call with no command string still goes to Foreman, whose check of the request refuses it.
    return [{ event: "shell", command: args.command, ...where, cwd: shellCwd(base, args.workdir) }]
  }
  if (tool === "write") return [{ event: "write", path: args.path, content: args.content ?? null, ...where }]
  if (tool === "edit") {
    return [{ event: "write", path: args.path, old: args.oldString ?? null, new: args.newString ?? null,
              replace_all: args.replaceAll === true, ...where }]
  }
  if (tool === "patch") {
    const text = str(args.patchText) ?? ""
    const start = text.indexOf("*** Begin Patch")
    if (start >= 0) {
      // OpenCode reads up to the last end line: a file whose content holds that line must not hide what follows.
      const end = text.lastIndexOf("*** End Patch")
      const patch = end > start ? text.slice(start, end + "*** End Patch".length) + "\n" : text.slice(start)
      return [{ event: "patch", patch, ...where }]
    }
    // Not the format Foreman reads: what it names still meets the guards around Foreman's own files.
    return [...text.matchAll(PATCH_PATHS)].map((m) => ({ event: "write", path: m[1], ...where }))
  }
  if (READ_ONLY_TOOLS.has(tool)) return []
  // Another tool that names a file (a plugin's or an MCP server's): the guards only, as for a change Foreman
  // cannot read.
  const path = str(args.path) ?? str(args.filePath) ?? str(args.file_path)
  return path ? [{ event: "write", path, ...where }] : []
}

function millis(value: unknown): number | undefined {
  if (typeof value === "number") return value
  if (typeof value === "string") {
    const n = Date.parse(value)
    return Number.isNaN(n) ? undefined : n
  }
  if (value instanceof Date) return value.getTime()
  return undefined
}

/** A session in the middle of a run, from OpenCode's record of it: its last execution started after the one
 * before ended (`time.busy` holds the start of the latest, `time.idle` the end of the last completed one). */
export function isRunning(session: unknown): boolean {
  const time = (session as any)?.time
  const busy = millis(time?.busy)
  const idle = millis(time?.idle)
  return busy !== undefined && (idle === undefined || busy > idle)
}

/** The person's `/foreman <args>`: the text after the command name. */
export function commandArgs(prompt: unknown): string {
  const text = prompt && typeof prompt === "object" ? str((prompt as Record<string, unknown>).text) : undefined
  return (text ?? "").trim()
}

/** The session's model as OpenCode records it (`provider/model`, with `#variant` when it has one): the request's
 * `model`, undefined when the record does not say. OpenCode has no separate effort: a variant is part of the model. */
export function modelOf(session: unknown): string | undefined {
  const ref = (session as any)?.model
  if (!ref || typeof ref.providerID !== "string" || typeof ref.id !== "string" || !ref.providerID || !ref.id) {
    return undefined
  }
  return `${ref.providerID}/${ref.id}${typeof ref.variant === "string" && ref.variant ? `#${ref.variant}` : ""}`
}

/** The model of the session's latest answer, from its messages (`ctx.session.context`): undefined when none says.
 * Seen on OpenCode 2.3.2: in `opencode run` the session's record carries no model, its assistant messages do. */
export function modelOfMessages(messages: unknown): string | undefined {
  if (!Array.isArray(messages)) return undefined
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m?.type === "assistant") {
      const model = modelOf(m)
      if (model) return model
    }
  }
  return undefined
}

/** `/foreman allow <id>` is the one command this server command asks a person about (OpenCode's permission prompt).
 * Merge and reject are not: through a server command nobody is attending (they are the TUI part's, `tui.ts`). */
export function needsPerson(args: string): boolean {
  const words = args.split(/\s+/).filter(Boolean)
  return words.length > 1 && words[0].toLowerCase() === "allow"
}

/** A question as the Python side sent it, or undefined when it is not shaped as the protocol says. */
export function questionOf(answer: Answer): Question | undefined {
  const q = answer?.question
  if (!q || typeof q !== "object" || typeof q.id !== "string" || typeof q.question !== "string"
      || !Array.isArray(q.options)) {
    return undefined
  }
  const options = q.options.filter((o) => o && typeof o.value === "string" && typeof o.label === "string" && o.label)
  return options.length ? { id: q.id, question: q.question, options } : undefined
}

export default {
  id: "foreman",
  setup: async (ctx: any) => {
    const base: string = ctx.location?.directory ?? process.cwd()
    const turns = new Map<string, string>()   // session -> the id of the person's prompt that started its current run
    const failed = new Map<string, string>()  // session -> why Foreman could not run, not yet shown to the person
    const shown = new Set<string>()           // sessions already shown that error
    const sentBack = new Map<string, number>() // session -> how many times its current run was already sent back

    const fault = (session: string, error: Error): string => {
      const text = `Foreman could not run (${error.message}).`
      if (!shown.has(session)) failed.set(session, text)
      return text
    }

    // The session's own model, for what the review says about its reviewer: OpenCode's record of the session when
    // it states one, else the model of its latest answer. Undefined when neither says.
    const sessionModel = async (session: string): Promise<string | undefined> => {
      try {
        const model = modelOf(await ctx.session.get({ sessionID: session }))
        if (model) return model
      } catch {}
      try {
        return modelOfMessages(await ctx.session.context({ sessionID: session }))
      } catch {
        return undefined
      }
    }

    // A question Foreman asks the person: OpenCode's own permission prompt. Resolves when a person approves;
    // throws when nobody can answer (`opencode run` rejects it), when the person refuses, and when the yes came
    // faster than a person can give one: `opencode run --auto` approves every question itself within
    // milliseconds (measured on 2.3.2), and that is nobody attending.
    const question = async (sessionID: string, message: string, resources: string[], source?: unknown) => {
      const asked = Date.now()
      await ctx.permission.assert({
        sessionID,
        action: PERMISSION,
        resources,
        metadata: { message },
        ...(source ? { source } : {}),
      })
      if (Date.now() - asked < PERSON_MS) {
        throw new Error("OpenCode approved this within a second, by itself (an auto-approve mode: `opencode run "
                        + "--auto`, the TUI's autoaccept permissions, the app's auto-approve): nobody is attending "
                        + "to answer Foreman.")
      }
    }

    // Foreman's questions are never settled by a saved "always" or an allow-everything rule: a person answers
    // each one. A configured deny still wins (OpenCode checks it before this hook).
    // The question carries Foreman's message, so the person sees why before answering.
    await ctx.permission.hook("evaluate", (event: any) => {
      if (event.action !== PERMISSION) return
      if (event.effect === "allow") event.effect = "ask"
      const message = event.metadata?.message
      if (typeof message === "string" && !event.message) event.message = message
    })

    await ctx.tool.hook("execute.before", async (event: any) => {
      const session = String(event.sessionID ?? "")
      const requests = toolRequests(String(event.tool ?? ""), event.input, base, session, turns.get(session) ?? "")
      for (const request of requests) {
        let answer: Answer
        try {
          answer = await ask(request)
        } catch (e) {
          // Foreman's own fault: the agent keeps working, but a command the gate would inspect goes to the person
          // with the error (refused with nobody there). Everything else runs; the error is shown once, at the
          // end of the run.
          const text = fault(session, e as Error)
          if (request.event !== "shell" || !looksGated(request.command)) continue
          // Not marked shown: OpenCode's question does not display this text, and under `opencode run` only the
          // model reads it. The end of the run still shows it.
          answer = { action: "ask", message: `${text} It could not inspect this command: approve only if you have `
                                             + "checked the change yourself." }
        }
        const message = answer.message || "Foreman refused this call."
        if (answer.action === "block") throw new Error(message)
        if (answer.action === "ask") {
          try {
            await question(session, message, [String(event.tool)], {
              type: "tool", messageID: event.messageID, id: event.id,
            })
          } catch (e) {
            // Nobody could answer (`opencode run` rejects every question) or the person said no: refused, with
            // Foreman's message for the model.
            const detail = (e as Error)?.message
            throw new Error(detail && !message.includes(detail) ? `${message}\n\n(${detail})` : message)
          }
        }
      }
    })

    // Whether the session is in the middle of a run. OpenCode's record says so (`time.busy` later than
    // `time.idle`), which also covers a run that ended by interruption, when the idle hook does not fire; this
    // plugin's own record is the fallback.
    const active = new Set<string>()
    const running = async (session: string): Promise<boolean> => {
      try {
        return isRunning(await ctx.session.get({ sessionID: session }))
      } catch {
        return active.has(session)
      }
    }

    // The person's prompt. OpenCode fires this for every prompt, also one sent while the agent is working (steer,
    // queue): only a prompt to a session at rest starts a new run, so a message mid-run keeps that run's notes and
    // its nudge. (OpenCode does not fire this for its own synthetic input.)
    await ctx.session.hook("prompt", async (event: any) => {
      const session = String(event.sessionID ?? "")
      const turn = String(event.messageID ?? "")
      if (turns.has(session) && (await running(session))) return
      turns.set(session, turn)
      sentBack.delete(session)
      active.add(session)
      try {
        await ask({ event: "turn_start", cwd: base, session, turn })
      } catch (e) {
        fault(session, e as Error) // shown at the end of the run
      }
    })

    // The session is about to go idle: send the agent back when its run left a blocker in the working tree, and,
    // where the person turned on the review at the end of every turn, when that review sends the change back. The
    // Python side counts the nudges (three in all at most); this side also stops at three per run, so a Python side
    // that cannot save its count never loops. That review starts a session of OpenCode and waits for it, so the
    // answer gets a command's time, and the session's model goes with the request, for the review's default
    // reviewer. OpenCode waits for this hook (seen on 2.3.2: a hook that took 45 seconds held the run until it
    // returned). Experimental in OpenCode.
    await ctx.session.hook("experimental.idle", async (event: any) => {
      const session = String(event.sessionID ?? "")
      const background = Array.isArray(event.background) ? event.background : []
      // The session's own background work wakes it again when it ends: the run is not over yet.
      if (background.some((work: any) => work?.sessionID === session)) return
      let answer: Answer = {}
      if ((sentBack.get(session) ?? 0) < MAX_SENT_BACK) {
        const model = await sessionModel(session)
        try {
          answer = await ask({ event: "turn_end", cwd: base, session, turn: turns.get(session) ?? "",
                               ...(model ? { model } : {}) }, HOOK, "python3", COMMAND_MS)
        } catch (e) {
          fault(session, e as Error)
        }
      }
      const error = failed.get(session)
      if (error) {
        // OpenCode has no notice a plugin can show; a failed session hook is the one error the person sees. Once
        // per session, when the agent has finished its work anyway.
        failed.delete(session)
        shown.add(session)
        throw new Error(`${error} Until that is fixed its gate does not inspect this session's calls; the `
                        + "git and gh commands it would inspect come to you first.")
      }
      if (answer.action === "continue" && answer.message) {
        sentBack.set(session, (sentBack.get(session) ?? 0) + 1)
        await ctx.session.synthetic({ sessionID: session, text: answer.message, metadata: { source: "foreman" } })
        return // the run goes on
      }
      active.delete(session)
      sentBack.delete(session)
    })

    // `/foreman <args>` as a server command: code, no model turn. OpenCode shows a command's error to the person and
    // nothing else, so Foreman's reply travels as that error. In the TUI with Foreman's TUI part installed, the
    // person's `/foreman` runs there instead (`tui.ts`); this one serves the apps, the HTTP API, the SDK and a TUI
    // without that part. A server command cannot tell who sent it, so `attended` is true only for `allow <id>`, after
    // the person answered OpenCode's own question in its interface: merge and reject find nobody attending here.
    await ctx.command.transform((editor: any) => {
      editor.add({
        name: "foreman",
        description: "Foreman: the board | verdict [pr|branch] | pipeline | prs | issues | use [path|n] | status [path] | "
                     + "allow [id] | review [target] [--fresh] | reviewer [model] | help (merge, reject: in the TUI)",
        execute: async (input: any) => {
          const args = commandArgs(input?.prompt)
          let attended = false
          if (needsPerson(args)) {
            try {
              await question(String(input.sessionID), `Allow the Foreman finding ${args.split(/\s+/)[1]}?`,
                             [args.split(/\s+/)[1]])
              attended = true
            } catch {
              attended = false
            }
          }
          const model = await sessionModel(String(input.sessionID))
          let answer: Answer
          try {
            // `session`: the repository pinned with `/foreman use` is kept per conversation. A server plugin has no
            // dialog of several options, and `attended` stays false for every command but `allow`, so a command
            // that would ask (which repository) answers with the list and what to type instead.
            answer = await ask({ event: "command", args, cwd: base, session: String(input.sessionID ?? ""), attended,
                                 ...(model ? { model } : {}) }, HOOK, "python3", COMMAND_MS)
          } catch (e) {
            throw new Error(`Foreman could not run (${(e as Error).message}).`)
          }
          // A question has no dialog here (the protocol: show its text and send nothing more).
          const asked = questionOf(answer)
          if (asked) throw new Error(`${asked.question}\n\nForeman: nothing was done (no dialog to answer it here).`)
          throw new Error(answer.reply ?? "Foreman gave no reply.")
        },
      })
    })
  },
}
