// Scripted snapshots for the preview, in the exact shape GET /api/plugins/foreman/pipeline returns (what
// foreman/panel_api.py produces from pipeline.json). Each scenario is a list of steps; a step is a snapshot, or
// { off: true } for a backend that answers 404 (Foreman not enabled for the profile).
(function () {
  'use strict'

  function iso(minutesAgo) { return new Date(Date.now() - minutesAgo * 60000).toISOString() }

  function station(name, status, detail, minutesAgo, extra) {
    return Object.assign({ name: name, status: status, detail: detail || '', at: minutesAgo == null ? null : iso(minutesAgo) }, extra || {})
  }

  function item(o) {
    var number = o.number == null ? null : o.number
    var kind = number == null ? 'branch' : 'pr'
    return {
      id: o.repo + (kind === 'pr' ? '#pr:' + number : '#branch:' + o.branch),
      repo: o.repo,
      root: '/home/dev/' + o.repo.split('/')[1],
      target: {
        kind: kind, number: number, branch: o.branch, title: o.title,
        url: kind === 'pr' ? 'https://github.com/' + o.repo + '/pull/' + number : null
      },
      head: 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678',
      stage: o.stage,
      stages: o.stages,
      bounces: o.bounces || 0,
      max_bounces: 3,
      updated: iso(o.updated || 0),
      events: (o.events || []).map(function (e) { return { at: iso(e[0]), text: e[1] } })
    }
  }

  function snap(items, problem) { return { version: 1, items: items, problem: problem || null } }

  var REVIEWER = 'openrouter/qwen3-coder'

  // ── (3) one change down the whole line ──────────────────────────────────────────────────────────────────────────
  function story(step) {
    var base = { repo: 'acme/scheduler', number: 6, branch: 'feat/iso-weeks', title: 'Parse ISO week dates in the scheduler' }
    var opened = [9, 'Agent opened pull request #6']
    var gatePass = [8, 'Gate passed: no skipped, deleted or weakened tests']
    var bounced = [6, 'Review asked for changes: 2 blocking, 1 high. Bounced back to the agent (1/3)']
    var fixed = [3, 'Agent pushed a fix; the gate passed again']
    var reviewPass = [1, 'Review by ' + REVIEWER + ' passed: no blocking findings']
    var steps = [
      { stage: 'gate', updated: 9, stages: [station('gate', 'pending', 'Checking the diff against main', 9), station('review', 'pending'), station('owner', 'pending'), station('merge', 'pending')], events: [opened] },
      { stage: 'review', updated: 8, stages: [station('gate', 'pass', 'Clean: 4 files, 2 tests added', 8), station('review', 'pending', 'Second model is reading the diff', 8, { model: REVIEWER }), station('owner', 'pending'), station('merge', 'pending')], events: [opened, gatePass] },
      { stage: 'bounced', bounces: 1, updated: 6, stages: [station('gate', 'pass', 'Clean: 4 files, 2 tests added', 8), station('review', 'fail', '2 blocking, 1 high: week 53 off by one in parse_iso_week()', 6, { model: REVIEWER }), station('owner', 'pending'), station('merge', 'pending')], events: [opened, gatePass, bounced] },
      { stage: 'review', bounces: 1, updated: 3, stages: [station('gate', 'pass', 'Clean after the fix: 5 files, 3 tests added', 3), station('review', 'pending', 'Second pass on the new head', 3, { model: REVIEWER }), station('owner', 'pending'), station('merge', 'pending')], events: [opened, gatePass, bounced, fixed] },
      { stage: 'awaiting_owner', bounces: 1, updated: 1, stages: [station('gate', 'pass', 'Clean after the fix: 5 files, 3 tests added', 3), station('review', 'pass', 'No blocking findings; 1 note on naming', 1, { model: REVIEWER }), station('owner', 'pending', 'Merge or reject: your call', 1), station('merge', 'pending')], events: [opened, gatePass, bounced, fixed, reviewPass] },
      { stage: 'merged', bounces: 1, updated: 0, stages: [station('gate', 'pass', 'Clean after the fix: 5 files, 3 tests added', 3), station('review', 'pass', 'No blocking findings; 1 note on naming', 1, { model: REVIEWER }), station('owner', 'approved', 'Approved by you', 0), station('merge', 'done', 'squash', 0)], events: [opened, gatePass, bounced, fixed, reviewPass, [0, 'You approved; merged by squash']] }
    ]
    return snap([item(Object.assign({}, base, steps[step]))])
  }

  // ── (2) blocked at the gate ─────────────────────────────────────────────────────────────────────────────────────
  function blocked() {
    return snap([item({
      repo: 'acme/billing', number: 9, branch: 'fix/rounding', title: 'Fix rounding of partial refunds', stage: 'gate', updated: 1,
      stages: [station('gate', 'fail', '1 blocker: test-skipped in tests/test_refunds.py:9', 1), station('review', 'pending'), station('owner', 'pending'), station('merge', 'pending')],
      events: [[4, 'Agent ran git commit'], [1, 'Gate blocked the commit: test skipped in tests/test_refunds.py:9']]
    })])
  }

  // ── (4) several at once (one repository: the panel offers commands only then) ─────────────────────────────────────────────────────────────────────────────────────────
  function several() {
    return snap([
      item({ repo: 'acme/app', number: 3, branch: 'chore/deps', title: 'Bump the date library', stage: 'merged', updated: 240,
        stages: [station('gate', 'pass', '', 300), station('review', 'skipped', 'Review not requested', 300), station('owner', 'approved', '', 240), station('merge', 'done', 'squash', 240)],
        events: [[240, 'Merged by squash']] }),
      item({ repo: 'acme/app', number: 9, branch: 'fix/rounding', title: 'Fix rounding of partial refunds', stage: 'gate', updated: 2,
        stages: [station('gate', 'fail', '1 blocker: test-skipped in tests/test_refunds.py:9', 2), station('review', 'pending'), station('owner', 'pending'), station('merge', 'pending')],
        events: [[2, 'Gate blocked the commit: test skipped in tests/test_refunds.py:9']] }),
      item({ repo: 'acme/app', number: 14, branch: 'feat/rate-limit', title: 'Rate-limit the export endpoint', stage: 'review', updated: 1,
        stages: [station('gate', 'pass', 'Clean', 3), station('review', 'pending', 'Second model is reading the diff', 1, { model: REVIEWER }), station('owner', 'pending'), station('merge', 'pending')],
        events: [[3, 'Gate passed'], [1, 'Review started']] }),
      item({ repo: 'acme/app', number: 12, branch: 'feat/tz', title: 'Store every schedule in UTC', stage: 'awaiting_owner', updated: 5, bounces: 1,
        stages: [station('gate', 'pass', 'Clean', 30), station('review', 'pass', 'No blocking findings', 6, { model: REVIEWER }), station('owner', 'pending', 'Merge or reject: your call', 5), station('merge', 'pending')],
        events: [[40, 'Agent opened pull request #12'], [20, 'Bounced back once: missing DST test'], [6, 'Review passed'], [5, 'Waiting for you']] }),
      item({ repo: 'acme/app', number: null, branch: 'feat/retry-backoff', title: 'Retry failed jobs with exponential backoff', stage: 'bounced', updated: 4, bounces: 2,
        stages: [station('gate', 'pass', 'Clean', 12), station('review', 'fail', '1 blocking: retries never stop on a permanent error', 4, { model: REVIEWER }), station('owner', 'pending'), station('merge', 'pending')],
        events: [[25, 'Bounced back (1/3): no jitter'], [4, 'Bounced back (2/3): retries never stop on a permanent error']] }),
      item({ repo: 'acme/app', number: 4, branch: 'feat/dark-mode', title: 'Dark mode for the settings page', stage: 'rejected', updated: 600,
        stages: [station('gate', 'pass', '', 700), station('review', 'notes', '3 notes', 650, { model: REVIEWER }), station('owner', 'rejected', 'Rejected by you: out of scope', 600), station('merge', 'skipped')],
        events: [[600, 'Rejected with reasons posted on the pull request']] })
    ])
  }

  // ── (5) the edges ───────────────────────────────────────────────────────────────────────────────────────────────
  function edges(step) {
    if (step === 1) return snap([], 'unreadable')
    if (step === 2) return { off: true }
    return snap([
      item({ repo: 'a-very-long-organisation-name/an-even-longer-repository-name-for-the-monorepo', number: 123456,
        branch: 'feature/JIRA-12345-refactor-the-entire-payment-reconciliation-pipeline-to-use-the-new-ledger',
        title: 'Refactor the entire payment reconciliation pipeline to use the new double-entry ledger, migrate the historical data, and remove the legacy batch job that nobody remembers writing',
        stage: 'review', updated: 2,
        stages: [station('gate', 'pass', 'Clean: 87 files, 41 tests added', 4), station('review', 'error', 'The reviewer model timed out after 120 s', 2, { model: 'some-provider/an-extremely-long-model-identifier-preview-2026-11' }), station('owner', 'pending'), station('merge', 'pending')],
        events: [[4, 'Gate passed'], [2, 'Review error: the reviewer model timed out after 120 s']] }),
      item({ repo: 'acme/web', number: null, branch: 'fix/<script>alert(1)</script>', title: '<img src=x onerror="alert(1)"> **not markdown** — shown as text',
        stage: 'gate', updated: 1,
        stages: [station('gate', 'fail', '2 blockers: check-changed in package.json:12; secret in .env.example:3', 1), station('review', 'pending'), station('owner', 'pending'), station('merge', 'pending')],
        events: [[1, 'Gate blocked the push: <b>the check entry point changed</b>']] })
    ])
  }

  window.__PREVIEW_SCENARIOS__ = [
    { id: 1, name: 'Empty', steps: [snap([], 'missing')] },
    { id: 2, name: 'Blocked at the gate', steps: [blocked()] },
    { id: 3, name: 'Gate → review → bounce → owner → merged', steps: [0, 1, 2, 3, 4, 5].map(story) },
    { id: 4, name: 'Several changes', steps: [several()] },
    { id: 5, name: 'Long text, corrupt file, backend off', steps: [0, 1, 2].map(edges) }
  ]
  // Rebuilt on demand so relative times stay fresh.
  window.__PREVIEW_STEP__ = function (scenario, step) {
    if (scenario === 3) return story(step)
    if (scenario === 5) return edges(step)
    return window.__PREVIEW_SCENARIOS__[scenario - 1].steps[step]
  }
})()
