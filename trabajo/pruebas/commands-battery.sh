#!/bin/bash
# Real-session battery 3: the /foreman commands from the CLI, one session, on PedValme/foreman-demo.
# The test pull requests #6-#10 all target the branch t/base, so main and the video's pull requests stay untouched.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
P=foremandev
REPO=~/foreman-demo
SID=""
slash() {  # slash "<label>" "<subcommand and args>"
  echo "=== $1"
  echo "cmd: /foreman $2"
  out=$(hermes -p $P chat ${SID:+--resume $SID} -q "/foreman $2" 2>&1)
  [ -z "$SID" ] && SID=$(printf '%s\n' "$out" | sed -n 's/^Session: *//p' | head -1)
  printf '%s\n' "$out" | sed '/^Resume this session/,$d' | grep -v '^[[:space:]]*$' | head -${3:-25} | cut -c1-240
}
git -C $REPO fetch -q origin '+refs/heads/*:refs/remotes/origin/*'
git -C $REPO checkout -q main 2>/dev/null; git -C $REPO pull -q 2>/dev/null

slash "1 use" "use $REPO" 8
echo "session: $SID"
slash "2 help" "help" 40
slash "3 prs" "prs" 40
slash "4 issues" "issues"
slash "5 verdict of a branch" "verdict t/merge"
slash "6 verdict typed as #8" "verdict #8" 12
slash "7 verdict typed as 8." "verdict 8." 12
slash "8 review of a branch" "review t/rebase"
slash "9 review of a pull request" "review 8"
slash "10 review of the same pull request again (stored, no model call)" "review 8" 12
slash "11 review --fresh" "review 8 --fresh"
slash "12 merge refused: conflicts" "merge 6 --yes"
slash "13 merge refused: draft" "merge 7 --yes"
slash "14 merge --merge" "merge 8 --merge --yes"
slash "15 merge --rebase right after (GitHub may still be computing)" "merge 9 --rebase --yes"
slash "16 reject --close without --yes (asks)" "reject 10 --close Not needed for this test."
slash "17 reject --close --yes" "reject 10 --close --yes Not needed for this test."
echo "=== GitHub state"
gh pr list -R PedValme/foreman-demo --state all --json number,state,isDraft,mergeable --jq '.[]|select(.number>=6)|"\(.number) \(.state) draft=\(.isDraft) \(.mergeable)"'
git -C $REPO fetch -q origin t/base && git -C $REPO log --oneline -6 origin/t/base
echo "=== done"
