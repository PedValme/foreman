"""The reviewer outside Hermes: a fresh session of the harness itself (PRODUCTO.md, rule 25).

In Hermes the review asks a second model through the host's own model access. Another harness gives a plugin no such
access, and it has something else: its own command to run one prompt without an interface. So here the reviewer is a
session of that same harness, started by Foreman, that did not write the code: no tools, no project settings, only
the diff in and one JSON object out. Which model and how much effort is the person's to choose
(``/foreman reviewer``); with nothing chosen it is the harness's default model one effort level above the session
that asked, and the review says so in plain words.

Everything else is ``plugin/foreman/review.py`` as it is: the prompt, the fence around the untrusted diff, the check
that every finding quotes a line of the diff, the verdict, the cache (the same diff by the same reviewer is never
sent twice) and the stored record. It runs here through the context it already takes: ``_Context`` is the part of
Hermes's plugin context the review uses, with the model call replaced by ``Host.fresh_session``.

Foreman launches the reviewer, never the agent that wrote the code: the verdict must not pass through the author's
hands. The person's command is the only way in (``core.person_reply``).
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from typing import Optional

from foreman import detector, grants, review

from . import core

logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"          # in Foreman's state directory: the person's choices, per harness
REVIEW_BUDGET_SECONDS = 420.0        # for one review, retries included (the harness's hook has its own limit)
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@#+-]{0,119}$")
_UNSET = ("default", "none", "reset", "clear")


# ─── The person's choice ─────────────────────────────────────────────────────

def _config_path() -> str:
    return os.path.join(grants.store_dir(), CONFIG_FILE)


def _config() -> dict:
    try:
        with open(_config_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def setting(host: core.Host) -> tuple:
    """(model, effort) the person chose for this harness; "" for what was not chosen."""
    chosen = (_config().get("reviewer") or {}).get(host.name) if isinstance(_config().get("reviewer"), dict) else None
    chosen = chosen if isinstance(chosen, dict) else {}
    model = chosen.get("model") if isinstance(chosen.get("model"), str) else ""
    effort = chosen.get("effort") if isinstance(chosen.get("effort"), str) else ""
    return (model if _MODEL_NAME.match(model) else ""), (effort if effort in host.efforts else "")


def _save_setting(host: core.Host, model: str, effort: str) -> None:
    data = _config()
    reviewers = data.get("reviewer") if isinstance(data.get("reviewer"), dict) else {}
    if model or effort:
        reviewers[host.name] = {"model": model, "effort": effort}
    else:
        reviewers.pop(host.name, None)
    data["reviewer"] = reviewers
    path = _config_path()
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ─── Who reviews ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Plan:
    model: str          # "" = the harness's default model
    effort: str         # "" = the harness's default effort
    raised_from: str    # the session's effort this plan is one level above; "" when it is not that
    chosen: bool        # the person set something
    author: core.Session

    @property
    def token(self) -> str:
        """A name for this reviewer: the review's cache keeps one result per diff and reviewer."""
        return "%s@%s" % (self.model or "default", self.effort or "default")


def plan(host: core.Host) -> Plan:
    model, effort = setting(host)
    author = host.session() or core.Session()
    if model or effort:
        return Plan(model, effort, "", True, author)
    levels = list(host.efforts)
    if author.effort in levels:
        at = levels.index(author.effort)
        return Plan("", levels[min(at + 1, len(levels) - 1)], author.effort, False, author)
    return Plan("", "", "", False, author)


def describe(host: core.Host, p: Plan, ran: str = "") -> list:
    """Who reviewed, in plain words, with what is and is not known about its independence."""
    how_to = "`%s <model> [effort]`" % host.person("reviewer")
    answered = " It was answered by %s." % ran if ran else ""
    if p.chosen:
        who = p.model or "%s's default model" % host.label
        line = "Reviewer: %s%s, in a fresh session that did not write the code (your `%s` choice).%s" % (
            who, " at effort %s" % p.effort if p.effort else "", host.person("reviewer"), answered)
        if p.model and p.author.model and review.same_model_id(p.model, p.author.model):
            return [line, "It is the same model that wrote the code%s."
                    % (": only the effort differs" if p.effort and p.effort != p.author.effort else "")]
        if not p.model:
            return [line, "It is the model that wrote the code unless this session uses another one."]
        if not p.author.model:
            return [line, "%s does not tell Foreman which model wrote the code, so whether this one differs is "
                          "for you to know." % host.label]
        return [line]
    default = "%s's default model" % host.label
    same = "the model that wrote the code unless this session uses another one"
    if p.raised_from and p.effort != p.raised_from:
        return ["Reviewer: %s at effort %s, one level above this session's %s, in a fresh session that did not "
                "write the code.%s" % (default, p.effort, p.raised_from, answered),
                "That is %s: more effort and a clean context, not another model. Choose another with %s."
                % (same, how_to)]
    if p.raised_from:
        return ["Reviewer: %s at effort %s, the highest there is and the same as this session's, in a fresh session "
                "that did not write the code.%s" % (default, p.effort, answered),
                "That is %s, with a clean context only. Choose another with %s." % (same, how_to)]
    return ["Reviewer: %s at its default effort, in a fresh session that did not write the code.%s"
            % (default, answered),
            "That is %s, and %s does not tell Foreman this session's effort, so it was not raised. Choose a reviewer "
            "with %s." % (same, host.label, how_to)]


