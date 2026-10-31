"""Review regressions for run budgets and actionable, bounded diagnostics.

Reuse the approved suite's offline fixtures without editing its protected file.
All elapsed time is simulated; these tests never sleep or use the network.
"""
from functools import partial
from unittest import mock
import unittest

from test_research_check import QUOTE, URL, ResearchCase, memo


class Clock:
    def __init__(self):
        self.now = 9876.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ResearchBudgetTests(ResearchCase):
    def timed_check(self, text, clock, fetcher, refresh=False, module=None):
        module = module or self.load_checker()
        with mock.patch.object(module, "main", partial(module.main, clock=clock)):
            return self.check(text, fetcher=fetcher, refresh=refresh, module=module)

    def sources(self, count):
        urls = ["https://evidence.example/budget/{}".format(i) for i in range(1, count + 1)]
        entries = "\n".join("[{}] {}\n> {}".format(i, url, QUOTE)
                            for i, url in enumerate(urls, 1))
        citations = "".join("[{}]".format(i) for i in range(1, count + 1))
        return memo(sources=entries, reasons="- Evidence. " + citations), urls

    def test_run_stops_at_240_seconds_and_rerun_uses_partial_cache(self):
        text, urls = self.sources(18)
        clock, calls = Clock(), []

        def fetch(url):
            calls.append(url)
            clock.advance(15)
            return QUOTE

        code, _, summary = self.timed_check(text, clock, fetch)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, urls[:16])
        self.assertEqual(len(self.cache_files()), 16)
        self.assertEqual(summary, "FAIL: 2 sources not fetched yet; rerun")
        fetcher = mock.Mock(return_value=QUOTE)
        self.assertEqual(self.timed_check(text, Clock(), fetcher)[0], 0)
        self.assertEqual(fetcher.call_args_list, [mock.call(url) for url in urls[16:]])

    def test_fetch_just_below_boundary_starts_but_next_one_does_not(self):
        text, urls = self.sources(3)
        clock, calls = Clock(), []

        def fetch(url):
            calls.append(url)
            clock.advance(239.5 if len(calls) == 1 else 0.5)
            return QUOTE

        code, _, summary = self.timed_check(text, clock, fetch)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, urls[:2])
        self.assertEqual(summary, "FAIL: 1 sources not fetched yet; rerun")

    def test_run_budget_includes_work_before_fetch_loop(self):
        text, _ = self.sources(2)
        clock, module = Clock(), self.load_checker()
        parse = module.parse_memo

        def delayed_parse(text):
            clock.advance(240)
            return parse(text)

        fetcher = mock.Mock(return_value=QUOTE)
        with mock.patch.object(module, "parse_memo", delayed_parse):
            code, _, summary = self.timed_check(text, clock, fetcher, module=module)
        self.assertNotEqual(code, 0)
        fetcher.assert_not_called()
        self.assertEqual(summary, "FAIL: 2 sources not fetched yet; rerun")

    def test_cached_and_manual_sources_still_checked_after_budget_exhaustion(self):
        cached = "https://evidence.example/cached"
        self.assertEqual(self.check(memo(sources="[1] " + cached + "\n> " + QUOTE),
                                    fetcher=mock.Mock(return_value=QUOTE))[0], 0)
        text = memo(reasons="- Evidence. [1][2][3][4]", sources=
                    "[1] " + URL + "\n> " + QUOTE + "\n"
                    "[2] " + cached + "\n> Invented cached quote.\n"
                    "[3] https://evidence.example/manual (manual)\n> Original manual quote.\n"
                    "[4] https://evidence.example/pending\n> " + QUOTE)
        clock, calls = Clock(), []

        def fetch(url):
            calls.append(url)
            clock.advance(240)
            return QUOTE

        code, output, summary = self.timed_check(text, clock, fetch)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [URL])
        self.assertIn("1 sources not fetched yet; rerun", summary)
        self.assertIn("quote not found [2]", summary)
        self.assertIn("[2] quote not found: Invented cached quote.", output.splitlines()[:-1])

    def test_failed_fetch_consumes_wall_time_without_being_cached(self):
        text, urls = self.sources(3)
        clock, calls = Clock(), []

        def fetch(url):
            calls.append(url)
            clock.advance(240)
            raise OSError("volatile fixture error")

        code, _, summary = self.timed_check(text, clock, fetch)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, urls[:1])
        self.assertEqual(self.cache_files(), [])
        self.assertIn("2 sources not fetched yet; rerun", summary)
        self.assertIn("fetch failed [1]", summary)

    def test_pending_count_uses_distinct_urls(self):
        text, urls = self.sources(3)
        text = text.replace(urls[2], urls[1])
        clock = Clock()

        def fetch(url):
            clock.advance(240)
            return QUOTE

        code, _, summary = self.timed_check(text, clock, fetch)
        self.assertNotEqual(code, 0)
        self.assertEqual(summary, "FAIL: 1 sources not fetched yet; rerun")

    def test_refresh_obeys_wall_time_budget_even_for_previously_cached_pages(self):
        text, urls = self.sources(2)
        self.assertEqual(self.check(text, fetcher=mock.Mock(return_value=QUOTE))[0], 0)
        clock, calls = Clock(), []

        def fetch(url):
            calls.append(url)
            clock.advance(240)
            return QUOTE

        code, _, summary = self.timed_check(text, clock, fetch, refresh=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, urls[:1])
        self.assertEqual(summary, "FAIL: 1 sources not fetched yet; rerun")


