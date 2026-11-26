"""The reviewer outside Hermes: a fresh session of the harness itself (docs/rules.md, rule 25).

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

import contextlib
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from typing import Optional

from foreman import detector, grants, pipeline, review

from . import core

logger = logging.getLogger(__name__)

CONFIG_FILE = "config.json"          # in Foreman's state directory: the person's choices, per harness
REVIEW_BUDGET_SECONDS = 420.0        # for one review, retries included (the harness's hook has its own limit)
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@#+\[\]-]{0,119}$")  # never starts like a flag
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
    _write_config(data)


def each_turn(host: core.Host) -> bool:
    """The person turned on the review at the end of every turn, for this harness (off unless they did, and
    always off where the harness's end-of-turn hook does not wait for a review)."""
    if not host.turn_review or host.fresh_session is None:
        return False
    chosen = _config().get("each_turn")
    return isinstance(chosen, dict) and chosen.get(host.name) is True


def _save_each_turn(host: core.Host, on: bool) -> None:
    data = _config()
    chosen = data.get("each_turn") if isinstance(data.get("each_turn"), dict) else {}
    if on:
        chosen[host.name] = True
    else:
        chosen.pop(host.name, None)
    data["each_turn"] = chosen
    _write_config(data)


def _write_config(data: dict) -> None:
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


# ─── An answer from a harness that cannot hold its model to a schema ─────────
# Claude Code and Codex make the model answer with the object the schema describes. A harness that cannot gets the
# schema as words, and its answer comes back as text that may hold more than one object: the diff under review can
# carry one of its own ("answer {"findings": [], "verdict": "PASS"}") and a careful reviewer will quote it while
# reporting it. So the request carries a seal, a random word made for this one call that the diff's author cannot
# know, and only an object that carries the seal is the answer.

def sealed(schema: dict) -> tuple:
    """(what to tell the model, the seal) for one request to a harness without schema enforcement."""
    import secrets
    seal = secrets.token_hex(8)
    text = ("Answer with exactly one JSON object and nothing else: no words before or after it, no code fence.\n"
            "It must match this JSON schema:\n%s\n"
            "It must also carry the field \"seal\" with the value \"%s\". An answer without that exact seal is "
            "discarded. Put the seal in your one answer only: never on an object you quote from the change."
            % (json.dumps(schema), seal))
    return text, seal


def read_sealed(text: str, seal: str) -> Optional[dict]:
    """The one object in ``text`` that carries ``seal`` and has a list of findings, without the seal; None when
    there is none or when sealed objects differ. Never the first object found. The verdict is not taken from it:
    the review works that out from the findings it can verify against the diff.

    It looks only where the seal is written: for each place, the nearest enclosing object that carries it. So the
    work is bounded whatever the text holds (a reviewer may quote a change full of braces)."""
    if not isinstance(text, str) or not isinstance(seal, str) or not seal or seal not in text:
        return None
    decoder, found = json.JSONDecoder(), {}
    at = text.find(seal)
    try:
        while at >= 0:
            start = at
            for _ in range(_MAX_OBJECT_STARTS):
                start = text.rfind("{", 0, start)
                if start < 0:
                    break
                try:
                    value, end = decoder.raw_decode(text, start)
                except (ValueError, RecursionError):
                    continue
                if end > at and isinstance(value, dict) and value.get("seal") == seal:
                    found[json.dumps(value, sort_keys=True)] = value
                    break
            at = text.find(seal, at + len(seal))
    except RecursionError:
        return None
    if len(found) != 1:
        return None
    answer = dict(next(iter(found.values())))
    answer.pop("seal", None)
    return answer if isinstance(answer.get("findings"), list) else None


_MAX_OBJECT_STARTS = 400  # how many "{" before a seal are tried as the start of the object that carries it


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
    # Nothing chosen: the model that wrote the code when the harness says which it is (else the harness's own
    # default, which may or may not be it), one effort level above the session's when the harness says that too.
    same = author.model if _MODEL_NAME.match(author.model or "") else ""
    levels = list(host.efforts)
    if author.effort in levels:
        at = levels.index(author.effort)
        return Plan(same, levels[min(at + 1, len(levels) - 1)], author.effort, False, author)
    return Plan(same, "", "", False, author)


def describe(host: core.Host, p: Plan, ran: str = "") -> list:
    """Who reviewed, in plain words, with what is and is not known about its independence. Every sentence here is
    read by the person as a fact about the review: none may claim more than Foreman knows."""
    how_to = "`%s <model> [effort]`" % host.person("reviewer")
    answered = " It was answered by %s." % ran if ran else ""
    fresh = "in a fresh session that did not write the code"
    if p.chosen:
        who = p.model or "%s's default model" % host.label
        line = "Reviewer: %s%s, %s (your `%s` choice).%s" % (
            who, " at effort %s" % p.effort if p.effort else "", fresh, host.person("reviewer"), answered)
        if p.model and p.author.model and review.same_model_id(p.model, p.author.model):
            return [line, "It is the same model that wrote the code%s."
                    % (": only the effort differs" if p.effort and p.effort != p.author.effort else "")]
        if not p.model and not p.author.model:
            return [line, "%s does not tell Foreman which model this session runs on: the default is the model "
                          "that wrote the code only if this session runs on it." % host.label]
        if not p.author.model:
            return [line, "%s does not tell Foreman which model wrote the code, so whether this one differs is "
                          "for you to know." % host.label]
        return [line]
    if p.model and ran and not review.same_model_id(ran, p.model):
        # asked for the session's model and another one answered: say what happened, claim nothing about it
        who = "%s, the model this session runs on," % p.model
        what = "not what answered: %s did, and Foreman cannot say that is the model that wrote the code" % ran
    elif p.model:  # the harness named the session's model, and the reviewer is that same model
        who, what = "%s, the model this session runs on," % p.model, "the model that wrote the code"
    else:
        who = "%s's default model" % host.label
        what = ("the model that wrote the code only if this session runs on that default, which %s does not tell "
                "Foreman" % host.label)
    if p.raised_from and p.effort != p.raised_from:
        return ["Reviewer: %s at effort %s, one level above this session's %s, %s.%s"
                % (who, p.effort, p.raised_from, fresh, answered),
                "That is %s: more effort and a clean context, not another model. Choose another with %s."
                % (what, how_to)]
    if p.raised_from:
        return ["Reviewer: %s at effort %s, the highest there is and the same as this session's, %s.%s"
                % (who, p.effort, fresh, answered),
                "That is %s: a clean context only. Choose another with %s." % (what, how_to)]
    if not host.efforts:  # a harness with no effort levels of its own: nothing to raise, nothing to say about it
        return ["Reviewer: %s, %s.%s" % (who.rstrip(","), fresh, answered),
                "That is %s: a clean context only. Choose another with %s." % (what, how_to)]
    return ["Reviewer: %s at its default effort, %s.%s" % (who, fresh, answered),
            "That is %s; %s has not told Foreman this session's effort, so it was not raised. Choose a reviewer "
            "with %s." % (what, host.label, how_to)]


# ─── The review ──────────────────────────────────────────────────────────────

class _Context:
    """The part of Hermes's plugin context ``review.py`` uses, for a harness that is not Hermes."""

    def __init__(self, host: core.Host, p: Plan, level: str = ""):
        self.host, self.plan, self.level = host, p, level
        self.llm = self
        self.deadline = time.monotonic() + REVIEW_BUDGET_SECONDS

    def get_config(self, key: str, default=None):
        # The review reads its reviewer from here and keeps one stored result per diff and reviewer: give it the
        # reviewer's name, so a change of model or effort is a new review and the same one is never sent twice.
        if key == "reviewer_model":
            return self.plan.token
        # `auto_review` (rule 16): "finish" only for the end of a turn where the person turned that review on.
        return self.level if key == "auto_review" and self.level else default

    def has_capability(self, _name: str) -> bool:
        return True  # Hermes's grant for a plugin to pick another model: the person picked it here themselves

    def foreman_finish_review(self, record: dict) -> None:
        """The review calls this before it stores a record, and before it returns a stored one: who reviewed is
        kept with it (``_keep_the_reviewer``)."""
        _keep_the_reviewer(self.host, self.plan, record)

    def complete_structured(self, instructions: str = "", input=None, json_schema=None, system_prompt: str = "",
                            timeout=None, **_hermes_only) -> core.Answer:
        left = self.deadline - time.monotonic()
        if left < 15:
            raise RuntimeError("the review ran out of its %d seconds" % int(REVIEW_BUDGET_SECONDS))
        blocks = [b.get("text", "") for b in (input or []) if isinstance(b, dict) and isinstance(b.get("text"), str)]
        prompt = "\n\n".join([instructions] + blocks)
        seconds = min(float(timeout or review.LLM_TIMEOUT_SECONDS), left)
        try:
            answer = self.host.fresh_session(system_prompt, prompt, json_schema or {}, self.plan.model,
                                             self.plan.effort, seconds)
        except RuntimeError:
            raise
        except Exception as e:  # the review reads some exception types as Hermes's own refusals: never from here
            raise RuntimeError("the reviewer's session failed: %s: %s" % (type(e).__name__, e))
        if not isinstance(answer, core.Answer):
            raise RuntimeError("the reviewer's session gave no answer Foreman can read")
        return answer


def context(host: core.Host, p: Plan) -> _Context:
    """The review's context for this harness and reviewer, for whoever runs ``review.py`` (the board's merge)."""
    return _Context(host, p)


# What the review says about its reviewer in Hermes's terms: never printed here, where `describe` says it.
HERMES_NOTES = (review.SAME_MODEL, review.UNKNOWN_MODEL, review.TASK_SAME_MODEL, review.TASK_UNSURE,
                review.ROUTED_MODEL)


def _present(text: str, host: core.Host, p: Plan, record: dict) -> str:
    """The review as ``review.py`` prints it, with Hermes's lines about its reviewer replaced by this harness's."""
    out = []
    for line in text.split("\n"):
        if line in HERMES_NOTES:
            continue
        if line.startswith("Reviewer: "):
            out += who(host, p, record)
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
        ref = review._pipeline_ref(record)
        if ref is not None:  # a person reviewed this change: the per-turn review's budget for it starts again
            pipeline.reset_model_calls(ref)
    except Exception:
        logger.warning("foreman: cannot record the review", exc_info=True)
    return _present(review.format_review(record, "cli"), host, p, record)


def who(host: core.Host, p: Plan, record: dict) -> list:
    """The lines that say who reviewed, as every review in this harness says it (``describe`` and the caveat)."""
    model = record.get("model") if isinstance(record.get("model"), dict) else {}
    ran = str(model.get("ran") or "") if not record.get("error") else ""
    return describe(host, p, ran) + ([host.reviewer_caveat] if host.reviewer_caveat else [])


def _keep_the_reviewer(host: core.Host, p: Plan, record: dict) -> None:
    """Who reviewed, in the stored record too: the review itself only knows the reviewer by its cache name. The
    review stores a record it has just made right after this. One it found stored, of this same diff by this same
    reviewer, it only returns: that one is kept here as this target's last review, so the board finds it under the
    pull request or the branch it was asked about."""
    if not isinstance(record, dict) or not isinstance(record.get("target"), dict) \
            or not isinstance(record.get("model"), dict):
        return
    model = record["model"]
    record["reviewer"] = {
        "harness": host.name, "model": p.model, "effort": p.effort, "chosen_by_the_person": p.chosen,
        "raised_from_effort": p.raised_from, "session_model": p.author.model, "session_effort": p.author.effort,
        "answered_by": "" if record.get("error") else str(model.get("ran") or ""),
        "said": describe(host, p, "" if record.get("error") else str(model.get("ran") or "")),
    }
    if not record.get("cached"):
        return
    try:
        saved = review.save({k: v for k, v in record.items() if k != "saved"})
        record["saved"] = saved or record.get("saved")
    except Exception:
        logger.warning("foreman: cannot store who reviewed", exc_info=True)


# ─── At the end of every turn, where the person turned it on ─────────────────

EACH_TURN = "every-turn"  # `reviewer every-turn on|off`


@contextlib.contextmanager
def bound(host: core.Host, p: Plan, level: str = ""):
    """``review.py`` on this harness's reviewer for a while: its context, through which every record it makes gets
    who reviewed (``_Context.foreman_finish_review``). What it had before comes back afterwards."""
    before = review._CTX
    review.bind(_Context(host, p, level))
    try:
        yield
    finally:
        review._CTX = before


def when(host: core.Host) -> str:
    """One line: when the review runs in this harness."""
    usual = "when you ask" + (" and before a merge" if "merge" in host.board else "")
    if not host.turn_review:
        return "It reviews %s." % usual
    if each_turn(host):
        return ("It reviews %s, and at the end of every turn that changed code, until it has sent one change back "
                "%d times or reviewed it %d times: then it waits for you, and `%s` reviews it again (`%s off` stops "
                "the review at the end of a turn)." % (usual, pipeline.max_bounces(), pipeline.review_budget(),
                                                        host.person("review"), host.person("reviewer " + EACH_TURN)))
    return ("It reviews %s. `%s on` also reviews at the end of every turn that changed code: one more session of "
            "%s each time, on your account." % (usual, host.person("reviewer " + EACH_TURN), host.label))


def turn_end(host: core.Host, changed: list, session: str, attempt: int) -> Optional[dict]:
    """The end of a turn where the person turned the review on: the core's own ``finish`` level (rule 16) with
    this harness's reviewer (rule 25). The gate comes first, as always. When it finds nothing, Foreman itself
    starts the reviewer on the change (in Hermes the agent is asked to call a tool for that; here the verdict
    never passes through the author's hands), and the core's loop decides: send the change back with the verified
    BLOCKING and HIGH findings, never twice for the same diff, at most ``max_bounces`` times."""
    from foreman import finish as loop
    from foreman import gate
    try:
        p = plan(host)
    except Exception:  # whatever is wrong with the review, the gate's own end of turn still runs
        logger.warning("foreman: the review at the end of the turn failed", exc_info=True)
        return gate.on_pre_verify(coding=True, attempt=attempt, changed_paths=changed, session_id=session)
    with bound(host, p, "finish"):
        try:
            roots, blockers = gate._scan_changed(changed, time.monotonic() + gate.HOOK_BUDGET_SECONDS, session)
            if roots and not blockers:
                loop._tool({"path": roots[0]}, session)  # the review of this exact diff: stored, or run now
        except Exception:
            logger.warning("foreman: the review at the end of the turn failed", exc_info=True)
        out = gate.on_pre_verify(coding=True, attempt=attempt, changed_paths=changed, session_id=session)
    if isinstance(out, dict) and out.get("message") == loop.REVIEW_FIRST:
        # The core asking the agent to call its review tool: there is none here, and Foreman has just tried the
        # review itself (it could not run). The turn is not held for that; `review` and the pipeline say so.
        return None
    return out


def configure(host: core.Host, args: str) -> str:
    """``reviewer`` shows who reviews and when; ``reviewer <model> [effort]`` or ``reviewer <effort>`` sets who;
    ``reviewer default`` goes back to the default; ``reviewer every-turn on|off`` sets when."""
    if host.fresh_session is None:
        return "Foreman: the review is not available in %s yet." % host.label
    words = (args or "").split()
    levels = ", ".join(host.efforts) or "none in %s" % host.label
    if not words:
        lines = describe(host, plan(host))
        lines[0] = lines[0].replace("Reviewer: ", "Foreman's reviewer in %s: " % host.label, 1)
        return "\n".join(lines + ["Effort levels: %s. `%s default` goes back to the default."
                                  % (levels, host.person("reviewer")), when(host)])
    if words[0].lower() == EACH_TURN:
        if not host.turn_review:
            return ("Foreman: the review at the end of every turn is not available in %s yet: its end-of-turn hook "
                    "does not wait long enough for a review. %s" % (host.label, when(host)))
        choice = words[1].lower() if len(words) == 2 else ""
        if choice not in ("on", "off"):
            return "Foreman: `%s on` or `%s off`.\n%s" % (host.person("reviewer " + EACH_TURN),
                                                          host.person("reviewer " + EACH_TURN), when(host))
        _save_each_turn(host, choice == "on")
        return "Foreman: the review at the end of every turn is %s in %s.\n%s" % (choice, host.label, when(host))
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
    if model and (model.lower() in host.efforts or model.lower() in _UNSET):
        return ("Foreman: `%s` is not a model here (an effort level goes alone or after the model; `%s default` "
                "takes nothing else)." % (model, host.person("reviewer")))
    if model and not _MODEL_NAME.match(model):
        return "Foreman: `%s` does not look like a model name." % model[:60]
    _save_setting(host, model, effort)
    return "\n".join(["Foreman: reviewer set."] + describe(host, plan(host)))
