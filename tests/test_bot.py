import os

os.environ.setdefault('PYWIKIBOT_NO_USER_CONFIG', '2')

import pytest  # noqa: E402

from parambot.bot import SUMMARY_LIMIT, Options, ParamBot, StopRun  # noqa: E402
from parambot.fixer import Issue, fix_wikitext  # noqa: E402
from parambot.report import Report  # noqa: E402
from parambot.rules import parse_config  # noqa: E402


def make_bot():
    return ParamBot(site=None, options=Options(bot_user='ExampleBot'))


def rules_table(template, *pairs):
    rows = ''.join(f'|-\n| {{{{para|{old}}}}} || {{{{para|{new}}}}}\n' for old, new in pairs)
    return f'{{|\n|+ {{{{tl|{template}}}}}\n{rows}|}}\n'


def test_default_pages_follow_bot_user():
    opts = Options(bot_user='ExampleBot')
    assert opts.rules_page == 'User:ExampleBot/Rules'
    assert opts.report_page == 'User:ExampleBot/Report'
    assert opts.run_page == 'User:ExampleBot/Run'


def test_summary():
    rulesets = parse_config(
        rules_table('Infobox settlement', ('imagesize', 'image_size'), ('image_caption', 'caption'))
        + rules_table('Infobox person', ('other_name', 'other_names'))).rulesets.values()
    result = fix_wikitext(
        '{{Infobox person|other_name=A|module={{Infobox settlement|imagesize=1|image_caption=B}}}}'
        '{{Infobox settlement|imagesize=2}}', rulesets)
    summary = make_bot()._summary(result)
    assert summary == (
        'Fixing deprecated parameters restored in '
        '[[Template:Infobox person|Infobox person]]: other_name → other_names; '
        '[[Template:Infobox settlement|Infobox settlement]]: imagesize → image_size, '
        'image_caption → caption ([[User:ExampleBot/Rules|rules]])')


def test_summary_is_truncated():
    pairs = [(f'param{i}', f'new_param{i}') for i in range(60)]
    rulesets = parse_config(rules_table('T', *pairs)).rulesets.values()
    text = '{{T|' + '|'.join(f'param{i}=x' for i in range(60)) + '}}'
    summary = make_bot()._summary(fix_wikitext(text, rulesets))
    assert len(summary) < SUMMARY_LIMIT + 50
    assert '…' in summary
    assert summary.endswith('([[User:ExampleBot/Rules|rules]])')


class FakePage:
    def __init__(self, title, ns, text, exists=True, redirect=False, broken=False):
        self._title, self._ns, self.text = title, ns, text
        self._exists, self._redirect, self._broken = exists, redirect, broken
        self.saved = []

    def title(self):
        return self._title

    def namespace(self):
        return self._ns

    def exists(self):
        if self._broken:
            raise ConnectionError('API timed out')
        return self._exists

    def save(self, **kwargs):
        self.saved.append(self.text)

    def isRedirectPage(self):
        return self._redirect

    def botMayEdit(self):
        return True

    def revisions(self, total=None):
        return []


SANDBOX_TEXT = '{{Infobox officeholder\n| termstart = 2020\n}}'


def _officeholder():
    return list(parse_config(
        rules_table('Infobox officeholder', ('termstart', 'term_start'))).rulesets.values())


def test_sandbox_skipped_by_default():
    bot = make_bot()
    bot._process(FakePage('User:Example/sandbox', 2, SANDBOX_TEXT), _officeholder())
    assert bot.diffs == []
    assert bot.report.skipped == [
        ('User:Example/sandbox', 'not an article; use --any-namespace to preview it in a dry run')]


def test_sandbox_preview_with_any_namespace():
    bot = ParamBot(site=None, options=Options(bot_user='ExampleBot', any_namespace=True))
    bot._process(FakePage('User:Example/sandbox', 2, SANDBOX_TEXT), _officeholder())
    assert bot.report.skipped == []
    assert bot.report.edits == 1
    assert '+| term_start = 2020' in bot.diffs[0]


def test_articles_still_work():
    bot = make_bot()
    bot._process(FakePage('Jane Example', 0, SANDBOX_TEXT), _officeholder())
    assert bot.report.edits == 1


