// Foreman's server part when the plugin is installed as a folder (the form OpenCode's TUI needs for `tui.ts`):
// OpenCode loads `server.ts` from a plugin folder. It is `foreman.ts` as it is, under the same id, so the single-file
// install (a link to `foreman.ts`) and the folder install run the same code.
import foreman from "./foreman.ts"

export default { id: "foreman", setup: foreman.setup }
