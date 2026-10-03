"""Finding and reading the rules pages.

The rules page (User:ParamBot/Rules) is an index.  Each template's rules are
on a page of their own, named after the template, which the index lists
under one of two headings, with the revision of it that has been approved:

    == Active ==
    * {{User:ParamBot/LinkRule|Infobox settlement|1234567890}}
    * {{User:ParamBot/LinkRule|Infobox officeholder|1234567999}}

    == Inactive ==
    * {{User:ParamBot/LinkRule|Infobox organization|1234568000}}

Active rules are used.  Inactive rules are read and checked like any others,
so their problems still reach the report, but they are never used.

The bot reads exactly the approved revision of each rules page, never a newer
one.  The index is template-editor protected (botpages checks that, and a
live run won't start without it), so only a template editor can approve a
revision, and the rules pages themselves needn't be protected: an edit to one
does nothing until a template editor reviews it and approves the new
revision.  LinkRule only shows the list nicely; the bot reads the index's
wikitext, so what the template displays doesn't matter to it.
"""

import logging
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

import mwparserfromhell
from mwparserfromhell.nodes import Template
from mwparserfromhell.wikicode import Wikicode

from . import messages as msg
from .options import Options
from .rules import Config, parse_config
from .wiki import Revision, Wiki, WikiPage
from .wikitext import normalize_template_name, normalize_title, strip_comments

log = logging.getLogger('parambot')

ACTIVE = 'active'
INACTIVE = 'inactive'
FILE_EXTENSION = '.mediawiki'


@dataclass
class Listed:
    """A rules page the index lists."""

    title: str
    active: bool
    revision: int | None     # the approved revision; None if there isn't one


@dataclass
class Listing:
    """The rules pages an index lists, by title, in order."""

    pages: dict[str, Listed] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    # Every rules page the index names, usable or not, for the report to link.
    named: set[str] = field(default_factory=set)


@dataclass
class _Source:
    """One page's (or file's) rules, before they're combined."""

    name: str                    # the page's title, or the file's path
    config: Config
    active: bool = True
    revision: int | None = None  # the revision read, for a page


# -- on the wiki -----------------------------------------------------------

def read_rules_pages(wiki: Wiki, index: WikiPage, options: Options) -> Config:
    """The approved revision of every rules page the index lists, read into
    one Config."""
    listing = read_index(index.text, options)
    config = Config(problems=list(listing.problems), pages=sorted(listing.named))
    try:
        subpages = wiki.subpages(options.rules_page)
    except Exception as error:
        # It's only for a note, so not worth stopping the run for.
        log.warning("Couldn't list the pages under %s: %s", options.rules_page, error)
        subpages = []
    config.unlisted = _unlisted(subpages, listing, options)
    if config.unlisted:
        config.notes.append(msg.rules_pages_unlisted(
            [template_for(title, options.rules_page) for title in config.unlisted],
            options.rules_page))
    written = parse_config(index.text)
    if written.rulesets or written.problems:
        config.problems.append(msg.rules_on_index(
            options.rules_page, list(written.rulesets), options.link_rule_page))

    listed = list(listing.pages.values())
    approved = wiki.revisions(e.revision for e in listed if e.revision is not None)
    unapproved = [e.title for e in listed if e.revision is None]
    current = wiki.load_titles(unapproved) if unapproved else {}
    sources = []
    for entry in listed:
        if entry.revision is None:
            config.problems.append(_unapproved(current[entry.title], options))
            continue
        text = _approved_text(entry, approved.get(entry.revision), options, config)
        if text is None:
            continue
        page_config = parse_config(text, template_for(entry.title, options.rules_page))
        if not page_config.rulesets:
            config.problems.append(msg.rules_page_empty(
                template_for(entry.title, options.rules_page), entry.revision))
        log.debug('Read %s, revision %d (%s)', entry.title, entry.revision,
                  ACTIVE if entry.active else INACTIVE)
        sources.append(_Source(entry.title, page_config, entry.active, entry.revision))
    return _combine(sources, config)


