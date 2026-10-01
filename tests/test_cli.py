import io
import sys

import pytest

from parambot.cli import _build_parser, _never_crash_printing, _options, main, scaffold_next_steps
from parambot.options import Options
from parambot.settings import Settings


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


def test_a_run_stops_after_20_hours_by_default():
    assert _options(_build_parser().parse_args(['run'])).max_hours == 20
    assert _options(_build_parser().parse_args(['run', '--max-hours', '0'])).max_hours == 0


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


# -- settings from parambot.toml -------------------------------------------

def _run_options(argv, settings=None, account=None):
    return _options(_build_parser().parse_args(argv), settings, account)


SETTINGS = Settings({'mode': 'report-only', 'report_page': 'User:ParamBot/Daily report',
                     'cooldown_days': 14, 'max_hours': 6.0, 'rules_protection': 'sysop',
                     'large_run': 100})


def test_settings_apply_to_a_run():
    opts = _run_options(['run'], SETTINGS)
    assert (opts.report_page, opts.cooldown_days, opts.max_hours, opts.large_run,
            opts.rules_protection) == ('User:ParamBot/Daily report', 14, 6.0, 100, 'sysop')
    assert opts.report_only


def test_the_command_line_overrides_the_settings():
    opts = _run_options(['run', '--cooldown-days', '0', '--max-hours', '2',
                         '--report-page', 'User:ParamBot/Report'], SETTINGS)
    assert (opts.cooldown_days, opts.max_hours, opts.report_page) == (
        0, 2, 'User:ParamBot/Report')


def test_settings_apply_to_check_rules_too():
    opts = _run_options(['check-rules'], SETTINGS)
    assert (opts.report_page, opts.rules_protection) == ('User:ParamBot/Daily report', 'sysop')
    assert not opts.saves_report


@pytest.mark.parametrize('mode, flags, expected', [
    (None, [], 'dry-run'),
    ('live', [], 'live'),
    ('report-only', [], 'report-only'),
    ('live', ['--dry-run'], 'dry-run'),
    ('live', ['--report-only'], 'report-only'),
    ('dry-run', ['--live'], 'live'),
    ('dry-run', ['--report-only'], 'report-only'),
    # Given more than one, the safest wins.
    (None, ['--live', '--report-only'], 'report-only'),
    (None, ['--live', '--dry-run'], 'dry-run'),
    (None, ['--report-only', '--dry-run'], 'dry-run'),
])
def test_the_mode_comes_from_the_settings_unless_the_command_line_says(mode, flags, expected):
    settings = Settings({'mode': mode} if mode else {})
    opts = _run_options(['run', *flags], settings)
    assert {'dry-run': (False, False), 'report-only': (False, True),
            'live': (True, False)}[expected] == (opts.live, opts.report_only)


def test_the_bot_account_comes_from_user_config():
    opts = _run_options(['run'], account='OtherBot')
    assert (opts.bot_user, opts.report_page) == ('OtherBot', 'User:OtherBot/Report')
    # --bot-user wins, and with neither it's ParamBot.
    assert _run_options(['--bot-user', 'X', 'run'], account='OtherBot').bot_user == 'X'
    assert _run_options(['run']).bot_user == 'ParamBot'


def test_a_bad_settings_file_stops_before_anything_else(tmp_path, capsys):
    path = tmp_path / 'parambot.toml'
    path.write_text('[limits]\ncooldown = 30\n', encoding='utf-8')
    with pytest.raises(SystemExit):
        main(['--config', str(path), 'run'])
    assert r'no setting [limits] cooldown' in capsys.readouterr().err


def test_any_namespace_says_how_to_overrule_a_live_mode_setting(tmp_path, capsys):
    path = tmp_path / 'parambot.toml'
    path.write_text('mode = "live"\n', encoding='utf-8')
    with pytest.raises(SystemExit):
        main(['--config', str(path), 'run', '--any-namespace', '--page', 'User:X/sandbox'])
    assert 'sets mode = "live": add --dry-run' in capsys.readouterr().err
