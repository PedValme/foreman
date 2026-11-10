# Decisions

One line per owner decision that still holds: `YYYY-MM-DD · decision · the owner's words or the reason`. When one
replaces another, delete the old line and say "replaces …". A decision the agent assumed is marked `(assumed)` until
the owner confirms it. An option the owner turned down is a decision too and stays:
`YYYY-MM-DD · rejected: what · the reason, with the owner's words`; proposing it again needs a new fact.

- 2026-11-09 · Enter the Hermes Agent Plugin Hackathon (closes 2026-11-11 17:00 EST) with Foreman: test-integrity
  gate inside the agent loop, ported from fábrica's `detector.py`, with hermes-security's SARIF as an optional source
  and a CI mode · Pedro: «Hagámoslo, no perdemos nada».
- 2026-11-09 · Public repository `PedValme/foreman`, MIT licence, category «en construcción», created with Pedro's
  account · Pedro: «ok crealo tu autorizo que usenos mi cuenta».
- 2026-11-09 · UX is part of the strategy: the plugin makes it easy to pick the repository, see branches, issues,
  pull requests and which issue each pull request closes, and to merge or reject with reasons, as guardia does ·
  Pedro: «que el plugin facilite la identificación del repo que el usuario quiera trabajar, ramas, issues, PRs,
  relación entre PRs e issues, fusión o rechazo con motivos como lo hace ahora guardia». Narrowed the same day to UX
  in the chat and terminal, no Desktop panel required · Pedro: «me exprese mal enfoque en UX no UI, puede ser TUI de
  hecho, mejor».
- 2026-11-09 · Slash commands never collide with Hermes's native ones, and every hackathon and catalog rule is
  respected · Pedro: «que los comandos con / no se crucen con los nativos de Hermes y respetemos todas la reglas de
  la hackathon». Agent's adjustment, accepted by Pedro («ok»): a single `/foreman` command with subcommands.
- 2026-11-09 · The plugin includes a guardia: a model reviewer, on a model different from the main one, defaulting
  to the failover model the user has configured in Hermes · Pedro: «podemos uncluir un guardia coml partr del
  plugin, o no?? con sugerencia de uso a un modelo diferente del principal, podria tomar por defecto el de failover
  de hermes quebtebga configurado el usuario».
- 2026-11-09 · A false-positive marker never passes alone: it escalates to the user's approval. A merge runs through
  the agent's terminal tool and Hermes's native approval; without `gh` the plugin still works on local git · agent's
  proposal (catalog rules 11 and 12), Pedro: «ok entonces?» answered as accepted with the rest of the list.
- 2026-11-09 · Test on Linux, macOS and Windows with GitHub Actions, and also on Pedro's own Hermes instance;
  the YOLO-mode behaviour is tested when we reach it · Pedro: «lo probamos cuanfo lleguemos» and «tambien … probar
  como te decia en mi instancia de hermes».
- 2026-11-10 · DECISIONES.md and ESTADO.md stay public in this repository; how the owner's machines are reached is
  kept out of it · Pedro: «déjalos públicos, limpia lo del ssh y sigue».
- 2026-11-09 · Demo video: the agent writes the script and the recording instructions (orientation, camera, tool)
  according to the rules and does the editing; Pedro records and publishes on X · Pedro: «guion e indicaciones de
  grabacion … tu haces la edicion!».
- 2026-11-09 · rejected: OnBrand (brand and content plugin) · the catalog entry `on-brand` (2026-11-09) already
  covers its name and its blocking linter, and its plan needed six days; Pedro chose Foreman.
- 2026-11-09 · rejected: guardia as a merge gate that publishes a GitHub check from the agent · `diaktoros` already
  publishes the check and the ruleset, `receipts` already blocks push and PR creation, and a check published by the
  agent that wrote the code is not independent; Pedro chose Foreman.
