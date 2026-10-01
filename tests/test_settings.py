"""The settings file, parambot.toml."""

import re
from pathlib import Path

import pytest

from parambot.options import Options
from parambot.settings import (
    _SCHEMA,
    DRY_RUN,
    READ_DELAY,
    Settings,
    SettingsError,
    default_path,
    load_settings,
)

EXAMPLE = Path(__file__).parent.parent / 'deploy' / 'parambot.example.toml'


def settings_in(tmp_path, text):
    path = tmp_path / 'parambot.toml'
    path.write_text(text, encoding='utf-8')
    return load_settings(str(path))


def test_the_example_shows_every_setting_with_its_default(tmp_path):
    # Remove the # in front of every setting, and nothing changes.
    text = re.sub(r'^# (\w+ = )', r'\1', EXAMPLE.read_text(encoding='utf-8'), flags=re.M)
    settings = settings_in(tmp_path, text)
    named = {setting.name for table in _SCHEMA.values() for setting in table.values()}
    assert set(settings.values) == named
    assert settings.mode == DRY_RUN
    assert settings.read_delay == READ_DELAY
    assert settings.contact == 'https://en.wikipedia.org/wiki/User:ParamBot'
    options = settings.options()
    assert options.pop('max_edits') == 0     # the same as None: no limit
    defaults = Options()
    assert options == {name: getattr(defaults, name) for name in options}


def test_the_example_as_it_is_sets_nothing():
    assert load_settings(str(EXAMPLE)).values == {}


def test_a_file_of_settings(tmp_path):
    settings = settings_in(tmp_path, '''
mode = "report-only"
[pages]
report = "User:ParamBot/Daily report"
[limits]
cooldown_days = 14
max_hours = 6        # a whole number is fine for a number
read_delay = 2.5
[rules]
protection = "sysop"
[output]
contact = "parambot@example.org"
''')
    assert settings.mode == 'report-only'
    assert settings.read_delay == 2.5
    assert settings.contact == 'parambot@example.org'
    assert settings.options() == {'report_page': 'User:ParamBot/Daily report',
                                  'cooldown_days': 14, 'max_hours': 6.0,
                                  'rules_protection': 'sysop'}
    options = Options(**settings.options())
    assert options.report_page == 'User:ParamBot/Daily report'
    assert options.run_page == 'User:ParamBot/Run'   # still the default


def test_no_file_means_the_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv('PYWIKIBOT_DIR', str(tmp_path))
    assert default_path() == str(tmp_path / 'parambot.toml')
    assert load_settings() == Settings()
    (tmp_path / 'parambot.toml').write_text('mode = "live"\n', encoding='utf-8')
    assert load_settings().mode == 'live'


def test_next_to_user_config_means_the_current_directory_without_pywikibot_dir(
        tmp_path, monkeypatch):
    monkeypatch.delenv('PYWIKIBOT_DIR', raising=False)
    monkeypatch.chdir(tmp_path)
    assert Path(default_path()) == tmp_path / 'parambot.toml'


def test_a_named_file_must_exist(tmp_path):
    with pytest.raises(SettingsError, match='does not exist'):
        load_settings(str(tmp_path / 'nope.toml'))


@pytest.mark.parametrize('text, error', [
    ('mode = "dry run"', 'mode must be one of "dry-run", "report-only", "live"'),
    ('[limits]\ncooldown = 30', r'no setting \[limits\] cooldown. Check the spelling: the '
                                r'settings under \[limits\] are cooldown_days, max_hours'),
    ('[limit]\ncooldown_days = 30', r'no setting limit\. .* are mode, \[pages\], \[limits\]'),
    ('cooldown_days = 30', 'no setting cooldown_days'),
    ('pages = "User:X"', r'\[pages\] is a section'),
    ('[limits]\ncooldown_days = "30"', r'\[limits\] cooldown_days must be a whole number'),
    ('[limits]\ncooldown_days = 1.5', 'must be a whole number'),
    ('[limits]\ncooldown_days = true', 'must be a whole number'),
    ('[limits]\nmax_hours = "20"', r'max_hours must be a number, without quotes'),
    ('[limits]\ncooldown_days = -1', 'must be at least 0'),
    ('[limits]\nfailures_in_a_row = 0', 'must be at least 1'),
    ('[pages]\nreport = ""', r'\[pages\] report must be some text'),
    ('[pages]\nreport = 5', 'must be some text, in quotes'),
    ('[rules]\nprotection = "full"', 'protection must be one of "autoconfirmed"'),
    ('[limits\n', 'parambot.toml: '),     # not TOML
])
def test_mistakes_are_explained(tmp_path, text, error):
    with pytest.raises(SettingsError, match=error):
        settings_in(tmp_path, text)
