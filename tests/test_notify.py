"""Notifications: the message for each event, third-party text made inert, off by default, delivery through a fake
terminal tool (never the network or a real chat), and `--repo` limited to repositories Foreman knows."""
import json
import os
import unittest

from tests_support import GitRepoCase  # first: it puts plugin/ on sys.path
from foreman import board, commands, gate, notify
from test_board import BoardCase, FakeCtx, clean_diff, pr_view


class NotifyCtx(FakeCtx):
    """A fake plugin context with settings; keeps the text of each message file while it exists."""

    def __init__(self, settings=None, raises=False, **kw):
        super().__init__(**kw)
        self.settings = dict(settings or {})
        self.sent_texts, self.raises = [], raises

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def set_config(self, key, value):
        self.settings[key] = value

    def dispatch_tool(self, name, args, **kwargs):
        if self.raises:
            raise RuntimeError("terminal exploded")
        if " --file " in args.get("command", ""):
            path = args["command"].split(" --file ", 1)[1].split(" --quiet")[0].strip().strip('"')
            with open(path, encoding="utf-8") as fh:
                self.sent_texts.append(fh.read())
            self.paths = getattr(self, "paths", []) + [path]
        return super().dispatch_tool(name, args, **kwargs)


def same(a, b):
    """One directory, however the platform spells it (8.3 names on Windows, /private/var on macOS)."""
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def event(kind="ready", number=6, repo="acme/widgets", **extra):
    e = {"kind": kind, "id": "%s#pr:%d" % (repo, number), "repo": repo,
         "target": {"kind": "pr", "number": number, "branch": "feat/x", "title": "Add retries",
                    "url": "https://github.com/%s/pull/%d" % (repo, number)},
         "head": "a" * 40, "summary": "CLEAN, review: no findings",
         "actions": [{"label": "Merge", "command": "/foreman merge %d --yes" % number},
                     {"label": "Reject", "command": "/foreman reject %d" % number}]}
    e.update(extra)
    return e


