"""The report page: what the bot could not do, for humans to follow up."""

import re
from dataclasses import dataclass, field

from .fixer import Issue
from .messages import CODE, MARKED_RE, PARA, QUOTED, TL, count

__all__ = ['Links', 'Report']

HEADER = ('<!-- This page is rewritten by the bot on every run; '
          'edits to it will be lost. -->')

# Characters a page title can't contain, so a name with one isn't linked.
_NOT_A_TITLE = re.compile(r'[\[\]{}|#<>\n]')
# Characters that can't go in a template argument such as {{para|name}}.
_NOT_AN_ARGUMENT = re.compile(r'[|={}\[\]<>\n]')
# A diff the report points to.  (Special:Permalink only appears as an example.)
_DIFF = r'Special:Diff/\d+/\d+'
# Wikitext that could do something in the middle of a line of the report,
# written as entities instead.  The bot's own sentences have none of it.
_WIKITEXT = re.compile(r"[\[\]{}|<>&]|'{2,}|~{3,}|_{2,}|\n")
_ENTITIES = {'[': '&#91;', ']': '&#93;', '{': '&#123;', '}': '&#125;', '|': '&#124;',
             '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&#39;', '~': '&#126;',
             '_': '&#95;', '\n': ' '}


def _escaped(text: str) -> str:
    """text, with anything in it that could work as wikitext made inert."""
    return _WIKITEXT.sub(lambda m: ''.join(_ENTITIES[c] for c in m.group(0)), text)


def _nowiki(text: str) -> str:
    # With < as an entity, which <nowiki> still shows as <, text can't close
    # the <nowiki> itself: rules pages, which anyone can edit, end up here.
    return f'<nowiki>{text.replace("<", "&lt;")}</nowiki>' if text else ''


def _code(text: str) -> str:
    return f'<code>{_nowiki(text)}</code>'


def _para(name: str) -> str:
    """A parameter name, as {{para|name}}, or as code if it can't go in one."""
    return _code(name) if not name or _NOT_AN_ARGUMENT.search(name) else f'{{{{para|{name}}}}}'


def _tl(name: str) -> str:
    """A template, as {{tl|name}}, or as code if it can't go in one."""
    return _code(f'{{{{{name}}}}}') if _NOT_AN_ARGUMENT.search(name) else f'{{{{tl|{name}}}}}'


# How each marked part of a message goes on the report.
_MARKED = {PARA: _para, TL: _tl, CODE: _code, QUOTED: _nowiki}


def _page(title: str) -> str:
    return f'[[:{title}]]'


def _template(name: str) -> str:
    return f'[[Template:{name}|{name}]]'


def _section(title: str, lines: list[str], intro: str = '') -> list[str]:
    """A report section: a heading, an optional line of explanation, then
    the lines, or "None." if there aren't any."""
    return [f'== {title} ==', *([intro] if intro else []), *(lines or ['None.']), '']


