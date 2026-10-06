"""The requests Wiki makes, with a stand-in for Pywikibot's site."""

import re
from datetime import UTC, datetime

from parambot.wiki import BATCH, Revision, Wiki


class Request:
    def __init__(self, data):
        self.data = data

    def submit(self):
        return self.data


class Site:
    """Enough of a Pywikibot site: templates expand as MediaWiki would, as
    far as these tests need, and each page of API results has at most two
    redirects or edits."""

    def __init__(self, redirects=None, contribs=()):
        self.expanded = []     # the text of each expandtemplates request
        self.queries = []      # the parameters of each API query
        self.redirect_map = redirects or {}
        self.contribs = list(contribs)   # (title, timestamp), newest first

    def expand_text(self, text, title):
        self.expanded.append(text)
        text = text.replace('{{x}}', 'X')
        # An unclosed comment hides the rest.
        return re.sub(r'<!--.*?(-->|$)', '', text, flags=re.S)

    def simple_request(self, **params):
        self.queries.append(dict(params))
        if params.get('list') == 'usercontribs':
            start = int(params.get('uccontinue', 0))
            data = {'query': {'usercontribs': [
                {'title': title, 'timestamp': timestamp}
                for title, timestamp in self.contribs[start:start + 2]]}}
            if start + 2 < len(self.contribs):
                data['continue'] = {'uccontinue': str(start + 2), 'continue': '-||'}
            return Request(data)
        start = int(params.get('rdcontinue', 0))
        pairs = [(title, redirect) for title in params['titles'].split('|')
                 for redirect in self.redirect_map.get(title, [])]
        pages = {}
        for title, redirect in pairs[start:start + 2]:
            pages.setdefault(title, []).append({'ns': 10, 'title': redirect})
        data = {'query': {'pages': [
            {'title': title, **({'redirects': pages[title]} if title in pages else {})}
            for title in params['titles'].split('|')]}}
        if start + 2 < len(pairs):
            data['continue'] = {'rdcontinue': str(start + 2), 'continue': '||'}
        return Request(data)


def test_texts_are_expanded_together():
    site = Site()
    assert Wiki(site).expand_all(['{{x}} one', 'two', '{{x}}']) == ['X one', 'two', 'X']
    assert len(site.expanded) == 1


def test_texts_are_expanded_one_by_one_if_one_swallows_the_rest():
    site = Site()
    assert Wiki(site).expand_all(['{{x}}', 'b <!-- c', 'd']) == ['X', 'b ', 'd']
    assert len(site.expanded) == 1 + 3


def test_texts_are_expanded_fifty_at_a_time():
    site = Site()
    texts = [f'{{{{x}}}} {i}' for i in range(2 * BATCH + 1)]
    assert Wiki(site).expand_all(texts) == [f'X {i}' for i in range(2 * BATCH + 1)]
    assert len(site.expanded) == 3


def test_redirects_are_looked_up_fifty_templates_at_a_time():
    titles = [f'Template:T{i}' for i in range(BATCH + 1)]
    site = Site(redirects={'Template:T0': ['Template:A', 'Template:B', 'Template:C'],
                           'Template:T1': ['Template:D'],
                           f'Template:T{BATCH}': ['Template:E']})
    found = Wiki(site).redirects(titles, 10)
    assert found['Template:T0'] == ['Template:A', 'Template:B', 'Template:C']
    assert found['Template:T1'] == ['Template:D']
    assert found[f'Template:T{BATCH}'] == ['Template:E']
    assert found['Template:T2'] == []
    # Two batches, the first continued once for its four redirects.
    assert len(site.queries) == 3
    assert all(query['rdnamespace'] == 10 for query in site.queries)


def test_subpages_are_listed_in_one_go(monkeypatch):
    class Page:
        """Enough of a Pywikibot page to split off the namespace."""

        def __init__(self, site, title):
            self._title = title

        def title(self, *, with_ns=True):
            return self._title if with_ns else self._title.partition(':')[2]

        def namespace(self):
            return 2

    class Listing(Site):
        def allpages(self, **params):
            self.queries.append(params)
            return [Page(self, 'User:ExampleBot/Rules/Infobox a'),
                    Page(self, 'User:ExampleBot/Rules/Instructions')]

    monkeypatch.setattr('parambot.wiki.pywikibot.Page', Page)
    site = Listing()
    assert Wiki(site).subpages('User:ExampleBot/Rules') == [
        'User:ExampleBot/Rules/Infobox a', 'User:ExampleBot/Rules/Instructions']
    # Pywikibot follows the continuation, 500 or 5,000 titles a request.
    assert site.queries == [{'prefix': 'ExampleBot/Rules/', 'namespace': 2,
                             'filterredir': False}]