class Render(unittest.TestCase):
    def test_ready_names_the_change_and_the_commands_without_yes(self):
        text = notify.render(event(), "whatsapp")
        self.assertTrue(text.startswith("Foreman: PR #6 is ready to merge and waits for you\n"))
        for part in ("Repository: acme/widgets", "Title: Add retries", "branch feat/x", "head aaaaaaa",
                     "Verdict: CLEAN, review: no findings", "https://github.com/acme/widgets/pull/6",
                     "\n/foreman merge 6 --repo acme/widgets\n", "\n/foreman reject 6 --repo acme/widgets\n",
                     "Merge (Foreman checks it again, then asks you with Merge / Cancel buttons):",
                     "Nothing is merged until you confirm there."):
            self.assertIn(part, text)
        self.assertNotIn("--yes", text)
        self.assertNotIn("`", text)

    def test_each_kind(self):
        self.assertIn("PR #6 needs your decision", notify.render(event("needs_owner")))
        for kind, words in (("merged", "was merged"), ("rejected", "was rejected")):
            text = notify.render(event(kind))
            self.assertIn("PR #6 %s" % words, text)
            self.assertNotIn("/foreman", text)  # nothing left to do

    def test_default_actions_when_the_event_has_none(self):
        self.assertIn("/foreman verdict 6 --repo acme/widgets", notify.render(event("needs_owner", actions=[])))
        self.assertIn("/foreman merge 6 --repo acme/widgets", notify.render(event("ready", actions=None)))

    def test_telegram_gets_tap_to_copy_commands(self):
        text = notify.render(event(), "telegram")
        self.assertIn("`/foreman merge 6 --repo acme/widgets`", text)
        self.assertIn("Tap a command to copy it", text)
        self.assertIn("`/foreman reject 6 --repo acme/widgets`", notify.render(event(), "slack"))

    def test_third_party_text_is_inert(self):
        title = ("<b>hi</b> @everyone [click](http://evil.example/x) *bold* _it_ MEDIA:/etc/secret.png "
                 "media : ~/k.txt `code` snake_case ‮evil")
        text = notify.render(event(target={"kind": "pr", "number": 6, "title": title, "branch": "@here",
                                           "url": "https://github.com/acme/widgets/pull/6"},
                                   summary="[[as_document]] see https://x.example"), "telegram")
        title_line = next(l for l in text.splitlines() if l.startswith("Title:"))
        for bad in ("<", ">", "*", "[", "]", "`", "‮", "://", "@everyone", "evil.example", "_it_"):
            self.assertNotIn(bad, title_line)
        self.assertNotRegex(text.lower(), r"media\s*:")
        self.assertIn("@​everyone", title_line)
        self.assertIn("snake_case", title_line)
        self.assertNotIn("@here", text)
        self.assertNotIn("[[", text)

    def test_crafted_actions_and_links_are_dropped(self):
        e = event(actions=[{"label": "Merge", "command": "/foreman merge 7 --yes"},
                           {"label": "x", "command": "/foreman merge 6; rm -rf /"},
                           {"label": "y", "command": "/foreman allow abc"},
                           {"label": "Reject", "command": "/foreman reject 6 --close --yes"}])
        e["target"]["url"] = "https://evil.example/acme/widgets/pull/6"  # right repo and number, wrong host
        text = notify.render(e)
        self.assertNotIn("merge 7", text)
        self.assertNotIn("rm -rf", text)
        self.assertNotIn("allow", text)
        self.assertNotIn("evil", text)
        self.assertIn("/foreman reject 6 --close --repo acme/widgets", text)

    def test_unknown_repository_gets_no_commands(self):
        text = notify.render(event(repo="not a repo; rm"))
        self.assertIn("Repository: unknown", text)
        self.assertNotIn("/foreman merge", text)
        self.assertIn("cannot name the repository", text)

    def test_events_foreman_cannot_describe(self):
        for bad in (None, {}, event(kind="deployed"), event(target={"kind": "pr", "number": "6"}),
                    event(target={"kind": "branch", "number": 6})):
            with self.assertRaises(ValueError):
                notify.render(bad)


