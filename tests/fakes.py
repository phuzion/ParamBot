"""A fake wiki and its pages, so no test touches a real wiki.

FakeWiki has the same methods as parambot.wiki.Wiki, and FakePage has the
parts of a Pywikibot Page listed in parambot.wiki.WikiPage.
"""

import re
from datetime import UTC, datetime, timedelta

from parambot.options import Options

BOT = 'ExampleBot'
OFFICEHOLDER_CATEGORY = 'Category:Pages using infobox officeholder with unknown parameters'
OFFICEHOLDER_SOURCE = (
    '{{Infobox}}{{#invoke:Check for unknown parameters|check'
    f'|unknown=[[{OFFICEHOLDER_CATEGORY}|_VALUE_]]| name | term_start | term_end }}}}')
OFFICEHOLDER_RULES = ('{| class="wikitable"\n|+ {{tl|Infobox officeholder}}\n'
                      '|-\n| {{para|termstart}} || {{para|term_start}}\n|}\n')
ARTICLE_TEXT = '{{Infobox officeholder\n| termstart = 2020\n}}'
NAMESPACES = {'User': 2, 'User talk': 3, 'Template': 10, 'Category': 14}


class FakeRevision:
    def __init__(self, user, timestamp):
        self.user, self.timestamp = user, timestamp


class FakePage:
    """A page on the fake wiki: the parts of a Pywikibot Page the bot uses."""

    def __init__(self, title, text='', *, exists=True, redirect_to=None, model='wikitext',
                 templates=(), protection=None, editable=True, may_edit=True,
                 revisions=(), redirects=(), broken=False, save_error=None, on_save=None):
        self._title, self.text = title, text
        self._exists, self.redirect_to, self.content_model = exists, redirect_to, model
        self._templates = [FakePage(t) for t in templates]
        self._protection = protection or {}
        self._editable, self._may_edit = editable, may_edit
        self._revisions, self._redirects = list(revisions), list(redirects)
        self._broken, self._save_error, self._on_save = broken, save_error, on_save
        self.saved = []       # the text of each save
        self.summaries = []   # the summary of each save

    def title(self, *, with_ns=True):
        prefix, _, rest = self._title.partition(':')
        return rest if not with_ns and prefix in NAMESPACES else self._title

    def namespace(self):
        prefix, _, _ = self._title.partition(':')
        return NAMESPACES.get(prefix, 0)

    def exists(self):
        if self._broken:
            raise ConnectionError('API timed out')
        return self._exists

    def isRedirectPage(self):
        return self.redirect_to is not None

    def getRedirectTarget(self):
        return self.redirect_to

    def redirects(self, *, namespaces=None):
        return self._redirects

    def templates(self):
        return self._templates

    def protection(self):
        return self._protection

    def has_permission(self, action='edit'):
        return self._editable

    def botMayEdit(self):
        return self._may_edit

    def revisions(self, total=None):
        return self._revisions[:total]

    def save(self, *, summary, minor, bot, quiet):
        if self._save_error:
            raise self._save_error
        self.saved.append(self.text)
        self.summaries.append(summary)
        if self._on_save:
            self._on_save()


class FakeWiki:
    """A wiki for tests.  Pages are looked up by title; any page not added
    is missing.  Categories hold 0 pages unless given."""

    def __init__(self, *pages, user=BOT, rights=('bot',)):
        self.pages = {}
        self.add(*pages)
        self.user, self.rights = user, set(rights)
        self.sizes = {}          # category -> size, or None for a missing category
        self.members = {}        # category -> [pages]
        self.expand_error = None
        self.expanded = []       # texts passed to expand()
        self.logged_in = False
        self.polled = []         # categories whose size was asked for
        self.loaded_titles = []  # titles passed to load_titles()
        self.fail_polling = None

    def add(self, *pages):
        for page in pages:
            self.pages[page.title()] = page
        return self

    def populate(self, category, *pages):
        """Put pages in a category (and on the wiki)."""
        self.add(*pages)
        self.members[category] = list(pages)
        self.sizes[category] = len(pages)
        return self

    # The Wiki interface.

    def login(self):
        self.logged_in = True
        return self.user

    def has_right(self, right):
        return right in self.rights

    def page(self, title, ns=0):
        if ns == 10 and not title.startswith('Template:'):
            title = 'Template:' + title
        return self.pages.get(title) or FakePage(title, exists=False)

    def load(self, pages, *, templates=False):
        yield from pages

    def load_titles(self, titles, *, templates=False):
        self.loaded_titles = list(titles)
        return {title: self.page(title) for title in titles}

    def expand(self, text):
        self.expanded.append(text)
        if self.expand_error:
            raise self.expand_error
        # Enough of MediaWiki for these tests: {{main other|x}} in an article is x.
        return re.sub(r'\{\{main other\|(.*)\}\}', r'\1', text).replace(
            '{{PAGENAME}}', 'ParamBot probe')

    def category_sizes(self, titles):
        if self.fail_polling:
            raise self.fail_polling
        self.polled += titles
        return {title: self.sizes.get(title, 0) for title in titles}

    def category_members(self, category, namespaces):
        return [p for p in self.members.get(category, []) if p.namespace() in namespaces]


def bot_pages(options, **changes):
    """The bot's own pages, set up properly, plus Infobox officeholder rules.
    changes replaces pages by title; None makes a page missing."""
    pages = {
        options.user_page: FakePage(options.user_page, templates=['Template:Bot']),
        options.rules_page: FakePage(options.rules_page, OFFICEHOLDER_RULES,
                                     protection={'edit': ('templateeditor', 'infinity')}),
        options.run_page: FakePage(options.run_page, 'yes'),
        options.report_page: FakePage(options.report_page, 'Placeholder.'),
        options.instructions_page: FakePage(options.instructions_page, 'Instructions.'),
        'Template:Infobox officeholder': FakePage('Template:Infobox officeholder',
                                                  OFFICEHOLDER_SOURCE),
    }
    for title, page in changes.items():
        pages[title] = page if page is not None else FakePage(title, exists=False)
    return list(pages.values())


def options(**changes):
    return Options(bot_user=BOT, **changes)


def wiki_for(opts, **changes):
    """A FakeWiki with the bot's pages set up properly for opts."""
    return FakeWiki(*bot_pages(opts, **changes))


def edited_by(user, days_ago=0):
    return FakeRevision(user, datetime.now(UTC) - timedelta(days=days_ago))
