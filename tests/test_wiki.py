"""The requests Wiki makes, with a stand-in for Pywikibot's site."""

import re
from datetime import UTC, datetime

from parambot.wiki import BATCH, Wiki


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