@dataclass
class Links:
    """The pages the report links to where it names them: the list of rules
    pages, each template's rules page and the template itself, and diffs.
    Everything else it says is shown as it is."""

    index: str = ''                                             # the list of rules pages
    rules_pages: dict[str, str] = field(default_factory=dict)   # {template: its rules page}
    other: tuple[str, ...] = ()                                 # other pages messages name

    def wikitext(self, text: str) -> str:
        """A message as wikitext: the pages it names linked, and its marked
        parts shown as they're marked (see messages.para, tl, code, quoted)."""
        out, last = [], 0
        for m in MARKED_RE.finditer(text):
            out += [self._linked(text[last:m.start()]), _MARKED[m.group(1)](m.group(2))]
            last = m.end()
        return ''.join([*out, self._linked(text[last:])])

    def _linked(self, text: str) -> str:
        targets = self._targets()
        names = sorted(targets, key=len, reverse=True)   # a rules page before its template
        # A whole name only: not "Infobox person" inside "Infobox person 2",
        # or the index inside the title of a rules page it doesn't know.
        pattern = re.compile(r'(?<![\w/:])(?:' + '|'.join([*map(re.escape, names), _DIFF])
                             + r')(?![\w/])')
        out, last = [], 0
        for m in pattern.finditer(text):
            target, label = targets.get(m.group(0), (m.group(0), m.group(0)))
            out += [_escaped(text[last:m.start()]),
                    f'[[{target}]]' if target == label else f'[[{target}|{label}]]']
            last = m.end()
        return ''.join([*out, _escaped(text[last:])])

    def rules_link(self, template: str) -> str:
        """A link to a template's rules page, or '' if it has none."""
        page = self.rules_pages.get(template)
        return f'[[{page}|rules]]' if page and not _NOT_A_TITLE.search(page) else ''

    def _targets(self) -> dict[str, tuple[str, str]]:
        """{text: (the page it links to, what it shows)}."""
        targets: dict[str, tuple[str, str]] = {}
        for title in (self.index, *self.other):
            targets[title] = (title, title)
        for template, page in self.rules_pages.items():
            # A rules page shows as its template's name: "Infobox person",
            # not "User:ParamBot/Rules/Infobox person".
            targets[page] = targets[template] = (page, template)
            targets[f'Template:{template}'] = (f'Template:{template}', f'Template:{template}')
        return {text: link for text, link in targets.items()
                if text and not _NOT_A_TITLE.search(link[0])}


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
    header: str = ''       # a page to transclude at the top, such as User:ParamBot/Header
    links: Links = field(default_factory=Links)

    def issue(self, title: str, issue: Issue) -> None:
        self.issues.append((title, issue))

    def skip(self, title: str, reason: str) -> None:
        self.skipped.append((title, reason))

    def stats_line(self, timestamp: str, live: bool) -> str:
        verb = 'made' if live else 'would have made (dry run)'
        return (f'Last run: {timestamp} (UTC). Polled '
                f'{count(self.categories_polled, "category", "categories")}, '
                f'{self.categories_populated} populated; checked '
                f'{count(self.pages_checked, "page")}; {verb} {count(self.edits, "edit")}.')

    def body(self) -> str:
        """The report without the stats line, for deciding whether to save."""
        out: list[str] = []
        # These two only appear when something is wrong.
        if self.setup:
            out += _section('Setup problems', self._bullets(self.setup),
                            'A live run refuses to start until these are fixed.')
        if self.errors:
            out += _section('Errors', self._bullets(self.errors),
                            'This run did not finish. Tell the bot operator.')
        out += _section('Needs human review', self._issue_table())
        out += _section('Not edited', [f'* {_page(title)}: {self.links.wikitext(reason)}'
                                       for title, reason in sorted(self.skipped)])
        out += _section('Rules page problems', self._bullets(self.problems))
        if self.notes:
            out += _section('Notes', self._bullets(self.notes))
        return '\n'.join(out).rstrip('\n') + '\n'

    def _bullets(self, items: list[str]) -> list[str]:
        return [f'* {self.links.wikitext(item)}' for item in items]

    def _issue_table(self) -> list[str]:
        if not self.issues:
            return []
        lines = ['{| class="wikitable sortable"', '! Page !! Template !! Parameter !! Problem']
        for title, issue in sorted(self.issues, key=lambda item: (item[0], item[1].template)):
            param = _para(issue.param)
            if issue.target:
                param += ' → ' + _para(issue.target)
            template = _template(issue.template)
            if rules := self.links.rules_link(issue.template):
                template += f' ({rules})'
            lines += ['|-', f'| {_page(title)} || {template} || {param} '
                            f'|| {self.links.wikitext(issue.reason)}']
        return [*lines, '|}']

    def render(self, timestamp: str, live: bool) -> str:
        top = [f'{{{{{self.header}}}}}'] if self.header else []
        return '\n'.join([*top, HEADER, self.stats_line(timestamp, live), '', self.body()])

    @staticmethod
    def body_of(text: str) -> str:
        """The body of a previously rendered report (everything after the
        stats line)."""
        parts = text.split('\n\n', 1)
        return parts[1] if len(parts) == 2 else text
