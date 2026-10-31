# Research worker rules

Read the goal's question, decision, rejected directions and stop condition before searching.
Deliver one file: `research/<id>/memo.md`.

- Answer the question first in one sentence, prefixed with `Conclusion:` or `结论：`.
- Give at most 3 reasons under `## Reasons` (or `## 理由`). Use one checkable claim per
  cited source, with numbered citations such as `[1]` or `[2][3]`.
- Under `## Sources` (or `## 来源`), write each `[n] https://...` followed by at least
  one `> quote` line. Quote verbatim in the original language. Never cite a page you
  did not open; search snippets alone are not a source.
- For paywalls, login pages, PDFs or other pages the checker cannot fetch, add
  `(manual)` (or `(手动)`) after the URL. Still open the source and record its original
  quote; manual quotes require human review.
- Record queries tried and unresolved questions under `## Uncertain / not found`.
- Stop when the stop condition in the goal is met; do not expand the scope.
- Run `python3 ~/aoe-chief/tools/research_check.py research/<id>/memo.md` yourself
  before ending a turn. Fix failures; if the fetch limit is reached, rerun to use
  the saved pages. Use `--refresh` when a cached page needs updating.
- Commit every turn and update `.chief/progress.md` so a fresh session can continue.

The check confirms quotes exist; the reviewer must still assess whether they support
the conclusion and whether the memo answers the question.
