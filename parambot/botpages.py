"""Checking the bot's own pages on the wiki before a run.

A live run refuses to start unless these are set up properly:

- User:<bot> uses {{bot}} to name the operator, as bot policy requires;
- the rules page is template-editor protected or higher, because it says
  which rules the bot uses;
- the Run page exists (it's deliberately left open, so anyone can stop the bot);
- the report page exists and the bot can edit it.

Dry runs and check-rules report the same problems without stopping.  The
pages the rules page lists, one per template, needn't be protected: the rules
page says which revision of each to use (see rulespages).
"""

from dataclasses import dataclass, field

from . import messages as msg
from .options import Options
from .wiki import Wiki, WikiPage

# Edit protection levels on the English Wikipedia, and what they're called.
PROTECTION_NAMES = {
    'autoconfirmed': 'semi-protected',
    'extendedconfirmed': 'extended-confirmed protected',
    'templateeditor': 'template-editor protected',
    'sysop': 'fully protected',
}
# The rules pages decide what the bot edits, so only people trusted to edit
# high-risk templates may change them.
RULES_PROTECTION = {'templateeditor', 'sysop'}
INDEFINITE = {'infinity', 'infinite', 'indefinite', 'never'}


@dataclass
class PageCheck:
    problems: list[str] = field(default_factory=list)  # each stops a live run
    notes: list[str] = field(default_factory=list)     # worth knowing, but not stopping


def check_bot_pages(wiki: Wiki, options: Options) -> PageCheck:
    titles = [options.user_page, options.run_page, options.report_page,
              options.instructions_page, options.faq_page, options.header_page]
    if not options.rules_files:
        titles += [options.rules_page, options.link_rule_page]
    pages = wiki.load_titles(titles, templates=True)
    check = PageCheck()

    user_page = _usable(pages[options.user_page], "the bot's user page", check)
    if user_page is not None and not any(
            t.title() == 'Template:Bot' for t in user_page.templates()):
        check.problems.append(msg.user_page_without_bot_template(options.user_page))

    if not options.rules_files:
        rules_page = _usable(pages[options.rules_page], 'the rules page', check)
        if rules_page is not None:
            _check_rules_protection(rules_page, check)
        if not pages[options.link_rule_page].exists():
            check.notes.append(msg.link_rule_missing(options.link_rule_page))

    run_page = _usable(pages[options.run_page], 'the Run page', check)
    if run_page is not None and _edit_level(run_page) in RULES_PROTECTION:
        check.notes.append(msg.run_page_protected(
            options.run_page, PROTECTION_NAMES[_edit_level(run_page)]))

    report_page = _usable(pages[options.report_page], 'the report page', check)
    if report_page is not None:
        _check_report_editable(report_page, options, check)

    if not pages[options.instructions_page].exists():
        check.notes.append(msg.instructions_missing(options.instructions_page))
    if not pages[options.faq_page].exists():
        check.notes.append(msg.faq_missing(options.faq_page))
    if not pages[options.header_page].exists():
        check.notes.append(msg.header_missing(options.header_page))
    return check


def too_weak(page: WikiPage) -> str | None:
    """How the page is protected, if that's too weak for a rules page, such
    as "not protected" or "semi-protected"; None if it's strong enough."""
    level = _edit_level(page)
    if level in RULES_PROTECTION:
        return None
    return PROTECTION_NAMES.get(level, f'{level} protected') if level else 'not protected'


def protection_expiry(page: WikiPage) -> str | None:
    """When the page's edit protection runs out, unless it never does."""
    level, expiry = _edit_protection(page)
    return expiry if level and expiry not in INDEFINITE else None


def _usable(page: WikiPage, what: str, check: PageCheck) -> WikiPage | None:
    """The page, if it exists and is an ordinary page."""
    title = page.title()
    if not page.exists():
        check.problems.append(msg.page_missing(title, what))
    elif page.isRedirectPage():
        check.problems.append(msg.page_is_redirect(title, what))
    elif page.content_model != 'wikitext':
        check.problems.append(msg.page_not_wikitext(title, what, page.content_model))
    else:
        return page
    return None


def _edit_protection(page: WikiPage) -> tuple[str, str]:
    """(level, expiry) of the page's edit protection; level is '' if none."""
    return page.protection().get('edit', ('', 'infinity'))


def _edit_level(page: WikiPage) -> str:
    return _edit_protection(page)[0]


def _check_rules_protection(page: WikiPage, check: PageCheck) -> None:
    current = too_weak(page)
    if current is not None:
        check.problems.append(msg.rules_page_unprotected(page.title(), current))
    elif (expiry := protection_expiry(page)) is not None:
        check.notes.append(msg.rules_protection_expires(page.title(), expiry))


def _check_report_editable(page: WikiPage, options: Options, check: PageCheck) -> None:
    if options.live:
        # Logged in, so the wiki can say whether the bot account may edit it.
        if not page.has_permission('edit'):
            check.problems.append(msg.report_page_not_editable(options.bot_user, page.title()))
    elif _edit_level(page) in RULES_PROTECTION:
        check.problems.append(msg.report_page_protected(
            page.title(), PROTECTION_NAMES[_edit_level(page)]))
