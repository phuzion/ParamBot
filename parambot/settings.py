"""The settings file, parambot.toml.

It goes next to Pywikibot's user-config.py: in PYWIKIBOT_DIR, or the current
directory if that isn't set.  ``--config`` names another file.  Every setting
is optional, and command-line options override them for one run.  The
account isn't here: it comes from user-config.py, which Pywikibot logs in
with.

deploy/parambot.example.toml lists every setting, with its default.
"""

import os
import tomllib
from dataclasses import dataclass, field
from typing import Any

from .options import PROTECTION_LEVELS

__all__ = ['FILE_NAME', 'DRY_RUN', 'REPORT_ONLY', 'LIVE', 'MODES', 'Settings', 'SettingsError',
           'load_settings', 'default_path']

FILE_NAME = 'parambot.toml'

# What a run does.
DRY_RUN = 'dry-run'           # read only; the report and the edits go to files
REPORT_ONLY = 'report-only'   # save the report page, and edit nothing else
LIVE = 'live'                 # edit articles
MODES = (DRY_RUN, REPORT_ONLY, LIVE)

# Seconds between API reads, at least: never more than 3,600 an hour.  A run
# needs a few dozen reads, plus one per 50 articles, so this costs little.
READ_DELAY = 1


@dataclass(frozen=True)
class _Setting:
    kind: type                      # int, float or str
    name: str                       # the Options field, or one of Settings' own
    choices: tuple[str, ...] = ()
    minimum: float | None = None


# {table: {key: setting}}; '' is the top of the file.
_SCHEMA: dict[str, dict[str, _Setting]] = {
    '': {'mode': _Setting(str, 'mode', choices=MODES)},
    'pages': {
        'rules': _Setting(str, 'rules_page'),
        'report': _Setting(str, 'report_page'),
        'run': _Setting(str, 'run_page'),
        'instructions': _Setting(str, 'instructions_page'),
        'faq': _Setting(str, 'faq_page'),
        'header': _Setting(str, 'header_page'),
        'link_rule': _Setting(str, 'link_rule_page'),
    },
    'limits': {
        'cooldown_days': _Setting(int, 'cooldown_days', minimum=0),
        'max_hours': _Setting(float, 'max_hours', minimum=0),
        'max_edits': _Setting(int, 'max_edits', minimum=0),
        'large_run': _Setting(int, 'large_run', minimum=0),
        'failures_in_a_row': _Setting(int, 'failures_in_a_row', minimum=1),
        'read_delay': _Setting(float, 'read_delay', minimum=0),
    },
    'rules': {'protection': _Setting(str, 'rules_protection', choices=PROTECTION_LEVELS)},
    'trial': {
        'edits': _Setting(int, 'trial_edits', minimum=0),
        'count_file': _Setting(str, 'trial_count_file'),
        'brfa': _Setting(str, 'brfa_page'),
        'log': _Setting(str, 'trial_log_page'),
    },
    'output': {
        'dir': _Setting(str, 'out_dir'),
        'contact': _Setting(str, 'contact'),
    },
}
# The settings that aren't Options fields.
_OWN = ('mode', 'read_delay', 'contact')


class SettingsError(Exception):
    """The settings file can't be used: the message says why."""


@dataclass
class Settings:
    """What the settings file sets: {name: value}, by the names in _SCHEMA."""

    values: dict[str, Any] = field(default_factory=dict)
    path: str | None = None   # the file they came from, if any

    @property
    def mode(self) -> str:
        return str(self.values.get('mode', DRY_RUN))

    @property
    def read_delay(self) -> float:
        return float(self.values.get('read_delay', READ_DELAY))

    @property
    def contact(self) -> str:
        """Who to contact about the bot, for the User-Agent; '' for the default."""
        return str(self.values.get('contact', ''))

    def options(self) -> dict[str, Any]:
        """The settings that are Options fields."""
        return {name: value for name, value in self.values.items() if name not in _OWN}


def default_path() -> str:
    """parambot.toml, next to user-config.py."""
    return os.path.join(os.environ.get('PYWIKIBOT_DIR', os.getcwd()), FILE_NAME)


def load_settings(path: str | None = None) -> Settings:
    """The settings in path, or in parambot.toml next to user-config.py if
    path is None.  That one needn't exist, but a file that's named must."""
    if path is None:
        path = default_path()
        if not os.path.exists(path):
            return Settings()
    try:
        with open(path, 'rb') as f:
            data = tomllib.load(f)
    except FileNotFoundError as error:
        raise SettingsError(f'{path} does not exist') from error
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise SettingsError(f'{path}: {error}') from error
    values: dict[str, Any] = {}
    for key, value in data.items():
        if key in _SCHEMA and key and isinstance(value, dict):
            for name, item in value.items():
                setting = _setting(path, key, name)
                values[setting.name] = _checked(path, f'[{key}] {name}', setting, item)
        else:
            setting = _setting(path, '', key)
            values[setting.name] = _checked(path, key, setting, value)
    return Settings(values, path)


def _setting(path: str, table: str, key: str) -> _Setting:
    setting = _SCHEMA[table].get(key)
    if setting is not None:
        return setting
    if not table and key in _SCHEMA:
        raise SettingsError(f'{path}: [{key}] is a section, with settings under it')
    where = f'[{table}] {key}' if table else key
    known = ', '.join(_SCHEMA[table]) if table else ', '.join(
        [*_SCHEMA[''], *(f'[{name}]' for name in _SCHEMA if name)])
    raise SettingsError(f'{path}: there is no setting {where}. Check the spelling: '
                        f'the settings{f" under [{table}]" if table else ""} are {known}.')


def _checked(path: str, where: str, setting: _Setting, value: Any) -> Any:
    """value, if it suits the setting."""
    if setting.kind is str:
        if not isinstance(value, str) or not value.strip():
            raise SettingsError(f'{path}: {where} must be some text, in quotes')
        value = value.strip()
    elif isinstance(value, bool) or not isinstance(value, (int, float)) or (
            setting.kind is int and not isinstance(value, int)):
        kind = 'a whole number' if setting.kind is int else 'a number'
        raise SettingsError(f'{path}: {where} must be {kind}, without quotes')
    elif setting.kind is float:
        value = float(value)
    if setting.choices and value not in setting.choices:
        choices = ', '.join(f'"{choice}"' for choice in setting.choices)
        raise SettingsError(f'{path}: {where} must be one of {choices}')
    if setting.minimum is not None and value < setting.minimum:
        raise SettingsError(f'{path}: {where} must be at least {setting.minimum:g}')
    return value
