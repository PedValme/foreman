// The Desktop panel through the sequences that hid it in the real app: navigation while a refresh is in flight, the
// REST call failing after a success, two commands sent quickly, a click with no chat box on screen, dispose and
// re-register, the status-bar chip, a render error, and a failed review with no bounce. Run by
// test_desktop_panel_sequences.py: node <this> <node_modules> <out dir with react.js and plugin.classic.js> <shim.js>
'use strict'
const fs = require('fs')
const path = require('path')

const [nodeModules, outDir, shimFile] = process.argv.slice(2)
const { JSDOM } = require(path.join(nodeModules, 'jsdom'))

const dom = new JSDOM('<!doctype html><html><head></head><body></body></html>', { runScripts: 'outside-only', pretendToBeVisual: true })
const w = dom.window
w.eval(fs.readFileSync(path.join(outDir, 'react.js'), 'utf8'))
w.eval(fs.readFileSync(shimFile, 'utf8'))
w.eval(fs.readFileSync(path.join(outDir, 'plugin.classic.js'), 'utf8'))

const M = w.__PREVIEW_MODULES__
const S = w.__PREVIEW_SDK__
const host = M['@hermes/plugin-sdk'].host
const plugin = w.__FOREMAN_PLUGIN__
const { createRoot } = M['react-dom/client']
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

const failures = []
const uncaught = []
function check(name, ok, detail) {
  if (!ok) failures.push(`${name}${detail ? ': ' + detail : ''}`)
}
w.addEventListener('error', e => uncaught.push(String(e.error || e.message)))

function station(name, status, detail) { return { name, status, detail: detail || '', at: null } }
function item(number, o) {
  return Object.assign({
    id: `acme/app#pr:${number}`, repo: 'acme/app', root: '/w/app',
    target: { kind: 'pr', number, branch: `feat/${number}`, title: `Change ${number}`, url: null },
    head: 'a'.repeat(40), stage: 'gate', bounces: 0, max_bounces: 3, updated: new Date().toISOString(),
    stages: [station('gate', 'fail', '1 blocker'), station('review', 'pending'), station('owner', 'pending'), station('merge', 'pending')],
    events: [{ at: new Date().toISOString(), text: 'Gate blocked the commit' }]
  }, o || {})
}
const snap = items => ({ version: 1, items, problem: null })
const TWO = snap([item(6), item(7)])

function reset() {
  S.preview.chat.set([])
  S.preview.draft.set('')
  S.preview.toasts.set([])
  S.preview.paneVisible.set(true)
  host.composer.submit = (sessionId, text) => { S.preview.chat.set(S.preview.chat.get().concat([{ kind: 'sent', text }])); return true }
  host.composer.setDraft = (sessionId, text) => { S.preview.draft.set(text); S.preview.chat.set(S.preview.chat.get().concat([{ kind: 'draft', text: text.trim() }])); return Promise.resolve(true) }
  delete host.revealPane
}
const kinds = kind => S.preview.chat.get().filter(m => m.kind === kind).map(m => m.text)
const toasts = () => S.preview.toasts.get().map(t => t.message).join(' | ')

function mount(backend) {
  const env = S.createContext(backend)
  plugin.register(env.ctx)
  const pane = env.contributions.find(c => c.area === 'panes')
  const chip = env.contributions.find(c => c.area === 'statusBar.right')
  const paneEl = w.document.createElement('div')
  const chipEl = w.document.createElement('div')
  w.document.body.append(paneEl, chipEl)
  const onUncaughtError = error => uncaught.push(String(error && error.message))
  const roots = [createRoot(paneEl, { onUncaughtError }), createRoot(chipEl, { onUncaughtError })]
  roots[0].render(pane.render())
  roots[1].render(chip.render())
  const element = pane.render()
  const store = element.props.store || element.props.children.props.store
  return {
    env, paneEl, chipEl, store,
    text: () => paneEl.textContent,
    buttons: label => [...paneEl.querySelectorAll('button')].filter(b => b.textContent.includes(label)),
    unmount() { roots.forEach(r => r.unmount()); env.dispose(); paneEl.remove(); chipEl.remove() }
  }
}

