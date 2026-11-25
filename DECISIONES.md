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
  drama en […], […] puedes usarla en lo que necesites […] y […] que es mi gailover/secundsria […]» (the machine and
  the accounts redacted on 2026-11-11 under the rule that nothing of the owner's private setup is public).
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
  text), category `automation`, and a real-app capture of the panel first among the screenshots · Pedro, to the
  four proposals: «sí a las cuatro, la web es correcta». Its fourth, the credit line linking to the company's
  website, was replaced on 2026-11-25 (below).
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
- 2026-11-11 · Overnight final review with subagents; the agent fixes what it finds · Pedro: «fluye» and
  «haz una revisión final muldimensional con subagentes para asegurar que todo está probado y listo para
  grabar y publicar mañana durante la mañana […] mañana con un nuevo guión (uno bien hehco y de realmente demuestre
  lo que queremos del plugin) grabamos y colocamos el PR en el repo de HErmes», and «usa mi hermes desktop de este
  win durante la noche si lo necesitas, si encuentras issues o cosas a corregir, las corriges, fluye mientras voy a
  descansar».
- 2026-11-11 · Reviewer picked from the configured models · Pedro: «sobre el desplegable si ok construyelo en
  paralelo»: a dropdown of the models already configured in the user's Hermes, built in parallel with the recording
  on its own branch (merged and re-pinned only if reviewed and tested in time, else after the submission), after «es que es
  realmente un desproposito que no pueda mostrar un simple combo con las opciones de proveedores y modelos ya
  configurados» and «tiene que haber manera de llamarlo orgánicamente». Ajustes del agente: the dropdown is
  Hermes's own auxiliary-model picker (Foreman registers its review as an auxiliary task, by default on the first
  fallback model, no capability needed) rather than a page Foreman draws itself.
- 2026-11-12 · Foreman stays in the owner's default Hermes profile, and Glorieto leaves its pull requests to the
  owner's `/foreman merge` · lives in PedValme/glorieto DECISIONES.md, 2026-11-12.