class Sending(GitRepoCase):
    def setUp(self):
        super().setUp()
        self._old = board._CTX

    def tearDown(self):
        board._CTX = self._old
        super().tearDown()

    def ctx(self, **kw):
        board.bind(NotifyCtx(**kw))
        return board._CTX

    def test_off_by_default_sends_nothing(self):
        ctx = self.ctx()
        r = notify.send(event())
        self.assertEqual((r["sent"], r["where"]), (False, None))
        self.assertIn("notifications are off", r["why_not"])
        self.assertEqual(ctx.dispatched, [])

    def test_on_without_a_destination(self):
        ctx = self.ctx(settings={"notify": "on"})
        r = notify.send(event())
        self.assertFalse(r["sent"])
        self.assertIn("no destination", r["why_not"])
        self.assertEqual(ctx.dispatched, [])

    def test_a_local_surface_is_not_a_destination(self):
        ctx = self.ctx(settings={"notify": True, "notify_to": "cli"})
        self.assertIn("not a messaging target", notify.send(event())["why_not"])
        self.assertEqual(ctx.dispatched, [])

    def test_sends_once_through_hermes_send(self):
        ctx = self.ctx(settings={"notify": "on", "notify_to": "telegram"})
        r = notify.send(event())
        self.assertEqual(r, {"sent": True, "where": "telegram", "why_not": None})
        name, args = ctx.dispatched[0]
        self.assertEqual(name, "terminal")
        self.assertRegex(args["command"], r'^hermes send --to "telegram" --file "[^"]+/notify/msg-[^"]+\.txt" --quiet$')
        self.assertEqual(args["timeout"], notify.SEND_TIMEOUT)
        self.assertEqual(ctx.sent_texts, [notify.render(event(), "telegram")])
        self.assertFalse(os.path.exists(ctx.paths[0]))  # the message file is removed
        self.assertIsNone(gate.on_pre_tool_call("terminal", {"command": args["command"]}))  # the gate lets it run
        again = notify.send(event())
        self.assertEqual((again["sent"], again["why_not"]), (False, "already sent"))
        self.assertEqual(len(ctx.dispatched), 1)
        self.assertTrue(notify.send(event(head="b" * 40))["sent"])  # a new head is a new event
        self.assertTrue(notify.send(event(number=7, id=None))["sent"])  # another PR, whatever the caller's id
        self.assertTrue(notify.send(event(number=8, id=None))["sent"])

    def test_the_agent_cannot_touch_the_notify_state(self):
        store = notify.grants.store_dir().replace("\\", "/")
        for command in ('echo [] > "%s/foreman-notify.json"' % store,
                        'hermes send --to "telegram" --file "%s/notify/msg-abc.txt" --quiet; rm x' % store,
                        'cp evil.txt "%s/notify/msg-abc.txt"' % store,
                        'rm "%s/notify/msg-abc.txt"' % store, 'cat "%s/foreman-notify.json"' % store,
                        'hermes send --to "telegram:%%X%%" --file "%s/notify/msg-abc.txt" --quiet' % store):
            self.assertEqual(gate.on_pre_tool_call("terminal", {"command": command})["action"], "block", command)
        self.assertEqual(gate.on_pre_tool_call("write_file", {"path": store + "/foreman-notify.json",
                                                              "content": "[]"})["action"], "block")

    def test_failures_are_reported_never_raised(self):
        ctx = self.ctx(settings={"notify": "on", "notify_to": "discord:#ops"},
                       result={"output": "", "exit_code": 1, "error": "hermes send: No home channel set"})
        r = notify.send(event())
        self.assertEqual((r["sent"], r["where"]), (False, "discord:#ops"))
        self.assertIn("No home channel set", r["why_not"])
        self.ctx(settings={"notify": "on", "notify_to": "telegram"},
                 result={"output": "bash: hermes: command not found", "exit_code": 127, "error": ""})
        self.assertIn("not on the PATH", notify.send(event())["why_not"])
        self.ctx(settings={"notify": "on", "notify_to": "telegram"}, raises=True)
        r = notify.send(event())
        self.assertFalse(r["sent"])
        self.assertIn("terminal exploded", r["why_not"])
        board._CTX = None
        self.assertFalse(notify.send(event())["sent"])
        self.ctx(settings={"notify": "on", "notify_to": "telegram"})
        r = notify.send({"kind": "ready"})
        self.assertFalse(r["sent"])
        self.assertIn("cannot describe this event", r["why_not"])
        self.assertFalse(notify.send("not an event")["sent"])

    def test_event_root_makes_the_repository_known(self):
        self.write("a.txt", "a\n")
        self.commit("base")
        self.git("remote", "add", "origin", "git@github.com:acme/widgets.git")
        self.ctx(settings={"notify": "on", "notify_to": "telegram"})
        notify.send(event(root=self.root))
        root, problem = board.known_repository("acme/widgets")
        self.assertIsNone(problem)
        self.assertTrue(same(root, self.root))
        notify.send(event(repo="other/thing", root=self.tmp, head="c" * 40))  # a root whose remote differs: ignored
        self.assertEqual(len(board.recent()), 1)


