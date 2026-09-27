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


def live_bot(tmp_path, run_page='yes'):
    bot = ParamBot(site=None, options=Options(bot_user='ExampleBot', live=True,
                                              out_dir=str(tmp_path)))
    bot.run_page_value = run_page
    bot._run_page_text = lambda: bot.run_page_value
    return bot


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
    bot = ParamBot(site=None, options=Options(out_dir=str(tmp_path)))

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
