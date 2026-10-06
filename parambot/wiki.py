"""Everything the bot asks of the wiki, in one place.

The rest of the bot reaches the wiki only through a Wiki object, which makes
it easy to see what the bot does there, and lets the tests use a fake wiki.
Pages are Pywikibot Page objects; the WikiPage protocol lists the parts of
them the bot relies on.
"""

import logging
import re
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import pywikibot

log = logging.getLogger('parambot')

# An article title to expand templates against, so {{main other}} and the
# like behave as they would in an article.
PROBE_TITLE = 'ParamBot probe'
BATCH = 50  # titles per API request


class WikiPage(Protocol):
    """The parts of a Pywikibot Page the bot uses (with Pywikibot's names,
    camelCase included)."""

    text: str
    content_model: str
    latest_revision_id: int

    def title(self, *, with_ns: bool = True) -> str: ...
    def namespace(self) -> Any: ...
    def exists(self) -> bool: ...
    def isRedirectPage(self) -> bool: ...
    def getRedirectTarget(self) -> 'WikiPage': ...
    def templates(self) -> list['WikiPage']: ...
    def protection(self) -> dict[str, tuple[str, str]]: ...
    def has_permission(self, action: str = 'edit') -> bool: ...
    def botMayEdit(self) -> bool: ...
    def getOldVersion(self, oldid: int) -> str: ...
    def save(self, *, summary: str, minor: bool, bot: bool, quiet: bool,
             nocreate: bool = False) -> None: ...


@dataclass(frozen=True)
class Revision:
    """One revision of a page."""

    revid: int
    title: str           # the page it belongs to, as the page is called now
    text: str | None     # None if the text has been hidden
    model: str           # the content model, such as "wikitext"
    latest: int          # the page's newest revision


