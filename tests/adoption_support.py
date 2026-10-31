"""Synthetic AoE sessions, native transcripts, and real Git for adopt acceptance.

Only external session I/O and time are faked. CLI dispatch, persistence,
transcript parsing, checks, scope scans, decisions and tick stay real.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from unittest import mock

import chief
from test_intent_task_flow import ChiefFixture


SID = "0123456789abcdef"
AGENT_ID = "00000000-0000-4000-8000-000000000001"
NOTICE = "AoE Chief: this conversation is now a supervised task"
GOAL = "Carry out the plan agreed earlier in this conversation."
READY = "\n> \n? for shortcuts\n"
FINAL = ("Conclusion: Implemented the next part of the plan.\n"
         "Evidence: ran the checks\nBlockers: none\n"
         "Next step: finish the plan\nDecision needed: none")


class AdoptionFixture(ChiefFixture):
    def patch(self, obj, name, **kwargs):
        patcher = mock.patch.object(obj, name, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, AOE_CHIEF_HOME=str(self.home), AOE_CHIEF_LANG="en")
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("TMUX", None)
        self.now = datetime(2030, 1, 2, 12, tzinfo=timezone.utc)
        self.patch(chief, "now_utc", side_effect=lambda: self.now)
        for name in ("AOE_HOME", "CODEX_HOME", "CLAUDE_HOME", "ANTIGRAVITY_HOME"):
            self.patch(chief, name, new=self.root / name.lower())
        self.cfg.update(aoe_colors=False, decision_ai=False, review=False)
        chief.save_cfg(self.cfg)
        self.write("tests/test_existing.py", "import unittest\nclass Existing(unittest.TestCase):\n    pass\n")
        self.write("config/policy.txt", "original policy\n")
        self.write("src/app.py", "value = 1\n")
        self.write("check.py", "print('synthetic check failure')\nraise SystemExit(1)\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "agreed plan baseline")
        self.git("checkout", "-q", "-b", "agreed-plan")
        self.base = self.git("rev-parse", "HEAD")
        self.rec = dict(id=SID, title="Existing conversation", tool="codex", view="terminal",
                        project_path=str(self.repo), agent_session_id=AGENT_ID,
                        state="live", status="idle", archived=False)
        self.records = {SID: self.rec}
        self.operations = []
        self.tmux_operations = []
        self.screen_text = READY
        self.tmux_name = "aoe_plan_with_underscores_" + SID[:8]
        self.patch(chief, "aoe", side_effect=self.fake_aoe)
        self.patch(chief, "screen", side_effect=lambda *a: self.screen_text)
        self.deliver = self.patch(chief, "deliver", return_value=True)
        self.patch(chief, "wait_ready", side_effect=self.ready)
        real_call = chief.call

        def call(args, **kwargs):
            if args[0] == "tmux":
                self.tmux_operations.append(tuple(args))
                if args[1] in ("display-message", "display"):
                    return self.tmux_name + "\n"
                if args[1] == "list-sessions":
                    return self.tmux_name + "\n"
                raise AssertionError("Unexpected tmux write: " + repr(args))
            if args[0] != "git":
                raise RuntimeError("Unexpected external process: " + repr(args))
            return real_call(args, **kwargs)

        self.patch(chief, "call", side_effect=call)
        self.write_records()
        self.conversation()

    def write_records(self):
        path = chief.AOE_HOME / "profiles" / self.cfg["profile"] / "sessions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"sessions": list(self.records.values())}), encoding="utf-8")

    def fake_aoe(self, cfg, *args):
        self.operations.append(args)
        if args[0] == "list":
            return json.dumps(list(self.records.values()))
        if args[:2] == ("session", "show"):
            return json.dumps(self.records[args[-1]])
        # Record attempted mutations without ever reaching a real AoE session.
        return ""

    def ready(self, cfg, sid, trust=False, timeout=120):
        self.assertFalse(trust, "adoption must not auto-confirm trust or action menus")
        return "ready" if chief.at_prompt(self.rec["status"], self.screen_text) else "timeout"

    def conversation(self, prompt="Implement the plan we agreed.", minutes=20,
                     reply=FINAL, finished=True, error=False, title=None):
        """Write native formats; prompt age differs from reply age on purpose."""
        start = (self.now - timedelta(minutes=minutes)).isoformat()
        end = (self.now - timedelta(seconds=1)).isoformat()
        tool = self.rec["tool"]
        if tool == "claude":
            path = chief.CLAUDE_HOME / "projects" / "fixture" / (AGENT_ID + ".jsonl")
            rows = [dict(type="user", timestamp=start, message={"content": prompt}),
                    dict(type="assistant", timestamp=end, message={
                        "content": [{"type": "text", "text": reply}],
                        "stop_reason": "end_turn" if finished else None})]
            if title:
                rows.append(dict(type="ai-title", aiTitle=title))
        elif tool == "antigravity":
            path = chief.ANTIGRAVITY_HOME / "brain" / AGENT_ID / ".system_generated/logs/transcript.jsonl"
            rows = [dict(type="USER_INPUT", created_at=start, content=prompt),
                    dict(type="PLANNER_RESPONSE", created_at=end, content=reply,
                         status="DONE" if finished else "RUNNING")]
            mapping = chief.ANTIGRAVITY_HOME / "cache/last_conversations.json"
            mapping.parent.mkdir(parents=True, exist_ok=True)
            mapping.write_text(json.dumps({self.rec["project_path"]: AGENT_ID}), encoding="utf-8")
        else:
            path = chief.CODEX_HOME / "sessions/2030/01/02" / ("rollout-fixture-" + AGENT_ID + ".jsonl")
            rows = [dict(type="response_item", timestamp=start, payload={
                        "type": "message", "role": "user", "content": [{"text": prompt}]}),
                    dict(type="response_item", timestamp=end, payload={
                        "type": "message", "role": "assistant", "content": [{"text": reply}]})]
            if finished or error:
                rows.append(dict(type="event_msg", timestamp=end, payload={
                    "type": "turn_aborted" if error else "task_complete", "reason": "interrupted"}))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def adopt(self, *flags, session=SID):
        args = ["adopt"] + ([] if session is None else [session]) + list(flags)
        code, out, err = self.cli(*args)
        self.assertEqual(code, 0, out + err)
        tasks = [t for t in chief.all_tasks() if t.get("session_id") == SID and t.get("state") in chief.ACTIVE]
        self.assertEqual(len(tasks), 1, "adoption must create one active board task")
        return tasks[0]

    def seed_task(self, **changes):
        """Seed the specified record so safety tests don't all stop at CLI parsing."""
        task = dict(id="adopted-plan", name="Agreed plan", goal=GOAL, adopted=True,
                    repo=str(self.repo), worktree=str(self.repo), base=self.base,
                    branch="agreed-plan", session_id=SID, tool=self.rec["tool"],
                    state="running", phase="build", test_first=False, autonomy="suggest",
                    checks=["python3 check.py"], protected=["tests", "config"],
                    started_at=self.now.isoformat(), kickoff_at=self.now.isoformat(),
                    budget={"rounds": 15, "hours": 4})
        task.update(changes)
        chief.save_task(task)
        return task

    def item(self):
        result = chief.collect(self.cfg, persist=False)
        return next(x for x in result["items"] if x["id"] == SID)

    def snapshot(self):
        # Include Git refs, index, excludes, transcripts, config, and task files.
        return {str(p.relative_to(self.root)): p.read_bytes() if p.is_file() else None
                for p in self.root.rglob("*")}

    def assert_session_untouched(self):
        self.deliver.assert_not_called()
        self.assertEqual([op for op in self.operations
                          if op[0] != "list" and op[:2] != ("session", "show")], [])
        self.assertFalse(any(op[1] not in ("display-message", "display", "list-sessions")
                             for op in self.tmux_operations))

    def refused(self, *args, message):
        before = self.snapshot()
        code, out, err = self.cli(*args)
        self.assertNotEqual(code, 0, "must refuse rather than change the task/session")
        self.assertNotIn("invalid choice", err, "refusal must come from validation, not a missing command")
        self.assertRegex((out + err).lower(), message)
        self.assertEqual(self.snapshot(), before, "refusal must change nothing")
        self.assert_session_untouched()