def test_missing_and_redirect_pages_are_reported():
    bot = make_bot()
    bot._process(FakePage('Nope', 0, '', exists=False), _officeholder())
    bot._process(FakePage('Redirect', 0, '#REDIRECT [[X]]', redirect=True), _officeholder())
    assert bot.report.skipped == [('Nope', 'page does not exist'), ('Redirect', 'page is a redirect')]


def test_any_namespace_refused_live():
    bot = ParamBot(site=None, options=Options(live=True, any_namespace=True))
    with pytest.raises(StopRun, match='dry runs only'):
        bot.run()   # refuses before touching the (absent) site


@pytest.mark.parametrize('argv', [
    ['run', '--any-namespace', '--live', '--page', 'User:X/sandbox'],
    ['run', '--any-namespace'],
])
def test_any_namespace_cli_guards(argv, capsys):
    from parambot.cli import main
    with pytest.raises(SystemExit):
        main(argv)
    assert '--any-namespace' in capsys.readouterr().err


class WikiPage:
    """A fake one of the bot's own pages, as _load_pages returns them."""

    def __init__(self, title, exists=True, redirect=False, model='wikitext',
                 templates=(), protection=None, editable=True):
        self._title, self._exists, self._redirect = title, exists, redirect
        self.content_model = model
        self._templates = [WikiPage(t) for t in templates]
        self._protection = protection or {}
        self._editable = editable

    def title(self):
        return self._title

    def exists(self):
        return self._exists

    def isRedirectPage(self):
        return self._redirect

    def templates(self):
        return self._templates

    def protection(self):
        return self._protection

    def has_permission(self, action='edit'):
        return self._editable


def set_up_wiki(bot, **changes):
    """Give the bot a correctly set-up set of pages, with changes: a dict
    of page title -> WikiPage, or None to make the page missing."""
    user = f'User:{bot.options.bot_user}'
    pages = {
        user: WikiPage(user, templates=['Template:Bot']),
        bot.options.rules_page: WikiPage(bot.options.rules_page,
                                         protection={'edit': ('templateeditor', 'infinity')}),
        bot.options.run_page: WikiPage(bot.options.run_page),
        bot.options.report_page: WikiPage(bot.options.report_page),
        f'{bot.options.rules_page}/Instructions': WikiPage(f'{bot.options.rules_page}/Instructions'),
    }
    for title, page in changes.items():
        pages[title] = page if page is not None else WikiPage(title, exists=False)
    bot.loaded_titles = []

    def load(titles):
        bot.loaded_titles = list(titles)
        return {t: pages[t] for t in titles}
    bot._load_pages = load
    return bot


def live_bot(tmp_path, run_page='yes'):
    bot = ParamBot(site=None, options=Options(bot_user='ExampleBot', live=True,
                                              out_dir=str(tmp_path)))
    bot.run_page_value = run_page
    bot._run_page_text = lambda: bot.run_page_value
    return set_up_wiki(bot)


def test_run_page_checked_before_every_edit(tmp_path):
    bot = live_bot(tmp_path)
    first = FakePage('First', 0, SANDBOX_TEXT)
    second = FakePage('Second', 0, SANDBOX_TEXT)
    bot._process(first, _officeholder())
    assert first.saved and 'term_start' in first.saved[0]
    bot.run_page_value = 'no <!-- switched off mid-run -->'
    with pytest.raises(StopRun, match='stopped before editing Second'):
        bot._process(second, _officeholder())
    assert second.saved == []


def _candidates(pages):
    from parambot.bot import Candidate
    return {p.title(): Candidate(p, _officeholder()) for p in pages}


def test_error_on_one_page_is_reported_and_the_run_continues():
    bot = make_bot()
    pages = [FakePage('A', 0, SANDBOX_TEXT), FakePage('B', 0, '', broken=True),
             FakePage('C', 0, SANDBOX_TEXT)]
    bot._process_all(_candidates(pages), pages)
    assert bot.report.edits == 2
    assert bot.report.skipped == [('B', 'error: ConnectionError: API timed out')]


def test_repeated_errors_stop_the_run():
    from parambot.bot import MAX_FAILURES_IN_A_ROW
    bot = make_bot()
    pages = [FakePage(f'P{i}', 0, '', broken=True) for i in range(MAX_FAILURES_IN_A_ROW + 3)]
    with pytest.raises(RuntimeError, match=f'{MAX_FAILURES_IN_A_ROW} pages in a row failed'):
        bot._process_all(_candidates(pages), pages)
    assert len(bot.report.skipped) == MAX_FAILURES_IN_A_ROW


