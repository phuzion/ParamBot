"""The report page: what the bot could not do, for humans to follow up."""

from dataclasses import dataclass, field

__all__ = ['Report']

HEADER = ('<!-- This page is rewritten by the bot on every run; '
          'edits to it will be lost. -->')


def _code(text):
    return f'<code><nowiki>{text}</nowiki></code>'


def _page(title):
    return f'[[:{title}]]'


def _template(name):
    return f'[[Template:{name}|{name}]]'


@dataclass
class Report:
    issues: list = field(default_factory=list)    # (title, fixer.Issue)
    skipped: list = field(default_factory=list)   # (title, reason)
    problems: list = field(default_factory=list)  # rules-page / rule set problems
    notes: list = field(default_factory=list)     # informational
    errors: list = field(default_factory=list)    # the run went wrong
    edits: int = 0
    pages_checked: int = 0
    categories_polled: int = 0
    categories_populated: int = 0

    def issue(self, title, issue):
        self.issues.append((title, issue))

    def skip(self, title, reason):
        self.skipped.append((title, reason))

    def stats_line(self, timestamp, live):
        verb = 'made' if live else 'would have made (dry run)'
        return (f"Last run: {timestamp} (UTC). Polled {self.categories_polled} "
                f"categories, {self.categories_populated} populated; checked "
                f"{self.pages_checked} pages; {verb} {self.edits} edits.")

    def body(self):
        """The report without the stats line, for deciding whether to save."""
        out = []
        if self.errors:
            out.append('== Errors ==')
            out.append('This run did not finish. Tell the bot operator.')
            for error in self.errors:
                out.append(f'* <nowiki>{error}</nowiki>')
            out.append('')
        out.append('== Needs human review ==')
        if self.issues:
            out.append('{| class="wikitable sortable"')
            out.append('! Page !! Template !! Parameter !! Problem')
            for title, issue in sorted(self.issues, key=lambda x: (x[0], x[1].template)):
                param = _code(issue.param)
                if issue.target:
                    param += ' → ' + _code(issue.target)
                out.append('|-')
                out.append(f'| {_page(title)} || {_template(issue.template)} || {param} '
                           f'|| <nowiki>{issue.reason}</nowiki>')
            out.append('|}')
        else:
            out.append('None.')
        out.append('')
        out.append('== Not edited ==')
        if self.skipped:
            for title, reason in sorted(self.skipped):
                out.append(f'* {_page(title)}: <nowiki>{reason}</nowiki>')
        else:
            out.append('None.')
        out.append('')
        out.append('== Rules page problems ==')
        if self.problems:
            for problem in self.problems:
                out.append(f'* <nowiki>{problem}</nowiki>')
        else:
            out.append('None.')
        if self.notes:
            out.append('')
            out.append('== Notes ==')
            for note in self.notes:
                out.append(f'* <nowiki>{note}</nowiki>')
        return '\n'.join(out) + '\n'

    def render(self, timestamp, live):
        return f'{HEADER}\n{self.stats_line(timestamp, live)}\n\n{self.body()}'

    @staticmethod
    def body_of(text):
        """The body of a previously rendered report (everything after the
        stats line)."""
        parts = text.split('\n\n', 1)
        return parts[1] if len(parts) == 2 else text
