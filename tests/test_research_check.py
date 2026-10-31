"""Acceptance contract for the research pilot in docs/design.md (v3).

No test contacts the network. DNS and urllib's HTTP transport are fixtures;
real socket connections are forbidden, including in CLI subprocesses.

Small implementation seams agreed by these tests:
* main(argv=None, fetcher=None) returns a CLI exit code. An injected fetcher
  takes one URL and returns extracted page text; the default fetcher uses urllib.
* Cache records are JSON objects with url, fetched_at and text, with the URL's
  SHA-256 digest as their filename (optionally suffixed with .json).
The tests otherwise exercise observable memo, CLI and documentation behavior.
"""
import contextlib
from email.message import Message
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import urllib.error
import urllib.request
import urllib.response


ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "tools" / "research_check.py"
URL = "https://evidence.example/article"
QUOTE = "Evidence supports the decision."
MAX_BYTES = 5 * 1024 * 1024


def memo(sources=None, reasons=None, conclusion="Conclusion: Choose option A.",
         reasons_heading="## Reasons", sources_heading="## Sources"):
    if sources is None:
        sources = "[1] " + URL + "\n> " + QUOTE
    if reasons is None:
        reasons = "- The evidence supports option A. [1]"
    return "# Research question\n\n{}\n\n{}\n{}\n\n{}\n{}\n".format(
        conclusion, reasons_heading, reasons, sources_heading, sources)


class Body(io.BytesIO):
    """Record bytes consumed so a size guard must also work without headers."""
    def __init__(self, content):
        super().__init__(content)
        self.bytes_read = 0

    def read(self, size=-1):
        data = super().read(size)
        self.bytes_read += len(data)
        return data