def test_a_success_resets_the_error_count():
    from parambot.bot import MAX_FAILURES_IN_A_ROW
    bot = make_bot()
    bad = MAX_FAILURES_IN_A_ROW - 1
    pages = ([FakePage(f'X{i}', 0, '', broken=True) for i in range(bad)]
             + [FakePage('Good', 0, SANDBOX_TEXT)]
             + [FakePage(f'Y{i}', 0, '', broken=True) for i in range(bad)])
    bot._process_all(_candidates(pages), pages)
    assert bot.report.edits == 1


def _only_report(tmp_path):
    reports = list(tmp_path.glob('report-*.wiki'))
    assert len(reports) == 1
    return reports[0].read_text(encoding='utf-8')


def test_crash_still_writes_the_report(tmp_path):
    bot = set_up_wiki(ParamBot(site=None, options=Options(out_dir=str(tmp_path))))

    def boom():
        raise ValueError('boom')
    bot._load_config = boom
    with pytest.raises(ValueError):
        bot.run()
    report = _only_report(tmp_path)
    assert '== Errors ==' in report
    assert 'ValueError: boom' in report


def test_live_crash_saves_the_report_page(tmp_path):
    bot = live_bot(tmp_path)
    bot._check_account = lambda: None
    saved = []
    bot._save_report_page = saved.append

    def boom():
        raise ValueError('boom')
    bot._load_config = boom
    with pytest.raises(ValueError):
        bot.run()
    assert len(saved) == 1 and 'ValueError: boom' in saved[0]
    assert list(tmp_path.glob('report-*.wiki')) == []


def test_live_report_falls_back_to_a_local_file(tmp_path):
    bot = live_bot(tmp_path)
    bot._check_account = lambda: None

    def unreachable(text):
        raise ConnectionError('wiki unreachable')
    bot._save_report_page = unreachable

    def boom():
        raise ValueError('boom')
    bot._load_config = boom
    with pytest.raises(ValueError):
        bot.run()
    assert 'ValueError: boom' in _only_report(tmp_path)


def test_switched_off_mid_run_makes_no_more_wiki_edits(tmp_path):
    bot = live_bot(tmp_path)
    bot._check_account = lambda: None
    saved = []
    bot._save_report_page = saved.append

    def switched_off():
        raise StopRun('User:ExampleBot/Run no longer says "yes"; stopped before editing X')
    bot._run = switched_off
    with pytest.raises(StopRun):
        bot.run()
    assert saved == []                       # no report edit either
    assert 'stopped before editing X' in _only_report(tmp_path)


def test_switched_off_before_the_run_does_nothing(tmp_path):
    bot = live_bot(tmp_path, run_page='no')
    bot._check_account = lambda: None
    with pytest.raises(StopRun, match='not running'):
        bot.run()
    assert list(tmp_path.iterdir()) == []


RULES = 'User:ExampleBot/Rules'
REPORT = 'User:ExampleBot/Report'
RUN = 'User:ExampleBot/Run'


def dry_bot(**options):
    return set_up_wiki(ParamBot(site=None, options=Options(bot_user='ExampleBot', **options)))


def test_correctly_set_up_pages_pass():
    bot = dry_bot()
    assert bot._check_pages() == []
    assert bot.report.notes == []
    assert set(bot.loaded_titles) == {'User:ExampleBot', RULES, RUN, REPORT,
                                      f'{RULES}/Instructions'}


@pytest.mark.parametrize('protection, expected', [
    ({}, 'is not protected'),
    ({'edit': ('autoconfirmed', 'infinity')}, 'is semi-protected'),
    ({'edit': ('extendedconfirmed', 'infinity')}, 'is extended-confirmed protected'),
    ({'move': ('sysop', 'infinity')}, 'is not protected'),    # move protection isn't enough
])
def test_rules_page_must_be_template_editor_protected(protection, expected):
    bot = set_up_wiki(dry_bot(), **{RULES: WikiPage(RULES, protection=protection)})
    problems = bot._check_pages()
    assert len(problems) == 1
    assert expected in problems[0]
    assert 'template-editor protected or higher' in problems[0]


