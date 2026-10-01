import io
import sys

import pytest

from parambot.cli import _build_parser, _never_crash_printing, _options, main, scaffold_next_steps
from parambot.options import Options


class Console(io.TextIOWrapper):
    """A terminal whose encoding can't show every character."""

    def isatty(self):
        return True


def _swap_output(monkeypatch, stream):
    monkeypatch.setattr(sys, 'stdout', stream)
    monkeypatch.setattr(sys, 'stderr', stream)


def test_printing_to_a_limited_console_does_not_crash(monkeypatch):
    buffer = io.BytesIO()
    _swap_output(monkeypatch, Console(buffer, encoding='cp1252', newline='\n'))
    _never_crash_printing()
    print('"a" → "b"')
    sys.stdout.flush()
    assert buffer.getvalue() == b'"a" ? "b"\n'


def test_redirected_output_is_utf8(monkeypatch):
    buffer = io.BytesIO()
    _swap_output(monkeypatch, io.TextIOWrapper(buffer, encoding='cp1252', newline='\n'))
    _never_crash_printing()
    print('"a" → "b"')
    sys.stdout.flush()
    assert buffer.getvalue() == '"a" → "b"\n'.encode()


def test_default_pages_follow_the_bot_user():
    opts = Options(bot_user='ExampleBot')
    assert opts.rules_page == 'User:ExampleBot/Rules'
    assert opts.report_page == 'User:ExampleBot/Report'
    assert opts.run_page == 'User:ExampleBot/Run'
    assert opts.instructions_page == 'User:ExampleBot/Rules/Instructions'


def test_run_options_are_built_in_one_go():
    args = _build_parser().parse_args([
        '--bot-user', 'ExampleBot', 'run', '--live', '--max-edits', '5', '--template', 'A',
        '--template', 'B', '--run-page', 'User:ExampleBot/Stop'])
    opts = _options(args)
    assert (opts.live, opts.max_edits, opts.templates) == (True, 5, ('A', 'B'))
    assert opts.run_page == 'User:ExampleBot/Stop'
    assert opts.report_page == 'User:ExampleBot/Report'   # the default


def test_no_edit_limit_by_default():
    assert _options(_build_parser().parse_args(['run'])).max_edits is None


def test_report_only_option():
    opts = _options(_build_parser().parse_args(['run', '--report-only']))
    assert opts.report_only and opts.saves_report and not opts.edits_articles
    # --live doesn't change that.
    opts = _options(_build_parser().parse_args(['run', '--report-only', '--live']))
    assert opts.report_only and not opts.edits_articles


def test_check_rules_options():
    args = _build_parser().parse_args(
        ['--rules-file', 'r.mediawiki', '--rules-file', 'rules/', 'check-rules'])
    opts = _options(args)
    assert opts.rules_files == ('r.mediawiki', 'rules/')
    assert opts.rules_source == 'r.mediawiki, rules/'
    assert not opts.live


def test_scaffold_says_where_the_table_goes():
    assert scaffold_next_steps(Options(bot_user='ExampleBot'), 'Infobox person') == (
        'Put this table on User:ExampleBot/Rules/Infobox person. Then a template editor lists '
        'it on User:ExampleBot/Rules, under "== Active ==" or "== Inactive ==", as '
        '{{User:ExampleBot/LinkRule|Infobox person|REVISION}}, with the number of the revision '
        'they approve.')


@pytest.mark.parametrize('argv', [
    ['run', '--any-namespace', '--live', '--page', 'User:X/sandbox'],
    ['run', '--any-namespace'],
])
def test_any_namespace_guards(argv, capsys):
    with pytest.raises(SystemExit):
        main(argv)
    assert '--any-namespace' in capsys.readouterr().err
