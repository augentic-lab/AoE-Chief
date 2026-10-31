"""Inbox adoption confirmation, release, and discoverability using a fake screen.

Uppercase A is the chosen free key. Drive the existing event loop so Enter and
Escape go through the same dispatch as real input, without prescribing new UI
methods or state fields. No curses terminal, AoE process, or AI is required.
"""
import os
from pathlib import Path
import threading
import unittest
from unittest import mock

import chief
import chief_tui as tui
from adoption_support import AdoptionFixture, GOAL, NOTICE, SID
from test_inbox_delegation import InboxFixture


class AdoptInboxTests(AdoptionFixture):
    ui = InboxFixture.ui
    idle = InboxFixture.idle
    frame = InboxFixture.frame

    def setUp(self):
        super().setUp()
        previous = os.getcwd()
        os.chdir(str(self.repo))
        self.addCleanup(os.chdir, previous)
        self.cfg["tracked_ids"] = [SID]
        chief.save_cfg(self.cfg)
        self.app = tui.Inbox(self.cfg, chief, 3600)
        self.ui_thread = threading.get_ident()
        self.scr = mock.Mock()
        self.scr.getmaxyx.return_value = (55, 240)
        self.patch(tui, "setup_colors", return_value={})
        self.patch(tui, "draw")
        self.patch(tui.curses, "curs_set")

    def no_adoption(self):
        self.assertEqual(chief.all_tasks(), [])
        self.assertFalse((self.repo / ".chief").exists())
        self.assert_session_untouched()

    def preview(self):
        text = "\n".join(self.frame())
        for value in (self.rec["title"], GOAL, "python3 -m unittest discover -s tests", "tests"):
            self.assertIn(value, text)
        self.assertIn("Enter", text)
        self.assertIn("Esc", text)
        self.no_adoption()

    def test_tracked_session_offers_adopt_and_escape_cancels_without_changes(self):
        refs = self.git("show-ref")
        self.ui(lambda: self.assertIn("A adopt", self.frame()[-1]),
                "A", self.idle, self.preview, "\x1b", self.no_adoption)
        self.assertEqual(self.git("show-ref"), refs)
        self.assertEqual(chief.config()["tracked_ids"], [SID])

    def test_enter_accepts_inferred_contract_once_and_keeps_context(self):
        worktrees = self.git("worktree", "list", "--porcelain")
        self.ui("A", self.idle, self.preview, "\n", self.idle)
        tasks = chief.all_tasks()
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertTrue(task["adopted"])
        self.assertEqual(task["session_id"], SID)
        self.assertEqual(task["goal"], GOAL)
        self.assertEqual(task["checks"], chief.infer_checks(str(self.repo)))
        self.assertEqual(task["protected"], chief.infer_protected(str(self.repo)))
        self.assertEqual(task["base"], self.base)
        self.assertEqual(self.git("worktree", "list", "--porcelain"), worktrees)
        self.deliver.assert_called_once()
        self.assertIn(NOTICE, self.deliver.call_args[0][2])
        self.ui("\n", self.idle)
        self.assertEqual(len(chief.all_tasks()), 1)
        self.deliver.assert_called_once()

    def test_adopted_card_says_in_place_and_close_key_releases_without_cleanup_offer(self):
        task = self.seed_task()

        def card():
            text = "\n".join(self.frame()).lower()
            self.assertIn("adopted", text)
            self.assertIn("in place", text)
            self.assertIn("c release", self.frame()[-1])
            self.assertNotIn("A adopt", self.frame()[-1])

        def confirm():
            self.assertIsNotNone(self.app.st["confirm"])
            self.assertIn("release", self.app.st["confirm"]["prompt"].lower())

        self.ui(card, "c", confirm, "y", self.idle, self.app.offer_cleanup)
        self.assertEqual(chief.load_task(task["id"])["state"], "done")
        self.assertIsNone(self.app.st["confirm"], "releasing must never offer to trash the session/worktree")
        self.assert_session_untouched()
        self.assertTrue(self.repo.is_dir())

    def test_delegated_card_keeps_close_action_and_does_not_offer_adoption(self):
        self.seed_task(adopted=False)

        def card():
            footer = self.frame()[-1]
            self.assertIn("c close", footer)
            self.assertNotIn("A adopt", footer)

        self.ui(card)


class AdoptDocumentationTests(unittest.TestCase):
    def test_docs_explain_in_place_adoption_presence_release_and_self_adoption(self):
        root = Path(__file__).resolve().parents[1]
        guide = (root / "docs/guide.md").read_text(encoding="utf-8").lower()
        self.assertIn("adopt", guide)
        self.assertRegex(guide, r"context")
        self.assertRegex(guide, r"current branch")
        self.assertRegex(guide, r"isolat")
        self.assertRegex(guide, r"hand.off")
        commands = (root / "docs/commands.md").read_text(encoding="utf-8")
        self.assertIn("adopt", commands)
        for flag in ("--goal", "--check", "--protected", "--test-first", "--dry-run"):
            self.assertIn(flag, commands)
        self.assertRegex(commands.lower(), r"release")
        inbox = (root / "docs/inbox.md").read_text(encoding="utf-8")
        self.assertRegex(inbox, r"(?m)\bA\b[^\n]*[Aa]dopt|[Aa]dopt[^\n]*\bA\b")
        config = (root / "docs/configuration.md").read_text(encoding="utf-8")
        self.assertRegex(config, r"presence_minutes[^\n]*10")
        handoff = (root / "rules/handoff.md").read_text(encoding="utf-8")
        self.assertIn("chief adopt", handoff)
        self.assertRegex(handoff.lower(), r"no session|without.*session|omit.*session")
        for flag in ("--name", "--goal", "--check"):
            self.assertIn(flag, handoff)
        self.assertLessEqual(len((root / "README.md").read_text(encoding="utf-8").splitlines()), 200)