@pytest.mark.parametrize('level', ['templateeditor', 'sysop'])
def test_template_editor_protection_or_higher_passes(level):
    bot = set_up_wiki(dry_bot(), **{RULES: WikiPage(RULES, protection={'edit': (level, 'infinity')})})
    assert bot._check_pages() == []


def test_expiring_protection_is_a_note():
    bot = set_up_wiki(dry_bot(), **{RULES: WikiPage(
        RULES, protection={'edit': ('templateeditor', '2026-12-01T00:00:00Z')})})
    assert bot._check_pages() == []
    assert 'expires 2026-12-01T00:00:00Z' in bot.report.notes[0]


def test_local_rules_file_skips_the_rules_page(tmp_path):
    bot = dry_bot(rules_file=str(tmp_path / 'rules.wiki'))
    assert bot._check_pages() == []
    assert RULES not in bot.loaded_titles


@pytest.mark.parametrize('title, page, expected', [
    ('User:ExampleBot', None, "User:ExampleBot (the bot's user page) does not exist"),
    ('User:ExampleBot', WikiPage('User:ExampleBot'), "doesn't use {{bot}}"),
    (RULES, None, f'{RULES} (the rules page) does not exist'),
    (RULES, WikiPage(RULES, redirect=True, protection={'edit': ('sysop', 'infinity')}),
     f'{RULES} (the rules page) is a redirect'),
    (RUN, None, f'{RUN} (the Run page) does not exist'),
    (REPORT, WikiPage(REPORT, model='json'), 'must be an ordinary wikitext page, not json'),
    (REPORT, WikiPage(REPORT, protection={'edit': ('sysop', 'infinity')}),
     'the bot probably cannot edit it'),
])
def test_broken_pages_are_problems(title, page, expected):
    bot = set_up_wiki(dry_bot(), **{title: page})
    problems = bot._check_pages()
    assert len(problems) == 1
    assert expected in problems[0]


def test_live_run_checks_the_bot_can_edit_the_report(tmp_path):
    bot = live_bot(tmp_path)
    set_up_wiki(bot, **{REPORT: WikiPage(REPORT, editable=False)})
    assert bot._check_pages() == [
        'ExampleBot cannot edit User:ExampleBot/Report (the report page). Check its protection.']


def test_protected_run_page_and_missing_instructions_are_notes():
    bot = set_up_wiki(dry_bot(), **{
        RUN: WikiPage(RUN, protection={'edit': ('sysop', 'infinity')}),
        f'{RULES}/Instructions': None})
    assert bot._check_pages() == []
    notes = '\n'.join(bot.report.notes)
    assert "most editors can't use it to stop the bot" in notes
    assert 'Instructions (the instructions for rule writers) does not exist' in notes


def test_live_run_refuses_to_start_and_lists_every_problem(tmp_path):
    bot = live_bot(tmp_path)
    bot._check_account = lambda: None
    set_up_wiki(bot, **{RULES: WikiPage(RULES), REPORT: None})
    ran = []
    bot._run = lambda: ran.append(True)
    with pytest.raises(StopRun) as stopped:
        bot.run()
    message = str(stopped.value)
    assert message.startswith("Not running, because of problems with the bot's pages:")
    assert f'{RULES} (the rules page) is not protected' in message
    assert f'{REPORT} (the report page) does not exist' in message
    assert ran == []
    assert list(tmp_path.iterdir()) == []   # nothing written anywhere


def test_dry_run_carries_on_and_reports_setup_problems(tmp_path):
    bot = set_up_wiki(dry_bot(out_dir=str(tmp_path)), **{RULES: WikiPage(RULES)})
    bot._run = lambda: None
    bot.run()
    report = _only_report(tmp_path)
    assert '== Setup problems ==' in report
    assert 'is not protected' in report


def test_no_rules_stops_the_run(tmp_path):
    bot = dry_bot(out_dir=str(tmp_path), rules_file=str(tmp_path / 'rules.wiki'))
    (tmp_path / 'rules.wiki').write_text('Nothing here yet.', encoding='utf-8')
    with pytest.raises(StopRun, match='has no rules'):
        bot.run()


def test_check_rules_reports_a_missing_rules_page():
    bot = set_up_wiki(dry_bot(), **{RULES: None})

    def missing():
        raise StopRun(f'Rules page {RULES} does not exist')
    bot._load_config = missing
    report = bot.check_rules()
    assert any('(the rules page) does not exist' in s for s in report.setup)
    assert f'Rules page {RULES} does not exist' in report.setup