class OfflineHTTP:
    """Replace only transport: urllib still handles redirects and HTTP errors."""
    def __init__(self):
        self.pages = {}
        self.requests = []
        self.timeouts = []
        self.bodies = []
        self.resolutions = []
        self.addresses = {}
        self.page(URL, "<p>" + QUOTE + "</p>")

    def page(self, url, body=QUOTE, content_type="text/html; charset=utf-8",
             status=200, headers=None):
        fields = {"Content-Type": content_type}
        fields.update(headers or {})
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.pages[url] = (status, fields, body)

    def redirect(self, url, target, status=302):
        self.page(url, "", status=status, headers={"Location": target})

    def resolve(self, host, port, *args, **kwargs):
        self.resolutions.append(host)
        if host in self.addresses:
            addresses = self.addresses[host]
            if isinstance(addresses, Exception):
                raise addresses
        else:
            try:
                addresses = [str(ipaddress.ip_address(host))]
            except ValueError:
                addresses = ["93.184.216.34"]
        result = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
            result.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
        return result

    def open(self, handler, http_class, request, **kwargs):
        url = request.full_url
        self.requests.append(url)
        self.timeouts.append(request.timeout)
        if url not in self.pages:
            raise AssertionError("Unexpected fixture URL: " + url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        status, headers, content = page
        message = Message()
        for key, value in headers.items():
            message[key] = value
        body = Body(content)
        self.bodies.append(body)
        response = urllib.response.addinfourl(body, message, url, status)
        response.msg = "fixture response"
        return response


class ResearchCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.work = self.root / "repository"
        self.work.mkdir()
        self.path = self.work / "memo.md"
        self.home = self.root / "home"
        self.home.mkdir()
        self.state = self.root / "chief-state"
        previous_cwd = os.getcwd()
        os.chdir(str(self.work))
        self.addCleanup(os.chdir, previous_cwd)
        environment = {
            "AOE_CHIEF_HOME": str(self.state), "HOME": str(self.home),
            "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "", "NO_PROXY": "*",
            "http_proxy": "", "https_proxy": "", "all_proxy": "", "no_proxy": "*",
        }
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.http = OfflineHTTP()
        for target, options in (
                ("socket.getaddrinfo", {"side_effect": self.http.resolve}),
                ("socket.create_connection", {"side_effect": AssertionError("Network forbidden")}),
                ("socket.socket.connect", {"side_effect": AssertionError("Network forbidden")}),
                ("socket.socket.connect_ex", {"side_effect": AssertionError("Network forbidden")}),
                ("urllib.request.AbstractHTTPHandler.do_open",
                 {"autospec": True, "side_effect": self.http.open})):
            patcher = mock.patch(target, **options)
            patcher.start()
            self.addCleanup(patcher.stop)

    def load_checker(self):
        self.assertTrue(CHECKER.is_file(), "Missing deliverable: tools/research_check.py")
        module = types.ModuleType("research_check_acceptance_subject")
        module.__file__ = str(CHECKER)
        patcher = mock.patch.dict(sys.modules, {module.__name__: module})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Compile explicitly: importing the deliverable must not create repo pyc files.
        exec(compile(CHECKER.read_text(encoding="utf-8"), str(CHECKER), "exec"), module.__dict__)
        self.assertTrue(callable(getattr(module, "main", None)), "Expose main(argv=None, fetcher=None)")
        return module

    def check(self, text=None, refresh=False, fetcher=None, module=None, path=None):
        if text is not None:
            self.path.write_text(text, encoding="utf-8")
        module = module or self.load_checker()
        argv = [str(path or self.path)] + (["--refresh"] if refresh else [])
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("External process forbidden")), \
                mock.patch("os.system", side_effect=AssertionError("External process forbidden")):
            try:
                code = module.main(argv, fetcher=fetcher) if fetcher is not None else module.main(argv)
            except SystemExit as exc:
                code = exc.code
        self.assertIsInstance(code, int, "main must expose the process exit code")
        output = stdout.getvalue()
        self.assertEqual(stderr.getvalue(), "", "Check diagnostics belong in the bounded output")
        self.assertLess(len(output), 800, output)
        self.assertNotIn("Traceback", output)
        lines = output.splitlines()
        self.assertTrue(lines, "Always print a final summary")
        self.assertLessEqual(len(lines), 11, "At most ten violation lines plus one summary")
        summaries = [line for line in lines if line.startswith(("OK:", "FAIL:"))]
        self.assertEqual(summaries, [lines[-1]], "Exactly one final summary line")
        self.assertEqual(lines[-1].startswith("OK:"), code == 0)
        return code, output, lines[-1]

    def fails(self, text, *ids, **kwargs):
        code, output, summary = self.check(text, **kwargs)
        self.assertNotEqual(code, 0)
        for source_id in ids:
            self.assertIn("[{}]".format(source_id), summary)
        return output, summary

    def cache_files(self, state=None):
        cache = (state or self.state) / "research-cache"
        return sorted(path for path in cache.glob("*") if path.is_file())


