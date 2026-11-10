"""The Desktop panel's reader: pipeline.json as untrusted, read-only data. A missing, corrupt or huge file reads as no
items and never raises; the documented shape passes through; text is kept as text, never interpreted."""
import json
import os
import shutil
import tempfile
import unittest

import tests_support  # noqa: F401  first: it puts plugin/ on sys.path
from foreman import panel_api

SHA = "a" * 40


def item(**over):
    base = {
        "id": "owner/repo#pr:6", "repo": "owner/repo", "root": "/abs/path",
        "target": {"kind": "pr", "number": 6, "branch": "feat/x", "title": "Add the thing",
                   "url": "https://github.com/owner/repo/pull/6"},
        "head": SHA,
        "stage": "review",
        "stages": [
            {"name": "gate", "status": "pass", "detail": "", "at": "2026-11-09T10:00:00Z"},
            {"name": "review", "status": "pending", "detail": "", "model": "provider/model", "at": None},
            {"name": "owner", "status": "pending", "detail": "", "at": None},
            {"name": "merge", "status": "pending", "detail": "", "at": None},
        ],
        "bounces": 1, "max_bounces": 3, "updated": "2026-11-09T10:01:00Z",
        "events": [{"at": "2026-11-09T10:00:00Z", "text": "Gate passed"}],
    }
    base.update(over)
    return base


class PanelApiCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="foreman-panel-")
        self.path = os.path.join(self.tmp, "pipeline.json")
        self._old = panel_api.PATH_OVERRIDE
        panel_api.PATH_OVERRIDE = self.path

    def tearDown(self):
        panel_api.PATH_OVERRIDE = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))

    def snapshot(self, *items):
        self.write({"version": 1, "items": list(items)})
        return panel_api.read_snapshot()

    # ─── missing, corrupt, huge ──────────────────────────────────────────────

    def test_missing_file_is_no_items(self):
        self.assertEqual(panel_api.read_snapshot(), {"version": 1, "items": [], "problem": "missing"})

    def test_corrupt_json_is_no_items(self):
        for bad in ("{", "not json", "", "[]", "null", '{"version": 1}', '{"version": 1, "items": {}}',
                    '{"items": "x"}', chr(0xFEFF) + "{}"):
            with self.subTest(bad=bad):
                self.write(bad)
                snap = panel_api.read_snapshot()
                self.assertEqual(snap["items"], [])
                self.assertEqual(snap["problem"], "unreadable")

    def test_deeply_nested_json_does_not_raise(self):
        self.write("[" * 100000 + "]" * 100000)
        self.assertEqual(panel_api.read_snapshot()["items"], [])

    def test_not_utf8_is_no_items(self):
        with open(self.path, "wb") as fh:
            fh.write(b'{"version": 1, "items": [\xff\xfe]}')
        self.assertEqual(panel_api.read_snapshot()["problem"], "unreadable")

    def test_huge_file_is_not_read(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write('{"version": 1, "items": [], "pad": "')
            fh.write("x" * (panel_api.MAX_BYTES + 10))
            fh.write('"}')
        self.assertEqual(panel_api.read_snapshot(), {"version": 1, "items": [], "problem": "too_large"})

    def test_a_directory_in_its_place_is_no_items(self):
        os.makedirs(self.path)
        self.assertEqual(panel_api.read_snapshot()["items"], [])

    def test_unknown_version_is_not_guessed(self):
        self.write({"version": 2, "items": [item()]})
        self.assertEqual(panel_api.read_snapshot(), {"version": 1, "items": [], "problem": "unsupported"})

    def test_item_count_is_capped(self):
        snap = self.snapshot(*[item(id="r#pr:%d" % n) for n in range(panel_api.MAX_ITEMS + 50)])
        self.assertEqual(len(snap["items"]), panel_api.MAX_ITEMS)

    # ─── shape passthrough ───────────────────────────────────────────────────

    def test_documented_shape_passes_through(self):
        original = item()
        snap = self.snapshot(original)
        self.assertIsNone(snap["problem"])
        self.assertEqual(snap["items"], [original])

    def test_every_documented_stage_is_kept(self):
        for stage in ("gate", "review", "bounced", "ready", "awaiting_owner", "merged", "rejected"):
            with self.subTest(stage=stage):
                self.assertEqual(self.snapshot(item(stage=stage))["items"][0]["stage"], stage)

    def test_branch_target_without_number_or_url(self):
        target = {"kind": "branch", "number": None, "branch": "feat/x", "title": "t", "url": None}
        snap = self.snapshot(item(id="owner/repo#branch:feat/x", target=target))
        self.assertEqual(snap["items"][0]["target"], target)

    def test_items_without_id_or_with_an_unknown_stage_are_dropped(self):
        snap = self.snapshot(item(id=""), item(id=None), item(stage="deployed"), "nope", 7, item(id="keep"))
        self.assertEqual([i["id"] for i in snap["items"]], ["keep"])

    def test_missing_stations_read_as_pending_in_line_order(self):
        snap = self.snapshot(item(stages=[{"name": "merge", "status": "done"}, {"name": "bogus", "status": "pass"}]))
        stations = snap["items"][0]["stages"]
        self.assertEqual([s["name"] for s in stations], ["gate", "review", "owner", "merge"])
        self.assertEqual([s["status"] for s in stations], ["pending", "pending", "pending", "done"])

    def test_unknown_station_status_is_unknown_not_guessed(self):
        snap = self.snapshot(item(stages=[{"name": "gate", "status": "approved"}]))
        self.assertIsNone(snap["items"][0]["stages"][0]["status"])

    def test_wrong_types_are_dropped_field_by_field(self):
        snap = self.snapshot(item(repo=["x"], head="not a sha", bounces=True, max_bounces=-1, updated=5,
                                  target={"kind": "tag", "number": "6", "title": 9, "url": "javascript:alert(1)"},
                                  events="Gate passed"))
        got = snap["items"][0]
        self.assertIsNone(got["repo"])
        self.assertIsNone(got["head"])
        self.assertEqual(got["bounces"], 0)
        self.assertIsNone(got["max_bounces"])
        self.assertIsNone(got["updated"])
        self.assertEqual(got["target"], {"kind": None, "number": None, "branch": None, "title": None, "url": None})
        self.assertEqual(got["events"], [])

    def test_only_https_links_survive(self):
        for url, kept in (("https://github.com/o/r/pull/1", True), ("http://github.com/o/r/pull/1", False),
                          ("javascript:alert(1)", False), ("file:///etc/passwd", False),
                          ("https://x.test/a b", False), ("data:text/html,<b>", False)):
            with self.subTest(url=url):
                got = self.snapshot(item(target=dict(item()["target"], url=url)))["items"][0]["target"]["url"]
                self.assertEqual(got, url if kept else None)

    def test_events_keep_the_latest(self):
        many = [{"at": "t%d" % n, "text": "event %d" % n} for n in range(panel_api.MAX_EVENTS + 5)]
        got = self.snapshot(item(events=many + [{"text": ""}, "junk"]))["items"][0]["events"]
        self.assertEqual(len(got), panel_api.MAX_EVENTS - 2)
        self.assertEqual(got[-1]["text"], "event %d" % (panel_api.MAX_EVENTS + 4))

    # ─── text is text ────────────────────────────────────────────────────────

    def test_markup_is_kept_verbatim_never_interpreted(self):
        title = '<img src=x onerror="alert(1)"> **bold** [link](javascript:x) &amp; {{x}}'
        got = self.snapshot(item(target=dict(item()["target"], title=title)))["items"][0]["target"]["title"]
        self.assertEqual(got, title)

    def test_control_and_bidi_characters_are_removed(self):
        rlo, zwsp, nul = chr(0x202E), chr(0x200B), chr(0)
        got = self.snapshot(item(target=dict(item()["target"], title="ok%s%s%sdone\nnext" % (rlo, zwsp, nul))))
        self.assertEqual(got["items"][0]["target"]["title"], "okdone next")

    def test_long_text_is_capped(self):
        got = self.snapshot(item(target=dict(item()["target"], title="t" * 5000),
                                 events=[{"at": None, "text": "e" * 5000}]))["items"][0]
        self.assertEqual(len(got["target"]["title"]), panel_api.MAX_TITLE)
        self.assertTrue(got["target"]["title"].endswith(panel_api.ELLIPSIS))
        self.assertEqual(len(got["events"][0]["text"]), panel_api.MAX_TEXT)

    def test_reading_never_writes(self):
        self.snapshot(item())
        before = os.listdir(self.tmp)
        with open(self.path, "rb") as fh:
            content = fh.read()
        panel_api.read_snapshot()
        self.assertEqual(os.listdir(self.tmp), before)
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), content)

    def test_notify_without_hermes_is_a_quiet_no(self):
        try:
            import hermes_cli.plugin_events  # noqa: F401
        except ImportError:
            self.assertFalse(panel_api.notify_changed())
        else:
            self.assertTrue(panel_api.notify_changed())

    def test_lone_surrogates_and_line_separators_are_removed(self):
        self.write(r'{"version": 1, "items": [{"id": "x", "stage": "gate", "target": {"title": "a\ud800b\u2028c"}}]}')
        title = panel_api.read_snapshot()["items"][0]["target"]["title"]
        self.assertEqual(title, "abc")
        title.encode("utf-8")

    def test_duplicate_ids_keep_the_first(self):
        snap = self.snapshot(item(repo="first"), item(repo="second"))
        self.assertEqual([i["repo"] for i in snap["items"]], ["first"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs named pipes")
    def test_a_named_pipe_in_its_place_is_not_opened(self):
        os.mkfifo(self.path)
        self.assertEqual(panel_api.read_snapshot()["problem"], "unreadable")


if __name__ == "__main__":
    unittest.main()