ANATOMY = 'Category:Anatomy infobox template using unknown parameters'


def _bone(caption_category=''):
    link = f' watches [[:{caption_category}]]' if caption_category else ''
    return parse_config('{|\n|+ {{tl|Infobox bone}}' + link + '\n| {{para|a}} || {{para|b}}\n|}'
                        ).rulesets['Infobox bone']


def test_category_matches():
    assert ParamBot._category_problem(_bone(ANATOMY), [ANATOMY]) is None
    assert ParamBot._category_problem(_bone(), [_bone().category]) is None


def test_category_differs_from_the_default():
    problem = ParamBot._category_problem(_bone(), [ANATOMY])
    assert 'not the usual Category:Pages using infobox bone with unknown parameters' in problem
    assert f'Add [[:{ANATOMY}]] to the caption of the Infobox bone table' in problem


def test_category_differs_from_the_caption():
    problem = ParamBot._category_problem(_bone('Category:Typo category'), [ANATOMY])
    assert "caption says to watch Category:Typo category" in problem
    assert f"Change the caption's category link to [[:{ANATOMY}]]" in problem


def test_one_line_rules_are_told_to_use_a_table():
    rs = parse_config('* {{AWB rename template parameter|Infobox bone|a|b}}').rulesets['Infobox bone']
    problem = ParamBot._category_problem(rs, [ANATOMY])
    assert "One-line rules can't name a category" in problem
    assert f'a table with [[:{ANATOMY}]] in its caption' in problem


def test_template_without_a_category():
    assert "doesn't put articles with unknown parameters in any category" in \
        ParamBot._category_problem(_bone(), [])


def test_category_unknown_is_not_a_problem():
    assert ParamBot._category_problem(_bone(), None) is None


class ExpandingSite:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def expand_text(self, text, title=None):
        self.calls.append((text, title))
        if self.error:
            raise self.error
        return self.result


def _with_unknown_text(rs, text):
    from parambot.templatescan import KnownParams
    rs.known = KnownParams(unknown_text=text)
    return rs


def test_template_categories_are_expanded_as_for_an_article():
    site = ExpandingSite(f'[[{ANATOMY}|_VALUE_ParamBot probe]]')
    bot = ParamBot(site=site, options=Options())
    rs = _with_unknown_text(_bone(), f'{{{{main other|[[{ANATOMY}|_VALUE_{{{{PAGENAME}}}}]]}}}}')
    assert bot._template_categories(rs) == [ANATOMY]
    assert site.calls[0][1] == 'ParamBot probe'


def test_plain_category_text_needs_no_expansion():
    site = ExpandingSite()
    bot = ParamBot(site=site, options=Options())
    assert bot._template_categories(_with_unknown_text(_bone(), f'[[{ANATOMY}]]')) == [ANATOMY]
    assert site.calls == []


def test_expansion_failure_skips_the_check():
    bot = ParamBot(site=ExpandingSite(error=ConnectionError('down')), options=Options())
    assert bot._template_categories(_with_unknown_text(_bone(), '{{main other|x}}')) is None


def test_explicit_category_overrides_a_default_from_another_table():
    config = parse_config('{|\n|+ {{tl|Infobox bone}}\n| {{para|a}} || {{para|b}}\n|}\n'
                          '{|\n|+ {{tl|Infobox bone}} [[:' + ANATOMY + ']]\n'
                          '| {{para|c}} || {{para|d}}\n|}')
    assert config.problems == []
    assert config.rulesets['Infobox bone'].category == ANATOMY


def test_report_roundtrip():
    report = Report()
    report.issue('Foo', Issue('Infobox person', 'alma_mater', 'education', 'both set'))
    report.skip('Bar', 'excluded by {{bots}}')
    report.problems.append('Template:X does not exist')
    text = report.render('2026-09-26 00:00', live=True)
    assert '[[:Foo]]' in text
    assert '<code><nowiki>alma_mater</nowiki></code> → <code><nowiki>education</nowiki></code>' in text
    assert '<nowiki>excluded by {{bots}}</nowiki>' in text
    assert Report.body_of(text) == report.body()
    # A new run with the same findings has the same body, so no save is needed.
    later = report.render('2026-09-27 00:00', live=True)
    assert later != text
    assert Report.body_of(later) == Report.body_of(text)