class ResearchStructureTests(ResearchCase):
    def test_english_and_chinese_memo_formats(self):
        formats = [("Conclusion: Choose A.", "## Reasons", "## Sources"),
                   ("结论：选择 A。", "## 理由", "## 来源")]
        for conclusion, reasons_heading, sources_heading in formats:
            with self.subTest(conclusion=conclusion):
                code, _, summary = self.check(memo(conclusion=conclusion,
                    reasons_heading=reasons_heading, sources_heading=sources_heading))
                self.assertEqual(code, 0)
                self.assertRegex(summary, r"^OK: 1 sources?, 1 quotes? verified")

    def test_missing_memo_is_a_failure_not_a_traceback(self):
        code, _, summary = self.check(path=self.work / "missing.md")
        self.assertNotEqual(code, 0)
        self.assertRegex(summary.lower(), r"missing|not found|not exist")
        self.assertEqual(self.http.requests, [])

    def test_directory_is_not_a_memo(self):
        code, _, _ = self.check(path=self.work)
        self.assertNotEqual(code, 0)

    def test_missing_or_empty_or_folded_conclusion_fails(self):
        for conclusion in ("", "Conclusion:", "结论：", "## Conclusion\nChoose A.",
                           "Conclusion:\nChoose A."):
            with self.subTest(conclusion=conclusion):
                _, summary = self.fails(memo(conclusion=conclusion))
                self.assertIn("conclusion", summary.lower())

    def test_both_required_section_headings_are_checked(self):
        for name, replacement in (("Reasons", "## Discussion"), ("Sources", "## Links")):
            with self.subTest(section=name):
                _, summary = self.fails(memo().replace("## " + name, replacement))
                self.assertIn(name.lower(), summary.lower())

    def test_adjacent_citations_must_all_have_entries(self):
        self.fails(memo(reasons="- Evidence. [1][2][10]"), 2, 10)

    def test_citations_in_conclusion_and_later_sections_are_checked(self):
        self.fails(memo(conclusion="Conclusion: Choose A. [3]") +
                   "\n## Uncertain / not found\nA remaining question. [4]\n", 3, 4)

    def test_bracket_numbers_inside_source_quotes_are_not_citations(self):
        self.http.page(URL, "The original includes [999].")
        code, _, _ = self.check(memo(sources="[1] " + URL + "\n> The original includes [999]."))
        self.assertEqual(code, 0)

    def test_entries_outside_sources_do_not_close_citations(self):
        self.fails(memo(sources="", reasons="[1] " + URL + "\n> " + QUOTE), 1)

    def test_cited_sources_require_url_and_nonempty_blockquote(self):
        for entry in ("[1]", "[1] " + URL, "[1] " + URL + "\n> ",
                      "[1] " + URL + "\n" + QUOTE,
                      "[1] " + URL + "\n[2] https://evidence.example/two\n> " + QUOTE):
            with self.subTest(entry=entry):
                self.fails(memo(sources=entry), 1)

    def test_every_quote_line_is_verified(self):
        self.fails(memo(sources="[1] " + URL + "\n> " + QUOTE + "\n> Invented second quote."), 1)

    def test_quote_of_uncited_source_is_also_verified(self):
        other = "https://evidence.example/unused"
        self.http.page(other)
        self.fails(memo(sources="[1] " + URL + "\n> " + QUOTE +
                   "\n[2] " + other + "\n> Invented quote."), 2)

    def test_source_quotes_stop_at_next_section(self):
        self.fails(memo(sources="[1] " + URL) + "\n## Appendix\n> " + QUOTE + "\n", 1)


