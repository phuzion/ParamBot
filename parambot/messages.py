"""Everything the bot says on its report page, in edit summaries and when it stops.

Rules-page problems are read by the editors who wrote the rules, so each one
says what was ignored and how to fix it.  Keeping the wording here keeps the
logic elsewhere short, and lets it be reviewed in one place.
"""

import re
from collections.abc import Sequence

AWB_TEMPLATE = 'AWB rename template parameter'

# Parts of a message that the report shows specially, each marked with
# private-use characters, which no wikitext holds:
PARA = ''     # a parameter name: {{para|name}}
TL = ''       # a template: {{tl|name}}
CODE = ''     # code to copy: <code><nowiki>...</nowiki></code>
QUOTED = ''   # text from a rules page or an error: <nowiki>...</nowiki>
END = ''
MARKED_RE = re.compile(f'([{PARA}{TL}{CODE}{QUOTED}])(.*?){END}', re.S)
_MARKERS = re.compile(f'[{PARA}{TL}{CODE}{QUOTED}{END}]')
# How plain() shows each of them.
_PLAIN = {PARA: '"{}"', TL: '{{{{{}}}}}', CODE: '{}', QUOTED: '{}'}


def _mark(kind: str, text: object) -> str:
    return f'{kind}{_MARKERS.sub("", str(text))}{END}'


def para(name: object) -> str:
    """A parameter name in a message."""
    return _mark(PARA, name)


def tl(name: str) -> str:
    """A template mentioned in a message, such as {{nobots}}."""
    return _mark(TL, name)


def code(text: str) -> str:
    """Wikitext in a message that's meant to be copied, not to work."""
    return _mark(CODE, text)


def quoted(text: object) -> str:
    """Text in a message from somewhere else: a rules page, or an error."""
    return _mark(QUOTED, text)


def plain(text: str) -> str:
    """A message as plain text, for the console: parameter names in quotes,
    and templates, code and quoted text as they are."""
    return MARKED_RE.sub(lambda m: _PLAIN[m.group(1)].format(m.group(2)), text)


def count(n: int, singular: str, plural: str = '') -> str:
    """"1 rule", "2 rules"."""
    return f'{n} {singular if n == 1 else plural or singular + "s"}'


def excerpt(text: object, limit: int = 60) -> str:
    """text on one line, cut to limit characters."""
    flat = ' '.join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 1] + '…'


def _and(names: list[str]) -> str:
    """a, b and c."""
    return names[0] if len(names) == 1 else f'{", ".join(names[:-1])} and {names[-1]}'


# -- the rules pages -------------------------------------------------------

def _link_rule(link_rule: str, name: str, revision: object) -> str:
    """How to list a rules page: {{User:ParamBot/LinkRule|Infobox foo|123}}, to copy."""
    return code(f'{{{{{link_rule}|{name}|{revision}}}}}')


def rules_on_index(index: str, templates: list[str], link_rule: str) -> str:
    which = f' (for {_and(templates)})' if templates else ''
    example = templates[0] if templates else 'Infobox example'
    return (f'{index} has rules written on it{which}, which the bot ignores: it only reads the '
            'pages listed under "== Active ==" and "== Inactive ==". Move each template\'s rules '
            f'to a page of its own, such as {index}/{example}, and list that page with '
            f'{_link_rule(link_rule, example, "REVISION")}.')


def index_without_active(index: str) -> str:
    return f'{index} has no "== Active ==" heading, so no rules are used.'


# The messages about one template's rules page name the template, which the
# report links to the page: "the Infobox person rules".

def listed_twice(template: str, index: str) -> str:
    return (f'The {template} rules are listed under both Active and Inactive on {index}. '
            'Treating them as inactive; take them off one of the two.')


def two_revisions(template: str, index: str, revisions: list[str]) -> str:
    return (f'{index} lists the {template} rules more than once, with different approved '
            f"revisions ({_and(revisions)}), so the bot isn't using them. Keep one.")


def link_rule_without_template(link_rule: str, call: object) -> str:
    return (f"A {code('{{' + link_rule + '}}')} on the rules page doesn't name a template, so "
            f'the bot ignored it: {quoted(excerpt(call))}')


