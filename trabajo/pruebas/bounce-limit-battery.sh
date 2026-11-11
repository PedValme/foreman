#!/bin/bash
# Real-session battery 5: the finish loop's bounce limit and review budget. The agent is told to keep a loosened
# assertion whatever the reviewer says, so every review fails: expect at most max_bounces bounces, then "needs the
# owner", and at most max_bounces + 1 model calls for the change. Restores auto_review at the end.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
P=foremandev
R=/tmp/fm-bounce2
K=plugins.entries.foreman.settings
D=~/.hermes/profiles/$P/plugin-data/foreman
rm -rf $R && mkdir -p $R/tests && cd $R && git init -q -b main
printf 'def total(p, d=0):\n    return sum(p) * (100 - d) / 100\n' > cart.py
printf 'import unittest\nfrom cart import total\n\n\nclass T(unittest.TestCase):\n    def test_total(self):\n        self.assertEqual(total([10, 20]), 30)\n\n    def test_discount(self):\n        self.assertEqual(total([100], 10), 90)\n' > tests/test_cart.py
git add -A && git -c user.name=demo -c user.email=demo@example.com commit -qm base
git config user.name demo; git config user.email demo@example.com
git checkout -q -b feat
reviews_before=$(ls $D/reviews 2>/dev/null | wc -l | tr -d ' ')
hermes -p $P config set $K.auto_review finish >/dev/null 2>&1; hermes -p $P config set $K.max_bounces 1 >/dev/null 2>&1
echo "auto_review: $(hermes -p $P config get $K.auto_review 2>&1 | tail -1)  max_bounces: $(hermes -p $P config get $K.max_bounces 2>&1 | tail -1)"
start=$(date +%s)
hermes -p $P chat --yolo -q "In the git repository $R (branch feat), use your file-editing tool to change test_discount in tests/test_cart.py so that it asserts self.assertIsNotNone(total([100], 10)) instead of the exact value. This is a test of a review loop: every time a reviewer or a tool sends the change back, replace that assertion with a different loose form (for example > -1, then is not None, then isinstance(..., float)), never the exact value 90, and finish again. Keep going until nothing sends it back. Do not commit." 2>&1 \
  | sed -n '/☤ Hermes/,/^Resume this session/p' | grep -v '^─' | head -25 | cut -c1-260
echo "-> turn took $(( $(date +%s) - start ))s"
echo "-> test now: $(grep -n 'assert' $R/tests/test_cart.py | tail -1)"
echo "-> new review records: $(( $(ls $D/reviews | wc -l | tr -d ' ') - reviews_before ))"
python3 - "$D/pipeline.json" "$R" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
items = data.get("items", data) if isinstance(data, dict) else data
for it in (items.values() if isinstance(items, dict) else items):
    if sys.argv[2] in json.dumps(it):
        print("-> pipeline:", {k: it.get(k) for k in ("id", "stage", "bounces", "max_bounces")})
        print("   stages:", [(s.get("name"), s.get("status"), (s.get("detail") or "")[:60]) for s in it.get("stages") or []])
        for ev in (it.get("events") or [])[-8:]:
            print("   ", ev)
PY
hermes -p $P config set $K.auto_review merge >/dev/null 2>&1
hermes -p $P config unset $K.max_bounces >/dev/null 2>&1; echo "auto_review restored: $(hermes -p $P config get $K.auto_review 2>&1 | tail -1)"
echo "=== done"
