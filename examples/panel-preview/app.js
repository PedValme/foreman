// The preview page: loads the real panel (out/plugin.classic.js, generated from desktop/plugin.js), feeds it the
// scripted snapshots from mock.js through a fake ctx.rest, and plays them. URL hash options, for screenshots:
//   #s=3&step=4&theme=dark&w=360&motion=reduce&still=1&open=1&shot=1&go=5&delay=1500
(function () {
  'use strict'
  if (!window.__PREVIEW_MODULES__ || !window.__FOREMAN_PLUGIN__) {
    document.querySelector('.pv-stage').innerHTML =
      '<p class="pv-missing">The preview is not built yet. Run <code>python examples/panel-preview/build.py</code>, then reload this page.</p>'
    return
  }
  var M = window.__PREVIEW_MODULES__
  var React = M.react
  var createRoot = M['react-dom/client'].createRoot
  var S = window.__PREVIEW_SDK__
  var SC = window.__PREVIEW_SCENARIOS__
  var params = new URLSearchParams(location.hash.slice(1))

  var state = {
    scenario: Math.min(5, Math.max(1, parseInt(params.get('s') || '3', 10) || 3)),
    step: parseInt(params.get('step') || '0', 10) || 0,
    theme: params.get('theme') === 'dark' ? 'dark' : 'light',
    width: params.get('w') || '400',
    reduce: params.get('motion') === 'reduce',
    playing: params.get('still') !== '1'
  }
  if (params.get('shot') === '1') document.documentElement.setAttribute('data-shot', '1')

  // prefers-reduced-motion, switchable from the toolbar (the panel reads it through matchMedia, as in the app).
  var realMatchMedia = window.matchMedia.bind(window)
  var motionListeners = new Set()
  window.matchMedia = function (query) {
    if (query.indexOf('prefers-reduced-motion') < 0) return realMatchMedia(query)
    var real = realMatchMedia(query)
    return {
      media: query,
      get matches () { return state.reduce || real.matches },
      addEventListener: function (type, fn) { motionListeners.add(fn) },
      removeEventListener: function (type, fn) { motionListeners.delete(fn) }
    }
  }

  // The backend: what GET /api/plugins/foreman/pipeline would answer.
  var current = null
  function backend (path) {
    if (path !== '/pipeline') return Promise.reject(new Error('404 Not Found'))
    if (current && current.off) return Promise.reject(new Error('404 Not Found: plugin foreman is not enabled in this profile'))
    return new Promise(function (resolve) { setTimeout(function () { resolve(JSON.parse(JSON.stringify(current))) }, 40) })
  }

  var env = S.createContext(backend)
  if (params.get('open') === '1') env.ctx.storage.set('doneOpen', true)
  current = window.__PREVIEW_STEP__(state.scenario, state.step)
  window.__FOREMAN_PLUGIN__.register(env.ctx)

  var pane = env.contributions.find(function (c) { return c.area === 'panes' })
  var chip = env.contributions.find(function (c) { return c.area === 'statusBar.right' })
  createRoot(document.getElementById('pane')).render(pane.render())
  createRoot(document.getElementById('chip')).render(chip.render())

  // The chat stand-in and toasts.
  function Chat () {
    var chat = S.useValue(S.preview.chat)
    return React.createElement(React.Fragment, null, chat.map(function (m, i) {
      var text = m.kind === 'sent' ? m.text : m.kind === 'draft' ? 'Put in the chat box: ' + m.text
        : m.kind === 'clipboard' ? 'Copied: ' + m.text : m.kind === 'link' ? 'Opened in the browser: ' + m.text : 'App action: ' + m.text
      return React.createElement('div', { key: i, className: 'pv-msg', 'data-kind': m.kind }, text)
    }))
  }
  function Composer () { return S.useValue(S.preview.draft) }
  function Toasts () {
    var toasts = S.useValue(S.preview.toasts)
    return React.createElement(React.Fragment, null, toasts.map(function (t) {
      return React.createElement('div', { key: t.id, className: 'pv-toast', role: 'status' }, t.message)
    }))
  }
  createRoot(document.getElementById('chat')).render(React.createElement(Chat))
  createRoot(document.getElementById('composer')).render(React.createElement(Composer))
  createRoot(document.getElementById('toasts')).render(React.createElement(Toasts))

  // Toolbar.
  function el (id) { return document.getElementById(id) }
  function stepsOf (n) { return SC[n - 1].steps.length }
  function show () {
    current = window.__PREVIEW_STEP__(state.scenario, state.step)
    env.emit('plugin.foreman.pipeline.updated')
    paint()
  }
  function paint () {
    document.documentElement.classList.toggle('dark', state.theme === 'dark')
    el('theme').textContent = state.theme === 'dark' ? 'Light' : 'Dark'
    el('motion').setAttribute('aria-pressed', String(state.reduce))
    el('play').textContent = state.playing ? 'Pause' : 'Play'
    el('pane-frame').style.width = state.width === 'full' ? '100%' : state.width + 'px'
    el('pane-frame').style.flex = state.width === 'full' ? '1' : 'none'
    document.querySelector('.pv-chat').style.display = state.width === 'full' ? 'none' : ''
    Array.prototype.forEach.call(el('scenarios').children, function (b, i) { b.setAttribute('aria-pressed', String(i + 1 === state.scenario)) })
    Array.prototype.forEach.call(el('widths').children, function (b) { b.setAttribute('aria-pressed', String(b.dataset.w === state.width)) })
    el('caption').textContent = 'Scenario ' + state.scenario + ': ' + SC[state.scenario - 1].name + ' · step ' + (state.step + 1) + '/' + stepsOf(state.scenario)
  }
  SC.forEach(function (s) {
    var b = document.createElement('button')
    b.textContent = s.id + '. ' + s.name
    b.onclick = function () { state.scenario = s.id; state.step = 0; show() }
    el('scenarios').appendChild(b)
  })
  ;['360', '400', '520', '900', 'full'].forEach(function (w) {
    var b = document.createElement('button')
    b.textContent = w === 'full' ? 'Full' : w + ' px'
    b.dataset.w = w
    b.onclick = function () { state.width = w; paint() }
    el('widths').appendChild(b)
  })
  el('prev').onclick = function () { state.step = (state.step - 1 + stepsOf(state.scenario)) % stepsOf(state.scenario); show() }
  el('next').onclick = function () { state.step = (state.step + 1) % stepsOf(state.scenario); show() }
  el('play').onclick = function () { state.playing = !state.playing; paint() }
  el('theme').onclick = function () { state.theme = state.theme === 'dark' ? 'light' : 'dark'; paint() }
  el('motion').onclick = function () { state.reduce = !state.reduce; motionListeners.forEach(function (fn) { fn() }); paint() }
  setInterval(function () {
    if (!state.playing || stepsOf(state.scenario) < 2) return
    state.step = (state.step + 1) % stepsOf(state.scenario)
    show()
  }, 2600)
  paint()
  // For a mid-animation screenshot: #...&go=<step>&delay=<ms> switches to that step after the delay.
  if (params.get('go') != null) {
    setTimeout(function () { state.step = parseInt(params.get('go'), 10) || 0; show() }, parseInt(params.get('delay') || '1500', 10))
  }
  // #...&probe=1 records the first token's x position every 100 ms into <body data-probe>, to check the motion
  // with `--dump-dom` (no screenshot needed).
  if (params.get('probe') === '1') {
    var samples = []
    setInterval(function () {
      var token = document.querySelector('.fm-token')
      samples.push(token ? Math.round(token.getBoundingClientRect().left) : -1)
      document.body.setAttribute('data-probe', samples.join(','))
    }, 100)
  }
})()
