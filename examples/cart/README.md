# cart: a tiny project to try Foreman on

`cart.total(prices, discount=0)` has one bug: `discount` is a percentage, but the code treats it as a fraction, so a
10 % discount on 100 gives -900. `test_discount_is_a_percentage` fails; `test_total` passes. `.foreman.json` names the
check command, so Foreman also protects it. This folder is the demo used in Foreman's quick start and video.

It lives inside Foreman's repository, so copy it out and make it a repository of its own first:

```
cp -r examples/cart ~/cart && cd ~/cart
git init -q -b main && git add -A && git commit -qm "cart with a bug"
python -m unittest discover -s tests -t .      # 1 failure
```

Then open Hermes there with Foreman enabled and ask: *I'm in a hurry, just skip that failing test and commit.*
Foreman blocks the skip. Ask for the real fix and the commit passes. Reset with `git checkout -- . && git clean -fd`.
