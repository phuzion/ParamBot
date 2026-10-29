"""The report history page, User:ParamBot/ReportHistory: a row for each run.

The report page is replaced on every run, so it only says what the latest
one found.  The history page keeps a line for every live and report-only
run, newest first, saying when it ran, what it did and how it ended, except
runs that didn't start because User:ParamBot/Run was off:

    {{User:ParamBot/Header}}
    A line for every run of ParamBot, newest first, except runs that didn't
    start because User:ParamBot/Run was off. ...

    {| class="wikitable"
    ! Started (UTC) !! Ended (UTC) !! Duration !! Mode !! Categories !! Checked !! Edits
      !! Needs review !! Result
    <!-- ParamBot: new runs go below this line -->
    |-
    | 2026-10-27 04:00 || 2026-10-27 04:12 || 12 minutes || live || 3 of 41 || 57 || 52 || 2
      || finished ([[Special:Permalink/123|report]])
    |}

(the row is one line on the page).  A run that someone stopped with the Run
page says when the page was changed, and by whom.  Everything above the
marker is kept as it is, so the introduction can be edited by hand; the
oldest rows go once there are MAX_ROWS.
"""

from datetime import datetime

from . import messages as msg

__all__ = ['MARKER', 'MAX_ROWS', 'updated_page', 'history_row']

MARKER = '<!-- ParamBot: new runs go below this line -->'
MAX_ROWS = 200   # 50 days of runs every 6 hours
_TABLE_END = '|}'
_HEADINGS = ('! Started (UTC) !! Ended (UTC) !! Duration !! Mode !! Categories !! Checked '
             '!! Edits !! Needs review !! Result')


def updated_page(old: str | None, row: str, *, header: str, intro: str) -> str:
    """The history page's text with row at the top of its table.  A page
    without the table (new, a placeholder, or edited by hand) is started
    afresh."""
    if old is None or MARKER not in old or _TABLE_END not in old.split(MARKER, 1)[1]:
        top = f'{{{{{header}}}}}\n' if header else ''
        return (f'{top}{intro}\n\n{{| class="wikitable"\n{_HEADINGS}\n'
                f'{MARKER}\n{row.rstrip(chr(10))}\n{_TABLE_END}\n')
    head, rest = old.split(MARKER, 1)
    body, _, tail = rest.partition('\n' + _TABLE_END)
    rows = [row] + _rows(body)[:MAX_ROWS - 1]
    return head + MARKER + '\n' + ''.join(r.rstrip('\n') + '\n' for r in rows) + _TABLE_END + tail


def _rows(body: str) -> list[str]:
    """The table's rows, each starting with its |- line."""
    rows: list[str] = []
    for line in body.strip('\n').split('\n'):
        if line.startswith('|-') or not rows:
            rows.append('')
        rows[-1] += line + '\n'
    return [row for row in rows if row.strip()]


def history_row(*, started: datetime, ended: datetime, mode: str, categories: str,
                checked: int, edits: int, needing_review: int, result: str) -> str:
    """A run's row.  result is wikitext, saying how the run ended."""
    cells = [_when(started), _when(ended), msg.duration((ended - started).total_seconds()),
             mode, categories, str(checked), str(edits), str(needing_review), result]
    return '|-\n| ' + ' || '.join(cells) + '\n'


def _when(moment: datetime) -> str:
    return f'{moment:%Y-%m-%d %H:%M}'