def not_a_revision(template: str, value: str) -> str:
    return (f'The approved revision given for the {template} rules is "{quoted(value)}", which '
            "isn't a "
            "revision number, so the bot isn't using them. Use the number from the page's "
            'history, such as the 1234567890 in Special:Permalink/1234567890.')


def rules_page_missing_from(template: str, index: str) -> str:
    return (f'The {template} rules are listed on {index}, but their page does not exist. '
            'Create it, or take it off the list.')


def no_approved_revision(template: str, index: str, link_rule: str, current: int) -> str:
    return (f"The {template} rules have no approved revision on {index}, so the bot isn't "
            'using them. If their current version is right, list them as '
            f'{_link_rule(link_rule, template, current)}.')


def revision_missing(template: str, revision: int) -> str:
    return (f"Revision {revision}, the approved revision of the {template} rules, doesn't exist "
            "or was deleted, so the bot isn't using them. Check the number.")


def revision_of_another_page(template: str, revision: int, actual: str) -> str:
    return (f'Revision {revision} is a revision of {actual}, not of the {template} rules, so '
            "the bot isn't using them. Check the number.")


def revision_hidden(template: str, revision: int) -> str:
    return (f'The text of revision {revision} of the {template} rules is hidden, so the bot '
            "isn't using them. Approve another revision.")


def rules_page_not_wikitext(template: str, model: str) -> str:
    return (f'The {template} rules page must be an ordinary wikitext page, not {model}, so the '
            'bot ignored it.')


def newer_than_approved(template: str, revision: int, latest: int, index: str) -> str:
    return (f'The {template} rules have changed since their approved revision ({revision}); '
            'the bot is still using that one. Review the changes at '
            f"Special:Diff/{revision}/{latest}, and if they're right, change the revision on "
            f'{index} to {latest}.')


def rules_page_empty(template: str, revision: int) -> str:
    return (f'Revision {revision} of the {template} rules page has nothing the bot could read. '
            'Approve a revision with a table of renames.')


def rules_on_two_pages(template: str, first: str, second: str) -> str:
    return (f'{template} has rules on two pages, {first} and {second}, so the bot ignored both. '
            'Put all of its rules on one page.')


def inactive_rules(templates: list[str]) -> str:
    return f'Inactive, so checked but not used: {", ".join(templates)}.'


# -- tables and rows -------------------------------------------------------

def two_categories(template: str, first: str, second: str) -> str:
    return (f'{template}: two tables give different categories to watch ("{first}" and '
            f'"{second}"). Using "{second}"; delete the wrong one.')


def table_without_caption(table: object) -> str:
    return ('A table of parameters has no caption naming its template, so the bot ignored it. '
            f"Add a line like {code('|+ {{tl|Infobox foo}}')} straight after {code('{|')}. "
            f'The table starts: {quoted(excerpt(table))}')


def caption_without_template(caption: object) -> str:
    return ("A table was ignored because its caption doesn't name a template. Its caption is: "
            f'{quoted(excerpt(caption))}')


def caption_with_several_templates(names: list[str]) -> str:
    return (f'{names[0]}: its caption names more than one template ({", ".join(names)}); '
            f'using "{names[0]}". Use one table per template.')


def table_for_another_template(page_template: str, named: str) -> str:
    return (f'The rules page for {page_template} has a table for {named}, so the bot ignored '
            "that table. Each template's rules go on a page of their own.")


def line_for_another_template(page_template: str, named: str) -> str:
    return (f'The rules page for {page_template} has a one-line rule for {named}, so the bot '
            "ignored it. Each template's rules go on a page of their own.")


def new_name_without_old(template: str) -> str:
    return f'{template}: a row has a new name but no old name, so the bot ignored it.'


def unclear_conflict_cell(template: str, old: str, said: str) -> str:
    return (f'{template}: in the row for {para(old)}, the "If both are set" column says '
            f'"{quoted(said)}". Write "merge" or leave it empty. Treating it as empty.')


