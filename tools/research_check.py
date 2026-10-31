#!/usr/bin/env python3
"""Check a research memo's structure and verbatim quotations; never use a model.

Usage: research_check.py path/to/memo.md [--refresh]
main(argv=None, fetcher=None) accepts a fetcher(url) returning extracted text.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import sys
import tempfile
import threading
from urllib.parse import quote, urljoin, urlsplit
import urllib.request


TIMEOUT = 15
MAX_BYTES = 5 * 1024 * 1024
MAX_FETCHES = 20
PUNCTUATION = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'",
                           "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-"})


class CheckFailure(Exception):
    """A fixed diagnostic category, safe to include in the final summary."""


def normalize(text):
    return " ".join(text.translate(PUNCTUATION).casefold().split())


class PageText(HTMLParser):
    BLOCKS = {"address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
              "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
              "nav", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if not self.hidden and tag in self.BLOCKS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1
        if not self.hidden and tag in self.BLOCKS:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def url_parts(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname or
                parts.username is not None or parts.password is not None or
                any(ord(char) <= 32 or ord(char) == 127 for char in url)):
            raise ValueError()
        if parts.port is not None and not 1 <= parts.port <= 65535:
            raise ValueError()
        return parts
    except ValueError:
        raise CheckFailure("unsafe URL")


def public_addresses(url):
    parts = url_parts(url)
    addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    if not addresses:
        raise CheckFailure("fetch failed")
    for family, socktype, protocol, canonname, sockaddr in addresses:
        address = ipaddress.ip_address(sockaddr[0])
        if (not address.is_global or address.is_loopback or address.is_private or address.is_link_local or
                address.is_reserved or address.is_multicast or address.is_unspecified):
            raise CheckFailure("unsafe URL")
    return addresses


def pinned_connection(connection_class, addresses, host, **kwargs):
    connection = connection_class(host, **kwargs)

    def connect(address, timeout=TIMEOUT, source_address=None):
        # Connect to the addresses already checked, retaining the original host
        # for HTTP Host and TLS certificate/SNI checks. Never resolve it again.
        last_error = None
        for family, socktype, protocol, canonname, sockaddr in addresses:
            sock = socket.socket(family, socktype, protocol)
            try:
                sock.settimeout(timeout)
                if source_address:
                    sock.bind(source_address)
                sock.connect(sockaddr)
                return sock
            except OSError as exc:
                last_error = exc
                sock.close()
        raise last_error or OSError("No public address")

    connection._create_connection = connect
    return connection


class PublicHTTP(urllib.request.HTTPHandler):
    def http_open(self, request):
        factory = partial(pinned_connection, http.client.HTTPConnection, public_addresses(request.full_url))
        return self.do_open(factory, request)


class PublicHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, request):
        factory = partial(pinned_connection, http.client.HTTPSConnection, public_addresses(request.full_url))
        return self.do_open(factory, request, context=self._context)


class PublicRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        self.followed = 0

    def http_error_302(self, request, response, code, message, headers):
        # urllib's default handler drains redirect bodies without a size limit.
        # Close instead: each hop uses a fresh connection and the same fetch deadline.
        response.close()
        location = headers.get("Location") or headers.get("URI")
        if not location:
            raise CheckFailure("fetch failed")
        if self.followed >= 5:
            raise CheckFailure("too many redirects")
        target = urljoin(request.full_url, quote(location, safe="/:?#[]@!$&'()*+,;=%", encoding="iso-8859-1"))
        url_parts(target)
        self.followed += 1
        # The HTTP/HTTPS handler resolves and validates every new target.
        return self.parent.open(urllib.request.Request(target), timeout=TIMEOUT)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


@contextmanager
def fetch_deadline():
    # Socket timeouts alone restart on every read. On POSIX, bound DNS, headers,
    # body reads and all redirects together; do not disturb an embedding caller's timer.
    enabled = (hasattr(signal, "setitimer") and threading.current_thread() is threading.main_thread() and
               signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0))
    if not enabled:
        yield
        return

    def timed_out(signum, frame):
        raise CheckFailure("fetch timed out")

    previous = signal.signal(signal.SIGALRM, timed_out)
    signal.setitimer(signal.ITIMER_REAL, TIMEOUT)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def fetch_page(url):
    url_parts(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), PublicHTTP(), PublicHTTPS(),
                                        PublicRedirects())
    with fetch_deadline(), opener.open(url, timeout=TIMEOUT) as response:
        content_type = response.headers.get_content_type()
        if not (content_type.startswith("text/") or content_type == "application/xhtml+xml"):
            raise CheckFailure("non-text content; mark source manual")
        length = response.headers.get("Content-Length", "")
        if length.isdigit() and int(length) > MAX_BYTES:
            raise CheckFailure("page too large")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise CheckFailure("page too large")
        text = body.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        if content_type in ("text/html", "application/xhtml+xml"):
            parser = PageText()
            parser.feed(text)
            parser.close()
            text = "".join(parser.parts)
        return text


def cache_path(url):
    state = Path(os.environ.get("AOE_CHIEF_HOME", "~/.local/state/aoe-chief")).expanduser()
    return state / "research-cache" / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json")


def cached_text(path, url):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["url"] == url and data["fetched_at"] and isinstance(data["text"], str):
            return data["text"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def save_page(path, url, text):
    directory = path.parent.resolve()
    # Some sandboxes place empty .git sentinels in /tmp; require actual Git
    # metadata, including the .git file used by a linked worktree.
    if any((parent / ".git").is_file() or (parent / ".git" / "HEAD").is_file()
           for parent in [directory] + list(directory.parents)):
        raise CheckFailure("cache must be outside repository")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=str(directory), delete=False) as stream:
            temporary = stream.name
            json.dump({"url": url, "fetched_at": datetime.now(timezone.utc).isoformat(), "text": text},
                      stream, ensure_ascii=False)
        os.replace(temporary, str(path))
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def parse_memo(text):
    outside, sources, duplicates = [], {}, set()
    in_sources, current, has_sources = False, None, False
    for line in text.splitlines():
        heading = re.fullmatch(r"(#{1,2})[ \t]+(.+?)[ \t]*", line)
        if heading:
            in_sources = heading.group(1) == "##" and heading.group(2) in ("Sources", "来源")
            has_sources = has_sources or in_sources
            current = None
        if not in_sources:
            outside.append(line)
            continue
        entry = re.match(r"^\[(\d+)\](.*)$", line)
        if entry:
            source_id = int(entry.group(1))
            if source_id in sources:
                duplicates.add(source_id)
            details = re.fullmatch(r"[ \t]+(\S+?)(?:[ \t]+\((manual|手动)\))?[ \t]*", entry.group(2))
            current = {"url": details.group(1) if details else "", "manual": bool(details and details.group(2)),
                       "quotes": []}
            sources[source_id] = current
        elif current is not None:
            blockquote = re.match(r"^[ \t]*>[ \t]?(.*)$", line)
            if blockquote and blockquote.group(1).strip():
                current["quotes"].append(blockquote.group(1).strip())
    body = "\n".join(outside)
    citations = {int(match) for match in re.findall(r"\[(\d+)\]", body)}
    return body, sources, citations, duplicates, has_sources


def id_list(ids):
    result = ""
    ordered = sorted(ids)
    for index, source_id in enumerate(ordered):
        token = "[{}]".format(source_id)
        if len(result) + len(token) > 90:
            return result + " +{} more".format(len(ordered) - index)
        result += token
    return result


def report(errors, sources=None, verified=0, manual=None, pending=0):
    if errors or pending:
        parts = [reason + (" " + id_list(ids) if ids else "") for reason, ids in sorted(errors.items())]
        if pending:
            parts.insert(0, "{} sources not fetched yet; rerun".format(pending))
        summary = "FAIL: "
        for part in parts:
            separator = "" if summary == "FAIL: " else "; "
            if len(summary) + len(separator) + len(part) > 775:
                summary += "; more violations"
                break
            summary += separator + part
        print(summary)
        return 1
    manual = manual or set()
    print("OK: {} sources, {} quotes verified, {} manual{}".format(
        len(sources), verified, len(manual), " " + id_list(manual) if manual else ""))
    return 0


class Arguments(argparse.ArgumentParser):
    def error(self, message):
        raise CheckFailure("invalid arguments")


def main(argv=None, fetcher=None):
    parser = Arguments(prog="research_check.py", description=__doc__.splitlines()[0])
    parser.add_argument("memo", help="path to memo.md")
    parser.add_argument("--refresh", action="store_true", help="refetch cached pages")
    try:
        args = parser.parse_args(argv)
    except CheckFailure as exc:
        return report({str(exc): set()})
    try:
        text = Path(args.memo).read_text(encoding="utf-8")
    except FileNotFoundError:
        return report({"missing memo": set()})
    except (OSError, UnicodeError):
        return report({"unreadable memo": set()})
    body, sources, citations, duplicates, has_sources = parse_memo(text)
    errors = {}

    def fail(reason, ids=()):
        errors.setdefault(reason, set()).update(ids)

    if not re.search(r"^(?:Conclusion:|结论：)[ \t]*\S[^\n]*$", body, re.M):
        fail("missing conclusion")
    if not re.search(r"^##[ \t]+(?:Reasons|理由)[ \t]*$", body, re.M):
        fail("missing reasons")
    if not has_sources:
        fail("missing sources")
    if citations - sources.keys():
        fail("missing source", citations - sources.keys())
    if duplicates:
        fail("duplicate source", duplicates)
    # Validate source records before making requests: malformed entries already
    # make the memo fail and should be corrected before spending fetch budget.
    for source_id, source in sorted(sources.items()):
        try:
            url_parts(source["url"])
        except CheckFailure:
            fail("invalid source", [source_id])
        if not source["quotes"]:
            fail("missing quote", [source_id])
    if any(reason in errors for reason in ("invalid source", "missing quote", "duplicate source")):
        return report(errors)
    fetched, attempts, verified, manual, pending = {}, 0, 0, set(), set()
    for source_id, source in sorted(sources.items()):
        url, quotes = source["url"], source["quotes"]
        if source["manual"]:
            manual.add(source_id)
            continue
        if url not in fetched:
            path = cache_path(url)
            page = None if args.refresh else cached_text(path, url)
            failure = None
            if page is None:
                if attempts >= MAX_FETCHES:
                    pending.add(url)
                    continue
                attempts += 1
                try:
                    page = (fetcher or fetch_page)(url)
                    if not isinstance(page, str):
                        raise CheckFailure("fetch failed")
                    save_page(path, url, page)
                except CheckFailure as exc:
                    failure = str(exc)
                except (OSError, ValueError, LookupError, http.client.HTTPException):
                    failure = "fetch failed"
            fetched[url] = (normalize(page) if failure is None else None, failure)
        page, failure = fetched[url]
        if failure:
            fail(failure, [source_id])
            continue
        for quote_text in quotes:
            if normalize(quote_text) in page:
                verified += 1
            else:
                fail("quote not found", [source_id])
    return report(errors, sources, verified, manual, len(pending))


if __name__ == "__main__":
    sys.exit(main())
