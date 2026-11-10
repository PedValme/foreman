// A stand-in for the few @hermes/plugin-sdk pieces Foreman's panel uses, so the real desktop/plugin.js runs in a
// plain browser. It is NOT the SDK: Button is a plain <button>, the composer is the fake chat box on the left, toasts
// are the preview's own. What it records (commands sent, drafts, clipboard, links) shows in the chat box.
(function () {
  'use strict'
  var M = window.__PREVIEW_MODULES__
  if (!M) throw new Error('Run build.py first: out/react.js is missing.')
  var React = M.react

  function atom(value) {
    var v = value
    var subs = new Set()
    return {
      get: function () { return v },
      set: function (next) { if (next === v) return; v = next; subs.forEach(function (f) { f(v) }) },
      listen: function (f) { subs.add(f); return function () { subs.delete(f) } },
      subscribe: function (f) { subs.add(f); f(v); return function () { subs.delete(f) } }
    }
  }

  function useValue(store) {
    return React.useSyncExternalStore(function (cb) { return store.listen(cb) }, store.get, store.get)
  }

  function Button(props) {
    var p = Object.assign({}, props)
    var cls = 'pv-btn pv-btn-' + (p.variant || 'default') + ' pv-btn-' + (p.size || 'default') + (p.className ? ' ' + p.className : '')
    delete p.variant; delete p.size; delete p.className
    return React.createElement('button', Object.assign({ type: 'button', className: cls }, p))
  }

  // What the preview page watches.
  var preview = {
    chat: atom([]),          // [{ kind, text }]
    draft: atom(''),
    toasts: atom([]),
    paneVisible: atom(true),
    busy: atom(false)
  }

  function say(kind, text) { preview.chat.set(preview.chat.get().concat([{ kind: kind, text: text, at: Date.now() }]).slice(-8)) }

  var host = {
    state: { busy: preview.busy },
    composer: {
      submit: function (sessionId, text) { say('sent', text); preview.draft.set(''); return true },
      getDraft: function () { return Promise.resolve(preview.draft.get()) },
      setDraft: function (sessionId, text) { preview.draft.set(text); say('draft', text.trim()); return Promise.resolve(true) },
      insertText: function () { return Promise.resolve(false) },
      focus: function () {}
    },
    notify: function (t) {
      var id = Math.random().toString(36).slice(2)
      preview.toasts.set(preview.toasts.get().concat([{ id: id, title: t.title || '', message: t.message || '' }]))
      setTimeout(function () { preview.toasts.set(preview.toasts.get().filter(function (x) { return x.id !== id })) }, 3500)
      return id
    },
    paneVisibility: function () { return preview.paneVisible }
  }

  M['@hermes/plugin-sdk'] = {
    atom: atom,
    useValue: useValue,
    Button: Button,
    host: host,
    PANES_AREA: 'panes',
    PALETTE_AREA: 'palette',
    STATUSBAR_AREAS: { left: 'statusBar.left', right: 'statusBar.right' }
  }

  // A PluginContext with the members the panel uses; every timer and listener is tracked and disposed.
  function createContext(backend) {
    var disposers = []
    var listeners = {}
    var contributions = []
    var storage = {}
    function track(fn) { disposers.push(fn); return fn }
    var ctx = {
      source: 'plugin:foreman',
      register: function (c) { contributions.push(c); return function () {} },
      registerMany: function (cs) { cs.forEach(function (c) { contributions.push(c) }); return function () {} },
      rest: function (path) { return backend(path) },
      onEvent: function (type, fn) {
        (listeners[type] = listeners[type] || []).push(fn)
        return track(function () { listeners[type] = (listeners[type] || []).filter(function (x) { return x !== fn }) })
      },
      onDispose: function (fn) { track(fn) },
      setTimeout: function (fn, ms) { var t = setTimeout(fn, ms); return track(function () { clearTimeout(t) }) },
      setInterval: function (fn, ms) { var t = setInterval(fn, ms); return track(function () { clearInterval(t) }) },
      addEventListener: function (target, type, fn, opts) {
        target.addEventListener(type, fn, opts)
        return track(function () { target.removeEventListener(type, fn, opts) })
      },
      runAction: function (id) { say('action', id); return { ok: true } },
      os: {
        writeClipboard: function (text) { say('clipboard', text); return Promise.resolve(true) },
        openExternal: function (url) { say('link', url); return Promise.resolve(true) }
      },
      storage: {
        get: function (k, d) { return k in storage ? storage[k] : d },
        set: function (k, v) { storage[k] = v },
        remove: function (k) { delete storage[k] }
      }
    }
    return {
      ctx: ctx,
      contributions: contributions,
      emit: function (type, payload) { (listeners[type] || []).slice().forEach(function (fn) { fn({ type: type, payload: payload || {} }) }) },
      dispose: function () { disposers.splice(0).forEach(function (fn) { try { fn() } catch (e) { /* ignore */ } }) }
    }
  }

  window.__PREVIEW_SDK__ = { preview: preview, createContext: createContext, useValue: useValue, atom: atom }
})()