def no_new_name(template: str, old: str) -> str:
    return (f'{template}: the row for {para(old)} has no new name, so the bot ignored it. If the '
            'parameter was removed with no replacement, write "remove".')


def several_new_names(template: str, old: str, news: list[str]) -> str:
    return (f'{template}: the row for {para(old)} has more than one new name '
            f'({_and([para(new) for new in news])}), '
            'so the bot ignored it. Give each row one new name.')


def markup_in_name(template: str, old: str, new: str | None) -> str:
    markup = ', '.join(code(example) for example in ('{{ }}', '[[ ]]', '|'))
    return (f'{template}: the bot ignored {para(old)} → {para(new) if new else "remove"}. '
            f"Parameter names can't contain markup such as {markup} or {code('<tags>')}.")


def several_names_in_one(template: str, name: str) -> str:
    return (f'{template}: {para(name)} looks like several names, so the bot ignored that row. '
            f"Write each name as {code('{{para|name}}')}.")


def number_in_one_name(template: str, old: str, new: str) -> str:
    return (f'{template}: {para(old)} → {para(new)} has "#" in only one of the names, so the bot '
            'ignored it. "#" stands for the number in names like term_start2, so use it in '
            'both names or in neither.')


def too_many_numbers(template: str, old: str) -> str:
    return f'{template}: {para(old)} has more than nine "#"s, so the bot ignored it.'


def rows_disagree(template: str, old: str, first: str | None, second: str | None) -> str:
    if first is None or second is None:
        return (f'{template}: one row renames {para(old)} to {para(first or second)} and '
                'another removes it, so the bot uses neither. Delete the wrong row.')
    return (f'{template}: {para(old)} is renamed to both {para(first)} and {para(second)}, so '
            'the bot uses neither. Delete the wrong row.')


def merge_disputed(template: str, old: str) -> str:
    return (f'{template}: only some of the rows for {para(old)} say merge, so the bot won\'t merge '
            'it. Make the rows agree.')


def malformed_one_line_rule(line: object) -> str:
    return (f'An {tl(AWB_TEMPLATE)} line needs exactly three parts: template, old name, '
            f'new name. The bot ignored: {quoted(excerpt(line, 120))}')


def rename_loop(template: str, old: str) -> str:
    return (f'{template}: the rules for {para(old)} go round in a circle (a → b, b → a). '
            'The bot ignored that rule.')


# -- templates -------------------------------------------------------------

def template_missing(template: str) -> str:
    return (f'Template:{template} does not exist, so its rules are switched off. '
            'Check the spelling of its name.')


def no_parameter_list(template: str, passed_to: Sequence[str] = ()) -> str:
    """passed_to: the templates a wrapper template passes its parameters on
    to, in order."""
    wrapped = ''
    if passed_to:
        chain = ', then '.join(f'Template:{name}' for name in passed_to)
        wrapped = f', and neither does the template it passes its parameters on to ({chain})'
    check = code('{{#invoke:Check for unknown parameters|check|...}}')
    return (f'Template:{template} has no list of accepted parameters the bot can read (a '
            f'{check} call){wrapped}, so its rules are switched off.')


def rules_for_a_redirect(template: str, actual: str, page: str) -> str:
    where = f' Move them to {page}.' if page else ''
    return (f'Template:{template} redirects to Template:{actual}, which has rules of its own, '
            f'so the bot ignored the {template} rules.{where}')


def same_template_twice(templates: list[str], actual: str) -> str:
    return (f'{_and(templates)} are the same template (Template:{actual}), so the bot ignored '
            f'their rules. Put them on one page, named after {actual}.')


def no_category(template: str) -> str:
    return (f"Template:{template} doesn't put articles with unknown parameters in any "
            "category, so the bot can't find them and its rules will never be used.")


def caption_category_wrong(template: str, watched: str, actual: str) -> str:
    return (f"The {template} table's caption says to watch {watched}, but the template puts "
            f"articles with unknown parameters in {actual}. Change the caption's category "
            f"link to {code(f'[[:{actual}]]')}.")


