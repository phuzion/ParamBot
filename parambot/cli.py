"""Command line entry point.

    parambot run                  a run, as parambot.toml's mode says: a dry run
                                  against the live wiki (no edits) unless it says otherwise
    parambot run --dry-run        a dry run, whatever parambot.toml says
    parambot run --page "User:X/sandbox" --any-namespace
                                  preview what the bot would do to a sandbox
    parambot run --live           real run (needs user-config.py and a bot account)
    parambot run --report-only    save the report page and edit nothing else
                                  (needs user-config.py, but no bot flag)
    parambot check-rules          check the bot's pages and the rules against the templates
    parambot scaffold TEMPLATE    print a rules table built from TEMPLATE's
                                  deprecated-parameter check, ready to paste

Settings are in parambot.toml, next to user-config.py (see
deploy/parambot.example.toml). Command-line options override them.
"""

import argparse
import io
import logging
import os
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING

from . import commit
from .options import Options
from .settings import DRY_RUN, LIVE, REPORT_ONLY, Settings, SettingsError, load_settings

# Pywikibot reads its configuration when it's first imported, so the modules
# that import it are imported inside the functions below, once _connect has
# set the environment up.  tests/test_cli.py checks that importing this
# module doesn't import Pywikibot.
if TYPE_CHECKING:
    from .wiki import Wiki


def main(argv: list[str] | None = None) -> int:
    _never_crash_printing()
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s %(message)s')
    try:
        settings = load_settings(args.config)
    except SettingsError as error:
        parser.error(str(error))
    logging.info('ParamBot %s', commit() or '(not running from a git checkout)')
    if settings.path:
        logging.info('Settings from %s', settings.path)
    if getattr(args, 'any_namespace', False):
        if _mode(args, settings) != DRY_RUN:
            parser.error('--any-namespace is for dry runs only; the bot only edits articles'
                         + ('' if args.live or args.report_only else
                            f'. {settings.path} sets mode = "{settings.mode}": add --dry-run'))
        if not args.page:
            parser.error('--any-namespace needs --page: name the sandbox page to preview')
    wiki, account = _connect(args, settings)
    options = _options(args, settings, account)
    commands = {'run': _run, 'check-rules': _check_rules, 'scaffold': _scaffold}
    return commands[args.command](args, wiki, options)


def _never_crash_printing() -> None:
    """Messages contain characters such as →, which some consoles can't show
    (Windows with a non-UTF-8 code page, for one).  Show a replacement there
    instead of crashing, and write output that goes to a file or a pipe as
    UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            encoding = stream.encoding if stream.isatty() else 'utf-8'
            stream.reconfigure(encoding=encoding, errors='replace')


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='parambot', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', metavar='FILE',
                        help='the settings file (default: parambot.toml next to user-config.py)')
    # Not from user-config.py: without a mylang there, Pywikibot quietly
    # picks test.wikipedia.
    parser.add_argument('--lang', default='en')
    parser.add_argument('--family', default='wikipedia')
    parser.add_argument('--bot-user',
                        help="bot account name (default: user-config.py's, else ParamBot); "
                             "also sets the default names of the bot's pages")
    parser.add_argument('--rules-page',
                        help='default: [pages] rules in parambot.toml, else User:<bot-user>/Rules')
    parser.add_argument('--rules-file', action='append', default=[],
                        help='read rules from this local file instead of the wiki; repeatable. '
                             'A directory means every .mediawiki file in it')
    parser.add_argument('-v', '--verbose', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)

    run = sub.add_parser(
        'run', help='poll the categories and fix pages',
        description='Without --dry-run, --report-only or --live, a run does what mode in '
                    'parambot.toml says, and is a dry run if it says nothing. Given more '
                    'than one, the safest wins: --dry-run, then --report-only.')
    run.add_argument('--dry-run', action='store_true',
                     help='read only: write the report and the edits it would make to files')
    run.add_argument('--live', action='store_true', help='actually edit')
    run.add_argument('--trial', action='store_true',
                     help='allow a live run without the bot flag, for a BRFA trial')
    run.add_argument('--report-only', action='store_true',
                     help='save the report page and never edit anything else, even with '
                          "--live; needs no bot flag, since it only edits the bot's own page")
    run.add_argument('--max-edits', type=int,
                     help='stop after this many edits, such as for a BRFA trial '
                          '(default: [limits] max_edits in parambot.toml, else no limit; '
                          '0 = no limit)')
    run.add_argument('--max-hours', type=float,
                     help='stop starting new work after this many hours, so a daily run '
                          'is done before the next starts (default: [limits] max_hours, '
                          'else 20; 0 = no limit)')
    run.add_argument('--cooldown-days', type=int,
                     help="don't repeat a fix on a page the bot edited this recently "
                          '(default: [limits] cooldown_days, else 30; 0 = off)')
    run.add_argument('--template', action='append', default=[],
                     help="only use this template's rules; repeatable")
    run.add_argument('--page', action='append', default=[],
                     help='only check this page (skips category polling); repeatable')
    run.add_argument('--any-namespace', action='store_true',
                     help='let --page pages be outside the main namespace (e.g. a user '
                          'sandbox), to preview what the bot would do; dry runs only')
    run.add_argument('--report-page',
                     help='default: [pages] report, else User:<bot-user>/Report')
    run.add_argument('--run-page', help='default: [pages] run, else User:<bot-user>/Run')
    run.add_argument('--out-dir',
                     help="where dry runs (and live runs that can't save the report) write "
                          'files (default: [output] dir, else out)')

    sub.add_parser('check-rules', help="check the bot's pages and every template's rules")

    scaffold = sub.add_parser(
        'scaffold', help="print a rules table built from a template's deprecated-parameter check")
    scaffold.add_argument('template')
    scaffold.add_argument('--oldid', type=int,
                          help='read this revision of the template instead of the current one')
    return parser


def _mode(args: argparse.Namespace, settings: Settings) -> str:
    """What a run does: the safest mode the command line asks for, if it
    asks for one, or else the settings file's."""
    if args.command != 'run' or args.dry_run:
        return DRY_RUN
    if args.report_only:
        return REPORT_ONLY
    if args.live:
        return LIVE
    return settings.mode


