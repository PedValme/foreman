// Foreman's TUI part for OpenCode (its TUI plugin API, checked on OpenCode 2.3.2): `/foreman <args>` typed by the
// person at the prompt of OpenCode's terminal interface.
//
// A TUI plugin's slash command runs inside the TUI process, before OpenCode looks for a server command of the same
// name, and only for what was typed at that prompt: the model's tools run in OpenCode's server, OpenCode 2.3.2 gives
// them no way to type into the TUI, and no auto-approve mode (`--auto`, the TUI's "auto accept", the app's
// auto-approve) answers this plugin's dialogs, which are not permission requests. So every request this part sends
// says `attended: true`; `allow <id>` first asks the person to confirm the finding's id. What it cannot see: keys
// typed into the terminal by another program, and code the agent plants in a plugin folder, which OpenCode loads
// with this plugin's powers (adapters/opencode/README.md, "Limits to know").
//
// As thin as the server part (`foreman.ts`, whose `ask` it uses): for each `/foreman` it runs `python3 -I
// <this clone>/adapters/hook.py opencode` with one `command` request (`adapters/foreman_hosts/neutral.py`) and shows
// the answer. A question goes to OpenCode's select dialog and the command runs again with the pick, at most three
// times. Nothing here decides what Foreman answers.
//
// Installed as a folder in a `plugins` folder of OpenCode's configuration (the TUI loads only folders): OpenCode's
// server takes `server.ts` from it and its TUI this file. No import beyond Node's built-ins and `foreman.ts`.

import { HOOK, ask, modelOf, needsPerson, questionOf } from "./foreman.ts"
import type { Answer, Option, Request } from "./foreman.ts"

// neutral.py: twelve minutes for a command that can merge (the review's seven and gh's three, with room), so Foreman
// is never stopped while gh may still be merging. The server part's command cannot merge and keeps ten.
export const COMMAND_MS = 720_000
const MAX_QUESTIONS = 3 // neutral.py: at most three questions for one command
const WORKING_MS = 1_500 // an answer slower than this gets a notice that Foreman is working (a review takes minutes)

/** The project's directory, as the TUI names it. */
function directory(ctx: any): string {
  const here = ctx?.location?.directory
  if (typeof here === "string" && here) return here
  try {
    const fallback = ctx?.data?.location?.default?.()?.directory
    if (typeof fallback === "string" && fallback) return fallback
  } catch {}
  return process.cwd()
}

// The home screen has no session: a repository pinned there with `/foreman use` is kept for this TUI's run, never
// under the empty key every session-less request would share (another project's TUI included).
const HOME_SESSION = `opencode-tui-home-${process.pid}-${Date.now()}`

/** The session the person is looking at, or this TUI's own key on the home screen. */
function sessionOf(ctx: any): string {
  try {
    const route = ctx.ui.router.current()
    if (route?.type === "session" && typeof route.sessionID === "string" && route.sessionID) return route.sessionID
  } catch {}
  return HOME_SESSION
}

/** The select dialog's options, one per option of the question; two equal labels get their numbers. */
export function selectOptions(options: Option[]): { title: string; value: string }[] {
  const labels = options.map((o) => o.label)
  const numbered = new Set(labels).size !== labels.length
  return options.map((o, i) => ({ title: numbered ? `${i + 1}. ${o.label}` : o.label, value: o.value }))
}

/** The open dialog made wide and centred: the board and a review are many lines, a question's options long paths. */
function widen(ctx: any): void {
  try {
    ctx.ui.dialog.set({ size: "xlarge", centered: true })
  } catch {}
}

/** Foreman's reply in an alert dialog. It is not awaited: the person closes it when they have read it. */
function show(ctx: any, message: string, title = "Foreman"): void {
  void Promise.resolve(ctx.ui.dialog.alert({ title, message })).catch(() => {})
  widen(ctx)
}

/** One `/foreman` the person typed. Exported for the tests. */
export async function run(ctx: any, input: string | undefined, hook = HOOK, python = "python3"): Promise<void> {
  const args = (input ?? "").trim()
  const session = sessionOf(ctx)
  if (needsPerson(args)) {
    const id = args.split(/\s+/)[1]
    const ok = await ctx.ui.dialog.confirm({
      title: "Foreman",
      message: `Allow the Foreman finding ${id}?`,
      label: { confirm: "Allow", cancel: "Cancel" },
    })
    if (ok !== true) {
      show(ctx, `Foreman: the finding ${id} was not allowed (you cancelled).`)
      return
    }
  }
  // The session's own model, as OpenCode records it, for what the review says about its reviewer.
  let model: string | undefined
  try {
    model = session === HOME_SESSION ? undefined : modelOf(ctx.data.session.get(session))
  } catch {}
  const request: Request = { event: "command", args, cwd: directory(ctx), session, attended: true,
                             ...(model ? { model } : {}) }
  for (let asked = 0; ; asked++) {
    const working = setTimeout(() => {
      try {
        ctx.ui.toast.show({ message: `Foreman is working on /foreman ${args}`.trim(), variant: "info" })
      } catch {}
    }, WORKING_MS)
    let answer: Answer
    try {
      answer = await ask(request, hook, python, COMMAND_MS)
    } catch (e) {
      show(ctx, `Foreman could not run (${(e as Error).message}).`, "Foreman could not run")
      return
    } finally {
      clearTimeout(working)
    }
    const question = questionOf(answer)
    if (!question) {
      show(ctx, answer.reply ?? "Foreman gave no reply.")
      return
    }
    if (asked >= MAX_QUESTIONS) {
      show(ctx, `${question.question}\n\nForeman: nothing was done (the question kept changing).`)
      return
    }
    const choice = ctx.ui.dialog.select({ title: question.question, options: selectOptions(question.options) })
    widen(ctx)
    const picked = await choice
    const value = question.options.some((o) => o.value === picked) ? picked : null
    request.answer = { id: question.id, value }
  }
}

export default {
  id: "foreman",
  setup(ctx: any) {
    ctx.keymap.layer(() => ({
      mode: "global",
      commands: [
        {
          id: "foreman.command",
          title: "Foreman",
          description: "Foreman: the board, verdict, pipeline, prs, issues, use, merge <pr>, reject <pr>, status, "
                       + "allow [id], review, reviewer, help",
          slash: { name: "foreman", arguments: true },
          // Not awaited: the TUI waits for a slash command before it takes the next prompt, and a review or a merge
          // takes minutes. The person keeps the prompt; Foreman's dialogs come when they are ready.
          run: (input?: string) => {
            void run(ctx, input).catch((e) => {
              show(ctx, `Foreman could not run (${(e as Error)?.message ?? e}).`, "Foreman could not run")
            })
          },
        },
      ],
    }))
  },
}