class ResearchQuoteTests(ResearchCase):
    def test_html_entities_tags_curly_quotes_dashes_whitespace_and_casefold(self):
        self.http.page(URL, '<p>The “Straße” &amp; ‘TEAM’</p>\n'
                       '<p>said &quot;YES&quot; — end–to–end.</p>')
        quote = 'the "STRASSE" & \'team\' said "yes" - end-to-end.'
        code, _, _ = self.check(memo(sources="[1] " + URL + "\n> " + quote))
        self.assertEqual(code, 0)

    def test_normalization_applies_to_quote_as_well_as_page(self):
        self.http.page(URL, '<p>"team" - ready&nbsp;&amp; waiting</p>')
        code, _, _ = self.check(memo(sources="[1] " + URL + "\n> “TEAM” — ready   & waiting"))
        self.assertEqual(code, 0)

    def test_inline_tags_preserve_visible_words(self):
        self.http.page(URL, "<p>Evidence <strong>supports</strong> the decision.</p>")
        self.assertEqual(self.check(memo())[0], 0)

    def test_original_language_and_declared_charset(self):
        phrase = "证据支持这一决定。"
        self.http.page(URL, ("<p>" + phrase + "</p>").encode("gb18030"),
                       content_type="text/html; charset=gb18030")
        self.assertEqual(self.check(memo(sources="[1] " + URL + "\n> " + phrase))[0], 0)

    def test_script_style_comments_and_tag_attributes_are_not_evidence(self):
        for hidden in ('<script>Invented quote.</script>', '<style>Invented quote.</style>',
                       '<!-- Invented quote. -->', '<p title="Invented quote.">Visible</p>'):
            with self.subTest(hidden=hidden):
                self.http.page(URL, hidden + "<p>Visible evidence.</p>")
                self.fails(memo(sources="[1] " + URL + "\n> Invented quote."), 1, refresh=True)

    def test_paraphrase_or_reordered_words_do_not_pass(self):
        for quote in ("Evidence does not support the decision.", "Decision supports the evidence."):
            with self.subTest(quote=quote):
                _, summary = self.fails(memo(sources="[1] " + URL + "\n> " + quote), 1)
                self.assertIn("quote not found", summary)

    def test_plain_text_and_xhtml_are_fetchable(self):
        for content_type in ("text/plain; charset=utf-8", "text/html", "application/xhtml+xml"):
            with self.subTest(content_type=content_type):
                self.http.page(URL, QUOTE, content_type=content_type)
                self.assertEqual(self.check(memo(), refresh=True)[0], 0)

    def test_manual_markers_skip_fetch_but_require_quotes_and_report_ids(self):
        for marker in ("(manual)", "(手动)"):
            with self.subTest(marker=marker):
                code, _, summary = self.check(memo(sources="[1] " + URL + " " + marker +
                                                   "\n> A manually inspected original quote."))
                self.assertEqual(code, 0)
                self.assertIn("1 manual [1]", summary)
                self.assertIn("0 quotes verified", summary)
        self.assertEqual(self.http.requests, [])
        self.assertEqual(self.cache_files(), [])

    def test_manual_source_still_requires_a_quote(self):
        self.fails(memo(sources="[1] " + URL + " (manual)"), 1)

    def test_manual_source_still_requires_an_http_url(self):
        self.fails(memo(sources="[1] file:///local/paper.pdf (manual)\n> Original quote."), 1)
        self.assertEqual(self.http.requests, [])

    def test_manual_marker_must_be_on_the_source_entry(self):
        self.fails(memo(sources="[1] " + URL + "\n> Invented (manual) quote."), 1)

    def test_ok_summary_counts_sources_verified_quotes_and_manual_sources(self):
        self.http.page(URL, QUOTE + " A second original statement.")
        text = memo(reasons="- First. [1]\n- Second. [4]", sources=
                    "[1] " + URL + "\n> " + QUOTE + "\n> A second original statement.\n\n"
                    "[4] https://evidence.example/locked (manual)\n> Original manual quote.")
        code, _, summary = self.check(text)
        self.assertEqual(code, 0)
        self.assertEqual(summary, "OK: 2 sources, 2 quotes verified, 1 manual [4]")

    def test_fetcher_can_be_injected_without_http_or_models(self):
        fetcher = mock.Mock(return_value=QUOTE)
        self.assertEqual(self.check(memo(), fetcher=fetcher)[0], 0)
        fetcher.assert_called_once_with(URL)
        self.assertEqual(self.http.requests, [])

    def test_manual_ids_are_deterministic_and_sorted(self):
        text = memo(reasons="- Manual evidence. [10][2]", sources=
                    "[10] https://evidence.example/ten (manual)\n> Original ten.\n"
                    "[2] https://evidence.example/two (manual)\n> Original two.")
        code, _, summary = self.check(text)
        self.assertEqual(code, 0)
        self.assertIn("2 manual [2][10]", summary)
        self.assertEqual(self.check(text)[2], summary)
        self.assertEqual(self.http.requests, [])


