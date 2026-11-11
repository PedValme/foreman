# Improvement after the hackathon: the native model picker in Foreman's settings

The owner wants Foreman's own settings in Hermes Desktop to offer a model picker like Hermes's native one: any
provider or subscription and any model, the ones already configured first (2026-11-11). Today the pick is made in
Desktop → Settings → Models → Auxiliary → "Foreman review" (Hermes's own picker; works), and Foreman's settings page
shows only two free-text fields. Research of 2026-11-11 against Hermes v0.23.x (`2bd378ed1b`), read-only:

## What exists (evidence in the Hermes clone)
- `ModelCatalogMenu` + `ModelMenuController` + `ModelMenuCloseContext` are exported by `@hermes/plugin-sdk`
  (`apps/desktop/src/sdk/index.ts:1656-1667`; the bundled kanban plugin uses them in `plugins/kanban/
  model-override.tsx`). Same searchable, provider-grouped picker as the composer. Not in the docs' export table.
- Its data: gateway RPC `model.options` via `host.request` (public: "the same JSON-RPC the app itself uses",
  desktop-plugin-sdk.md:50); with `explicit_only` it lists the providers the user configured, the main model marked.
  The native Auxiliary picker shows the same list; it does not list unconfigured providers either.
- A plugin can own a settings page: `ctx.registerSettingsPage` (desktop-plugin-sdk.md:193, 1005-1030); with a
  `config_schema` too, the schema form becomes its "Agent settings" sub-page.
- Saving Foreman's own settings: `host.request('plugins.manage', {action:'settings', key:'foreman', values})`
  (public; same writer as the schema form).
- No public way for a plugin to write `auxiliary.foreman_review` (`config.set` refuses `auxiliary.*`; the native
  row saves through `POST /api/model/set`, reachable only through `window.hermesDesktop`, which catalog rule 8 forbids).

## Plan (v1, public surfaces only; about 1 to 1.5 days)
- `plugin/desktop/plugin.js`: a settings page "Foreman" with `ListRow` "Reviewer model" → `DropdownMenu` →
  `ModelCatalogMenu` (controller writes `reviewer_model` / `reviewer_provider` through `plugins.manage settings`;
  refuses custom-endpoint rows, which `ctx.llm` cannot select); a header "Used in this Hermes" (main, fallbacks,
  auxiliary picks); a line "Reviewer now: X (from Models → Auxiliary / from this setting)"; a reset to "Hermes's
  auxiliary pick"; a link to the native row. Namespace import of the SDK and feature detection.
- `plugin/dashboard/plugin_api.py`: `GET /reviewer` → `{effective, used, settings}`, from one resolver shared with
  `review.choose_model` / `task_route` so the page and the review cannot disagree.
- Tests: jsdom sequences (one write per pick, custom rows refused, reset, refresh on `settings.changed`, no throw on
  an older host, dispose); Python for `/reviewer` and parity with `choose_model`; `hermes plugins validate` clean.
- Costs of v1: two places for one choice until Hermes adds the seam below (the page says which one is in effect);
  the setting needs the override capabilities; profile scope of `host.request` to verify.
- When Hermes adds the seam: write `auxiliary.foreman_review` instead and retire `reviewer_model` (about half a day).

## The Hermes seam (also in `hermes-issue-seams.md`)
A `config_schema` field type `auxiliary_model` with `task:` (rendered with the native picker, saved to
`auxiliary.<task>`), or a gateway method / SDK verb `ctx.models.setAuxiliary(task, route)` limited to the calling
plugin's own tasks; plus `ModelCatalogMenu` listed in the SDK docs.
