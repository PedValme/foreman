# Improvement after the hackathon: the native model picker in Foreman's settings

The owner wants Foreman's own settings in Hermes Desktop to offer a model picker like Hermes's native one: any
provider or subscription and any model, the ones already configured first (2026-11-11). Today the pick is made in
Desktop → Settings → Models → Auxiliary → "Foreman review" (Hermes's own picker; works), and Foreman's settings page
shows only two free-text fields. Research of 2026-11-11 against Hermes v0.23.x (`2bd378ed1b`), read-only:

## Read again on 2026-11-25 against Hermes v0.23.3 (`caafe5389a`): asked of the owner before building
The plan below still holds in its parts: `ModelCatalogMenu`, `ModelMenuController` and `ModelMenuCloseContext` are
exported (`apps/desktop/src/sdk/index.ts:1654-1669`, source only), the menu fetches `model.options` by itself, the
working example moved to `apps/desktop/src/plugins/kanban/model-override.tsx`, `ctx.registerSettingsPage` and
`plugins.manage` with `action: 'settings'` are as described, a plugin reads its own settings from `plugins.manage`
with `action: 'list'` (`settings_schema[].value`) and hears `plugin.foreman.settings.changed`. There is still no
public write to `auxiliary.<task>` (`config.set` answers 4002, "unknown config key") and no `config_schema` field
of a model type.

What that means for the person, which the plan understated: the pick this page can save is Foreman's own
`reviewer_model`, and `review.choose_model` uses it only when the operator has granted
`plugins.entries.foreman.llm.allow_model_override` (and `allow_provider_override` for another provider). Without
the grant the review runs on the host's model and says so in a note. So on a default install a picker that looks
native would not take effect, while Models → Auxiliary → "Foreman review" does, with no grant.

Recommended to the owner on 2026-11-25, and waiting for his answer: not in the catalog update to 0.2.0; one
focused issue to Hermes for the seam below (it is section 6 of #153841, whose maintainer asked for one issue per
seam), sent under his account after he reads it. The alternatives he was given: a light page (which model
reviews now and where the pick comes from, with a button to the native picker), or the plan below as it is, with
a warning when the grant is missing.

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