class Subcommands(GitRepoCase):
    def setUp(self):
        super().setUp()
        self._old = board._CTX
        board.bind(NotifyCtx())

    def tearDown(self):
        board._CTX = self._old
        super().tearDown()

    def run_cmd(self, text, platform=None):
        return commands.handle_slash(text, session_key="s", platform=platform)

    def test_show_on_off(self):
        out = self.run_cmd("notify")
        self.assertIn("Foreman notifications: OFF (nothing is sent anywhere)", out)
        self.assertIn("Destination: not set", out)
        self.assertIn("say where", self.run_cmd("notify on").lower())
        self.assertNotIn("notify", board._CTX.settings)
        out = self.run_cmd("notify on Telegram")
        self.assertIn("notifications are on, to telegram (your Telegram home channel", out)
        self.assertEqual(board._CTX.settings, {"notify": "on", "notify_to": "telegram"})
        self.assertIn("Foreman notifications: ON", self.run_cmd("notify"))
        self.assertIn("notifications are off", self.run_cmd("notify off"))
        self.assertEqual(board._CTX.settings["notify"], "off")
        self.assertEqual(board._CTX.dispatched, [])

    def test_on_in_a_chat_defaults_to_that_platform(self):
        board._CTX.settings["notify_to"] = "slack:C1"
        self.run_cmd("notify on", platform="discord")
        self.assertEqual(board._CTX.settings["notify_to"], "discord")
        self.run_cmd("notify on", platform="cli")  # from a terminal: keeps the saved target
        self.assertEqual(board._CTX.settings["notify_to"], "discord")
        self.assertIn("say where", self.run_cmd("notify on cli").lower())

    def test_test_sends_the_sample_even_while_off(self):
        self.assertIn("no destination yet", self.run_cmd("notify test"))
        board._CTX.settings["notify_to"] = "telegram"
        out = self.run_cmd("notify test")
        self.assertIn("sent this to telegram", out)
        self.assertIn("(Test message: the pull request below is an example.)", board._CTX.sent_texts[0])
        self.assertIn("`/foreman merge 6 --repo example/repo`", board._CTX.sent_texts[0])
        self.assertIn("Foreman notifications: OFF", self.run_cmd("notify"))

    def test_help_lists_notify(self):
        self.assertIn("notify", self.run_cmd("help"))


class RepoOption(BoardCase):
    """`--repo`: a command from a chat with no pinned repository names one Foreman already knows, nothing else."""

    def setUp(self):
        super().setUp()
        self.github()
        self.gh.add(["pr", "view", "7"], pr_view(7))
        self.gh.add(["pr", "diff", "7"], clean_diff())

    def chat(self, text):
        return commands.handle_slash(text, session_key="telegram-chat", platform="telegram")

    def test_owner_name_of_a_known_repository(self):
        board.bind(FakeCtx(choice="merge"))
        out = self.chat("merge 7 --repo acme/widgets")
        self.assertIn("merged PR #7", out)
        self.assertEqual(len(board._CTX.dispatched), 1)
        self.assertTrue(same(board._CTX.dispatched[0][1]["workdir"], self.root))
        self.assertIn("Foreman verdict for PR #7: CLEAN", self.chat("verdict 7 --repo=acme/widgets"))

    def test_path_of_a_known_repository(self):
        self.assertIn("Foreman verdict for PR #7: CLEAN", self.chat("verdict 7 --repo %s" % self.root))

    def test_unknown_names_and_paths_are_refused(self):
        os.makedirs(os.path.join(self.root, "sub"), exist_ok=True)
        for value in ("other/widgets", self.tmp, os.path.expanduser("~"), "../repo", "acme/widgets;x",
                      os.path.join(self.root, "sub")):
            board.bind(FakeCtx(choice="merge"))
            out = self.chat("merge 7 --repo %s" % value)
            self.assertIn("is not a repository Foreman knows", out)
            self.assertEqual(board._CTX.dispatched, [])
            self.assertEqual(self.gh.calls, [])
        self.assertIn("Usage: --repo", self.chat("reject 7 --repo"))

    def test_no_answer_hint_keeps_the_repository(self):
        board.bind(FakeCtx(can_ask=False))
        out = self.chat("merge 7 --repo acme/widgets")
        self.assertIn("/foreman merge 7 --repo acme/widgets --yes", out)
        self.assertEqual(board._CTX.dispatched, [])

    def test_without_repo_a_chat_with_nothing_pinned_finds_nothing(self):
        out = self.chat("merge 7")
        self.assertNotIn("merged", out)
        self.assertEqual(board._CTX.dispatched, [])


if __name__ == "__main__":
    unittest.main()
