// Foreman: the Desktop half. A pane that shows each change on Foreman's line, Gate -> Review -> Owner -> Merge, with
// a token at the station where the change is now, plus a status-bar chip ("Foreman · 2 waiting for you").
//
// Disk plugin, loaded uncompiled: only @hermes/plugin-sdk, react and react/jsx-runtime resolve, so there is no JSX
// and no build step; this file is the source.
//
// Data: GET /api/plugins/foreman/pipeline (dashboard/plugin_api.py), through ctx.rest. It returns Foreman's own state
// file and nothing else. The panel refreshes on the `plugin.foreman.pipeline.updated` event, when a turn completes,
// and by polling: every 2 s while the pane is on screen, every 15 s while it is not (for the chip), never while the
// window is hidden. Every timer and listener goes through ctx, so it ends with the plugin.
//
// Safety: titles, branch names, paths and event lines come from pull requests and the agent. They are rendered as
// React text only, never as HTML. The buttons do one thing: put a Foreman slash command into the chat, exactly the
// text a person would type (`/foreman merge 6`), and the command does the rest with its own checks and confirmation.
// Nothing here calls gh, git or the network.
//
// Robustness: every host call is wrapped (a host that lacks a member or throws changes nothing here), both
// contributions render inside their own error boundary (a bad snapshot shows a small "reload" card, never a throw into
// the app), a failing REST call keeps the last answer on screen ("reconnecting…"), and nothing writes after dispose.
import { atom, Button, host, PALETTE_AREA, PANES_AREA, STATUSBAR_AREAS, useValue } from '@hermes/plugin-sdk'
import { Component, useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'foreman'
const PANE_ID = 'pane'
const PANE_KEY = `${ID}:${PANE_ID}` // the contribution-scoped id the host knows the pane by
const STYLE_ID = 'foreman-plugin-style'
const EVENT = `plugin.${ID}.pipeline.updated`
const POLL_VISIBLE_MS = 2000
const POLL_BACKGROUND_MS = 15000
const RECENT_MS = 15 * 60 * 1000

// ─── tiny element helper (React.createElement's shape over jsx/jsxs) ──────────────────────────────────────────────

function h(type, props, ...children) {
  const p = props ? { ...props } : {}
  const key = p.key
  delete p.key
  const kids = children.filter(c => c !== null && c !== undefined && c !== false && c !== '')
  if (kids.length === 1) p.children = kids[0]
  else if (kids.length > 1) p.children = kids
  return kids.length > 1 ? jsxs(type, p, key) : jsx(type, p, key)
}

// A host call that may be missing on this desktop build or may throw: the fallback instead.
function safe(fn, fallback) {
  try {
    const v = fn()
    return v === undefined ? fallback : v
  } catch {
    return fallback
  }
}

const str = v => (typeof v === 'string' ? v : typeof v === 'number' && Number.isFinite(v) ? String(v) : '')

// ─── the model: where a change stands ─────────────────────────────────────────────────────────────────────────────

const STATIONS = ['gate', 'review', 'owner', 'merge']
const LABEL = { code: 'Agent', gate: 'Gate', review: 'Review', owner: 'Owner', merge: 'Merge' }
// Where the token sits: 0 is the coding side, 1..4 the stations.
const POSITION = { bounced: 0, gate: 1, review: 2, ready: 3, awaiting_owner: 3, rejected: 3, merged: 4 }
const WORDS = {
  gate: { pass: 'passed', fail: 'blocked', skipped: 'skipped', pending: 'waiting', active: 'checking' },
  review: { pass: 'passed', notes: 'notes', fail: 'failed', error: 'error', skipped: 'skipped', pending: 'waiting', active: 'reviewing' },
  owner: { approved: 'approved', rejected: 'rejected', skipped: 'skipped', pending: 'waiting', active: 'your call' },
  merge: { done: 'merged', refused: 'refused', skipped: 'skipped', pending: 'waiting', active: 'merging' }
}
const KIND = { pass: 'ok', approved: 'ok', done: 'ok', fail: 'bad', rejected: 'bad', refused: 'bad', notes: 'warn', error: 'error', skipped: 'skip' }
const GROUPS = [
  { id: 'owner', label: 'Waiting for you' },
  { id: 'blocked', label: 'Blocked' },
  { id: 'moving', label: 'On the line' },
  { id: 'done', label: 'Done' }
]

function stationsOf(item) {
  const out = {}
  for (const s of Array.isArray(item.stages) ? item.stages : []) if (s && STATIONS.includes(s.name)) out[s.name] = s
  for (const name of STATIONS) out[name] = out[name] || { name, status: 'pending', detail: '' }
  return out
}

function groupOf(item, st) {
  if (item.stage === 'merged' || item.stage === 'rejected') return 'done'
  if (item.stage === 'ready' || item.stage === 'awaiting_owner') return 'owner'
  if (item.stage === 'bounced') return 'blocked'
  if (item.stage === 'gate' && st.gate.status === 'fail') return 'blocked'
  if (item.stage === 'review' && (st.review.status === 'fail' || st.review.status === 'error')) return 'blocked'
  return 'moving'
}

function toneOf(item, group) {
  if (item.stage === 'merged') return 'merged'
  if (item.stage === 'rejected') return 'rejected'
  if (item.stage === 'bounced') return 'bounced'
  return group
}

function bounceText(item) {
  const n = Number.isInteger(item.bounces) ? item.bounces : 0
  return Number.isInteger(item.max_bounces) ? `${n}/${item.max_bounces}` : `${n}`
}

function pillText(item, st) {
  switch (item.stage) {
    case 'gate': return st.gate.status === 'fail' ? 'Blocked at the gate' : 'At the gate'
    case 'review':
      if (st.review.status === 'fail') return 'Review failed'
      if (st.review.status === 'error') return 'Review error'
      return 'In review'
    case 'bounced': return `Bounced back · ${bounceText(item)}`
    case 'ready': return 'Ready for you'
    case 'awaiting_owner': return 'Waiting for you'
    case 'merged': return 'Merged'
    case 'rejected': return 'Rejected'
    default: return item.stage
  }
}

function refOf(item) {
  const t = item.target || {}
  if (t.kind === 'pr' && Number.isInteger(t.number)) return `#${t.number}`
  return t.branch || ''
}

function titleOf(item) {
  const t = item.target || {}
  return t.title || t.branch || item.id
}

// The reader (dashboard/plugin_api.py) already validates every field; this keeps the panel from throwing on anything
// that still slips through (a newer or hand-edited state file): strings stay strings, lists stay lists.
// A review that failed with no bounce counted (a merge-time review, or a state file written before Foreman stopped
// calling that a bounce) is not "bounced back": it reads as the failed review it is, at the Review station.
function shapeOf(raw, i) {
  const item = raw && typeof raw === 'object' ? raw : {}
  const bounces = Number.isInteger(item.bounces) && item.bounces > 0 ? item.bounces : 0
  const stage = item.stage === 'bounced' && !bounces ? 'review' : str(item.stage) || 'gate'
  const t = item.target && typeof item.target === 'object' ? item.target : {}
  return {
    ...item,
    id: str(item.id) || `item-${i}`,
    repo: str(item.repo),
    stage,
    bounces,
    updated: str(item.updated),
    target: { ...t, title: str(t.title), branch: str(t.branch), url: str(t.url) || null },
    stages: Array.isArray(item.stages) ? item.stages.filter(s => s && typeof s === 'object')
      .map(s => ({ ...s, detail: str(s.detail), model: str(s.model) })) : [],
    events: Array.isArray(item.events) ? item.events.filter(e => e && typeof e === 'object')
      .map(e => ({ at: str(e.at), text: str(e.text) })) : []
  }
}

function sortItems(items) {
  const rank = { owner: 0, blocked: 1, moving: 2, done: 3 }
  return items
    .map(shapeOf)
    .map(item => {
      const st = stationsOf(item)
      const group = groupOf(item, st)
      return { item, st, group, tone: toneOf(item, group) }
    })
    .sort((a, b) => rank[a.group] - rank[b.group] || String(b.item.updated || '').localeCompare(String(a.item.updated || '')))
}

function countsOf(items) {
  const c = { owner: 0, blocked: 0, moving: 0, done: 0 }
  for (const row of sortItems(items)) c[row.group] += 1
  return c
}

function summaryText(c) {
  const parts = []
  if (c.owner) parts.push(`${c.owner} waiting for you`)
  if (c.blocked) parts.push(`${c.blocked} blocked`)
  if (c.moving) parts.push(`${c.moving} on the line`)
  if (!parts.length && c.done) parts.push(`${c.done} done`)
  return parts.join(' · ')
}

function ago(iso, now) {
  const t = Date.parse(iso || '')
  if (!Number.isFinite(t)) return ''
  const s = Math.max(0, Math.round((now - t) / 1000))
  if (s < 45) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const hr = Math.round(m / 60)
  if (hr < 24) return `${hr}h ago`
  return `${Math.round(hr / 24)}d ago`
}

// ─── commands: the same text a person types ───────────────────────────────────────────────────────────────────────

const SAFE_BRANCH = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$/

// The argument a Foreman command takes for this change: a PR number, or a branch name that cannot carry anything else.
function argOf(item) {
  const t = item.target || {}
  if (t.kind === 'pr' && Number.isInteger(t.number) && t.number > 0) return String(t.number)
  if (t.kind === 'branch' && typeof t.branch === 'string' && SAFE_BRANCH.test(t.branch) && !t.branch.includes('..') &&
      !/^#?\d+$/.test(t.branch)) return t.branch // all digits would read as a PR number
  return null
}

const SAFE_REPO = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$/

// A Foreman command acts on the chat's repository unless it names one with `--repo owner/name` (which Foreman accepts
// only for a repository it already knows on this machine). Merge, reject and verdict name the card's repository;
// review takes no --repo, so it is offered only when one repository is on the line. Without a usable repository name
// and with several repositories on the line, no command is offered rather than one that could reach the wrong one.
function actionsOf(item, st, group, oneRepo) {
  const repo = typeof item.repo === 'string' && SAFE_REPO.test(item.repo) && !item.repo.includes('..') ? item.repo : null
  const arg = repo || oneRepo ? argOf(item) : null
  const where = repo ? ` --repo ${repo}` : ''
  const isPr = (item.target || {}).kind === 'pr'
  const out = []
  if (arg && group === 'owner' && isPr) {
    out.push({ id: 'merge', label: `Merge ${refOf(item)}`, command: `/foreman merge ${arg}${where}`, mode: 'submit', primary: true,
      hint: 'Runs in the chat: Foreman checks the verdict again and asks you to confirm.' })
    out.push({ id: 'reject', label: 'Reject…', command: `/foreman reject ${arg}${where}`, mode: 'draft',
      hint: 'Puts the command in the chat box: add a note and press Enter.' })
  } else if (arg && group !== 'done') {
    out.push({ id: 'verdict', label: 'Show verdict', command: `/foreman verdict ${arg}${where}`, mode: 'submit',
      hint: 'Read-only: CLEAN or BLOCKED, with the reasons and the exact line.' })
    if (oneRepo && item.stage === 'review' && st.review.status === 'error') {
      out.push({ id: 'review', label: 'Review again…', command: `/foreman review ${arg}`, mode: 'draft',
        hint: 'Puts the command in the chat box; a review spends model tokens.' })
    }
  }
  return out
}

function notify(message) {
  safe(() => host.notify({ kind: 'info', title: 'Foreman', message }), null)
}

// Put the command where the person can send it, and never move them anywhere: host.composer answers only for a chat
// box that is on screen (it never navigates), so when none is (a page such as Capabilities fills the main area) a
// command that runs goes to the clipboard with a toast; a command to finish by hand goes into the chat box draft.
async function sendCommand(ctx, action) {
  const composer = safe(() => host.composer, null)
  const call = async (name, ...args) => {
    try {
      return composer && typeof composer[name] === 'function' ? await composer[name](...args) : undefined
    } catch {
      return undefined
    }
  }
  // A second click on the same command within a moment is the same intent, not a second command.
  const now = Date.now()
  if (now - (recentClicks.get(action.command) || 0) < REPEAT_MS) return
  recentClicks.set(action.command, now)
  if (action.mode === 'submit') {
    if ((await call('submit', null, action.command)) === true) return
    // No chat box on screen. The draft door could land in a chat kept hidden behind the page, so the clipboard.
  } else {
    const draft = await call('getDraft', null)
    // Never overwrite what the person is typing.
    if (!(typeof draft === 'string' && draft.trim()) && (await call('setDraft', null, `${action.command} `)) === true) {
      await call('focus', null)
      return
    }
  }
  let copied = false
  try {
    copied = (await ctx.os?.writeClipboard?.(action.command)) === true
  } catch {
    copied = false
  }
  notify(copied ? `No chat on screen: copied ${action.command}. Open a chat and paste it.` : `Type ${action.command} in a chat.`)
}

const REPEAT_MS = 1500
const recentClicks = new Map()

// ─── data: one store, one poller ──────────────────────────────────────────────────────────────────────────────────

function describeError(err) {
  const text = String((err && (err.message || err.statusText)) || err || '')
  if (/\b404\b|not found|not enabled/i.test(text)) return { kind: 'off', text }
  return { kind: 'down', text }
}

// Is the pane on screen? host.paneVisibility is a memoized atom per pane id (safe to keep for the plugin's life); an
// older desktop without it, or one that throws, counts as "on screen" so polling never stops.
function paneAtom() {
  return safe(() => (typeof host.paneVisibility === 'function' ? host.paneVisibility(PANE_KEY) : null), null)
}

function paneOnScreen(visible) {
  return visible ? safe(() => visible.get() === true, true) : true
}

function startData(ctx, store) {
  let last = null
  let inflight = null
  let cancel = null
  // A poll can still be in flight when the plugin is disabled or reloaded: nothing may write or re-arm after that.
  let disposed = false
  const visible = paneAtom()
  const put = value => { if (!disposed) store.set(value) }

  const refresh = () => {
    if (inflight) return inflight
    inflight = (async () => {
      try {
        if (typeof ctx.rest !== 'function') throw new Error('not enabled: this desktop has no plugin REST')
        const snapshot = await ctx.rest('/pipeline')
        const key = JSON.stringify(snapshot)
        if (key !== last || store.get().phase !== 'ready' || store.get().error) {
          last = key
          put({ phase: 'ready', snapshot: snapshot && Array.isArray(snapshot.items) ? snapshot : { items: [] }, error: null })
        }
      } catch (err) {
        // A profile or connection switch, a gateway restart, a 401 while a grant is re-minted: keep the last answer
        // on screen ("reconnecting…") and let the next poll recover.
        const prev = store.get()
        put({ phase: prev.snapshot ? 'ready' : 'error', snapshot: prev.snapshot, error: describeError(err) })
      } finally {
        inflight = null
      }
    })()
    return inflight
  }

  safe(() => ctx.onDispose(() => { disposed = true; safe(() => cancel?.(), null) }), null)
  const schedule = () => {
    if (disposed) return
    safe(() => cancel?.(), null)
    const ms = paneOnScreen(visible) ? POLL_VISIBLE_MS : POLL_BACKGROUND_MS
    cancel = safe(() => ctx.setTimeout(tick, ms), null)
  }
  const tick = async () => {
    if (disposed) return
    if (typeof document === 'undefined' || !document.hidden) await refresh()
    schedule()
  }
  const wake = () => { if (!disposed) void refresh().then(schedule) }

  safe(() => ctx.onEvent(EVENT, () => void refresh()), null)
  safe(() => ctx.onEvent('message.complete', () => void refresh()), null)
  if (typeof document !== 'undefined') {
    safe(() => ctx.addEventListener(document, 'visibilitychange', () => { if (!document.hidden) wake() }), null)
  }
  if (visible && typeof visible.listen === 'function') {
    const stop = safe(() => visible.listen(on => { if (on) wake() }), null)
    if (typeof stop === 'function') safe(() => ctx.onDispose(stop), null)
  }
  void tick()
  return refresh
}

// Bring the pane into view: host.revealPane (desktop 0.23+, the same reveal the app's own toggles use) fronts the
// tab, opens its side, restores its zone and puts a closed pane back. It never toggles anything closed. On a desktop
// without it, say where the pane is instead of guessing with a sidebar toggle (view.toggleRightSidebar is the file
// browser's ⌘J and acts on whichever column sits outermost on the right, not on this pane).
const WHERE = 'Open the right side (Ctrl+J, ⌘J on a Mac) and pick the Foreman tab; if its zone is folded, click the ' +
  'rail. No tab? Capabilities → Plugins (Capacidades → Plugins), Foreman: turn its Desktop switch off and on.'

function reveal(ctx) {
  const visible = paneAtom()
  if (visible && paneOnScreen(visible)) return
  const revealed = safe(() => {
    if (typeof host.revealPane !== 'function') return false
    host.revealPane(PANE_KEY)
    return true
  }, false)
  if (!revealed) return notify(`Foreman’s pane is not on screen. ${WHERE}`)
  safe(() => ctx.setTimeout(() => {
    if (visible && !paneOnScreen(visible)) notify(`Foreman could not bring its pane forward. ${WHERE}`)
  }, 300), null)
}

// ─── hooks ────────────────────────────────────────────────────────────────────────────────────────────────────────

function useReducedMotion() {
  const query = '(prefers-reduced-motion: reduce)'
  const [reduced, setReduced] = useState(() => typeof matchMedia === 'function' && matchMedia(query).matches)
  useEffect(() => {
    if (typeof matchMedia !== 'function') return undefined
    const mq = matchMedia(query)
    const on = () => setReduced(mq.matches)
    on()
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [])
  return reduced
}

function useNow(ms) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

// ─── glyphs (inline SVG, drawn in currentColor) ───────────────────────────────────────────────────────────────────

const PATHS = {
  check: ['M3.5 8.4l2.9 2.9 6.1-6.6'],
  x: ['M4.6 4.6l6.8 6.8', 'M11.4 4.6l-6.8 6.8'],
  bang: ['M8 3.8v5', 'M8 11.6v.4'],
  warn: ['M8 2.6l5.8 10.2H2.2z', 'M8 6.6v2.8', 'M8 11v.3'],
  minus: ['M4.4 8h7.2'],
  question: ['M6 6.1a2 2 0 1 1 2.9 1.8c-.6.3-.9.7-.9 1.3v.4', 'M8 11.5v.3'],
  code: ['M6 4.8L2.8 8 6 11.2', 'M10 4.8L13.2 8 10 11.2'],
  gate: ['M8 1.9l5 2v3.7c0 3-2.1 5.3-5 6.5-2.9-1.2-5-3.5-5-6.5V3.9z'],
  review: ['M1.6 8s2.4-4.3 6.4-4.3S14.4 8 14.4 8s-2.4 4.3-6.4 4.3S1.6 8 1.6 8z', 'M8 9.8a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6z'],
  owner: ['M8 7.6a2.4 2.4 0 1 0 0-4.8 2.4 2.4 0 0 0 0 4.8z', 'M3.4 13.4c.7-2.4 2.5-3.6 4.6-3.6s3.9 1.2 4.6 3.6'],
  merge: ['M4.5 6.2a1.9 1.9 0 1 0 0-3.8 1.9 1.9 0 0 0 0 3.8z', 'M11.5 13.6a1.9 1.9 0 1 0 0-3.8 1.9 1.9 0 0 0 0 3.8z',
    'M4.5 14V6.2', 'M4.5 6.2a5.5 5.5 0 0 0 5.1 5.5'],
  back: ['M6 3.6L2.8 6.6 6 9.6', 'M3 6.6h6.4a3.6 3.6 0 0 1 0 7.2H7']
}

function Glyph({ name, size = 14 }) {
  return h('svg', { className: 'fm-glyph', width: size, height: size, viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor',
    strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, focusable: 'false' },
  (PATHS[name] || PATHS.question).map((d, i) => h('path', { key: i, d })))
}

// ─── the line ─────────────────────────────────────────────────────────────────────────────────────────────────────

function stationView(name, station, active) {
  const status = station.status
  const words = WORDS[name]
  if (status === 'pending' || status === undefined) {
    return { kind: active ? 'active' : 'idle', glyph: name, word: active ? words.active : words.pending }
  }
  if (status === null || !(status in words)) return { kind: 'unknown', glyph: 'question', word: 'unknown' }
  const kind = KIND[status] || 'idle'
  const glyph = { ok: 'check', bad: 'x', warn: 'bang', error: 'warn', skip: 'minus' }[kind] || name
  return { kind, glyph, word: words[status] }
}

function Station({ name, view, detail, active }) {
  const label = `${LABEL[name]}: ${view.word}`
  return h('div', { className: 'fm-st', role: 'listitem', tabIndex: 0, 'aria-label': detail ? `${label}. ${detail}` : label,
    title: detail || label, 'data-kind': view.kind, 'data-active': active ? 'true' : 'false' },
  h('span', { className: 'fm-dot' }, h(Glyph, { name: view.glyph })),
  h('span', { className: 'fm-st-name' }, LABEL[name]),
  h('span', { className: 'fm-st-word' }, view.word))
}

function Line({ item, st, tone }) {
  const pos = POSITION[item.stage] ?? 1
  const prev = useRef(pos)
  const dir = pos < prev.current ? 'back' : 'forward'
  useEffect(() => { prev.current = pos }, [pos])
  const bounced = item.stage === 'bounced'
  const segs = [0, 1, 2, 3].map(i => {
    let state = i < pos ? 'done' : 'todo'
    if (bounced && i < 2) state = 'bounce'
    return h('span', { key: i, className: 'fm-seg', 'data-s': state, style: { left: `${10 + i * 20}%` } })
  })
  const codeView = bounced
    ? { kind: 'warn', glyph: 'back', word: `fixing · ${bounceText(item)}` }
    : { kind: 'idle', glyph: 'code', word: item.bounces ? `${bounceText(item)} bounces` : 'coding' }
  const ref = refOf(item)
  return h('div', { className: 'fm-line' },
    h('span', { className: 'fm-track', 'aria-hidden': true }),
    segs,
    h('div', { className: 'fm-token', 'data-dir': dir, 'data-tone': tone, style: { '--fm-pos': pos }, 'aria-hidden': true },
      h('span', { className: 'fm-token-chip' }, bounced ? `↺ ${bounceText(item)}` : ref || '•'),
      h('span', { className: 'fm-token-tip' })),
    h('div', { className: 'fm-stations', role: 'list', 'aria-label': `Where ${ref || 'this change'} stands on the line` },
      h(Station, { key: 'code', name: 'code', view: codeView, active: bounced, detail: bounced ? `Bounced back to the agent (${bounceText(item)})` : '' }),
      STATIONS.map((name, i) => {
        const active = pos === i + 1 && (st[name].status === 'pending' || st[name].status === undefined)
        const view = stationView(name, st[name], active)
        return h(Station, { key: name, name, view, active, detail: st[name].detail || '' })
      })))
}

// ─── a card ───────────────────────────────────────────────────────────────────────────────────────────────────────

function Details({ st }) {
  const rows = STATIONS.map(name => {
    const s = st[name]
    const head = name === 'review' && s.model ? `Review by ${s.model}` : LABEL[name]
    if (!s.detail) return null
    const view = stationView(name, s, false)
    return h('li', { key: name, className: 'fm-detail', 'data-kind': view.kind },
      h(Glyph, { name: view.glyph, size: 12 }),
      h('span', null, h('b', null, head), ': ', s.detail))
  }).filter(Boolean)
  if (!rows.length) return null
  return h('ul', { className: 'fm-details', 'aria-label': 'Station details' }, rows)
}

function Timeline({ events, now }) {
  const list = (Array.isArray(events) ? events : []).slice(-4).reverse()
  if (!list.length) return null
  return h('ol', { className: 'fm-events', 'aria-label': 'Latest events' },
    list.map((e, i) => h('li', { key: `${e.at || ''}-${i}`, className: 'fm-event' },
      h('span', { className: 'fm-event-at' }, ago(e.at, now) || '·'),
      h('span', { className: 'fm-event-text' }, e.text))))
}

function Actions({ ctx, item, st, group, oneRepo }) {
  const actions = actionsOf(item, st, group, oneRepo)
  const url = (item.target || {}).url
  const blind = !actions.length && !oneRepo && group !== 'done' && argOf(item)
  if (!actions.length && !url && !blind) return null
  const hint = blind ? 'Several repositories are on the line: pick this one in the chat with /foreman use, then run /foreman there.'
    : actions.find(a => a.primary)?.hint
  return h('div', { className: 'fm-actions-wrap' },
    h('div', { className: 'fm-actions' },
      actions.map(a => h(Button, {
        key: a.id, size: 'sm', variant: a.primary ? 'default' : 'outline',
        title: `${a.command} (${item.repo || 'this repository'}): ${a.hint}`,
        'aria-label': `${a.label}: sends ${a.command} to the chat`,
        onClick: () => void sendCommand(ctx, a)
      }, a.label)),
      url ? h(Button, { key: 'open', size: 'sm', variant: 'ghost', title: url, 'aria-label': `Open ${refOf(item)} in the browser`,
        onClick: () => void Promise.resolve(safe(() => ctx.os.openExternal(url), null)).catch(() => null) }, 'Open ↗') : null),
    hint ? h('p', { className: 'fm-hint' }, hint) : null)
}

function Card({ ctx, row, now, oneRepo, compact }) {
  const { item, st, group, tone } = row
  const titleId = `fm-t-${item.id.replace(/[^A-Za-z0-9_-]/g, '_')}`
  const ref = refOf(item)
  return h('article', { className: 'fm-card', 'data-tone': tone, 'data-compact': compact ? 'true' : 'false', 'aria-labelledby': titleId },
    h('div', { className: 'fm-meta' },
      h('span', { className: 'fm-repo', title: item.repo || '' }, item.repo || 'local repository'),
      ref ? h('span', { className: 'fm-ref', title: ref, 'data-pr': ref.startsWith('#') ? 'true' : 'false' }, ref) : null,
      h('span', { key: item.stage, className: 'fm-pill', 'data-tone': tone }, pillText(item, st))),
    h('h3', { id: titleId, className: 'fm-name', title: titleOf(item) }, titleOf(item)),
    h(Line, { item, st, tone }),
    compact ? null : h('div', { className: 'fm-body' },
      h(Details, { st }),
      h(Timeline, { events: item.events, now })),
    compact ? null : h(Actions, { ctx, item, st, group, oneRepo }))
}

// ─── the pane ─────────────────────────────────────────────────────────────────────────────────────────────────────

function MiniLine() {
  return h('div', { className: 'fm-mini', 'aria-hidden': true },
    STATIONS.map((name, i) => h('span', { key: name, className: 'fm-mini-st' },
      i ? h('span', { className: 'fm-mini-bar' }) : null,
      h('span', { className: 'fm-mini-dot' }, h(Glyph, { name, size: 12 })))))
}

const PROBLEMS = {
  unreadable: 'Foreman’s state file could not be read.',
  too_large: 'Foreman’s state file is larger than the panel reads.',
  unsupported: 'Foreman’s state file is from a newer version of Foreman.'
}

function Empty({ ctx, problem }) {
  return h('div', { className: 'fm-empty' },
    h(MiniLine, null),
    h('p', { className: 'fm-empty-title' }, 'No changes on the line yet'),
    h('p', { className: 'fm-empty-text' },
      'When the agent commits, opens a pull request or asks for a review, the change shows up here and moves Gate → Review → Owner → Merge. Start with /foreman in the chat.'),
    h(Button, { size: 'sm', variant: 'outline', onClick: () => void sendCommand(ctx, { command: '/foreman', mode: 'submit' }) }, 'Run /foreman'),
    problem && PROBLEMS[problem] ? h('p', { className: 'fm-note' }, `${PROBLEMS[problem]} It is written again on the next change.`) : null)
}

function Loading() {
  return h('div', { className: 'fm-loading', role: 'status', 'aria-label': 'Loading Foreman’s line' },
    [0, 1].map(i => h('div', { key: i, className: 'fm-skel' },
      h('span', { className: 'fm-skel-bar fm-skel-short' }),
      h('span', { className: 'fm-skel-bar' }),
      h('span', { className: 'fm-skel-line' }))))
}

function Failure({ error, onRetry }) {
  const off = error && error.kind === 'off'
  return h('div', { className: 'fm-empty', role: 'alert' },
    h('p', { className: 'fm-empty-title' }, off ? 'Foreman is not running for this profile' : 'Foreman’s line is unreachable'),
    h('p', { className: 'fm-empty-text' }, off
      ? 'Turn Foreman on in Capabilities → Plugins (the Agent column, for this profile), then retry.'
      : 'The gateway did not answer. It may be restarting.'),
    h(Button, { size: 'sm', variant: 'outline', onClick: onRetry }, 'Retry'))
}

function Panel({ ctx, store, refresh }) {
  const state = useValue(store)
  const reduced = useReducedMotion()
  const now = useNow(30000)
  const [doneOpen, setDoneOpen] = useState(() => safe(() => ctx.storage.get('doneOpen', false), false) === true)
  const toggleDone = () => {
    const next = !doneOpen
    setDoneOpen(next)
    safe(() => ctx.storage.set('doneOpen', next), null) // storage is a convenience
  }
  const items = state.snapshot && Array.isArray(state.snapshot.items) ? state.snapshot.items : []
  const rows = sortItems(items)
  const counts = countsOf(items)
  const oneRepo = new Set(rows.map(r => r.item.repo)).size <= 1
  let body
  if (state.phase === 'loading') body = h(Loading, null)
  else if (state.phase === 'error') body = h(Failure, { error: state.error, onRetry: () => void refresh() })
  else if (!rows.length) body = h(Empty, { ctx, problem: state.snapshot && state.snapshot.problem })
  else {
    // One flat, keyed list (group headings are rows too), so a card that changes group keeps its element and its
    // token travels instead of jumping. Finished changes stay in view for a while, then fold into "Done".
    const children = []
    for (const g of GROUPS) {
      const list = rows.filter(r => r.group === g.id)
      if (!list.length) continue
      if (g.id !== 'done') {
        children.push(h('h2', { key: `g-${g.id}`, className: 'fm-group-label' }, g.label))
        for (const r of list) children.push(h(Card, { key: r.item.id, ctx, row: r, now, oneRepo, compact: false }))
        continue
      }
      const recent = list.filter(r => now - (Date.parse(r.item.updated || '') || 0) < RECENT_MS)
      const older = list.filter(r => !recent.includes(r))
      children.push(h('h2', { key: 'g-done', className: 'fm-group-label' }, recent.length ? 'Just finished' : g.label))
      for (const r of recent) children.push(h(Card, { key: r.item.id, ctx, row: r, now, oneRepo, compact: true }))
      if (older.length) {
        children.push(h('button', { key: 'g-done-toggle', type: 'button', className: 'fm-group-toggle', 'aria-expanded': doneOpen, onClick: toggleDone },
          h('span', { className: 'fm-caret', 'data-open': doneOpen ? 'true' : 'false', 'aria-hidden': true }, '›'),
          `${recent.length ? 'Earlier' : 'Show'} · ${older.length}`))
        if (doneOpen) for (const r of older) children.push(h(Card, { key: r.item.id, ctx, row: r, now, oneRepo, compact: true }))
      }
    }
    body = h('div', { className: 'fm-list' }, children)
  }
  const ready = state.phase === 'ready'
  const tally = [['owner', 'waiting for you'], ['blocked', 'blocked'], ['moving', 'on the line'], ['done', 'done']]
    .filter(([k]) => counts[k]).map(([k, word]) => ({ k, text: `${counts[k]} ${word}` }))
  return h('div', { className: 'fm', 'data-motion': reduced ? 'reduce' : 'full' },
    h('header', { className: 'fm-head' },
      h('div', { className: 'fm-head-row' },
        h('h1', { className: 'fm-title' }, 'Foreman'),
        h('p', { className: 'fm-sub' }, 'Gate → Review → Owner → Merge'),
        state.error && ready ? h('span', { className: 'fm-stale', title: 'Showing the last answer; reconnecting.' }, 'reconnecting…') : null),
      h('ul', { className: 'fm-counts', 'aria-live': 'polite', 'aria-label': ready ? summaryText(counts) || 'Nothing on the line' : 'Loading' },
        ready ? tally.map(t => h('li', { key: t.k, className: 'fm-count', 'data-tone': t.k === 'done' ? 'merged' : t.k }, t.text)) : null)),
    h('div', { className: 'fm-scroll' }, body))
}

function Chip({ ctx, store }) {
  const state = useValue(store)
  const items = state.snapshot && Array.isArray(state.snapshot.items) ? state.snapshot.items : []
  const c = countsOf(items)
  const tone = c.owner ? 'owner' : c.blocked ? 'blocked' : c.moving ? 'moving' : 'idle'
  const text = c.owner ? `${c.owner} waiting for you` : c.blocked ? `${c.blocked} blocked` : c.moving ? `${c.moving} on the line` : ''
  return h('button', { type: 'button', className: 'fm-chip', 'data-tone': tone, onClick: () => reveal(ctx),
    title: text ? `Foreman: ${text}` : 'Foreman: nothing on the line', 'aria-label': text ? `Foreman: ${text}. Show the line.` : 'Foreman. Show the line.' },
  h('span', { className: 'fm-chip-dot', 'aria-hidden': true }),
  h('span', null, 'Foreman'),
  text ? h('span', { className: 'fm-chip-text' }, `· ${text}`) : null)
}

// The blast wall inside our own contributions: a render error in the panel or the chip shows a small card with a
// Reload button (a fresh render from the current data) instead of reaching the host's boundary.
class Guard extends Component {
  constructor(props) {
    super(props)
    this.state = { failed: false }
  }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error) {
    safe(() => console.warn('[foreman] the panel hit an error and shows its reload card', error), null)
  }

  render() {
    if (!this.state.failed) return this.props.children
    const reload = () => this.setState({ failed: false })
    if (this.props.chip) {
      return h('button', { type: 'button', className: 'fm-chip', 'data-tone': 'idle', onClick: reload,
        title: 'Foreman hit an error. Click to reload.', 'aria-label': 'Foreman hit an error. Reload.' },
      h('span', { className: 'fm-chip-dot', 'aria-hidden': true }), h('span', null, 'Foreman · reload'))
    }
    return h('div', { className: 'fm' },
      h('div', { className: 'fm-empty', role: 'alert' },
        h('p', { className: 'fm-empty-title' }, 'Foreman panel hit an error'),
        h('p', { className: 'fm-empty-text' }, 'Nothing on the line changed; only this view failed to draw.'),
        h('button', { type: 'button', className: 'fm-group-toggle', onClick: reload }, 'Reload')))
  }
}

// ─── styles: theme variables only, so every theme and both modes repaint it ───────────────────────────────────────

const CSS = `
.fm,.fm-chip{--fm-ok:var(--ui-green);--fm-bad:var(--ui-red);--fm-warn:var(--ui-yellow);--fm-err:var(--ui-orange);--fm-act:var(--ui-accent)}
.fm{container-type:inline-size;display:flex;flex-direction:column;height:100%;min-height:0;color:var(--ui-text-secondary);font-size:12px;line-height:1.45}
.fm *{box-sizing:border-box}
.fm [data-tone=owner],.fm-chip[data-tone=owner],.fm [data-tone=moving],.fm-chip[data-tone=moving]{--fm-tone:var(--fm-act)}
.fm [data-tone=blocked],.fm-chip[data-tone=blocked]{--fm-tone:var(--fm-bad)}
.fm [data-tone=bounced]{--fm-tone:var(--fm-warn)}
.fm [data-tone=merged]{--fm-tone:var(--fm-ok)}
.fm [data-tone=rejected],.fm-chip[data-tone=idle]{--fm-tone:var(--ui-text-quaternary)}
.fm-head{display:flex;flex-direction:column;gap:6px;padding:11px 14px 10px;border-bottom:1px solid var(--ui-stroke-tertiary)}
.fm-head-row{display:flex;align-items:baseline;gap:8px;min-width:0}
.fm-title{margin:0;font-size:13px;font-weight:600;line-height:1.2;color:var(--ui-text-primary)}
.fm-sub{min-width:0;margin:0;overflow:hidden;text-overflow:ellipsis;font-size:10.5px;color:var(--ui-text-quaternary);white-space:nowrap}
.fm-stale{margin-left:auto;font-size:10.5px;color:var(--ui-text-quaternary);white-space:nowrap}
.fm-counts{display:flex;flex-wrap:wrap;gap:3px 12px;margin:0;padding:0;list-style:none}
.fm-counts:empty{display:none}
.fm-count{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--ui-text-secondary);white-space:nowrap}
.fm-count::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--fm-tone)}
.fm-scroll{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;padding:4px 12px 18px;display:flex;flex-direction:column}
.fm-list{display:flex;flex-direction:column;gap:8px}
.fm-group-label{margin:10px 2px 0;font-size:10.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--ui-text-quaternary)}
.fm-group-toggle{align-self:flex-start;display:flex;align-items:center;gap:6px;margin:0;padding:2px;background:none;border:0;border-radius:4px;font:inherit;font-size:10.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--ui-text-quaternary);cursor:pointer;text-align:left}
.fm-group-toggle:hover{color:var(--ui-text-secondary)}
.fm-group-toggle:focus-visible,.fm-st:focus-visible,.fm-chip:focus-visible{outline:2px solid var(--ui-accent);outline-offset:2px}
.fm-caret{display:inline-block;font-size:13px;line-height:1;transition:transform .2s ease}
.fm-caret[data-open=true]{transform:rotate(90deg)}
.fm-cards{display:flex;flex-direction:column;gap:8px}
.fm-card{position:relative;padding:10px 12px 12px;border:1px solid var(--ui-stroke-tertiary);border-radius:8px;background:var(--ui-bg-quinary);animation:fm-enter .26s ease-out both}
.fm-card[data-tone=owner]{border-color:color-mix(in srgb,var(--fm-act) 42%,var(--ui-stroke-tertiary));box-shadow:0 0 0 3px color-mix(in srgb,var(--fm-act) 9%,transparent)}
.fm-card[data-tone=blocked]{border-color:color-mix(in srgb,var(--fm-bad) 38%,var(--ui-stroke-tertiary))}
.fm-card[data-tone=bounced]{border-color:color-mix(in srgb,var(--fm-warn) 42%,var(--ui-stroke-tertiary))}
.fm-card[data-compact=true]{padding:8px 12px 6px;background:transparent}
.fm-card[data-compact=true] .fm-name{font-size:12px;-webkit-line-clamp:1}
.fm-meta{display:flex;align-items:center;gap:6px;min-width:0;font-size:11px;color:var(--ui-text-tertiary)}
.fm-repo{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--font-mono,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace);font-size:10.5px}
.fm-ref{flex:0 1 auto;min-width:0;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--font-mono,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace);font-size:10.5px;color:var(--ui-text-secondary)}
.fm-pill{flex-shrink:0;margin-left:auto;padding:1px 8px;border-radius:999px;font-size:10.5px;font-weight:600;line-height:16px;white-space:nowrap;color:var(--fm-tone);background:color-mix(in srgb,var(--fm-tone) 12%,transparent);border:1px solid color-mix(in srgb,var(--fm-tone) 28%,transparent);animation:fm-pop .45s ease-out both}
.fm-ref[data-pr=true]{flex-shrink:0;max-width:none}
.fm-name{margin:4px 0 0;font-size:13px;font-weight:500;line-height:1.35;color:var(--ui-text-primary);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}
.fm-line{position:relative;margin:10px -4px 0;padding-top:24px}
.fm-track,.fm-seg{position:absolute;top:36px;height:2px;border-radius:2px}
.fm-track{left:10%;right:10%;background:var(--ui-stroke-secondary)}
.fm-seg{width:20%;transition:background-color .35s ease}
.fm-seg[data-s=done]{background:color-mix(in srgb,var(--fm-ok) 75%,transparent)}
.fm-seg[data-s=bounce]{background-image:repeating-linear-gradient(90deg,var(--fm-warn) 0 6px,transparent 6px 10px);background-size:20px 2px;animation:fm-flow-back .9s linear infinite}
.fm-stations{position:relative;z-index:1;display:grid;grid-template-columns:repeat(5,minmax(0,1fr))}
.fm-st{--fm-c:var(--ui-text-quaternary);display:flex;flex-direction:column;align-items:center;gap:2px;min-width:0;padding:0 1px 2px;border-radius:6px;outline:none}
.fm-st[data-kind=ok]{--fm-c:var(--fm-ok)}
.fm-st[data-kind=bad]{--fm-c:var(--fm-bad)}
.fm-st[data-kind=warn]{--fm-c:var(--fm-warn)}
.fm-st[data-kind=error]{--fm-c:var(--fm-err)}
.fm-st[data-kind=active]{--fm-c:var(--fm-act)}
.fm-st[data-kind=idle]{--fm-c:var(--ui-text-tertiary)}
.fm-dot{position:relative;display:grid;place-items:center;width:26px;height:26px;border-radius:50%;color:var(--fm-c);border:1.5px solid var(--fm-c);background:color-mix(in srgb,var(--fm-c) 14%,var(--ui-bg-editor))}
.fm-st[data-kind=idle] .fm-dot{border-color:var(--ui-stroke-primary);background:var(--ui-bg-editor)}
.fm-st[data-kind=skip] .fm-dot,.fm-st[data-kind=unknown] .fm-dot{border-style:dashed;background:var(--ui-bg-editor)}
.fm-st[data-active=true] .fm-dot::after{content:"";position:absolute;inset:-5px;border-radius:50%;border:2px solid var(--fm-c);opacity:0;animation:fm-pulse 1.9s ease-out infinite}
.fm-st-name{margin-top:2px;font-size:11px;font-weight:600;line-height:1.2;color:var(--ui-text-secondary);white-space:nowrap}
.fm-st-word{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10px;line-height:1.2;color:var(--ui-text-tertiary)}
.fm-st[data-kind=ok] .fm-st-word,.fm-st[data-kind=bad] .fm-st-word,.fm-st[data-kind=active] .fm-st-word,.fm-st[data-kind=error] .fm-st-word{color:color-mix(in srgb,var(--fm-c) 82%,var(--ui-text-primary));font-weight:600}
.fm-st[data-kind=warn] .fm-st-word{color:color-mix(in srgb,var(--fm-c) 70%,var(--ui-text-primary));font-weight:600}
.fm-token{position:absolute;z-index:2;top:0;left:calc(10% + var(--fm-pos) * 20%);display:flex;flex-direction:column;align-items:center;transform:translateX(-50%);pointer-events:none;transition:left .5s cubic-bezier(.3,.7,.2,1)}
.fm-token[data-dir=back]{transition-duration:.75s;transition-timing-function:cubic-bezier(.5,0,.2,1)}
.fm-token-chip{max-width:76px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:0 7px;border-radius:999px;font-size:10px;font-weight:700;line-height:16px;color:var(--fm-tone);background:color-mix(in srgb,var(--fm-tone) 16%,var(--ui-bg-editor));border:1px solid color-mix(in srgb,var(--fm-tone) 55%,transparent)}
.fm-token-tip{width:0;height:0;margin-top:-1px;border-left:4px solid transparent;border-right:4px solid transparent;border-top:4px solid color-mix(in srgb,var(--fm-tone) 55%,transparent)}
.fm-body{display:grid;grid-template-columns:minmax(0,1fr);gap:8px;margin-top:10px}
.fm-body:empty{display:none}
.fm-details,.fm-events{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:4px}
.fm-detail{--fm-c:var(--ui-text-tertiary);display:flex;align-items:flex-start;gap:6px;font-size:11.5px;line-height:1.4;color:var(--ui-text-secondary);overflow-wrap:anywhere}
.fm-detail .fm-glyph{flex-shrink:0;margin-top:2px;color:var(--fm-c)}
.fm-detail[data-kind=ok]{--fm-c:var(--fm-ok)}
.fm-detail[data-kind=bad]{--fm-c:var(--fm-bad)}
.fm-detail[data-kind=warn]{--fm-c:var(--fm-warn)}
.fm-detail[data-kind=error]{--fm-c:var(--fm-err)}
.fm-detail b{font-weight:600;color:var(--ui-text-primary)}
.fm-events{padding-left:8px;border-left:1px solid var(--ui-stroke-tertiary)}
.fm-event{display:flex;gap:8px;font-size:11px;line-height:1.4;color:var(--ui-text-tertiary)}
.fm-event-at{flex-shrink:0;width:52px;color:var(--ui-text-quaternary);font-variant-numeric:tabular-nums}
.fm-event-text{min-width:0;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
.fm-actions-wrap{margin-top:10px}
.fm-actions{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.fm-hint{margin:6px 0 0;font-size:10.5px;color:var(--ui-text-quaternary)}
.fm-empty{display:flex;flex-direction:column;align-items:center;gap:8px;margin:auto;padding:28px 12px;max-width:340px;text-align:center}
.fm-empty-title{margin:4px 0 0;font-size:13px;font-weight:600;color:var(--ui-text-primary)}
.fm-empty-text{margin:0 0 6px;font-size:11.5px;line-height:1.5;color:var(--ui-text-tertiary)}
.fm-note{margin:6px 0 0;font-size:10.5px;color:var(--ui-text-quaternary)}
.fm-mini{display:flex;align-items:center;color:var(--ui-text-quaternary)}
.fm-mini-st{display:flex;align-items:center}
.fm-mini-dot{display:grid;place-items:center;width:24px;height:24px;border-radius:50%;border:1.5px solid var(--ui-stroke-primary)}
.fm-mini-st:first-child .fm-mini-dot{color:var(--fm-act);border-color:var(--fm-act);animation:fm-glow 2.4s ease-in-out infinite}
.fm-mini-bar{width:22px;height:2px;background:var(--ui-stroke-secondary)}
.fm-loading{display:flex;flex-direction:column;gap:8px}
.fm-skel{display:flex;flex-direction:column;gap:8px;padding:12px;border:1px solid var(--ui-stroke-tertiary);border-radius:8px}
.fm-skel-bar,.fm-skel-line{display:block;height:9px;border-radius:4px;background:linear-gradient(90deg,var(--ui-bg-quaternary),var(--ui-bg-secondary),var(--ui-bg-quaternary));background-size:200% 100%;animation:fm-shimmer 1.4s linear infinite}
.fm-skel-short{width:45%}
.fm-skel-line{height:26px;margin-top:6px;border-radius:13px}
.fm-chip{display:inline-flex;align-items:center;gap:5px;height:100%;padding:0 6px;border:0;border-radius:4px;background:none;font:inherit;font-size:11px;line-height:1;color:var(--ui-text-tertiary);cursor:pointer;white-space:nowrap}
.fm-chip:hover{color:var(--ui-text-secondary);background:var(--ui-control-hover-background)}
.fm-chip-dot{width:6px;height:6px;border-radius:50%;background:var(--fm-tone,var(--ui-text-quaternary))}
.fm-chip[data-tone=owner] .fm-chip-text{color:var(--ui-text-secondary)}
.fm-chip[data-tone=owner] .fm-chip-dot{animation:fm-blink 2.2s ease-in-out infinite}
@keyframes fm-enter{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@keyframes fm-pop{0%{transform:scale(.92);opacity:.4}60%{transform:scale(1.04);opacity:1}100%{transform:none}}
@keyframes fm-pulse{0%{transform:scale(.82);opacity:.6}100%{transform:scale(1.32);opacity:0}}
@keyframes fm-flow-back{to{background-position:-20px 0}}
@keyframes fm-shimmer{to{background-position:-200% 0}}
@keyframes fm-blink{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes fm-glow{0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--fm-act) 0%,transparent)}50%{box-shadow:0 0 0 4px color-mix(in srgb,var(--fm-act) 18%,transparent)}}
@container (min-width: 600px){
  .fm-body{grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:16px}
  .fm-line{width:min(100%,620px);margin-left:auto;margin-right:auto}
}
.fm[data-motion=reduce] *,.fm[data-motion=reduce] *::after{animation:none!important;transition:none!important}
@media (prefers-reduced-motion: reduce){.fm *,.fm *::after,.fm-chip *{animation:none!important;transition:none!important}}
`

// ─── registration ─────────────────────────────────────────────────────────────────────────────────────────────────

export default {
  id: ID,
  name: 'Foreman',
  register(ctx) {
    // Idempotent: a reload disposes the previous incarnation first, but a copy left by a module the host could not
    // unload must not stack, so the one style element is found by its id and replaced.
    // Nothing before registerMany may throw: a throw in register() makes the host roll back every contribution, the
    // pane included, and a pane that is not registered is the one thing layout adoption cannot put back.
    safe(() => {
      if (typeof document === 'undefined') return
      document.getElementById(STYLE_ID)?.remove()
      const style = document.createElement('style')
      style.id = STYLE_ID
      style.setAttribute('data-plugin', ID)
      style.textContent = CSS
      document.head.append(style)
      ctx.onDispose(() => style.remove())
    }, null)

    const store = atom({ phase: 'loading', snapshot: null, error: null })
    let refreshNow = () => Promise.resolve()
    const refresh = () => refreshNow()

    ctx.registerMany([
      {
        id: PANE_ID,
        area: PANES_AREA,
        title: 'Foreman',
        data: { placement: 'right', width: '380px' },
        render: () => jsx(Guard, { children: jsx(Panel, { ctx, store, refresh }) })
      },
      {
        id: 'chip',
        area: STATUSBAR_AREAS.right,
        order: 140,
        render: () => jsx(Guard, { chip: true, children: jsx(Chip, { ctx, store }) })
      },
      {
        id: 'show',
        area: PALETTE_AREA,
        data: { id: 'foreman.show', label: 'Foreman: show the line', keywords: ['foreman', 'pipeline', 'gate', 'review', 'merge'], run: () => reveal(ctx) }
      }
    ])

    // A remembered dismissal keeps adoption from ever placing the pane again (store.ts adoptContributedPanes skips
    // dismissed ids). For a one-pane plugin the user's own Close turns the plugin off instead of dismissing, so a
    // dismissal of this pane never comes from the user's tab ✕: forget it, so adoption puts the pane back where its
    // placement says, without fronting it or opening a side (host.undismissPane, desktop 0.23).
    safe(() => (typeof host.undismissPane === 'function' ? host.undismissPane(PANE_KEY) : null), null)

    const run = safe(() => startData(ctx, store), null)
    if (typeof run === 'function') refreshNow = run
  }
}
