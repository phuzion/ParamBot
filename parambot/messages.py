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


# -- the rules page --------------------------------------------------------

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


def renamed_and_removed(template: str, old: str) -> str:
    return f'{template}: "{old}" is both renamed and removed. Delete one.'


def renamed_twice(template: str, old: str, first: str | None, second: str | None) -> str:
    first, second = first or 'remove', second or 'remove'
    return (f'{template}: "{old}" is renamed to both "{first}" and "{second}". '
            f'Using "{second}"; delete the wrong row.')


def malformed_one_line_rule(line: object) -> str:
    return (f'An {{{{{AWB_TEMPLATE}}}}} line needs exactly three parts: template, old name, '
            f'new name. The bot ignored: {excerpt(line, 120)}')


def rename_loop(template: str, old: str) -> str:
    return (f'{template}: the rules for "{old}" go round in a circle (a → b, b → a). '
            'The bot ignored that rule.')


# -- templates -------------------------------------------------------------

def template_missing(template: str) -> str:
    return (f'Template:{template} does not exist, so its rules are switched off. '
            "Check the spelling in the table's caption.")


def no_parameter_list(template: str) -> str:
    return (f'Template:{template} has no list of accepted parameters the bot can read (a '
            '{{#invoke:Check for unknown parameters|check|...}} call), so its rules are '
            'switched off.')


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
    return (f'{title} (the rules page) is {current}. It decides what the bot edits, so it must '
            'be template-editor protected or higher. Ask at Wikipedia:Requests for page '
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
    return f'{source} has no rules, so there is nothing to do'


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