class Wiki:
    """A wiki, through Pywikibot."""

    def __init__(self, site: Any) -> None:
        self.site = site

    # -- the account -------------------------------------------------------

    def login(self) -> str:
        """Log in with the account in user-config.py; return its name.

        Pywikibot first tries the login saved in its cookie file, and only
        uses the bot password if that no longer works.  A saved login keeps
        the grants of the bot password it was made with, even once
        user-password.py names another, so the log says which it used."""
        name = str(self.site.username())
        self.site.login(cookie_only=True)
        if self.site.logged_in():
            log.info('Logged in as %s, reusing the saved login in pywikibot-%s.lwp',
                     name, name)
        else:
            self.site.login()
            if self.site.logged_in():
                log.info('Logged in as %s with the bot password in user-password.py', name)
            else:
                log.warning('Could not log in as %s', name)
        return str(self.site.username())

    def has_right(self, right: str) -> bool:
        return bool(self.site.has_right(right))

    # -- pages -------------------------------------------------------------

    def page(self, title: str, ns: int = 0) -> WikiPage:
        """A page, not yet loaded.  ns is the namespace for titles without a
        prefix: 10 for templates."""
        page: WikiPage = pywikibot.Page(self.site, title, ns=ns)
        return page

    def load(self, pages: Iterable[WikiPage], *, templates: bool = False) -> Iterator[WikiPage]:
        """Load pages' text and details in batches, yielding them as they
        arrive.  With templates, also load the templates each page uses."""
        yield from self.site.preloadpages(list(pages), groupsize=BATCH, templates=templates)

    def load_titles(self, titles: Iterable[str], *, templates: bool = False
                    ) -> dict[str, WikiPage]:
        """{title: loaded page} for titles, in one batch."""
        pages = {title: self.page(title) for title in titles}
        loaded = {p.title(): p for p in self.load(pages.values(), templates=templates)}
        return {title: loaded.get(page.title(), page) for title, page in pages.items()}

    def revisions(self, revids: Iterable[int]) -> dict[int, Revision]:
        """The given revisions, of any pages, by ID.  Revisions that don't
        exist, or were deleted with their page, are left out."""
        revids = list(revids)
        found: dict[int, Revision] = {}
        for i in range(0, len(revids), BATCH):
            data = self.site.simple_request(
                action='query', prop='revisions|info', rvprop='ids|content',
                rvslots='main', revids='|'.join(map(str, revids[i:i + BATCH])),
                formatversion=2).submit()
            for page in data['query'].get('pages', []):
                for revision in page.get('revisions', []):
                    main = revision.get('slots', {}).get('main', {})
                    found[revision['revid']] = Revision(
                        revision['revid'], page['title'], main.get('content'),
                        main.get('contentmodel', page.get('contentmodel', '')),
                        page['lastrevid'])
        return found

    def subpages(self, title: str) -> list[str]:
        """The titles of the pages under title/, without redirects: a
        request for each 500 of them (5,000 with the bot right)."""
        parent = pywikibot.Page(self.site, title)
        return [page.title() for page in self.site.allpages(
            prefix=parent.title(with_ns=False) + '/', namespace=parent.namespace(),
            filterredir=False)]

    def recent_edits(self, user: str, since: datetime) -> dict[str, datetime]:
        """{title: when user last edited it}, for every page user has edited
        since then: a request per 500 edits (5,000 for bots), rather than a
        look at each page's history."""
        found: dict[str, datetime] = {}
        params: dict[str, Any] = {
            'action': 'query', 'list': 'usercontribs', 'ucuser': user,
            'ucend': since.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'ucprop': 'title|timestamp', 'uclimit': 'max', 'formatversion': 2}
        while True:
            data = self.site.simple_request(**params).submit()
            for edit in data['query']['usercontribs']:   # newest first
                when = datetime.fromisoformat(edit['timestamp'].replace('Z', '+00:00'))
                found.setdefault(edit['title'], when)
            if 'continue' not in data:
                break
            params.update(data['continue'])
        return found

    def redirects(self, titles: list[str], ns: int) -> dict[str, list[str]]:
        """{title: the titles in namespace ns that redirect to it}, for
        BATCH titles a request rather than one each."""
        found: dict[str, list[str]] = {title: [] for title in titles}
        for i in range(0, len(titles), BATCH):
            params: dict[str, Any] = {
                'action': 'query', 'prop': 'redirects', 'titles': '|'.join(titles[i:i + BATCH]),
                'rdnamespace': ns, 'rdprop': 'title', 'rdlimit': 'max', 'formatversion': 2}
            while True:
                data = self.site.simple_request(**params).submit()
                for page in data['query']['pages']:
                    found.setdefault(page['title'], []).extend(
                        redirect['title'] for redirect in page.get('redirects', []))
                if 'continue' not in data:
                    break
                params.update(data['continue'])
        return found

    def expand(self, text: str) -> str:
        """text with its templates expanded, as if it were in an article."""
        return str(self.site.expand_text(text, title=PROBE_TITLE))

    def expand_all(self, texts: list[str]) -> list[str]:
        """Each text expanded as if it were in an article, BATCH texts a
        request rather than one each."""
        expanded: list[str] = []
        for i in range(0, len(texts), BATCH):
            expanded += self._expand_together(texts[i:i + BATCH])
        return expanded

    def _expand_together(self, texts: list[str]) -> list[str]:
        if len(texts) == 1:
            return [self.expand(texts[0])]
        # A marker no text can contain, between the texts.  If a text's markup
        # swallows a marker (an unclosed {{ or <!--), expand them one by one.
        marker = f'ParamBot-{uuid.uuid4().hex}'
        parts = re.split(rf'\s*{marker}\s*', self.expand(
            ''.join(f'\n{marker}\n{text}' for text in texts)))
        if len(parts) != len(texts) + 1 or parts[0].strip():
            return [self.expand(text) for text in texts]
        return parts[1:]

    # -- categories --------------------------------------------------------

    def category_sizes(self, titles: list[str]) -> dict[str, int | None]:
        """The number of pages in each category.  None for a category that
        has neither a page nor any members."""
        sizes: dict[str, int | None] = {}
        for i in range(0, len(titles), BATCH):
            data = self.site.simple_request(
                action='query', prop='categoryinfo', titles='|'.join(titles[i:i + BATCH]),
                formatversion=2).submit()
            for info in data['query']['pages']:
                if 'categoryinfo' in info:
                    sizes[info['title']] = info['categoryinfo'].get('pages', 0)
                elif info.get('missing'):
                    sizes[info['title']] = None
        return sizes

    def category_members(self, category: str, namespaces: Iterable[int]) -> Iterator[WikiPage]:
        yield from pywikibot.Category(self.site, category).members(namespaces=list(namespaces))