- 2026-11-14 · The owner's default profile runs the catalog's version of Foreman (ce9b01a, installed pinned from
  the repo until Hermes's bundled catalog lists it, then by name) · Pedro: «sí, hazlo», to the recommendation to
  install the catalog's version.
- 2026-11-14 · The `foremandev` profile stays on the owner's Hermes machine: every new version is tried there before
  it is pinned in the catalog and installed in the default profile · Pedro: «ok corrigela», after asking «si queremos
  hacer mejoras o correcciones a Foreman, no necesitamos el foremandev?».
- 2026-11-22 · No catalog SHA bump for README-only changes (the hackathon award and the GIF): they reach the catalog
  page together with the next substantial plugin change, in one pull request · Pedro: «mejor todavia, cusndo hagamos
  un cambio mayor lo subimos todo», to the proposal of a bump with the notify README fix and the GIF.
- 2026-11-23 · The owner's networks and personal profiles are worked in a separate project; this repository keeps
  Foreman and its technical side · Pedro: «tú te quedss con foreman y los aspectos tecnicos».
- 2026-11-24 · Foreman becomes harness-agnostic: one core and an adapter per harness, for Claude Code, Codex, pi and
  OpenCode in the same campaign, with the full line on pi and OpenCode · Pedro: «los 4 a la vez, en opencode y pi
  casi seguro que deberia poderse hacer la version full tambien similar a hermes». Adjustments he saw and confirmed
  («confirmo los ajustes, arranca»): each harness is published when its own end-to-end test passes, without waiting
  for the others; OpenCode means its v2 plugin API only; "full" is the gate, `/foreman` (board, verdict, review,
  merge, reject, allow, pipeline) and the reviewer, while the phone notifications and the Desktop panel stay
  Hermes-only.
- 2026-11-24 · Outside Hermes the reviewer is a session that did not write the code, on another model or with more
  effort, as the user chooses · Pedro: «para el segundo modelo revisor lo que podemos hacer es lo que hacemos con
  claude code por protocolo ahora, que un subagente que no escribio el codigo reciba el encargo y de preferencia con
  un modelo diferente o con un nivel extra de esfuerzo (ejem, si escribio opus 5.5 medio el review lo hace o sonnet o
  5.5 alto) podria ser decision del usuario dependiendo de cuanto este dispuesto a usar de su sub». Adjustments he saw
  and confirmed («confirmo los ajustes, arranca»): Foreman launches that session, never the agent that wrote the
  code (the verdict must not pass through the author's hands); it reviews when someone asks to merge by default, on
  every turn only if the user turns it on; with nothing chosen, the same model one effort level up, and the record
  says so.
- 2026-11-24 · The Hermes plugin stays as listed: changes to the core land on `main` and reach Hermes together, in
  one substantial catalog update · Pedro: «el plugin de hermes queda intacto salvo como dices que se haga una
  actuwlizacion mayor acumulada que sfecte el nucleo».
- 2026-11-24 · One public name in every store, `foreman-gate` · Pedro: «si, confirmo, hazlo así», to this reading
  of his «por que no foreman-gate para todos y el nombre foreman se mantiene de fondo coml sugieres»: the adapters
  are published as `foreman-gate` (npm and with it pi's catalog, OpenCode's ecosystem page, the marketplaces of
  Claude Code and Codex, Anthropic's directory), from this one repository, and `foreman` stays where it is the name
  in use: the command `/foreman`, the plugin inside Claude Code (its name is the prefix of `/foreman:status`),
  OpenCode's plugin id and the Hermes catalog entry. He saw with it: first the `package.json`, the marketplace
  renamed and the four installations tried from git, with nothing published; each publication (npm, OpenCode's
  page, Anthropic's directory) waits for his yes. Va en: this repository's AGENTS.md (the index).
- 2026-11-25 · The push refused after a rebase is fixed first · Pedro: «sí, empieza por el arreglo del rebase»,
  to the recommendation he read after asking, of the evaluation of Foreman for any agent (`trabajo/agnostico.md`),
  «antes de hacerlo, valenla pena???»: fix that defect of today's gate, then `action.yml` with a README that
  speaks by level, then publish what is already built (each publication with his own yes, as before); the generic
  host, the terminal command with `status` and Foreman's own installer of git's hooks, not now (nobody has asked
  for Foreman on a harness it does not cover: 28 stars, no issue from outside).
- 2026-11-25 · Two more false refusals of the gate first · Pedro: «sí, arregla primero los dos rechazos falsos»,
  to the proposal he read: before `action.yml`, the `git commit` that concludes a merge of the base branch with
  conflicts, and the branch that follows the base branch itself (`git checkout -b topic origin/main`) pushed
  before it is rebased, both refused for the base branch's own change to a test; then `action.yml` and the README
  by level, as decided the same day.
- 2026-11-25 · The credit is his personal brand · Pedro: «que quede todo asociado anmi marca personal @pedvalme»,
  in full: «quiero que quitemos el "by aqp intelligence" o la referencia esa que pusimos que quede todo asociado
  anmi marca personal @pedvalme o sea Pedro Valencia». Replaces the credit line of 2026-11-10 (the company's).
  The link is his X profile · Pedro: «enlace mi X», to the first version, which linked to GitHub. Ajustes del
  agente: the closing line of both READMEs reads "Built by Pedro Valencia (@pedvalme)" and links to
  https://x.com/PedValme, the address this repository already used for his demo video; the `author` fields and
  the licence already say `PedValme` and stay. The page in Hermes's catalog shows the plugin's README at the
  pinned commit, so it changes with the catalog update.
- 2026-11-25 · The external pull request is finished by us, with the credit its author's · Pedro: «3. ok», to
  the plan he read after his «creo que seria bueno hacer las correcciones del PR externo dandole el credito al
  externo, aprovrchando que estamos haciendo una mejora grande»: the change asked of #57 on 2026-11-23 goes as a
  commit of ours on its author's own branch (it allows maintainers' edits), after a comment there that says so,
  so the pull request merges as theirs; the whole diff re-read, reviewed by an agent that did not write it, its
  held CI run approved.
- 2026-11-24 · The root README announces the adapters · Pedro: «ok al readme», to the section he read ("In Claude
  Code, Codex, pi and OpenCode": the install command from git for each, what each gives, where the limits are).
  npm, OpenCode's page, Anthropic's directory and the issue to Hermes still wait for his yes, one by one.
