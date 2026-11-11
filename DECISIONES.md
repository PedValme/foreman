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
- 2026-11-09 · DECISIONES.md and ESTADO.md stay public in this repository; how the owner's machines are reached is
  kept out of it · Pedro: «déjalos públicos, limpia lo del ssh y sigue».
- 2026-11-09 · `main` is protected: changes only by pull request, no force push, no deletion, the CI checks
  required; only the owner's account and the agents' account can merge, nobody else · Pedro: «con solo yo me referia
  a solo nosotros o sea bot y yo, que otra gente no pueda fusionar sin niestra luz verde. Si aprobado que lo hagas».
- 2026-11-09 · Two test beds: the owner's Token Plan voice plugins in a private repository, for real merges and
  rejections; the small cart example for the demo video · Pedro: «usemos el plugin de token plan como test creemosle
  un repo, es una sinulacion mas limpia porque es tgabajo que se hsria normalmente sobre un hermes agent gateway»,
  and to the proposal of both, the first one private: «sí, vamos con los dos, crea el repo privado».
- 2026-11-09 · The demo video shows the plugin working as before and after: loaded, then enabled, then acting ·
  Pedro: «el video debe mostar al plugin funcionando, con lo que abria que activarlo luego de mostrar que esta
  cargado y ver como luego de activado entra en accion».
- 2026-11-09 · Demo video: the agent writes the script and the recording instructions (orientation, camera, tool)
  according to the rules and does the editing; Pedro records and publishes on X · Pedro: «guion e indicaciones de
  grabacion … tu haces la edicion!».
- 2026-11-09 · rejected: OnBrand (brand and content plugin) · the catalog entry `on-brand` (2026-11-09) already
  covers its name and its blocking linter, and its plan needed six days; Pedro chose Foreman.
- 2026-11-09 · rejected: guardia as a merge gate that publishes a GitHub check from the agent · `diaktoros` already
  publishes the check and the ruleset, `receipts` already blocks push and PR creation, and a check published by the
  agent that wrote the code is not independent; Pedro chose Foreman.
- 2026-11-09 · Foreman grows into the whole line of a software factory in one plugin: automatic reviews, bounces
  back to the agent, a notice to the owner and approval from the messaging app, a second-family checker model
  (optional), an agent doing what guardia does, and a visual animated workflow in the Desktop panel showing where
  each change is. The core promise stays the gate · Pedro: «si queremos ganar necesitamos algo que aporte mas
  valor, por eso mi idea inicial en muy simple era llevar la fabrica completa a un plugin o sea las revisiones en
  auto, los rebotes, las notificaciones o aprobacilnes de fusion por boton en etelegram […] y un sgebte que haga
  lo que hace guardia. Inckuso para hacerlo ganador con un workflow visual en motion que se vea desde el panel»,
  and «dale de largo a todo lo que puedas avanzar durante la noche».
- 2026-11-09 · The second-model review runs by default when someone asks to merge; the full loop on every coding
  turn is an option the user turns on (`auto_review`: `merge` default, `finish`, `off`) · Pedro chose «Al fusionar
  (Recomendado)» over «En cada turno». A merge is never automatic (agent's limit, catalog rule 12, accepted with
  the plan).
- 2026-11-09 · On the owner's Hermes machine, in the dedicated profile: test sessions through the night, more
  test issues and pull requests in the private test repository, and the agent answers the consent screen that
  lets Foreman use another model as reviewer · Pedro chose all three, and: «hay dos cuentas que puedes usar sin
  drama en glorieto, openai chatgpt por suscripcion puedes usarla en lo que necesites terra y sol 6.1 y opencode
  go que es mi gailover/secundsria usa puro deepseek 4.1 flash en high de esa sub».
- 2026-11-09 · The Desktop panel is checked on the Hermes Desktop of the development PC or on the web version ·
  Pedro: «hay hermes desktop en este pc pero puedes usar la version web tambien».
- 2026-11-09 · The catalog pull request and the feature request to Hermes go out under the owner's account only
  after he has seen the texts · Pedro chose «Preparo y te muestro (Recomendado)».
- 2026-11-09 · The installable plugin lives in a subdirectory (`plugin/`), so a user's install gets only the
  plugin while the method documents stay public in the repository · Pedro: «sí, mueve el plugin a una subcarpeta
  al final como propones».
- 2026-11-10 · A public demo repository, `PedValme/foreman-demo`, made from the cart example, for the video's board
  and merge shots · Pedro: «crea el repo foreman-demo y empecemos con telegram».
- 2026-11-10 · The catalog entry: a short description (the full disclosure stays in the README and the pull request
  text), category `automation`, and a real-app capture of the panel first among the screenshots; the credit line
  links to https://aqpintelligence.com, in that closing line only · Pedro, to the four proposals: «sí a las cuatro,
  la web es correcta».
- 2026-11-10 · The catalog pull request is opened when the work is finished, not before · Pedro: «El PR primero
  terminemos».
- 2026-11-10 · Nothing is recorded or submitted until every function of the plugin has been tried end to end and
  works; the video comes only after that, and it shows the whole line that was redesigned, not one small function ·
  Pedro: «por que cojones estamos a punto de grabar el video si todavía no hemos terminado de probar punta a punta
  el plugin y TODAS, entendido?? TODAS! Sus funcionalidades??????? […] primero resolvamos lo que falta y luego
  cuanto tengamos todo como reloj suizo RECIEN grabamos», and earlier: «solo estamos mostrando una función mínima
  del plugin y no todo lo que rediseñamos ayer en la tarde».
- 2026-11-10 · A skip marker counts in test files as before; outside them it counts only when written as code, not
  inside a quoted string or a comment (Foreman flagged its own detector and a shell script that only quoted one),
  so a skip helper defined outside the tests is still caught · Pedro: «sí, solo en archivos de test como
  recomiendas»; then, told that this lets a skip helper defined in a non-test file through, he chose «Tests +
  código fuera (Recomendado)». Ajustes del agente (from the review, after his choice): in the files that run the
  check (CI workflows, Makefile, tox, nox, package.json…) a quoted marker still counts, because a command there
  can write a skip into the tests; in Python files `//` is not a comment.