async function restFailsAfterSuccess() {
  reset()
  let fail = false
  const m = mount(() => (fail ? Promise.reject(new Error('401 Unauthorized')) : Promise.resolve(JSON.parse(JSON.stringify(TWO)))))
  await sleep(80)
  check('rest: first answer drawn', m.text().includes('Change 6'), m.text().slice(0, 200))
  fail = true
  m.env.emit('plugin.foreman.pipeline.updated')
  await sleep(80)
  check('rest: cards stay after a failure', m.text().includes('Change 6') && m.text().includes('Change 7'))
  check('rest: says reconnecting', m.text().includes('reconnecting'))
  fail = false
  m.env.emit('message.complete')
  await sleep(80)
  check('rest: recovers', !m.text().includes('reconnecting'))
  m.unmount()
}

async function navigationWhileRefreshing() {
  reset()
  let release = null
  let calls = 0
  const m = mount(() => {
    calls += 1
    if (calls === 1) return Promise.resolve(JSON.parse(JSON.stringify(TWO)))
    return new Promise(resolve => { release = () => resolve(JSON.parse(JSON.stringify(TWO))) })
  })
  await sleep(80)
  m.env.emit('plugin.foreman.pipeline.updated') // a refresh now in flight
  // The main area turns into a page (no chat box on screen) and the pane is hidden and shown again meanwhile.
  host.composer.submit = () => false
  S.preview.paneVisible.set(false)
  S.preview.paneVisible.set(true)
  m.env.emit('plugin.foreman.pipeline.updated')
  const verdict = m.buttons('Show verdict')
  check('nav: buttons are there', verdict.length === 2, String(verdict.length))
  verdict[0].click()
  await sleep(30)
  // No chat box on screen: the clipboard, never a hidden chat's draft, never a navigation.
  check('nav: copied, not sent nor drafted', kinds('clipboard').some(t => /^\/foreman verdict [67] --repo acme\/app$/.test(t)) &&
    kinds('sent').length === 0 && kinds('draft').length === 0, JSON.stringify(S.preview.chat.get()))
  check('nav: toast says why', toasts().includes('No chat on screen'), toasts())
  check('nav: no app action ran', kinds('action').length === 0)
  release && release()
  await sleep(50)
  check('nav: still drawn', m.text().includes('Change 7') && m.store.get().phase === 'ready')
  check('nav: still no app action', kinds('action').length === 0)
  m.unmount()
}

async function doubleSubmit() {
  reset()
  await sleep(1600) // past the repeat window of the clicks in the previous sequence
  const m = mount(() => Promise.resolve(JSON.parse(JSON.stringify(TWO))))
  await sleep(80)
  const [a, b] = m.buttons('Show verdict')
  a.click(); b.click(); a.click()
  await sleep(30)
  check('double: a repeat click is one command, two cards two', kinds('sent').length === 2, JSON.stringify(kinds('sent')))
  check('double: the right commands', kinds('sent').slice().sort().join() ===
    '/foreman verdict 6 --repo acme/app,/foreman verdict 7 --repo acme/app', kinds('sent').join())
  check('double: pane intact', m.text().includes('Change 6'))
  m.unmount()
}

async function disposeAndRegisterAgain() {
  reset()
  const styles = () => w.document.querySelectorAll('style#foreman-plugin-style').length
  let release = null
  let first = true
  const m = mount(() => {
    if (first) { first = false; return new Promise(resolve => { release = () => resolve(JSON.parse(JSON.stringify(TWO))) }) }
    return Promise.resolve(JSON.parse(JSON.stringify(TWO)))
  })
  check('dispose: one style element', styles() === 1, String(styles()))
  const store = m.store
  m.unmount() // disabled while its first request is still out
  check('dispose: style removed', styles() === 0, String(styles()))
  release()
  await sleep(30)
  check('dispose: a late answer writes nothing', store.get().phase === 'loading', store.get().phase)
  // Registered twice without a dispose in between (a module the host could not unload): still one style element.
  const a = mount(() => Promise.resolve(JSON.parse(JSON.stringify(TWO))))
  const b = mount(() => Promise.resolve(JSON.parse(JSON.stringify(TWO))))
  check('register twice: one style element', styles() === 1, String(styles()))
  await sleep(80)
  check('register again: draws', b.text().includes('Change 6'))
  check('register: forgets a stale dismissal of its pane', S.preview.undismissed.every(id => id === 'foreman:pane') &&
    S.preview.undismissed.length >= 3, JSON.stringify(S.preview.undismissed))
  a.unmount(); b.unmount()
  // A host member that throws during register() must not stop the pane from registering (a throw there rolls back
  // every contribution, and an unregistered pane is the one layout adoption cannot put back).
  const saved = host.paneVisibility
  host.paneVisibility = () => { throw new Error('host broke') }
  const env = S.createContext(() => Promise.resolve(JSON.parse(JSON.stringify(TWO))))
  let threw = null
  try { plugin.register(env.ctx) } catch (err) { threw = err }
  host.paneVisibility = saved
  check('register: never throws', threw === null, String(threw))
  check('register: pane registered anyway', env.contributions.some(c => c.area === 'panes' && c.id === 'pane'))
  env.dispose()
}

