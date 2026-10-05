import io
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from fakes import (
    BOT,
    OFFICEHOLDER_CATEGORY,
    FakePage,
    FakeWiki,
    options,
    wiki_for,
)

from parambot.cli import (
    _account,
    _build_parser,
    _never_crash_printing,
    _options,
    _user_agent,
    main,
    scaffold_next_steps,
)
from parambot.options import Options
from parambot.settings import Settings

ROOT = Path(__file__).parent.parent


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


def test_the_trial_count_is_kept_next_to_user_config(tmp_path, monkeypatch):
    # Wherever a run starts from, so that every run adds to the same count.
    monkeypatch.setenv('PYWIKIBOT_DIR', str(tmp_path))
    assert Path(_run_options(['run']).trial_count_file) == tmp_path / 'trial-edits.txt'
    elsewhere = str(tmp_path / 'state' / 'count.txt')
    settings = Settings({'trial_edits': 100, 'trial_count_file': elsewhere})
    opts = _run_options(['run'], settings)
    assert (opts.trial_edits, opts.trial_count_file) == (100, elsewhere)


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


def test_the_wiki_is_the_english_wikipedia_unless_the_command_line_says():
    # Not user-config.py's: without a mylang, Pywikibot picks test.wikipedia.
    args = _build_parser().parse_args(['run'])
    assert (args.lang, args.family) == ('en', 'wikipedia')


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


# -- connecting ------------------------------------------------------------