def test_the_bots_recent_edits_are_looked_up_together():
    site = Site(contribs=[('A', '2026-09-28T10:00:00Z'), ('B', '2026-09-27T09:00:00Z'),
                          ('A', '2026-09-20T08:00:00Z')])
    found = Wiki(site).recent_edits('ExampleBot', datetime(2026, 9, 1, tzinfo=UTC))
    assert found == {'A': datetime(2026, 9, 28, 10, tzinfo=UTC),   # the newest edit
                     'B': datetime(2026, 9, 27, 9, tzinfo=UTC)}
    assert len(site.queries) == 2
    assert site.queries[0]['ucuser'] == 'ExampleBot'
    assert site.queries[0]['ucend'] == '2026-09-01T00:00:00Z'


# -- the account, pages, revisions and categories --------------------------

class Page:
    """Enough of a Pywikibot page: a title, first letter upper-cased as
    MediaWiki does."""

    def __init__(self, site, title, ns=0):
        self.site, self.ns = site, ns
        self._title = title[:1].upper() + title[1:]

    def title(self, *, with_ns=True):
        return self._title if with_ns else self._title.partition(':')[2]


class Pages(Site):
    """A site that logs in, loads pages, and answers revision and category
    queries the way the API does (formatversion=2)."""

    def __init__(self, revisions=(), categories=None, unloadable=()):
        super().__init__()
        # {revid: (title, text, model)}; text None if it's hidden.
        self.revision_data = {revid: rest for revid, *rest in revisions}
        self.category_data = categories or {}    # title: size, or None if missing
        self.unloadable = set(unloadable)        # titles preloadpages leaves out
        self.preloaded = []                      # (pages, groupsize, templates) per call
        self.saved_login = False    # whether the cookie file holds a login that works
        self.password_works = True
        self.logins = []            # cookie_only, per call to login()
        self.session = None         # 'saved' or 'password', once logged in

    def login(self, cookie_only=False):
        self.logins.append(cookie_only)
        if self.session:
            return
        if self.saved_login:
            self.session = 'saved'
        elif not cookie_only and self.password_works:
            self.session = 'password'

    def logged_in(self):
        return self.session is not None

    def username(self):
        return 'ExampleBot'

    def has_right(self, right):
        return right == 'bot'

    def preloadpages(self, pages, *, groupsize, templates):
        self.preloaded.append((len(pages), groupsize, templates))
        return [page for page in pages if page.title() not in self.unloadable]

    def simple_request(self, **params):
        self.queries.append(dict(params))
        if params.get('prop') == 'revisions|info':
            pages = {}
            for revid in map(int, params['revids'].split('|')):
                if revid not in self.revision_data:
                    continue
                title, text, model = self.revision_data[revid]
                main = {'contentmodel': model, **({'content': text} if text is not None else
                                                  {'texthidden': True})}
                page = pages.setdefault(title, {'title': title, 'lastrevid': 99,
                                                'contentmodel': model, 'revisions': []})
                page['revisions'].append({'revid': revid, 'slots': {'main': main}})
            return Request({'query': {'pages': list(pages.values())}})
        if params.get('prop') == 'categoryinfo':
            pages = []
            for title in params['titles'].split('|'):
                size = self.category_data.get(title, 'empty')
                if size is None:
                    pages.append({'title': title, 'missing': True})
                elif size == 'empty':   # the category page exists, but nothing is in it
                    pages.append({'title': title})
                else:
                    pages.append({'title': title, 'categoryinfo': {'pages': size, 'size': size}})
            return Request({'query': {'pages': pages}})
        raise AssertionError(f'unexpected query {params}')


