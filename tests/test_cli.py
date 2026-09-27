import pytest

from parambot.cli import _build_parser, _options, main
from parambot.options import Options


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


def test_check_rules_options():
    opts = _options(_build_parser().parse_args(['--rules-file', 'r.mediawiki', 'check-rules']))
    assert opts.rules_file == 'r.mediawiki'
    assert not opts.live


@pytest.mark.parametrize('argv', [
    ['run', '--any-namespace', '--live', '--page', 'User:X/sandbox'],
    ['run', '--any-namespace'],
])
def test_any_namespace_guards(argv, capsys):
    with pytest.raises(SystemExit):
        main(argv)
    assert '--any-namespace' in capsys.readouterr().err