class ResearchFetchSafetyTests(ResearchCase):
    def test_only_http_and_https_schemes_are_allowed(self):
        for url in ("file:///etc/passwd", "ftp://evidence.example/a", "data:text/plain,quote",
                    "javascript:alert(1)", "http:///no-host", "https://[invalid/"):
            with self.subTest(url=url):
                self.fails(memo(sources="[1] " + url + "\n> " + QUOTE), 1)
        self.assertEqual(self.http.requests, [])

    def test_unsafe_ipv4_and_ipv6_literals_never_reach_transport(self):
        addresses = ("127.0.0.1", "10.1.2.3", "172.16.1.2", "192.168.1.2",
                     "169.254.169.254", "0.0.0.0", "224.0.0.1", "240.0.0.1",
                     "192.0.2.1", "::1", "::", "fe80::1", "fc00::1", "ff02::1",
                     "2001:db8::1", "::ffff:127.0.0.1", "::ffff:10.1.2.3")
        for address in addresses:
            host = "[" + address + "]" if ":" in address else address
            with self.subTest(address=address):
                self.fails(memo(sources="[1] http://" + host + "/\n> " + QUOTE), 1)
        self.assertEqual(self.http.requests, [])
        self.assertEqual(self.cache_files(), [])

    def test_dns_names_resolving_to_private_or_mixed_addresses_are_refused(self):
        for addresses in (["10.1.2.3"], ["::1"], ["93.184.216.34", "169.254.1.2"],
                          ["2606:4700:4700::1111", "fc00::1"]):
            with self.subTest(addresses=addresses):
                self.http.addresses["evidence.example"] = addresses
                self.fails(memo(), 1)
        self.assertIn("evidence.example", self.http.resolutions)
        self.assertEqual(self.http.requests, [])

    def test_dns_failure_is_a_bounded_check_failure(self):
        self.http.addresses["evidence.example"] = socket.gaierror("fixture DNS unavailable")
        self.fails(memo(), 1)
        self.assertEqual(self.http.requests, [])
        self.assertEqual(self.cache_files(), [])

    def test_public_http_and_ipv6_hosts_are_allowed(self):
        for url in ("http://evidence.example/article", "https://[2606:4700:4700::1111]/"):
            with self.subTest(url=url):
                self.http.page(url)
                self.assertEqual(self.check(memo(sources="[1] " + url + "\n> " + QUOTE))[0], 0)

    def test_redirect_to_private_literal_or_dns_name_is_refused(self):
        targets = ("http://127.0.0.1/secret", "http://[::1]/secret",
                   "http://internal.example/secret", "file:///etc/passwd")
        for target in targets:
            with self.subTest(target=target):
                self.http.requests[:] = []
                self.http.addresses["internal.example"] = ["10.0.0.1"]
                self.http.redirect(URL, target)
                self.fails(memo(), 1, refresh=True)
                self.assertEqual(self.http.requests, [URL])
                self.assertEqual(self.cache_files(), [])

    def test_all_standard_redirect_codes_recheck_the_target(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                self.http.requests[:] = []
                self.http.redirect(URL, "http://10.0.0.1/private", status=status)
                self.fails(memo(), 1, refresh=True)
                self.assertEqual(self.http.requests, [URL])

    def test_five_redirects_and_relative_targets_are_allowed(self):
        urls = [URL] + ["https://evidence.example/hop{}".format(i) for i in range(1, 6)]
        for index, url in enumerate(urls[:-1]):
            self.http.redirect(url, "/hop{}".format(index + 1))
        self.http.page(urls[-1])
        self.assertEqual(self.check(memo())[0], 0)
        self.assertEqual(self.http.requests, urls)
        self.assertTrue(all(timeout == 15 for timeout in self.http.timeouts))

    def test_sixth_redirect_is_not_followed(self):
        urls = [URL] + ["https://evidence.example/hop{}".format(i) for i in range(1, 7)]
        for index, url in enumerate(urls[:-1]):
            self.http.redirect(url, urls[index + 1])
        self.http.page(urls[-1])
        self.fails(memo(), 1)
        self.assertLessEqual(len(self.http.requests), 6)
        self.assertNotIn(urls[-1], self.http.requests)
        self.assertEqual(self.cache_files(), [])

    def test_non_text_content_fails_with_manual_source_guidance(self):
        for content_type in ("application/pdf", "application/octet-stream", "image/png", "application/json"):
            with self.subTest(content_type=content_type):
                self.http.page(URL, QUOTE, content_type=content_type)
                output, _ = self.fails(memo(), 1, refresh=True)
                self.assertIn("manual", output.lower())
                self.assertEqual(self.cache_files(), [])

    def test_timeout_and_http_failures_are_not_cached(self):
        for failure in (socket.timeout("fixture timeout"), urllib.error.URLError("fixture error")):
            with self.subTest(failure=type(failure).__name__):
                self.http.pages[URL] = failure
                self.fails(memo(), 1)
                self.assertEqual(self.http.timeouts[-1], 15)
                self.assertEqual(self.cache_files(), [])
        self.http.page(URL, "Not found", status=404)
        self.fails(memo(), 1)
        self.assertEqual(self.cache_files(), [])

    def test_size_cap_covers_declared_and_undeclared_or_false_lengths(self):
        for headers in ({"Content-Length": str(MAX_BYTES + 100)}, {}, {"Content-Length": "1"}):
            with self.subTest(headers=headers):
                self.http.page(URL, b"x" * (MAX_BYTES + 100), headers=headers)
                self.fails(memo(), 1, refresh=True)
                self.assertLessEqual(self.http.bodies[-1].bytes_read, MAX_BYTES + 1)
                self.assertEqual(self.cache_files(), [])


class ResearchCacheAndOutputTests(ResearchCase):
    def test_cache_is_sha256_keyed_and_contains_extracted_text_and_metadata(self):
        self.assertEqual(self.check(memo())[0], 0)
        files = self.cache_files()
        self.assertEqual(len(files), 1)
        digest = hashlib.sha256(URL.encode("utf-8")).hexdigest()
        self.assertIn(files[0].name, (digest, digest + ".json"))
        record = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(record["url"], URL)
        self.assertTrue(record["fetched_at"])
        self.assertIsInstance(record["text"], str)
        self.assertIn(QUOTE.casefold(), record["text"].casefold())
        self.assertNotIn("<p>", record["text"])
        self.assertEqual(sorted(path.name for path in self.work.iterdir()), ["memo.md"])

    def test_cache_reuse_survives_reloading_the_checker_and_refresh_refetches(self):
        first = self.check(memo())
        self.assertEqual(first[0], 0)
        self.http.page(URL, "The new page no longer contains the quote.")
        second = self.check(memo(), module=self.load_checker())
        self.assertEqual(second[0], 0)
        self.assertEqual(second[2], first[2])
        self.assertEqual(self.http.requests, [URL])
        self.fails(memo(), 1, refresh=True)
        self.assertEqual(self.http.requests, [URL, URL])
        self.fails(memo(), 1)
        self.assertEqual(self.http.requests, [URL, URL])

    def test_failed_fetch_is_retried_on_next_run(self):
        self.http.pages[URL] = urllib.error.URLError("temporary fixture failure")
        self.fails(memo(), 1)
        self.assertEqual(self.cache_files(), [])
        self.http.page(URL)
        self.assertEqual(self.check(memo())[0], 0)
        self.assertEqual(self.http.requests, [URL, URL])

    def test_default_cache_home_is_local_state_aoe_chief(self):
        del os.environ["AOE_CHIEF_HOME"]
        self.assertEqual(self.check(memo())[0], 0)
        default_state = self.home / ".local" / "state" / "aoe-chief"
        self.assertEqual(len(self.cache_files(state=default_state)), 1)
        self.assertEqual(self.cache_files(), [])

    def test_duplicate_urls_fetch_once_but_verify_each_sources_quote(self):
        text = memo(reasons="- Evidence. [1][2]", sources="[1] " + URL + "\n> " + QUOTE +
                    "\n\n[2] " + URL + "\n> Invented quote.")
        self.fails(text, 2)
        self.assertEqual(self.http.requests, [URL])
        self.assertEqual(len(self.cache_files()), 1)

    def many_sources(self, count):
        urls = ["https://evidence.example/source/{}".format(i) for i in range(1, count + 1)]
        for url in urls:
            self.http.page(url)
        sources = "\n\n".join("[{}] {}\n> {}".format(i, url, QUOTE)
                                for i, url in enumerate(urls, 1))
        reasons = "- Evidence. " + "".join("[{}]".format(i) for i in range(1, count + 1))
        return memo(sources=sources, reasons=reasons), urls

    def test_twenty_uncached_url_cap_makes_progress_on_rerun(self):
        text, urls = self.many_sources(23)
        _, summary = self.fails(text)
        self.assertIn("3 sources not fetched yet; rerun", summary)
        self.assertEqual(len(self.http.requests), 20)
        self.assertEqual(len(self.cache_files()), 20)
        self.assertEqual(len(set(self.http.requests)), 20)
        self.assertEqual(self.check(text)[0], 0)
        self.assertCountEqual(self.http.requests, urls)
        self.assertEqual(len(self.cache_files()), 23)

    def test_manual_sources_do_not_consume_fetch_budget(self):
        text, urls = self.many_sources(20)
        text += "\n[99] https://evidence.example/manual (manual)\n> Manually read original.\n"
        self.assertEqual(self.check(text)[0], 0)
        self.assertCountEqual(self.http.requests, urls)

    def test_cached_sources_do_not_consume_fetch_budget(self):
        text, _ = self.many_sources(20)
        self.assertEqual(self.check(text)[0], 0)
        text, _ = self.many_sources(40)
        self.assertEqual(self.check(text)[0], 0)
        self.assertEqual(len(self.http.requests), 40)

    def test_refresh_also_obeys_twenty_fetch_cap(self):
        text, _ = self.many_sources(21)
        self.fails(text)
        self.assertEqual(self.check(text)[0], 0)
        previous = len(self.http.requests)
        _, summary = self.fails(text, refresh=True)
        self.assertIn("1 sources not fetched yet; rerun", summary)
        self.assertEqual(len(self.http.requests) - previous, 20)

    def test_failed_attempts_also_consume_fetch_budget(self):
        text, urls = self.many_sources(23)
        for url in urls:
            self.http.pages[url] = urllib.error.URLError("fixture failure")
        _, summary = self.fails(text)
        self.assertEqual(len(self.http.requests), 20)
        self.assertIn("3 sources not fetched yet; rerun", summary)
        self.assertEqual(self.cache_files(), [])

    def test_final_line_groups_ids_in_numeric_order_and_uses_fixed_reason_words(self):
        other = "https://evidence.example/ten"
        self.http.page(other)
        text = memo(conclusion="", reasons="- Evidence. [10][2]", sources=
                    "[10] " + other + "\n> Missing ten.\n[2] " + URL + "\n> Missing two.")
        _, summary = self.fails(text, 2, 10)
        self.assertIn("quote not found [2][10]", summary)
        self.assertIn("missing conclusion", summary)
        self.assertEqual(self.check(text)[2], summary)

    def test_volatile_fetch_errors_do_not_change_the_final_summary(self):
        summaries = []
        for detail in ("different exception 2026-10-31 /tmp/first", "another exception 2027-01-01 /tmp/second"):
            self.http.pages[URL] = urllib.error.URLError(detail)
            _, summary = self.fails(memo(), 1)
            summaries.append(summary)
            self.assertNotIn(detail, summary)
            self.assertNotIn("https://", summary)
        self.assertEqual(summaries[0], summaries[1])

    def test_many_failures_keep_the_summary_and_entire_output_under_800_characters(self):
        text = memo(conclusion="", sources="", reasons="- Evidence. " +
                    "".join("[{}]".format(i) for i in range(1, 251)))
        output, summary = self.fails(text)
        self.assertEqual(output.splitlines()[-1], summary)
        self.assertEqual(self.check(text)[2], summary)


class ResearchCLITests(ResearchCase):
    def cli(self, arguments):
        self.assertTrue(CHECKER.is_file(), "Missing deliverable: tools/research_check.py")
        # -I -S excludes project/site dependencies; guards apply before run_path.
        bootstrap = ("import os, runpy, socket, subprocess, sys\n"
                     "def forbidden(*args, **kwargs):\n"
                     "    raise AssertionError('Network forbidden in CLI acceptance test')\n"
                     "socket.getaddrinfo = forbidden\n"
                     "socket.create_connection = forbidden\n"
                     "socket.socket.connect = forbidden\n"
                     "socket.socket.connect_ex = forbidden\n"
                     "subprocess.Popen = forbidden\n"
                     "os.system = forbidden\n"
                     "sys.argv = sys.argv[1:]\n"
                     "runpy.run_path(sys.argv[0], run_name='__main__')\n")
        return subprocess.run([sys.executable, "-I", "-S", "-c", bootstrap, str(CHECKER)] + arguments,
                              cwd=str(self.work), env=dict(os.environ),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=10)

    def test_cli_manual_success_and_refresh_exit_zero_using_only_stdlib(self):
        self.path.write_text(memo(sources="[1] " + URL + " (manual)\n> Original quote."), encoding="utf-8")
        for extra in ([], ["--refresh"]):
            with self.subTest(arguments=extra):
                result = self.cli([str(self.path)] + extra)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertTrue(result.stdout.splitlines()[-1].startswith("OK:"))
                self.assertLess(len(result.stdout), 800)

    def test_cli_failure_is_nonzero_and_ends_in_fail_summary(self):
        self.path.write_text(memo(conclusion="", sources=""), encoding="utf-8")
        result = self.cli([str(self.path)])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertTrue(result.stdout.splitlines()[-1].startswith("FAIL:"))
        self.assertLess(len(result.stdout), 800)

    def test_cli_missing_path_and_invalid_arguments_are_nonzero(self):
        for arguments in ([str(self.work / "absent.md")], [], ["--not-an-option"]):
            with self.subTest(arguments=arguments):
                result = self.cli(arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stdout + result.stderr)


class ResearchDocumentationTests(unittest.TestCase):
    def research_section(self, path):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"(?ims)^## Research tasks\s*\n(.*?)(?=^## |\Z)", text)
        self.assertIsNotNone(match, str(path.relative_to(ROOT)) + " needs a Research tasks section")
        return match.group(1)

    def test_worker_rules_cover_the_agreed_research_workflow(self):
        path = ROOT / "rules" / "research.md"
        self.assertTrue(path.is_file(), "Missing deliverable: rules/research.md")
        text = " ".join(path.read_text(encoding="utf-8").lower().split())
        self.assertLess(len(text.split()), 600, "Keep the worker rules short")
        patterns = (r"(?:answer|conclusion).*first.*(?:one|single).*sentence",
                    r"(?:at most|up to|no more than) (?:3|three) reasons",
                    r"one (?:checkable )?claim.*(?:per|each).*source",
                    r"verbatim", r"original language",
                    r"never cite.*(?:not|haven't|didn't).*open|only cite.*open",
                    r"queries.*(?:uncertain|not found)", r"stop condition",
                    r"(?:run|check).*before.*(?:ending|end).*turn", r"commit.*every turn")
        for pattern in patterns:
            with self.subTest(requirement=pattern):
                self.assertRegex(text, pattern)

    def test_handoff_covers_session_rotation_and_worker_tool_constraints(self):
        section = " ".join(self.research_section(ROOT / "rules" / "handoff.md").lower().split())
        for phrase in ("delegate to chief", "adopt", "rotat", "codex", "claude", "glm", "antigravity"):
            with self.subTest(requirement=phrase):
                self.assertIn(phrase, section)
        self.assertRegex(section, r"claude.*default.*model|default.*claude.*model|claude model.*default")
        self.assertRegex(section, r"glm.*stale|stale.*glm")
        self.assertRegex(section, r"antigravity.*approval|approval.*antigravity")
        self.assertRegex(section, r"(?:do not|don't|avoid|unsuitable).*antigravity|antigravity.*(?:not|unsuitable)")

    def test_handoff_has_a_research_contract_example(self):
        section = self.research_section(ROOT / "rules" / "handoff.md")
        blocks = re.findall(r"```json\s*\n(.*?)\n```", section, re.S)
        self.assertTrue(blocks, "Show a complete research contract example")
        contract = json.loads(blocks[0])
        self.assertIs(contract["test_first"], False)
        self.assertIn(contract["tool"], ("codex", "claude"))
        self.assertNotIn("model", contract, "Chief uses the worker's configured default model")
        self.assertEqual(len(contract["checks"]), 1)
        self.assertRegex(contract["checks"][0],
                         r"^python3 ~/aoe-chief/tools/research_check\.py research/[^\s]+/memo\.md$")
        goal = contract["goal"]
        self.assertIn("read ~/aoe-chief/rules/research.md first", goal.lower())
        for concept in ("question", "decision", "stop", "reject"):
            with self.subTest(concept=concept):
                self.assertIn(concept, goal.lower())

    def test_guide_links_design_and_worker_rules(self):
        section = self.research_section(ROOT / "docs" / "guide.md")
        self.assertRegex(section, r"\]\((?:\./)?design\.md(?:#[^)]*)?\)")
        self.assertRegex(section, r"\]\(\.\./rules/research\.md(?:#[^)]*)?\)")


if __name__ == "__main__":
    unittest.main()