# ─── The review ──────────────────────────────────────────────────────────────

class _Context:
    """The part of Hermes's plugin context ``review.py`` uses, for a harness that is not Hermes."""

    def __init__(self, host: core.Host, p: Plan):
        self.host, self.plan = host, p
        self.llm = self
        self.deadline = time.monotonic() + REVIEW_BUDGET_SECONDS

    def get_config(self, key: str, default=None):
        # The review reads its reviewer from here and keeps one stored result per diff and reviewer: give it the
        # reviewer's name, so a change of model or effort is a new review and the same one is never sent twice.
        return self.plan.token if key == "reviewer_model" else default

    def has_capability(self, _name: str) -> bool:
        return True  # Hermes's grant for a plugin to pick another model: the person picked it here themselves

    def complete_structured(self, instructions: str = "", input=None, json_schema=None, system_prompt: str = "",
                            timeout=None, **_hermes_only) -> core.Answer:
        left = self.deadline - time.monotonic()
        if left < 15:
            raise RuntimeError("the review ran out of its %d seconds" % int(REVIEW_BUDGET_SECONDS))
        blocks = [b.get("text", "") for b in (input or []) if isinstance(b, dict) and isinstance(b.get("text"), str)]
        prompt = "\n\n".join([instructions] + blocks)
        seconds = min(float(timeout or review.LLM_TIMEOUT_SECONDS), left)
        answer = self.host.fresh_session(system_prompt, prompt, json_schema or {}, self.plan.model, self.plan.effort,
                                         seconds)
        if not isinstance(answer, core.Answer):
            raise RuntimeError("the reviewer's session gave no answer Foreman can read")
        return answer


_HERMES_NOTES = (review.SAME_MODEL, review.UNKNOWN_MODEL, review.TASK_SAME_MODEL, review.TASK_UNSURE,
                 review.ROUTED_MODEL)


def _present(text: str, host: core.Host, p: Plan, record: dict) -> str:
    """The review as ``review.py`` prints it, with Hermes's lines about its reviewer replaced by this harness's."""
    model = record.get("model") if isinstance(record.get("model"), dict) else {}
    ran = str(model.get("ran") or "") if not record.get("error") else ""
    out = []
    for line in text.split("\n"):
        if line in _HERMES_NOTES:
            continue
        if line.startswith("Reviewer: "):
            out += describe(host, p, ran)
            continue
        out.append(line)
    return "\n".join(out)


def run(host: core.Host, args: str, cwd: str) -> str:
    """``review [<pull request>|<branch>] [--fresh]``: the current branch and its uncommitted changes by default."""
    if host.fresh_session is None:
        return "Foreman: the review is not available in %s yet." % host.label
    if not cwd or not os.path.isdir(cwd):
        return "Foreman review: this session has no working directory to find the repository from."
    root = detector.find_repo(cwd)
    if not root:
        return "Foreman review: %s is not inside a git repository." % cwd
    words = (args or "").split()
    fresh = "--fresh" in words
    target = [w for w in words if w != "--fresh"]
    if len(target) > 1:
        return "Foreman review: one target at most (a pull request number or a branch); got `%s`." % " ".join(target)
    p = plan(host)
    record = review.run_review(target[0] if target else "", where=root, ctx=_Context(host, p), fresh=fresh)
    try:
        review.record_in_pipeline(record)
    except Exception:
        logger.warning("foreman: cannot record the review", exc_info=True)
    return _present(review.format_review(record, "cli"), host, p, record)


def configure(host: core.Host, args: str) -> str:
    """``reviewer`` shows who reviews; ``reviewer <model> [effort]`` or ``reviewer <effort>`` sets it;
    ``reviewer default`` goes back to the default."""
    if host.fresh_session is None:
        return "Foreman: the review is not available in %s yet." % host.label
    words = (args or "").split()
    levels = ", ".join(host.efforts) or "none in %s" % host.label
    if not words:
        lines = describe(host, plan(host))
        lines[0] = lines[0].replace("Reviewer: ", "Foreman's reviewer in %s: " % host.label, 1)
        return "\n".join(lines + ["Effort levels: %s. `%s default` goes back to the default."
                                  % (levels, host.person("reviewer"))])
    if len(words) == 1 and words[0].lower() in _UNSET:
        _save_setting(host, "", "")
        return "\n".join(["Foreman: the reviewer is back to the default."] + describe(host, plan(host)))
    if len(words) > 2:
        return "Foreman: `%s <model> [effort]`, `%s <effort>` or `%s default`." % (
            host.person("reviewer"), host.person("reviewer"), host.person("reviewer"))
    model, effort = (words + [""])[:2]
    if len(words) == 1 and model.lower() in host.efforts:
        model, effort = "", model.lower()
    effort = effort.lower()
    if effort and effort not in host.efforts:
        return "Foreman: `%s` is not an effort level of %s (%s)." % (effort, host.label, levels)
    if model and not _MODEL_NAME.match(model):
        return "Foreman: `%s` does not look like a model name." % model[:60]
    _save_setting(host, model, effort)
    return "\n".join(["Foreman: reviewer set."] + describe(host, plan(host)))
