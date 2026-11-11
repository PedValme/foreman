#!/bin/bash
# Real-session battery 4: the review settings and the "could not run" path, on PedValme/foreman-demo PR #11
# (targets t/base). Restores every setting it changes at the end.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
P=foremandev
REPO=~/foreman-demo
K=plugins.entries.foreman
SID=""
cfg() { hermes -p $P config set "$K.$1" "$2" >/dev/null 2>&1; echo "   (set $1 = $2)"; }
slash() {  # slash "<label>" "<subcommand and args>" [lines]
  echo "=== $1"
  echo "cmd: /foreman $2"
  out=$(hermes -p $P chat ${SID:+--resume $SID} -q "/foreman $2" 2>&1)
  [ -z "$SID" ] && SID=$(printf '%s\n' "$out" | sed -n 's/^Session: *//p' | head -1)
  printf '%s\n' "$out" | sed '/^Resume this session/,$d' | grep -v '^[[:space:]]*$' | head -${3:-20} | cut -c1-240
}
git -C $REPO fetch -q origin '+refs/heads/*:refs/remotes/origin/*'
slash "0 use" "use $REPO" 4

echo "## A. reviewer_model and reviewer_provider set by hand"
cfg settings.reviewer_model deepseek-v4.1-flash; cfg settings.reviewer_provider opencode-go
slash "A1 review --fresh names the setting as the source" "review 11 --fresh"

echo "## B. same-model notice when the consent to another model is withdrawn"
cfg llm.allow_model_override false; cfg llm.allow_provider_override false
slash "B1 review --fresh without the capabilities" "review 11 --fresh"
cfg llm.allow_model_override true; cfg llm.allow_provider_override true

echo "## C. could not run: a model that does not exist"
cfg settings.reviewer_model no-such-model-xyz
slash "C1 review --fresh with an unreachable model" "review 11 --fresh"
slash "C2 merge --yes while the review could not run (must not merge)" "merge 11 --yes"
echo "-> PR 11: $(gh pr view 11 -R PedValme/foreman-demo --json state --jq .state)"

echo "## D. auto_review off: the merge skips the model"
hermes -p $P config unset "$K.settings.reviewer_model" >/dev/null 2>&1
hermes -p $P config unset "$K.settings.reviewer_provider" >/dev/null 2>&1
cfg settings.auto_review off
slash "D1 merge --yes with auto_review off" "merge 11 --yes"
echo "-> PR 11: $(gh pr view 11 -R PedValme/foreman-demo --json state --jq .state)"
cfg settings.auto_review merge
echo "=== settings now"
hermes -p $P config get $K 2>&1 | tail -15
echo "=== done"
