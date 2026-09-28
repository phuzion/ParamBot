"""Everything the bot says on its report page, in edit summaries and when it stops.

Rules-page problems are read by the editors who wrote the rules, so each one
says what was ignored and how to fix it.  Keeping the wording here keeps the
logic elsewhere short, and lets it be reviewed in one place.
"""

AWB_TEMPLATE = 'AWB rename template parameter'


def excerpt(text: object, limit: int = 60) -> str:
    """text on one line, cut to limit characters."""
    flat = ' '.join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 1] + '…'


def _and(names: list[str]) -> str:
    """a, b and c."""
    return names[0] if len(names) == 1 else f'{", ".join(names[:-1])} and {names[-1]}'


# -- the rules pages -------------------------------------------------------

def _link_rule(link_rule: str, name: str, revision: object) -> str:
    """How to list a rules page: {{User:ParamBot/LinkRule|Infobox foo|123}}."""
    return f'{{{{{link_rule}|{name}|{revision}}}}}'


def rules_on_index(index: str, templates: list[str], link_rule: str) -> str:
    which = f' (for {_and(templates)})' if templates else ''
    example = templates[0] if templates else 'Infobox example'
    return (f'{index} has rules written on it{which}, which the bot ignores: it only reads the '
            'pages listed under "== Active ==" and "== Inactive ==". Move each template\'s rules '
            f'to a page of its own, such as {index}/{example}, and list that page with '
            f'{_link_rule(link_rule, example, "REVISION")}.')


def index_without_active(index: str) -> str:
    return f'{index} has no "== Active ==" heading, so no rules are used.'


def listed_twice(title: str, index: str) -> str:
    return (f'{title} is listed under both Active and Inactive on {index}. Treating it as '
            'inactive; take it off one of them.')


def two_revisions(title: str, index: str, revisions: list[str]) -> str:
    return (f'{index} lists {title} more than once, with different approved revisions '
            f'({_and(revisions)}), so the bot isn\'t using it. Keep one.')


def link_rule_without_template(link_rule: str, call: object) -> str:
    return (f'A {{{{{link_rule}}}}} on the rules page doesn\'t name a template, so the bot '
            f'ignored it: {excerpt(call)}')


def not_a_revision(title: str, value: str) -> str:
    return (f'The approved revision given for {title} is "{value}", which isn\'t a revision '
            "number, so the bot isn't using its rules. Use the number from the page's history, "
            'such as the 1234567890 in Special:Permalink/1234567890.')


def rules_page_missing_from(title: str, index: str) -> str:
    return f'{title} is listed on {index} but does not exist. Create it, or take it off the list.'


def no_approved_revision(title: str, index: str, link_rule: str, current: int) -> str:
    name = title[len(index) + 1:]
    return (f'{title} has no approved revision on {index}, so the bot isn\'t using its rules. '
            f'If its current version is right, list it as {_link_rule(link_rule, name, current)}.')


def revision_missing(title: str, revision: int) -> str:
    return (f"Revision {revision}, the approved revision of {title}, doesn't exist or was "
            "deleted, so the bot isn't using its rules. Check the number.")


def revision_of_another_page(title: str, revision: int, actual: str) -> str:
    return (f'Revision {revision} is a revision of {actual}, not of {title}, so the bot isn\'t '
            f'using the {title} rules. Check the number.')


def revision_hidden(title: str, revision: int) -> str:
    return (f'The text of revision {revision} of {title} is hidden, so the bot isn\'t using its '
            'rules. Approve another revision.')


def rules_page_not_wikitext(title: str, model: str) -> str:
    return f'{title} must be an ordinary wikitext page, not {model}, so the bot ignored it.'


def newer_than_approved(title: str, revision: int, latest: int, index: str) -> str:
    return (f'{title} has changed since its approved revision ({revision}); the bot is still '
            f'using that one. Review the changes at Special:Diff/{revision}/{latest}, and if '
            f'they\'re right, change the revision on {index} to {latest}.')


def rules_page_empty(title: str, revision: int) -> str:
    return (f'Revision {revision} of {title} has no rules the bot could read. Approve a revision '
            'with a table of renames.')


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
            'Add a line like "|+ {{tl|Infobox foo}}" straight after "{|". '
            f'The table starts: {excerpt(table)}')


def caption_without_template(caption: object) -> str:
    return ("A table was ignored because its caption doesn't name a template. Its caption is: "
            f'{excerpt(caption)}')


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
    return (f'{template}: in the row for "{old}", the "If both are set" column says "{said}". '
            'Write "merge" or leave it empty. Treating it as empty.')


def no_new_name(template: str, old: str) -> str:
    return (f'{template}: the row for "{old}" has no new name, so the bot ignored it. If the '
            'parameter was removed with no replacement, write "remove".')


def several_new_names(template: str, old: str, news: list[str]) -> str:
    return (f'{template}: the row for "{old}" has more than one new name ({", ".join(news)}), '
            'so the bot ignored it. Give each row one new name.')


def markup_in_name(template: str, old: str, new: str | None) -> str:
    return (f'{template}: the bot ignored "{old}" → "{new or "remove"}". Parameter names '
            "can't contain markup such as {{ }}, [[ ]], | or <tags>.")


def several_names_in_one(template: str, name: str) -> str:
    return (f'{template}: "{name}" looks like several names, so the bot ignored that row. '
            'Write each name as {{para|name}}.')


