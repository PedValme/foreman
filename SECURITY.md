# Security

Foreman is a security control: a way to get a change past it without a person seeing it is a vulnerability, and so
is anything that lets a pull request, a diff or a model's answer make Foreman run code or print text it did not write.

## Reporting
Please report it privately, not in a public issue: use **Report a vulnerability** on this repository's Security tab
(GitHub's private vulnerability reporting). Include the version or commit, the harness (Hermes Agent, Claude Code,
Codex, pi, OpenCode or CI) and the smallest steps that reproduce it.

You will get an answer within a week. A confirmed issue is fixed on `main` and, for Hermes users, reaches them through
the next update of the plugin's catalog entry; the advisory credits you unless you ask otherwise.

## Known limits
The limits Foreman already discloses (what the detector does not see, what an agent's shell can reach outside Hermes,
the conditions for the check in CI to be a lock) are in the plugin's [README](plugin/README.md) and are not
vulnerabilities by themselves.

## Supported versions
The latest commit on `main` and the version listed in Hermes's plugin catalog.
