"""The report page: what the bot could not do, for humans to follow up."""

from dataclasses import dataclass, field

from .fixer import Issue

__all__ = ['Report']

HEADER = ('<!-- This page is rewritten by the bot on every run; '
          'edits to it will be lost. -->')


def _code(text: str) -> str:
    return f'<code><nowiki>{text}</nowiki></code>'


def _page(title: str) -> str:
    return f'[[:{title}]]'


def _template(name: str) -> str:
    return f'[[Template:{name}|{name}]]'


def _section(title: str, lines: list[str], intro: str = '') -> list[str]:
    """A report section: a heading, an optional line of explanation, then
    the lines, or "None." if there aren't any."""
    return [f'== {title} ==', *([intro] if intro else []), *(lines or ['None.']), '']


def _bullets(items: list[str]) -> list[str]:
    return [f'* <nowiki>{item}</nowiki>' for item in items]


@dataclass
class Report:
    issues: list[tuple[str, Issue]] = field(default_factory=list)  # (page title, issue)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (page title, reason)
    problems: list[str] = field(default_factory=list)  # with the rules pages or templates
    notes: list[str] = field(default_factory=list)     # for information
    errors: list[str] = field(default_factory=list)    # the run went wrong
    setup: list[str] = field(default_factory=list)     # bot pages that would stop a live run
    edits: int = 0
    pages_checked: int = 0
    categories_polled: int = 0
    categories_populated: int = 0

    def issue(self, title: str, issue: Issue) -> None:
        self.issues.append((title, issue))

    def skip(self, title: str, reason: str) -> None:
        self.skipped.append((title, reason))

    def stats_line(self, timestamp: str, live: bool) -> str:
        verb = 'made' if live else 'would have made (dry run)'
        return (f'Last run: {timestamp} (UTC). Polled {self.categories_polled} '
                f'categories, {self.categories_populated} populated; checked '
                f'{self.pages_checked} pages; {verb} {self.edits} edits.')

    def body(self) -> str:
        """The report without the stats line, for deciding whether to save."""
        out: list[str] = []
        # These two only appear when something is wrong.
        if self.setup:
            out += _section('Setup problems', _bullets(self.setup),
                            'A live run refuses to start until these are fixed.')
        if self.errors:
            out += _section('Errors', _bullets(self.errors),
                            'This run did not finish. Tell the bot operator.')
        out += _section('Needs human review', self._issue_table())
        out += _section('Not edited', [f'* {_page(title)}: <nowiki>{reason}</nowiki>'
                                       for title, reason in sorted(self.skipped)])
        out += _section('Rules page problems', _bullets(self.problems))
        if self.notes:
            out += _section('Notes', _bullets(self.notes))
        return '\n'.join(out).rstrip('\n') + '\n'

    def _issue_table(self) -> list[str]:
        if not self.issues:
            return []
        lines = ['{| class="wikitable sortable"', '! Page !! Template !! Parameter !! Problem']
        for title, issue in sorted(self.issues, key=lambda item: (item[0], item[1].template)):
            param = _code(issue.param)
            if issue.target:
                param += ' → ' + _code(issue.target)
            lines += ['|-', f'| {_page(title)} || {_template(issue.template)} || {param} '
                            f'|| <nowiki>{issue.reason}</nowiki>']
        return [*lines, '|}']

    def render(self, timestamp: str, live: bool) -> str:
        return f'{HEADER}\n{self.stats_line(timestamp, live)}\n\n{self.body()}'

    @staticmethod
    def body_of(text: str) -> str:
        """The body of a previously rendered report (everything after the
        stats line)."""
        parts = text.split('\n\n', 1)
        return parts[1] if len(parts) == 2 else text
