"""A fake wiki and its pages, so no test touches a real wiki.

FakeWiki has the same methods as parambot.wiki.Wiki, and FakePage has the
parts of a Pywikibot Page listed in parambot.wiki.WikiPage.
"""

import re
from collections import Counter
from datetime import UTC, datetime, timedelta

from pywikibot import exceptions as pwb_exc

from parambot.options import Options
from parambot.wiki import Revision

BOT = 'ExampleBot'
LINK_RULE = f'User:{BOT}/LinkRule'
OFFICEHOLDER_CATEGORY = 'Category:Pages using infobox officeholder with unknown parameters'
OFFICEHOLDER_SOURCE = (
    '{{Infobox}}{{#invoke:Check for unknown parameters|check'
    f'|unknown=[[{OFFICEHOLDER_CATEGORY}|_VALUE_]]| name | term_start | term_end }}}}')
OFFICEHOLDER_RULES = ('{| class="wikitable"\n|+ {{tl|Infobox officeholder}}\n'
                      '|-\n| {{para|termstart}} || {{para|term_start}}\n|}\n')
OFFICEHOLDER_REVISION = 1001


def link_rule(template, revision=''):
    """How the rules page lists a template's rules page."""
    return f'* {{{{{LINK_RULE}|{template}|{revision}}}}}\n'


ACTIVE_OFFICEHOLDER = '== Active ==\n' + link_rule('Infobox officeholder', OFFICEHOLDER_REVISION)
ARTICLE_TEXT = '{{Infobox officeholder\n| termstart = 2020\n}}'
NAMESPACES = {'User': 2, 'User talk': 3, 'Template': 10, 'Category': 14}
TEMPLATE_EDITOR = {'edit': ('templateeditor', 'infinity')}


class FakeRevision:
    def __init__(self, user, timestamp):
        self.user, self.timestamp = user, timestamp


class FakePage:
    """A page on the fake wiki: the parts of a Pywikibot Page the bot uses."""

    def __init__(self, title, text='', *, exists=True, redirect_to=None, model='wikitext',
                 templates=(), protection=None, editable=True, may_edit=True,
                 revisions=(), redirects=(), broken=False, save_error=None, on_save=None,
                 revid=None, history=None, deleted_before_save=False):
        self._title, self.text = title, text
        # Deleted after the bot loaded it: a save recreates it unless the
        # wiki is told not to create pages.
        self._deleted_before_save = deleted_before_save
        # The current revision's ID, and older revisions: {revid: text, or
        # None if hidden}.
        self.latest_revision_id, self.history = revid, dict(history or {})
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

    def templates(self):
        return self._templates

    def protection(self):
        return self._protection

    def has_permission(self, action='edit'):
        return self._editable

    def botMayEdit(self):
        return self._may_edit

    def save(self, *, summary, minor, bot, quiet, nocreate=False):
        if self._save_error:
            raise self._save_error
        if self._deleted_before_save and nocreate:
            raise pwb_exc.NoCreateError(0)   # MediaWiki's "missingtitle"
        self.text = self.text.rstrip()   # as MediaWiki saves it
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
        self.expanded = []       # texts passed to expand() or expand_all()
        self.requests = Counter()  # API requests that could be one per template
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
        pages = list(pages)
        self.requests['load with templates' if templates else 'load'] += 1
        yield from pages

    def load_titles(self, titles, *, templates=False):
        self.loaded_titles = list(titles)
        return {title: self.page(title) for title in titles}

    def revisions(self, revids):
        revids = set(revids)
        found = {}
        for page in self.pages.values():
            if not page._exists:
                continue
            versions = {**page.history, page.latest_revision_id: page.text}
            for revid, text in versions.items():
                if revid in revids:
                    found[revid] = Revision(revid, page.title(), text, page.content_model,
                                            page.latest_revision_id)
        return found

    def subpages(self, title):
        self.requests['subpages'] += 1
        return sorted(name for name, page in self.pages.items()
                      if name.startswith(title + '/') and page.exists()
                      and not page.isRedirectPage())

    def recent_edits(self, user, since):
        # Pages have no history of their own to look at: the bot must ask
        # about its own edits once, not about each page.
        self.requests['recent_edits'] += 1
        found = {}
        for page in self.pages.values():
            for revision in page._revisions:
                when = revision.timestamp
                if revision.user == user and when >= since:
                    found[page.title()] = max(when, found.get(page.title(), when))
        return found

    def redirects(self, titles, ns):
        self.requests['redirects'] += 1
        targets = {page.redirect_to.title(): page.redirect_to
                   for page in self.pages.values() if page.redirect_to is not None}
        found = {}
        for title in titles:
            page = self.pages.get(title) or targets.get(title)
            found[title] = [redirect.title() for redirect in page._redirects] if page else []
        return found

    def expand_all(self, texts):
        self.requests['expand'] += 1
        if self.expand_error:
            raise self.expand_error
        return [self._expand(text) for text in texts]

    def expand(self, text):
        self.requests['expand'] += 1
        if self.expand_error:
            raise self.expand_error
        return self._expand(text)

    def _expand(self, text):
        self.expanded.append(text)
        # Enough of MediaWiki for these tests: {{main other|x}} in an article is x.
        text = re.sub(r'\{\{lcfirst:([^{}]*)\}\}', lambda m: m[1][:1].lower() + m[1][1:], text)
        return re.sub(r'\{\{main other\|(.*)\}\}', r'\1', text).replace(
            '{{PAGENAME}}', 'ParamBot probe')

    def category_sizes(self, titles):
        if self.fail_polling:
            raise self.fail_polling
        self.polled += titles
        return {title: self.sizes.get(title, 0) for title in titles}

    def category_members(self, category, namespaces):
        return [p for p in self.members.get(category, []) if p.namespace() in namespaces]


def rules_page(opts, template, text='', revid=None, **kwargs):
    """A template's rules page, whose current revision is revid."""
    return FakePage(f'{opts.rules_page}/{template}', text, revid=revid, **kwargs)


def bot_pages(options, **changes):
    """The bot's own pages, set up properly, with active Infobox officeholder
    rules.  changes replaces pages by title; None makes a page missing."""
    officeholder = rules_page(options, 'Infobox officeholder', OFFICEHOLDER_RULES,
                              OFFICEHOLDER_REVISION)
    pages = {
        options.user_page: FakePage(options.user_page, templates=['Template:Bot']),
        options.rules_page: FakePage(options.rules_page, ACTIVE_OFFICEHOLDER,
                                     protection=TEMPLATE_EDITOR),
        options.link_rule_page: FakePage(options.link_rule_page, 'Shows a rules page.'),
        officeholder.title(): officeholder,
        options.run_page: FakePage(options.run_page, 'yes'),
        options.report_page: FakePage(options.report_page, 'Placeholder.'),
        options.instructions_page: FakePage(options.instructions_page, 'Instructions.'),
        options.faq_page: FakePage(options.faq_page, 'Questions and answers.'),
        options.header_page: FakePage(options.header_page, "Links to the bot's pages."),
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