def unusual_category(template: str, default: str, actual: str, has_table: bool) -> str:
    link = code(f'[[:{actual}]]')
    if has_table:
        fix = f'Add {link} to the caption of the {template} table.'
    else:
        fix = (f"One-line rules can't name a category, so put the {template} rules in a "
               f'table with {link} in its caption.')
    return (f'Template:{template} puts articles with unknown parameters in {actual}, not the '
            f'usual {default}, so its rules will never find anything. {fix}')


def rules_waiting(template: str, names: list[str]) -> str:
    listed = _and([para(name) for name in names])
    if len(names) == 1:
        return (f'{template}: 1 rule waits because the template still accepts its old name, '
                f'{listed}. That is normal: the rule starts working once the template drops '
                'that name. If the rule is backwards, swap its names.')
    return (f'{template}: {len(names)} rules wait because the template still accepts their old '
            f'names, {listed}. That is normal: they start working once the template drops '
            'those names. If a rule is backwards, swap its names.')


UNKNOWN_CHECK = 'Module:Check for unknown parameters'


def rules_not_needed(template: str, names: list[str], setting: str) -> str:
    """Rules whose old names the template accepts only because of a setting
    such as mapframe_args=y, which makes the check accept map parameters."""
    listed = _and([para(name) for name in names])
    if len(names) == 1:
        return (f"{template}: 1 rule isn't needed, because {listed} is one of the map "
                f'parameters that {UNKNOWN_CHECK} accepts for any template with {setting}=y. '
                f'Delete the rule unless the template stops using {setting}.')
    return (f"{template}: {len(names)} rules aren't needed, because {listed} are map "
            f'parameters that {UNKNOWN_CHECK} accepts for any template with {setting}=y. '
            f'Delete the rules unless the template stops using {setting}.')


def target_not_accepted(template: str, old: str, new: str) -> str:
    return (f'{template}: the rule {para(old)} → {para(new)} renames to a parameter the '
            f'template does not accept. Check the spelling of {para(new)}.')


def category_missing(category: str, templates: list[str]) -> str:
    return (f'{category} has no page and no members. If the template uses a different '
            'category, put a link to it in the caption of the table for '
            + ', '.join(templates))


# -- the bot's own pages ---------------------------------------------------

def page_missing(title: str, what: str) -> str:
    return f'{title} ({what}) does not exist. Create it.'


def page_is_redirect(title: str, what: str) -> str:
    return f'{title} ({what}) is a redirect. It must be the page itself.'


def page_not_wikitext(title: str, what: str, model: str) -> str:
    return f'{title} ({what}) must be an ordinary wikitext page, not {model}.'


def user_page_without_bot_template(title: str) -> str:
    return (f"{title} doesn't use {tl('bot')} to name the bot's operator, which bot policy "
            'requires.')


PROTECTION_REQUESTS = 'Wikipedia:Requests for page protection'


def rules_page_unprotected(title: str, current: str) -> str:
    return (f'{title} (the rules page) is {current}. It says which rules the bot uses, so it '
            f'must be template-editor protected or higher. Ask at {PROTECTION_REQUESTS}.')


def rules_protection_expires(title: str, expiry: str) -> str:
    return (f"{title}'s protection expires {expiry}, and the bot won't run after that. Ask for "
            'indefinite protection.')


def run_page_protected(title: str, level: str) -> str:
    return (f"{title} is {level}, so most editors can't use it to stop the bot. It's meant to "
            'be open to everyone.')


def report_page_not_editable(bot_user: str, title: str) -> str:
    return f'{bot_user} cannot edit {title} (the report page). Check its protection.'


def report_page_protected(title: str, level: str) -> str:
    return (f'{title} (the report page) is {level}, so the bot probably cannot edit it. '
            'Lower its protection.')


def instructions_missing(title: str) -> str:
    return (f'{title} (the instructions for rule writers) does not exist. Copy '
            'docs/rules-instructions.mediawiki there.')


def faq_missing(title: str) -> str:
    return (f'{title} (the FAQ every edit summary links to) does not exist. Copy '
            'docs/faq.mediawiki there.')