def number_in_one_name(template: str, old: str, new: str) -> str:
    return (f'{template}: "{old}" → "{new}" has "#" in only one of the names, so the bot '
            'ignored it. "#" stands for the number in names like term_start2, so use it in '
            'both names or in neither.')


def too_many_numbers(template: str, old: str) -> str:
    return f'{template}: "{old}" has more than nine "#"s, so the bot ignored it.'


def rows_disagree(template: str, old: str, first: str | None, second: str | None) -> str:
    if first is None or second is None:
        return (f'{template}: one row renames "{old}" to "{first or second}" and another '
                'removes it, so the bot uses neither. Delete the wrong row.')
    return (f'{template}: "{old}" is renamed to both "{first}" and "{second}", so the bot uses '
            'neither. Delete the wrong row.')


def merge_disputed(template: str, old: str) -> str:
    return (f'{template}: only some of the rows for "{old}" say merge, so the bot won\'t merge '
            'it. Make the rows agree.')


def malformed_one_line_rule(line: object) -> str:
    return (f'An {{{{{AWB_TEMPLATE}}}}} line needs exactly three parts: template, old name, '
            f'new name. The bot ignored: {excerpt(line, 120)}')


def rename_loop(template: str, old: str) -> str:
    return (f'{template}: the rules for "{old}" go round in a circle (a → b, b → a). '
            'The bot ignored that rule.')


# -- templates -------------------------------------------------------------

def template_missing(template: str) -> str:
    return (f'Template:{template} does not exist, so its rules are switched off. '
            'Check the spelling of its name.')


def no_parameter_list(template: str) -> str:
    return (f'Template:{template} has no list of accepted parameters the bot can read (a '
            '{{#invoke:Check for unknown parameters|check|...}} call), so its rules are '
            'switched off.')


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
            f'link to [[:{actual}]].')


def unusual_category(template: str, default: str, actual: str, has_table: bool) -> str:
    if has_table:
        fix = f'Add [[:{actual}]] to the caption of the {template} table.'
    else:
        fix = (f"One-line rules can't name a category, so put the {template} rules in a "
               f'table with [[:{actual}]] in its caption.')
    return (f'Template:{template} puts articles with unknown parameters in {actual}, not the '
            f'usual {default}, so its rules will never find anything. {fix}')


def rules_waiting(template: str, names: list[str]) -> str:
    return (f'{template}: {len(names)} rule(s) wait because the template still accepts the '
            f'old name ({", ".join(names)}). That is normal: they start working once the '
            'template drops those names. If a rule is backwards, swap its names.')


def target_not_accepted(template: str, old: str, new: str) -> str:
    return (f'{template}: the rule "{old} = {new}" renames to a parameter the template does '
            f'not accept. Check the spelling of "{new}".')


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
    return (f"{title} doesn't use {{{{bot}}}} to name the bot's operator, which bot policy "
            'requires.')


def rules_page_unprotected(title: str, current: str) -> str:
    return (f'{title} (the rules page) is {current}. It says which rules the bot uses, so it '
            'must be template-editor protected or higher. Ask at Wikipedia:Requests for page '
            'protection.')


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


def link_rule_missing(title: str) -> str:
    return (f'{title} (the template that shows the list of rules pages) does not exist. Copy '
            'docs/link-rule.mediawiki there.')


# -- articles --------------------------------------------------------------

SKIP_MISSING = 'page does not exist'
SKIP_REDIRECT = 'page is a redirect'
SKIP_NOT_ARTICLE = 'not an article; use --any-namespace to preview it in a dry run'
SKIP_EXCLUDED = 'excluded by {{bots}}/{{nobots}}'
SKIP_EDIT_CONFLICT = 'edit conflict; will be retried on the next run'
SKIP_PROTECTED = 'page is protected'


def skip_recently_edited(bot_user: str, when: object) -> str:
    return (f'{bot_user} already edited this page on {when:%Y-%m-%d}; not repeating a fix '
            'within the cooldown in case it was reverted on purpose')


def skip_save_failed(error: Exception) -> str:
    return f'save failed: {error}'


def skip_error(error: Exception) -> str:
    return f'error: {type(error).__name__}: {error}'


def name_has_comment() -> str:
    return 'parameter name contains a comment'


def target_rejected(target: str) -> str:
    return f'the template does not accept "{target}"; check the rule'


def both_set(old: str, new: str) -> str:
    return f'"{old}" and "{new}" are both set, to different values'


def several_rules_match(rules: list[str]) -> str:
    return (f'more than one "#" rule matches it ({"; ".join(rules)}), so the bot left it alone. '
            'Delete one of those rows, or add a row for this exact name')


def edit_summary(parts: list[str], rules_page: str, limit: int) -> str:
    text = 'Fixing deprecated parameters restored in ' + '; '.join(parts)
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + '…'
    return f'{text} ([[{rules_page}|rules]])'


def report_summary(edits: int, needing_review: int) -> str:
    return f'Updating report: {edits} edits, {needing_review} pages need review'


# -- stopping --------------------------------------------------------------

def stopped_at_max_edits(max_edits: int) -> str:
    return f'Stopped after {max_edits} edits (--max-edits).'


def too_many_failures(failures: int, error: Exception) -> str:
    return (f'{failures} pages in a row failed; the last error was '
            f'{type(error).__name__}: {error}')


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
    return f'The run stopped early because of an error: {type(error).__name__}: {error}'