class ResearchDiagnosticTests(ResearchCase):
    def test_each_failed_quote_gets_its_own_line_before_the_summary(self):
        text = memo(sources="[1] " + URL + "\n> " + QUOTE +
                    "\n> Invented first quote.\n> Invented second quote.")
        output, summary = self.fails(text, 1)
        self.assertEqual(output.splitlines(), [
            "[1] quote not found: Invented first quote.",
            "[1] quote not found: Invented second quote.", summary])
        self.assertEqual(summary, "FAIL: quote not found [1]")

    def test_quote_snippet_and_fetch_failure_give_source_specific_context(self):
        pdf = "https://evidence.example/paper.pdf"
        self.http.page(pdf, QUOTE, content_type="application/pdf")
        quote = "An invented passage " + "x" * 100
        text = memo(reasons="- Evidence. [3][5]", sources=
                    "[3] " + URL + "\n> " + quote + "\n[5] " + pdf + "\n> " + QUOTE)
        output, summary = self.fails(text, 3, 5)
        self.assertEqual(output.splitlines()[:-1], [
            "[3] quote not found: " + quote[:60],
            "[5] non-text content; mark source manual"])
        self.assertNotIn(quote[:60], summary)

    def test_missing_source_lines_are_individual_and_numerically_ordered(self):
        output, summary = self.fails(memo(reasons="- Evidence. [10][2]", sources=""), 2, 10)
        self.assertEqual(output.splitlines(), ["[2] missing source", "[10] missing source", summary])

    def test_source_validation_errors_have_diagnostics_without_fetching(self):
        text = memo(reasons="- Evidence. [3][5]", sources=
                    "[3] " + URL + "\n[5] file:///local.pdf\n> Original quote.")
        output, summary = self.fails(text, 3, 5)
        self.assertIn("[3] missing quote", output.splitlines()[:-1])
        self.assertIn("[5] invalid source", output.splitlines()[:-1])
        self.assertEqual(output.splitlines()[-1], summary)
        self.assertEqual(self.http.requests, [])

    def test_unsafe_url_and_structure_problems_have_separate_lines(self):
        text = memo(conclusion="", sources="[1] http://127.0.0.1/\n> " + QUOTE)
        output, summary = self.fails(text, 1)
        self.assertIn("missing conclusion", output.splitlines()[:-1])
        self.assertIn("[1] unsafe URL", output.splitlines()[:-1])
        self.assertEqual(output.splitlines()[-1], summary)

    def test_at_most_ten_violation_lines_then_one_summary(self):
        quotes = "\n".join("> Absent {}.".format(i) for i in range(25))
        output, summary = self.fails(memo(sources="[1] " + URL + "\n" + quotes), 1)
        self.assertEqual(len(output.splitlines()), 11)
        self.assertEqual(output.splitlines()[0], "[1] quote not found: Absent 0.")
        self.assertEqual(output.splitlines()[-2], "[1] quote not found: Absent 9.")
        self.assertEqual(output.splitlines()[-1], summary)

    def test_long_unicode_quote_diagnostics_and_summary_fit_under_800_characters(self):
        quote = "证据" * 100
        quotes = "\n".join("> " + quote + str(i) for i in range(25))
        output, summary = self.fails(memo(sources="[1] " + URL + "\n" + quotes), 1)
        lines = output.splitlines()
        self.assertGreater(len(lines), 1)
        self.assertLessEqual(len(lines), 11)
        self.assertLess(len(output), 800)
        self.assertEqual(lines[0], "[1] quote not found: " + quote[:60])
        self.assertEqual(lines[-1], summary)

    def test_summary_does_not_change_when_quote_diagnostics_change(self):
        outputs, summaries = [], []
        for quote in ("First invented quote.", "A much longer invented quote " + "x" * 100):
            output, summary = self.fails(memo(sources="[1] " + URL + "\n> " + quote), 1)
            outputs.append(output)
            summaries.append(summary)
        self.assertNotEqual(outputs[0], outputs[1])
        self.assertEqual(summaries[0], summaries[1])

    def test_many_source_failures_preserve_final_summary_with_bounded_diagnostics(self):
        text = memo(conclusion="", sources="", reasons="- Evidence. " +
                    "".join("[{}]".format(i) for i in range(1, 251)))
        output, summary = self.fails(text)
        self.assertGreater(len(output.splitlines()), 1)
        self.assertLess(len(output), 800)
        self.assertIn("missing conclusion", summary)
        self.assertIn("missing source", summary)
        self.assertEqual(self.check(text)[2], summary)

    def test_success_still_has_only_the_single_ok_line(self):
        code, output, summary = self.check(memo())
        self.assertEqual(code, 0)
        self.assertEqual(output.splitlines(), [summary])


if __name__ == "__main__":
    unittest.main()