def test_importing_the_cli_does_not_import_pywikibot():
    # Pywikibot reads its configuration when it's first imported, so it has
    # to wait until _connect has set the environment up for a dry run.
    result = subprocess.run(
        [sys.executable, '-c', 'import sys, parambot.cli; sys.exit("pywikibot" in sys.modules)'],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('usernames, account', [
    ({'wikipedia': {'en': 'ParamBot'}}, 'ParamBot'),
    ({'wikipedia': {'en': 'ParamBot@ReportOnly'}}, 'ParamBot'),   # with a bot password's name
    ({'wikipedia': {'*': 'ParamBot'}}, 'ParamBot'),               # for every language
    ({'wikipedia': {'*': 'Other', 'en': 'ParamBot'}}, 'ParamBot'),
    ({'wikipedia': {'de': 'ParamBot'}}, None),
    ({'wiktionary': {'en': 'ParamBot'}}, None),
    ({}, None),
])
def test_the_account_user_config_names_for_the_wiki(usernames, account):
    assert _account(usernames, 'wikipedia', 'en') == account


def test_the_user_agent_names_the_commit_and_a_contact():
    assert _user_agent('', 'en', 'wikipedia', 'Param Bot', '24cef13') == (
        'ParamBot/24cef13 (https://en.wikipedia.org/wiki/User:Param_Bot) '
        '{pwb} ({revision}) {http_backend} {python}')
    # Not from a git checkout, and with a contact from the settings.
    assert _user_agent('ops@example.org', 'en', 'wikipedia', 'ParamBot', None).startswith(
        'ParamBot (ops@example.org) {pwb}')


# -- the commands, on a fake wiki ------------------------------------------

def run_main(monkeypatch, tmp_path, wiki, *argv):
    """main(), with the fake wiki for a connection, and no settings file."""
    monkeypatch.setenv('PYWIKIBOT_DIR', str(tmp_path))
    monkeypatch.setattr('parambot.cli._connect', lambda args, settings: (wiki, None))
    return main(['--bot-user', BOT, *argv])


def article():
    return FakePage('Jane Example', '{{Infobox officeholder\n| termstart = 2020\n}}')


def test_a_finished_run_exits_with_0_and_prints_what_it_did(monkeypatch, tmp_path, capsys):
    wiki = wiki_for(options()).populate(OFFICEHOLDER_CATEGORY, article())
    assert run_main(monkeypatch, tmp_path, wiki, 'run', '--out-dir', str(tmp_path / 'out')) == 0
    assert capsys.readouterr().out.rstrip().endswith('would have made (dry run) 1 edit.')
    assert list((tmp_path / 'out').glob('edits-*.diff'))


def test_a_run_that_is_switched_off_exits_with_2(monkeypatch, tmp_path):
    # Anything but 0 gets Toolforge to email the operators.
    opts = options()
    wiki = wiki_for(opts, **{opts.run_page: FakePage(opts.run_page, 'no')})
    assert run_main(monkeypatch, tmp_path, wiki, 'run', '--live', '--out-dir', str(tmp_path)) == 2


def test_a_run_stopped_by_an_error_exits_with_1_and_writes_the_report(monkeypatch, tmp_path):
    wiki = wiki_for(options())
    wiki.fail_polling = ConnectionError('API down')
    assert run_main(monkeypatch, tmp_path, wiki, 'run', '--out-dir', str(tmp_path)) == 1
    [report] = tmp_path.glob('report-*.mediawiki')
    assert 'ConnectionError: <nowiki>API down</nowiki>' in report.read_text(encoding='utf-8')


def test_a_trial_without_its_count_file_logs_where_it_looked_and_stops(
        monkeypatch, tmp_path, caplog):
    settings = tmp_path / 'parambot.toml'
    settings.write_text('[trial]\nedits = 3\n', encoding='utf-8')
    with caplog.at_level('INFO'):
        assert run_main(monkeypatch, tmp_path, wiki_for(options()),
                        '--config', str(settings), 'run') == 2
    path = str(tmp_path / 'trial-edits.txt')
    assert f'BRFA trial: its count of edits is in {path}' in caplog.messages
    [stop] = [r.getMessage() for r in caplog.records if r.levelname == 'ERROR']
    assert stop.startswith(f"There's no count of trial edits at {path}, so the bot stopped")
    # As plain text: none of the report's private-use markup characters.
    assert not any('' <= c <= '' for c in stop)


def test_check_rules_exits_with_0_when_all_is_well(monkeypatch, tmp_path, capsys):
    assert run_main(monkeypatch, tmp_path, wiki_for(options()), 'check-rules') == 0
    out = capsys.readouterr().out
    assert 'SETUP' not in out and 'PROBLEM' not in out


def test_check_rules_exits_with_1_and_lists_what_is_wrong(monkeypatch, tmp_path, capsys):
    opts = options()
    unprotected = FakePage(opts.rules_page, wiki_for(opts).page(opts.rules_page).text)
    wiki = wiki_for(opts, **{opts.rules_page: unprotected})
    assert run_main(monkeypatch, tmp_path, wiki, 'check-rules') == 1
    assert (f'SETUP   {opts.rules_page} (the rules page) is not protected.'
            in capsys.readouterr().out)


DEPRECATED_CHECK = ('{{#invoke:Check for deprecated parameters|check|_category=[[Category:X]]'
                    '|imagesize=image_size|_remove=nationality}}')


def test_scaffold_prints_a_rules_table_and_where_it_goes(monkeypatch, tmp_path, capsys):
    wiki = FakeWiki(FakePage('Template:Infobox foo', DEPRECATED_CHECK))
    assert run_main(monkeypatch, tmp_path, wiki, 'scaffold', 'Infobox foo') == 0
    out, err = capsys.readouterr()
    assert out.startswith('{| class="wikitable"\n|+ {{tl|Infobox foo}}\n')
    assert '| {{para|imagesize}} || {{para|image_size}}' in out
    assert '| {{para|nationality}} || remove' in out
    assert f'Put this table on User:{BOT}/Rules/Infobox foo.' in err


def test_scaffold_can_read_an_old_revision(monkeypatch, tmp_path, capsys):
    # From before the deprecated-parameter check was taken out.
    template = FakePage('Template:Infobox foo', '{{Infobox}}', history={41: DEPRECATED_CHECK})
    assert run_main(monkeypatch, tmp_path, FakeWiki(template),
                    'scaffold', 'Infobox foo', '--oldid', '41') == 0
    assert '{{para|imagesize}}' in capsys.readouterr().out


def test_scaffold_without_a_deprecated_check_exits_with_1(monkeypatch, tmp_path, capsys):
    wiki = FakeWiki(FakePage('Template:Infobox foo', '{{Infobox}}'))
    assert run_main(monkeypatch, tmp_path, wiki, 'scaffold', 'Infobox foo') == 1
    assert ('Template:Infobox foo has no {{#invoke:Check for deprecated parameters}} call'
            in capsys.readouterr().err)


def test_python_dash_m_parambot_runs_the_command_line(monkeypatch, capsys):
    # As the Toolforge job does.
    monkeypatch.setattr(sys, 'argv', ['parambot', '--help'])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module('parambot', run_name='__main__')
    assert stop.value.code == 0
    assert 'check-rules' in capsys.readouterr().out
