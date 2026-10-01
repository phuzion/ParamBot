"""Command line entry point.

    parambot run                  dry run against the live wiki (no edits)
    parambot run --page "User:X/sandbox" --any-namespace
                                  preview what the bot would do to a sandbox
    parambot run --live           real run (needs user-config.py and a bot account)
    parambot run --report-only    save the report page and edit nothing else
                                  (needs user-config.py, but no bot flag)
    parambot check-rules          check the bot's pages and the rules against the templates
    parambot scaffold TEMPLATE    print a rules table built from TEMPLATE's
                                  deprecated-parameter check, ready to paste
"""

import argparse
import io
import logging
import os
import sys
from datetime import UTC, datetime

from .options import Options
from .wiki import Wiki

# Pywikibot reads its configuration when it's first imported, so the modules
# that import it are imported inside the functions below, after _connect.

# Seconds between API reads, at least: never more than 3,600 an hour.  A run
# needs a few dozen reads, plus one per 50 articles, so this costs little.
READ_DELAY = 1


def main(argv: list[str] | None = None) -> int:
    _never_crash_printing()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if getattr(args, 'any_namespace', False):
        if args.live:
            parser.error('--any-namespace is for dry runs only; the bot only edits articles')
        if not args.page:
            parser.error('--any-namespace needs --page: name the sandbox page to preview')
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s %(message)s')
    wiki = _connect(args)
    commands = {'run': _run, 'check-rules': _check_rules, 'scaffold': _scaffold}
    return commands[args.command](args, wiki)


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
    parser.add_argument('--lang', default='en')
    parser.add_argument('--family', default='wikipedia')
    parser.add_argument('--bot-user', default='ParamBot',
                        help='bot account name; also sets the default rules/report/run pages')
    parser.add_argument('--rules-page', default='', help='default: User:<bot-user>/Rules')
    parser.add_argument('--rules-file', action='append', default=[],
                        help='read rules from this local file instead of the wiki; repeatable. '
                             'A directory means every .mediawiki file in it')
    parser.add_argument('-v', '--verbose', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)

    run = sub.add_parser('run', help='poll the categories and fix pages')
    run.add_argument('--live', action='store_true', help='actually edit (default is a dry run)')
    run.add_argument('--trial', action='store_true',
                     help='allow --live without the bot flag, for a BRFA trial')
    run.add_argument('--report-only', action='store_true',
                     help='save the report page and never edit anything else, even with '
                          "--live; needs no bot flag, since it only edits the bot's own page")
    run.add_argument('--max-edits', type=int, default=100)
    run.add_argument('--cooldown-days', type=int, default=30,
                     help="don't repeat a fix on a page the bot edited this recently (0 = off)")
    run.add_argument('--template', action='append', default=[],
                     help="only use this template's rules; repeatable")
    run.add_argument('--page', action='append', default=[],
                     help='only check this page (skips category polling); repeatable')
    run.add_argument('--any-namespace', action='store_true',
                     help='let --page pages be outside the main namespace (e.g. a user '
                          'sandbox), to preview what the bot would do; dry runs only')
    run.add_argument('--report-page', default='', help='default: User:<bot-user>/Report')
    run.add_argument('--run-page', default='', help='default: User:<bot-user>/Run')
    run.add_argument('--out-dir', default='out',
                     help="where dry runs (and live runs that can't save the report) write files")

    sub.add_parser('check-rules', help="check the bot's pages and every template's rules")

    scaffold = sub.add_parser(
        'scaffold', help="print a rules table built from a template's deprecated-parameter check")
    scaffold.add_argument('template')
    scaffold.add_argument('--oldid', type=int,
                          help='read this revision of the template instead of the current one')
    return parser


def _options(args: argparse.Namespace) -> Options:
    common = dict(bot_user=args.bot_user, rules_page=args.rules_page,
                  rules_files=tuple(args.rules_file))
    if args.command != 'run':
        return Options(**common)
    return Options(
        **common,
        live=args.live,
        trial=args.trial,
        report_only=args.report_only,
        max_edits=args.max_edits,
        cooldown_days=args.cooldown_days,
        templates=tuple(args.template),
        pages=tuple(args.page),
        any_namespace=args.any_namespace,
        report_page=args.report_page,
        run_page=args.run_page,
        out_dir=args.out_dir,
    )


def _connect(args: argparse.Namespace) -> Wiki:
    """Set up Pywikibot and return the wiki to work on."""
    # Dry runs only read, so they work without a user-config.py.
    base = os.environ.get('PYWIKIBOT_DIR', os.getcwd())
    saves = getattr(args, 'live', False) or getattr(args, 'report_only', False)
    if not saves and not os.path.exists(
            os.path.join(base, 'user-config.py')):
        os.environ.setdefault('PYWIKIBOT_NO_USER_CONFIG', '2')
    import pywikibot
    from pywikibot import config

    from . import __version__

    # Wikimedia throttles clients that don't say who they are.
    contact = os.environ.get('PARAMBOT_CONTACT') or \
        f'https://{args.lang}.{args.family}.org/wiki/User:{args.bot_user.replace(" ", "_")}'
    config.user_agent_format = (f'ParamBot/{__version__} ({contact}) '
                                '{pwb} ({revision}) {http_backend} {python}')
    # A floor under the time between API reads, whatever part of the bot asks.
    config.minthrottle = READ_DELAY
    return Wiki(pywikibot.Site(args.lang, args.family))


def _run(args: argparse.Namespace, wiki: Wiki) -> int:
    from .bot import ParamBot, StopRun

    try:
        report = ParamBot(wiki, _options(args)).run()
    except StopRun as stop:
        logging.error('%s', stop)
        return 2
    except Exception:
        return 1  # already logged, with the traceback, and put in the report
    print(report.stats_line(datetime.now(UTC).strftime('%Y-%m-%d %H:%M'), args.live,
                            args.report_only))
    return 0


def _check_rules(args: argparse.Namespace, wiki: Wiki) -> int:
    from . import messages as msg
    from .bot import ParamBot

    report = ParamBot(wiki, _options(args)).check_rules()
    for label, lines in (('SETUP  ', report.setup), ('PROBLEM', report.problems),
                         ('NOTE   ', report.notes)):
        for line in lines:
            print(label, msg.plain(line))
    return 1 if report.problems or report.setup else 0


def _scaffold(args: argparse.Namespace, wiki: Wiki) -> int:
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
    print(scaffold_next_steps(_options(args), template), file=sys.stderr)
    return 0


def scaffold_next_steps(options: Options, template: str) -> str:
    """Where a scaffolded table goes."""
    return (f'Put this table on {options.rules_page}/{template}. Then a template editor lists '
            f'it on {options.rules_page}, under "== Active ==" or "== Inactive ==", as '
            f'{{{{{options.link_rule_page}|{template}|REVISION}}}}, with the number of the '
            'revision they approve.')


if __name__ == '__main__':
    sys.exit(main())
