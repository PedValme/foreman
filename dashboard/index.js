// Foreman has no web dashboard page: its dashboard/ folder exists for the backend route (plugin_api.py) that the
// Desktop panel (desktop/plugin.js) reads. The dashboard loads every plugin's entry script, so this one registers an
// empty, hidden page instead of failing to load.
(function () {
  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("foreman", function () { return null; });
  }
})();