def _unlisted(subpages: list[str], listing: Listing, options: Options) -> list[str]:
    """The pages under the index that it doesn't list, such as a new
    template's rules that nobody has listed yet.  The bot doesn't use them,
    so the report says so.  Not the instructions, which aren't rules."""
    listed = {_canonical(title) for title in (*listing.named, options.instructions_page)}
    return sorted(title for title in subpages if _canonical(title) not in listed)


def _unapproved(page: WikiPage, options: Options) -> str:
    """The problem with a rules page listed without an approved revision."""
    template = template_for(page.title(), options.rules_page)
    if not page.exists():
        return msg.rules_page_missing_from(template, options.rules_page)
    return msg.no_approved_revision(template, options.rules_page, options.link_rule_page,
                                    page.latest_revision_id)


def _approved_text(entry: Listed, revision: Revision | None, options: Options,
                   config: Config) -> str | None:
    """The text of a rules page's approved revision, if it can be used.
    Otherwise the reason goes on the report."""
    assert entry.revision is not None
    template = template_for(entry.title, options.rules_page)
    if revision is None:
        config.problems.append(msg.revision_missing(template, entry.revision))
    elif _canonical(revision.title) != _canonical(entry.title):
        config.problems.append(
            msg.revision_of_another_page(template, entry.revision, revision.title))
    elif revision.text is None:
        config.problems.append(msg.revision_hidden(template, entry.revision))
    elif revision.model != 'wikitext':
        config.problems.append(msg.rules_page_not_wikitext(template, revision.model))
    else:
        if revision.latest != entry.revision:
            config.notes.append(msg.newer_than_approved(
                template, entry.revision, revision.latest, options.rules_page))
        return revision.text
    return None


def read_index(text: str, options: Options) -> Listing:
    """The rules pages listed in the index's wikitext: each LinkRule, link or
    transclusion of a rules page under its Active and Inactive headings (only
    a LinkRule gives an approved revision).  Anything elsewhere on the index,
    such as links to archives, doesn't count."""
    index = options.rules_page
    code = mwparserfromhell.parse(text)
    listing = Listing()
    found: dict[str, set[str]] = {}               # title -> the headings it's under
    revisions: dict[str, set[int | None]] = {}    # title -> the revisions given for it
    headings = set()
    for section in code.get_sections(levels=[2]):
        kind = _heading_kind(section)
        if kind is None:
            continue
        headings.add(kind)
        for call in section.filter_templates():
            if _canonical(str(call.name).lstrip(':')) != _canonical(options.link_rule_page):
                continue
            entry = _link_rule(call, options, listing)
            if entry is not None:
                title, revision = entry
                found.setdefault(title, set()).add(kind)
                revisions.setdefault(title, set()).add(revision)
        # A plain link to a rules page lists it without an approved revision,
        # so the report can say which revision to approve.
        for title in [*_linked(section, index), *_transcluded(section, index)]:
            if title != options.instructions_page:
                listing.named.add(title)
                found.setdefault(title, set()).add(kind)
                revisions.setdefault(title, set())
    if ACTIVE not in headings:
        listing.problems.append(msg.index_without_active(index))

    for title, kinds in found.items():
        if kinds == {ACTIVE, INACTIVE}:
            listing.problems.append(msg.listed_twice(template_for(title, index), index))
        if len(revisions[title]) > 1:
            given = sorted('none' if r is None else str(r) for r in revisions[title])
            listing.problems.append(msg.two_revisions(template_for(title, index), index, given))
            continue
        revision = next(iter(revisions[title]), None)
        listing.pages[title] = Listed(title, kinds == {ACTIVE}, revision)
    return listing


def _link_rule(call: Template, options: Options, listing: Listing
               ) -> tuple[str, int | None] | None:
    """The rules page a LinkRule names, and the revision it approves.  The
    page goes in listing.named even if the revision is no good."""
    name = normalize_template_name(_param(call, '1').lstrip('/'))
    if not name:
        listing.problems.append(msg.link_rule_without_template(options.link_rule_page, call))
        return None
    title = f'{options.rules_page}/{name}'
    listing.named.add(title)
    revision = _param(call, '2')
    if not revision:
        return title, None
    if not revision.isdigit():
        listing.problems.append(msg.not_a_revision(name, revision))
        return None
    return title, int(revision)