def test_logging_in_gives_the_account_name(caplog):
    site = Pages()
    wiki = Wiki(site)
    with caplog.at_level('INFO', 'parambot'):
        assert wiki.login() == 'ExampleBot'
    assert site.session == 'password'
    assert caplog.messages == ['Logged in as ExampleBot with the bot password in user-password.py']
    assert wiki.has_right('bot') and not wiki.has_right('sysop')


def test_the_log_says_when_a_saved_login_is_reused(caplog):
    # A saved login keeps the grants of the bot password it was made with,
    # whatever user-password.py says now, so the operators need to know.
    site = Pages()
    site.saved_login = True
    with caplog.at_level('INFO', 'parambot'):
        Wiki(site).login()
    assert site.session == 'saved' and site.logins == [True]
    assert caplog.messages == [
        'Logged in as ExampleBot, reusing the saved login in pywikibot-ExampleBot.lwp']


def test_the_log_says_when_logging_in_fails(caplog):
    site = Pages()
    site.password_works = False
    with caplog.at_level('INFO', 'parambot'):
        Wiki(site).login()
    assert site.logins == [True, False]
    assert caplog.messages == ['Could not log in as ExampleBot']


def test_a_page_is_made_in_the_namespace_asked_for(monkeypatch):
    monkeypatch.setattr('parambot.wiki.pywikibot.Page', Page)
    page = Wiki(Pages()).page('Infobox person', ns=10)
    assert (page.title(), page.ns) == ('Infobox person', 10)


def test_pages_are_loaded_fifty_at_a_time_with_their_templates_if_asked():
    site = Pages()
    pages = [Page(site, f'P{i}') for i in range(3)]
    assert list(Wiki(site).load(pages, templates=True)) == pages
    assert site.preloaded == [(3, BATCH, True)]


def test_titles_are_loaded_in_one_go_and_found_however_they_were_written(monkeypatch):
    monkeypatch.setattr('parambot.wiki.pywikibot.Page', Page)
    site = Pages(unloadable={'User:Gone'})
    found = Wiki(site).load_titles(['user:ExampleBot/Run', 'User:Gone'])
    # As asked for, and the page that couldn't be loaded is still there.
    assert set(found) == {'user:ExampleBot/Run', 'User:Gone'}
    assert found['user:ExampleBot/Run'].title() == 'User:ExampleBot/Run'
    assert found['User:Gone'].title() == 'User:Gone'
    assert site.preloaded == [(2, BATCH, False)]


def test_revisions_are_fetched_fifty_at_a_time():
    site = Pages(revisions=[(revid, f'User:ExampleBot/Rules/T{revid}', f'text {revid}',
                             'wikitext') for revid in range(1, BATCH + 2)])
    found = Wiki(site).revisions(range(1, BATCH + 2))
    assert len(found) == BATCH + 1
    assert found[7] == Revision(7, 'User:ExampleBot/Rules/T7', 'text 7', 'wikitext', 99)
    assert len(site.queries) == 2


def test_missing_and_hidden_revisions():
    site = Pages(revisions=[(5, 'User:ExampleBot/Rules/T', None, 'wikitext')])
    found = Wiki(site).revisions([5, 6])
    assert set(found) == {5}       # 6 doesn't exist, or was deleted with its page
    assert found[5].text is None   # its text was hidden


def test_category_sizes_fifty_at_a_time():
    titles = [f'Category:C{i}' for i in range(BATCH + 1)]
    site = Pages(categories={'Category:C0': 3, 'Category:C1': None, f'Category:C{BATCH}': 1})
    sizes = Wiki(site).category_sizes(titles)
    assert (sizes['Category:C0'], sizes['Category:C1'], sizes[f'Category:C{BATCH}']) == (3, None, 1)
    # A category page with nothing in it has no size to give, so it's left
    # out, and the bot counts it as empty.
    assert 'Category:C2' not in sizes
    assert len(site.queries) == 2


def test_category_members_in_the_namespaces_asked_for(monkeypatch):
    asked = []

    class Category:
        def __init__(self, site, title):
            asked.append(title)

        def members(self, *, namespaces):
            asked.append(namespaces)
            return iter(['Article'])

    monkeypatch.setattr('parambot.wiki.pywikibot.Category', Category)
    assert list(Wiki(Pages()).category_members('Category:C', (0,))) == ['Article']
    assert asked == ['Category:C', [0]]