def _options(args: argparse.Namespace, settings: Settings | None = None,
             account: str | None = None) -> Options:
    """The options for a run: the settings file's, then the command line's.
    account is the bot account user-config.py names, if it names one."""
    settings = settings or Settings()
    values = settings.options()
    if args.bot_user or account:
        values['bot_user'] = args.bot_user or account
    if args.rules_page:
        values['rules_page'] = args.rules_page
    values['rules_files'] = tuple(args.rules_file)
    # The trial's count lives next to user-config.py, unless the path says
    # otherwise, so that every run on the machine adds to the same count.
    values['trial_count_file'] = os.path.join(
        os.environ.get('PYWIKIBOT_DIR', os.getcwd()),
        values.get('trial_count_file', Options.trial_count_file))
    if args.command == 'run':
        mode = _mode(args, settings)
        values.update(live=mode == LIVE, report_only=mode == REPORT_ONLY, trial=args.trial,
                      templates=tuple(args.template), pages=tuple(args.page),
                      any_namespace=args.any_namespace)
        for name in ('max_edits', 'max_hours', 'cooldown_days', 'report_page', 'run_page',
                     'out_dir'):
            if getattr(args, name) is not None:
                values[name] = getattr(args, name)
    return Options(**values)


def _connect(args: argparse.Namespace, settings: Settings) -> tuple['Wiki', str | None]:
    """Set up Pywikibot.  Returns the wiki to work on, and the bot account
    user-config.py names, if it names one."""
    # Dry runs only read, so they work without a user-config.py.
    base = os.environ.get('PYWIKIBOT_DIR', os.getcwd())
    if _mode(args, settings) == DRY_RUN and not os.path.exists(
            os.path.join(base, 'user-config.py')):
        os.environ.setdefault('PYWIKIBOT_NO_USER_CONFIG', '2')
    import pywikibot
    from pywikibot import config

    from .wiki import Wiki

    account = _account(config.usernames, args.family, args.lang)
    config.user_agent_format = _user_agent(
        settings.contact, args.lang, args.family, args.bot_user or account or Options.bot_user,
        commit())
    # A floor under the time between API reads, whatever part of the bot asks.
    config.minthrottle = settings.read_delay
    return Wiki(pywikibot.Site(args.lang, args.family)), account


def _account(usernames: Mapping[str, Mapping[str, str]], family: str, lang: str) -> str | None:
    """The bot account user-config.py's usernames name for the wiki, if any."""
    names = usernames.get(family, {})
    account = names.get(lang) or names.get('*')
    # "ParamBot@name" names a bot password too, but that name goes in
    # user-password.py: the account is ParamBot.
    return account.split('@')[0] if account else None


def _user_agent(contact: str, lang: str, family: str, bot_user: str,
                running: str | None) -> str:
    """Pywikibot's user_agent_format for the bot.  Wikimedia throttles
    clients that don't say who they are.  The commit it's running from,
    if it knows it, stands in for a version number."""
    contact = contact or f'https://{lang}.{family}.org/wiki/User:{bot_user.replace(" ", "_")}'
    product = f'ParamBot/{running}' if running else 'ParamBot'
    return f'{product} ({contact}) ' '{pwb} ({revision}) {http_backend} {python}'


def _run(args: argparse.Namespace, wiki: 'Wiki', options: Options) -> int:
    from . import messages as msg
    from .bot import ParamBot, StopRun

    try:
        report = ParamBot(wiki, options).run()
    except StopRun as stop:
        # Without the report's markup: a log is plain text.
        logging.error('%s', msg.plain(str(stop)))
        return 2
    except Exception:
        return 1  # already logged, with the traceback, and put in the report
    print(report.stats_line(options.live, options.report_only))
    return 0


def _check_rules(args: argparse.Namespace, wiki: 'Wiki', options: Options) -> int:
    from . import messages as msg
    from .bot import ParamBot

    report = ParamBot(wiki, options).check_rules()
    for label, lines in (('SETUP  ', report.setup), ('PROBLEM', report.problems),
                         ('NOTE   ', report.notes)):
        for line in lines:
            print(label, msg.plain(line))
    return 1 if report.problems or report.setup else 0


def _scaffold(args: argparse.Namespace, wiki: 'Wiki', options: Options) -> int:
    from .templatescan import scaffold_table

    page = wiki.page(args.template, ns=10)
    text = page.getOldVersion(args.oldid) if args.oldid else page.text
    template = page.title(with_ns=False)
    table, warnings = scaffold_table(template, text)
    if table is None:
        print(f'{page.title()} has no {{{{#invoke:Check for deprecated parameters}}}} call',
              file=sys.stderr)
        return 1
    for warning in warnings:
        print(f'Could not turn "{warning}" into a row; add rows for it by hand.',
              file=sys.stderr)
    print(table)
    print(scaffold_next_steps(options, template), file=sys.stderr)
    return 0


def scaffold_next_steps(options: Options, template: str) -> str:
    """Where a scaffolded table goes."""
    return (f'Put this table on {options.rules_page}/{template}. Then a template editor lists '
            f'it on {options.rules_page}, under "== Active ==" or "== Inactive ==", as '
            f'{{{{{options.link_rule_page}|{template}|REVISION}}}}, with the number of the '
            'revision they approve.')


if __name__ == '__main__':
    sys.exit(main())