async function chipBringsThePaneForward() {
  reset()
  const m = mount(() => Promise.resolve(JSON.parse(JSON.stringify(TWO))))
  await sleep(80)
  check('chip: counts', m.chipEl.textContent.includes('2 blocked'), m.chipEl.textContent)
  S.preview.paneVisible.set(false)
  const revealed = []
  host.revealPane = id => { revealed.push(id); S.preview.paneVisible.set(true) }
  m.chipEl.querySelector('button').click()
  await sleep(400)
  check('chip: revealPane with the scoped id', revealed.join() === 'foreman:pane', revealed.join())
  check('chip: no toast when it worked', toasts() === '', toasts())
  check('chip: never toggles a sidebar', kinds('action').length === 0, JSON.stringify(kinds('action')))
  delete host.revealPane
  S.preview.paneVisible.set(false)
  m.chipEl.querySelector('button').click()
  await sleep(30)
  check('chip: older desktop gets a precise toast', toasts().includes('Ctrl+J') && toasts().includes('Capabilities'), toasts())
  check('chip: still no app action', kinds('action').length === 0)
  m.unmount()
}

async function renderErrorStaysInside() {
  reset()
  const odd = snap([null, 5, { id: 9, stage: 'gate', target: { kind: 'pr', number: 9, title: { x: 1 } }, stages: 'x',
    events: [{ text: { a: 1 } }, null] }])
  const m = mount(() => Promise.resolve(odd))
  await sleep(80)
  check('odd data: drawn without an error', !m.text().includes('hit an error') && uncaught.length === 0, m.text().slice(0, 200))
  const boom = {}
  Object.defineProperty(boom, 'stage', { enumerable: true, get() { throw new Error('boom') } })
  m.store.set({ phase: 'ready', snapshot: snap([boom]), error: null })
  await sleep(30)
  check('throw: the panel shows its reload card', m.text().includes('Foreman panel hit an error'), m.text().slice(0, 200))
  check('throw: the chip shows its reload state', m.chipEl.textContent.includes('reload'), m.chipEl.textContent)
  check('throw: nothing reached the host', uncaught.length === 0, uncaught.join())
  m.store.set({ phase: 'ready', snapshot: JSON.parse(JSON.stringify(TWO)), error: null })
  m.buttons('Reload')[0].click()
  await sleep(30)
  check('throw: reload draws again', m.text().includes('Change 6'), m.text().slice(0, 200))
  m.unmount()
}

async function failedReviewWithoutBounce() {
  reset()
  const it = item(8, { stage: 'bounced', bounces: 0,
    stages: [station('gate', 'pass', 'Clean'), station('review', 'fail', '1 blocking'), station('owner', 'pending'), station('merge', 'refused', 'review found blocking problems')] })
  const m = mount(() => Promise.resolve(snap([it])))
  await sleep(80)
  const text = m.text()
  check('no bounce: reads Review failed', text.includes('Review failed'), text.slice(0, 300))
  check('no bounce: no bounce wording', !/Bounced back|fixing|0\/3/.test(text), text.slice(0, 300))
  check('no bounce: token at Review', m.paneEl.querySelector('.fm-token').style.getPropertyValue('--fm-pos') === '2')
  check('no bounce: no dashed track', !m.paneEl.querySelector('.fm-seg[data-s=bounce]'))
  m.unmount()
  reset()
  const real = mount(() => Promise.resolve(snap([Object.assign({}, it, { bounces: 1 })])))
  await sleep(80)
  check('one bounce: still Bounced back', real.text().includes('Bounced back · 1/3'), real.text().slice(0, 300))
  real.unmount()
}

;(async () => {
  for (const run of [restFailsAfterSuccess, navigationWhileRefreshing, doubleSubmit, disposeAndRegisterAgain,
    chipBringsThePaneForward, renderErrorStaysInside, failedReviewWithoutBounce]) {
    try {
      await run()
    } catch (err) {
      failures.push(`${run.name} threw: ${err && err.stack}`)
    }
  }
  check('no uncaught error anywhere', uncaught.length === 0, uncaught.join(' | '))
  if (failures.length) {
    console.log(failures.join('\n'))
    process.exit(1)
  }
  console.log('ok')
  process.exit(0)
})()
