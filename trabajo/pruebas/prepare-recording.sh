#!/bin/bash
# Prepare PedValme/foreman-demo and the owner's Hermes for a take of the demo video (trabajo/demo-video.md).
# Run from the development PC (gh logged in, ssh to the owner's Hermes machine). Without --go it only prints what it
# would do. Keeps the two counter-examples (#3 a skipped test, #4 loosened assertions) and issue #1.
set -u
R=PedValme/foreman-demo
HOST=${FOREMAN_HERMES_HOST:-glorieto}   # the owner's Hermes machine (ssh alias in his own config)
GO=0; [ "${1:-}" = "--go" ] && GO=1
run() { echo "+ $*"; [ $GO = 1 ] && eval "$@"; }

echo "== Pull requests to close (all open ones except #3 and #4)"
for n in $(gh pr list -R $R --state open --json number --jq '.[].number'); do
  case $n in 3|4) continue ;; esac
  run gh pr close $n -R $R --comment "'Closed to prepare the demo recording.'"
done

echo "== Remote branches to delete (t/* and fix/discount from an earlier take)"
for b in $(gh api repos/$R/branches --paginate --jq '.[].name'); do
  case $b in t/*|fix/discount) run gh api -X DELETE repos/$R/git/refs/heads/$b ;; esac
done

echo "== Issue #1 open"
[ "$(gh issue view 1 -R $R --json state --jq .state)" = "OPEN" ] || run gh issue reopen 1 -R $R

echo "== The clone on the Hermes machine: main, clean, no other local branches"
run ssh $HOST "'cd ~/foreman-demo && git fetch -q --prune origin && git checkout -q main && git reset -q --hard origin/main && git clean -qfd && git for-each-ref --format=\"%(refname:short)\" refs/heads | grep -vx main | xargs -r git branch -q -D; git status -sb | head -1'"

echo "== Foreman's pipeline on the real profile archived, so the panel starts empty (reviews and grants kept)"
STAMP=$(date +%Y%m%d-%H%M%S)
run ssh $HOST "'cd ~/.hermes/plugin-data/foreman && for f in pipeline.json pipeline-meta.json; do [ -f \$f ] && mv \$f \$f.bak-$STAMP; done; ls'"

[ $GO = 1 ] && echo "Done." || echo "Dry run: nothing changed. Run with --go to do it."
