"""Self-adoption uses the existing session once its command/turn finishes.

Real CLI, native transcripts, Git, persistence and tick; external I/O is faked
by the approved adoption fixture, which this file leaves unchanged.
"""
from datetime import timedelta
import os
from unittest import mock

import chief
from adoption_support import AdoptionFixture, NOTICE, READY, SID

REAL_WAIT_READY = chief.wait_ready


class AdoptSelfAcceptanceTests(AdoptionFixture):
    def self_adopt(self, tool="codex", *flags):
        self.rec.update(tool=tool, status="running")
        self.write_records()
        self.conversation(prompt="Adopt this conversation and implement our plan.",
                          minutes=0.1, finished=False)
        with mock.patch.dict(os.environ, TMUX="/tmp/self-adopt-tmux,12,0"):
            task = self.adopt("--check", "python3 -c 'pass'", *flags, session=None)
        self.assertEqual(task["state"], "needs-you")
        self.assertFalse(task.get("kickoff_at"))
        self.assertIn("chief kickoff " + task["id"], task["note"])
        self.deliver.assert_not_called()
        return task

    def ready_session(self):
        self.rec["status"] = "idle"
        self.screen_text = READY
        self.write_records()

    def assert_notice_delivered(self, task):
        self.deliver.assert_called_once()
        self.assertEqual(self.deliver.call_args[0][1], SID)
        self.assertIn(NOTICE, self.deliver.call_args[0][2])
        stored = chief.load_task(task["id"])
        self.assertEqual(stored["state"], "running")
        self.assertTrue(stored.get("kickoff_at"))
        self.assertFalse(stored.get("note"))
        self.assertTrue(any("adoption" in event["text"].lower()
                            for event in chief.events_since(stored, None)))

    def run_self_adoption(self, tool):
        task = self.self_adopt(tool)
        self.assertIn("automatically", task["note"].lower())
        chief.tick(self.cfg)
        self.assert_session_untouched()
        self.now += timedelta(seconds=15)
        self.ready_session()
        chief.tick(self.cfg)
        self.assert_notice_delivered(task)
        # A real delivery starts a new turn. Subsequent ticks must not resend
        # the initial notice, whether the worker is busy or has finished it.
        self.rec["status"] = "running"
        self.write_records()
        chief.tick(self.cfg)
        self.now += timedelta(minutes=1)
        self.ready_session()
        self.conversation(prompt=NOTICE, minutes=0.5)
        chief.tick(self.cfg)
        chief.tick(self.cfg)
        self.deliver.assert_called_once()

    def test_codex_busy_self_adoption_delivers_once_on_next_ready_tick(self):
        self.run_self_adoption("codex")

    def test_claude_busy_self_adoption_delivers_once_on_next_ready_tick(self):
        self.run_self_adoption("claude")

    def test_prompt_started_before_adoption_does_not_pause_automation(self):
        self.conversation(prompt="Adopt this conversation.", minutes=0.1)
        task = self.adopt("--check", "python3 check.py")
        self.deliver.reset_mock()
        self.assertFalse(chief.user_present(self.cfg, task, chief.transcript(self.rec)))
        self.assertFalse(any(kind == "presence" for _, _, kind in self.item()["signals"]))
        chief.tick(self.cfg)
        self.deliver.assert_called_once()
        self.assertIn(chief.CONTINUE_MARK, self.deliver.call_args[0][2])

    def test_human_prompt_after_adoption_still_pauses_then_notice_resumes(self):
        task = self.self_adopt()
        self.now += timedelta(minutes=1)
        self.ready_session()
        self.conversation(prompt="Wait, let us discuss one detail first.", minutes=0.5)
        self.assertTrue(chief.user_present(self.cfg, task, chief.transcript(self.rec)))
        chief.tick(self.cfg)
        self.deliver.assert_not_called()
        self.assertFalse(chief.load_task(task["id"]).get("kickoff_at"))
        self.assertTrue(any(kind == "presence" for _, _, kind in self.item()["signals"]))
        self.now += timedelta(minutes=10)
        chief.tick(self.cfg)
        self.assert_notice_delivered(task)

    def test_pending_notice_never_types_into_busy_stopped_or_menu_sessions(self):
        task = self.self_adopt()
        self.now += timedelta(minutes=11)  # Isolate readiness from the presence bug.
        for status, screen in (
                ("running", READY), ("stopped", READY),
                ("idle", "Do you trust the contents of this project?\n> Yes, I trust this folder\n  No, exit\n"),
                ("waiting", "Accept this file edit?\n> 1. Yes\n  2. No\n"),
                ("idle", "worker is drawing its UI")):
            with self.subTest(status=status, screen=screen):
                self.rec["status"], self.screen_text = status, screen
                self.write_records()
                with mock.patch.object(chief, "wait_ready", side_effect=REAL_WAIT_READY):
                    chief.tick(self.cfg)
                self.assert_session_untouched()
                self.assertFalse(chief.load_task(task["id"]).get("kickoff_at"))
        self.ready_session()
        chief.tick(self.cfg)
        self.assert_notice_delivered(task)

    def test_dry_tick_describes_pending_delivery_without_sending(self):
        task = self.self_adopt()
        self.now += timedelta(minutes=11)
        self.ready_session()
        actions = chief.tick(self.cfg, dry=True)
        self.assertTrue(any("adoption" in action.lower() for action in actions))
        self.deliver.assert_not_called()
        self.assertFalse(chief.load_task(task["id"]).get("kickoff_at"))
        chief.tick(self.cfg)
        self.assert_notice_delivered(task)

    def test_new_human_prompt_during_readiness_probe_defers_notice(self):
        task = self.self_adopt()
        self.now += timedelta(minutes=11)
        self.ready_session()

        def user_arrives(*args, **kwargs):
            self.conversation(prompt="Pause while I explain another constraint.", minutes=0.1)
            return "ready"

        with mock.patch.object(chief, "wait_ready", side_effect=user_arrives):
            chief.tick(self.cfg)
        self.deliver.assert_not_called()
        self.assertFalse(chief.load_task(task["id"]).get("kickoff_at"))
        self.now += timedelta(minutes=10)
        chief.tick(self.cfg)
        self.assert_notice_delivered(task)

    def test_unconfirmed_delivery_is_not_retried_automatically(self):
        task = self.self_adopt()
        self.now += timedelta(minutes=11)
        self.ready_session()
        self.deliver.return_value = False
        chief.tick(self.cfg)
        self.deliver.assert_called_once()
        self.assertTrue(chief.load_task(task["id"]).get("kickoff_at"))
        self.assertEqual(chief.load_task(task["id"])["state"], "needs-you")
        chief.tick(self.cfg)
        self.deliver.assert_called_once()

    def test_delivery_error_does_not_cause_an_automatic_duplicate(self):
        task = self.self_adopt()
        self.now += timedelta(minutes=11)
        self.ready_session()
        self.deliver.side_effect = RuntimeError("connection lost after sending")
        chief.tick(self.cfg)
        self.deliver.assert_called_once()
        stored = chief.load_task(task["id"])
        self.assertTrue(stored.get("kickoff_at"))
        self.assertEqual(stored["state"], "needs-you")
        self.assertIn("chief kickoff " + task["id"], stored["note"])
        chief.tick(self.cfg)
        self.deliver.assert_called_once()

    def test_test_first_receives_pending_notice_before_waiting_for_approval(self):
        task = self.self_adopt("codex", "--test-first")
        self.ready_session()
        chief.tick(self.cfg)
        self.assert_notice_delivered(task)
        self.assertEqual(chief.load_task(task["id"])["phase"], "test")
        self.assertIn("approve the acceptance tests", self.deliver.call_args[0][2])
        chief.tick(self.cfg)
        self.deliver.assert_called_once()

    def test_observe_receives_pending_notice_without_automatic_recovery(self):
        task = self.self_adopt("codex", "--autonomy", "observe")
        self.ready_session()
        chief.tick(self.cfg)
        self.assert_notice_delivered(task)
        chief.tick(self.cfg)
        self.deliver.assert_called_once()