def _param(call: Template, name: str) -> str:
    return strip_comments(call.get(name).value).strip() if call.has(name) else ''


def template_for(title: str, index: str) -> str:
    """The template a rules page is for: its name after the index's."""
    return normalize_template_name(title[len(index) + 1:])


def subpage(target: str, index: str) -> str | None:
    """The full title of the page target names, if it's a subpage of index.
    target is what a link or transclusion names, such as "/Infobox foo",
    "/Infobox foo/" or "User:ParamBot/Rules/Infobox foo"."""
    target = strip_comments(target).partition('#')[0]   # no section links
    target = ' '.join(target.replace('_', ' ').split())
    if target.startswith('/'):
        name = target[1:]
    else:
        prefix = _canonical(index) + '/'
        full = _canonical(target.lstrip(':').strip())
        if not full.startswith(prefix):
            return None
        name = full[len(prefix):]
    # [[/Infobox foo/]] is the same link, shown without the slash.
    name = name.strip().removesuffix('/').strip()
    return f'{index}/{name}' if name else None


def _canonical(title: str) -> str:
    """A title with its namespace and first letter written the usual way."""
    title = ' '.join(strip_comments(title).replace('_', ' ').split())
    namespace, colon, rest = title.partition(':')
    if not colon:
        return normalize_title(title)
    return f'{normalize_title(namespace)}:{normalize_title(rest)}'


def _heading_kind(section: Wikicode) -> str | None:
    """ACTIVE or INACTIVE for a section headed "Active" or "Inactive"."""
    headings = section.filter_headings(recursive=False)
    if not headings:
        return None
    name = ' '.join(headings[0].title.strip_code().split()).lower()
    return name if name in (ACTIVE, INACTIVE) else None


def _transcluded(code: Wikicode, index: str) -> Iterator[str]:
    """The subpages of index that code transcludes, in order."""
    for call in code.filter_templates():
        title = subpage(str(call.name), index)
        if title is not None:
            yield title


def _linked(code: Wikicode, index: str) -> Iterator[str]:
    """The subpages of index that code links to."""
    for link in code.filter_wikilinks():
        title = subpage(str(link.title), index)
        if title is not None:
            yield title


# -- local files -----------------------------------------------------------

def read_rules_files(paths: Iterable[str]) -> Config:
    """Rules from local files instead of the wiki, all active.  A directory
    stands for every .mediawiki file in it."""
    sources = []
    for path in _files(paths):
        with open(path, encoding='utf-8') as f:
            sources.append(_Source(path, parse_config(f.read())))
    return _combine(sources, Config())


def _files(paths: Iterable[str]) -> Iterator[str]:
    for path in paths:
        if os.path.isdir(path):
            yield from sorted(os.path.join(path, name) for name in os.listdir(path)
                              if name.endswith(FILE_EXTENSION))
        else:
            yield path


# -- combining -------------------------------------------------------------

def _combine(sources: list[_Source], config: Config) -> Config:
    """Put every source's rules into config.  A template's rules must all be
    on one page: if two pages have rules for it, neither is used."""
    homes: dict[str, str] = {}    # template -> the source its rules came from
    shared: set[str] = set()      # templates with rules in more than one source
    for source in sources:
        config.problems.extend(source.config.problems)
        config.notes.extend(source.config.notes)
        for template, ruleset in source.config.rulesets.items():
            ruleset.page = source.name if source.revision is not None else ''
            ruleset.revision = source.revision
            ruleset.active = source.active
            if template in shared:
                continue
            if template in homes:
                config.problems.append(
                    msg.rules_on_two_pages(template, homes[template], source.name))
                del config.rulesets[template]
                shared.add(template)
                continue
            homes[template] = source.name
            config.rulesets[template] = ruleset
    return config