def header_missing(title: str) -> str:
    return (f"{title} (the links across the top of the bot's pages and the report) does not "
            'exist. Copy docs/header.mediawiki there.')


def link_rule_missing(title: str) -> str:
    return (f'{title} (the template that shows the list of rules pages) does not exist. Copy '
            'docs/link-rule.mediawiki there.')


# -- articles --------------------------------------------------------------

SKIP_MISSING = 'page does not exist'
SKIP_REDIRECT = 'page is a redirect'
SKIP_NOT_ARTICLE = 'not an article; use --any-namespace to preview it in a dry run'
SKIP_EXCLUDED = f'excluded by {tl("bots")}/{tl("nobots")}'
SKIP_EDIT_CONFLICT = 'edit conflict; will be retried on the next run'
SKIP_DELETED = 'page was deleted while the bot was working on it'
SKIP_PROTECTED = 'page is protected'


def skip_recently_edited(bot_user: str, when: object) -> str:
    return (f'{bot_user} already edited this page on {when:%Y-%m-%d}; not repeating a fix '
            'within the cooldown in case it was reverted on purpose')


def skip_save_failed(error: Exception) -> str:
    return f'save failed: {quoted(error)}'


def skip_error(error: Exception) -> str:
    return f'error: {type(error).__name__}: {quoted(error)}'


def name_has_comment() -> str:
    return 'parameter name contains a comment'


def target_rejected(target: str) -> str:
    return f'the template does not accept {para(target)}; check the rule'


def both_set(old: str, new: str) -> str:
    return f'{para(old)} and {para(new)} are both set, to different values'


def several_rules_match(rules: list[str]) -> str:
    return (f'more than one "#" rule matches it ({"; ".join(rules)}), so the bot left it alone. '
            'Delete one of those rows, or add a row for this exact name')


def edit_summary(parts: list[str], rules_page: str, faq_page: str, limit: int) -> str:
    """At most limit characters: what changed, then links to the rules used and
    the FAQ.  A summary too long to fit is cut between changes, so no link in
    it is left broken."""
    links = f' ([[{rules_page}|rules]] · [[{faq_page}|FAQ]])'
    text = 'Fixing deprecated parameters restored in ' + '; '.join(parts)
    room = limit - len(links)
    if len(text) > room:
        cut = text[:room - 1]
        boundary = max(cut.rfind(', '), cut.rfind('; '))
        text = (cut[:boundary] if boundary > 0 else cut.rstrip()) + '…'
    return text + links


def report_summary(edits: int, needing_review: int) -> str:
    need = 'needs' if needing_review == 1 else 'need'
    return f'Updating report: {count(edits, "edit")}, {count(needing_review, "page")} {need} review'


# -- stopping --------------------------------------------------------------

def stopped_at_max_edits(max_edits: int) -> str:
    return f'Stopped after {count(max_edits, "edit")} (--max-edits).'


def too_many_failures(failures: int, error: Exception) -> str:
    return (f'{count(failures, "page")} in a row failed; the last error was '
            f'{type(error).__name__}: {quoted(error)}')


ANY_NAMESPACE_LIVE = '--any-namespace is for dry runs only'


def pages_not_ready(problems: list[str]) -> str:
    return "Not running, because of problems with the bot's pages:\n- " + '\n- '.join(problems)


def no_rules(source: str) -> str:
    return f'{source} has no rules the bot can use.'


def wrong_account(user: str, expected: str) -> str:
    return f'Logged in as {user!r}, expected {expected!r}'


def no_bot_right(user: str) -> str:
    return f'{user} does not have the bot right; use --trial for BRFA trial edits'


def run_page_off(title: str, before: str | None = None) -> str:
    if before:
        return f'{title} no longer says "yes"; stopped before editing {before}'
    return f'{title} does not say "yes"; not running'


def rules_page_missing(title: str) -> str:
    return f'Rules page {title} does not exist'


def stopped_early(reason: object) -> str:
    return f'Stopped early: {reason}'


def run_failed(error: Exception) -> str:
    return (f'The run stopped early because of an error: {type(error).__name__}: '
            f'{quoted(error)}')
