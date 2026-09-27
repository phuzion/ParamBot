"""Command line entry point.

    parambot run                  dry run against the live wiki (no edits)
    parambot run --page "User:X/sandbox" --any-namespace
                                  preview what the bot would do to a sandbox
    parambot run --live           real run (needs user-config.py and a bot account)
    parambot check-rules          load the rules and check them against the templates
    parambot scaffold TEMPLATE    print a rules table built from TEMPLATE's
                                  deprecated-parameter check, ready to paste
"""

import argparse
import logging
import os
import sys


def _build_parser():
    parser = argparse.ArgumentParser(prog='parambot', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--lang', default='en')
    parser.add_argument('--family', default='wikipedia')
    parser.add_argument('--bot-user', default='ParamBot',
                        help='bot account name; also sets the default rules/report/run pages')
    parser.add_argument('--rules-page', help='default: User:<bot-user>/Rules')
    parser.add_argument('--rules-file', help='read rules from a local file instead of the wiki')
    parser.add_argument('-v', '--verbose', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)

    run = sub.add_parser('run', help='poll the categories and fix pages')
    run.add_argument('--live', action='store_true', help='actually edit (default is a dry run)')
    run.add_argument('--trial', action='store_true',
                     help='allow --live without the bot flag, for a BRFA trial')
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
    run.add_argument('--report-page', help='default: User:<bot-user>/Report')
    run.add_argument('--run-page', help='default: User:<bot-user>/Run')
    run.add_argument('--out-dir', default='out',
                     help="where dry runs (and live runs that can't save the report) write files")

    sub.add_parser('check-rules', help="check every template's rules against the template")

    scaffold = sub.add_parser(
        'scaffold', help="print a rules table built from a template's deprecated-parameter check")
    scaffold.add_argument('template')
    scaffold.add_argument('--oldid', type=int,
                          help='read this revision of the template instead of the current one')
    return parser


def _setup_pywikibot(live, bot_user, lang, family):
    # Dry runs only read, so they work without a user-config.py.
    base = os.environ.get('PYWIKIBOT_DIR', os.getcwd())
    if not live and not os.path.exists(os.path.join(base, 'user-config.py')):
        os.environ.setdefault('PYWIKIBOT_NO_USER_CONFIG', '2')
    import pywikibot
    from pywikibot import config

    from . import __version__

    # Wikimedia throttles clients that don't say who they are.
    contact = os.environ.get('PARAMBOT_CONTACT') or \
        f'https://{lang}.{family}.org/wiki/User:{bot_user.replace(" ", "_")}'
    config.user_agent_format = (f'ParamBot/{__version__} ({contact}) '
                                '{pwb} ({revision}) {http_backend} {python}')
    return pywikibot


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    if getattr(args, 'any_namespace', False):
        if args.live:
            parser.error('--any-namespace is for dry runs only; the bot only edits articles')
        if not args.page:
            parser.error('--any-namespace needs --page: name the sandbox page to preview')
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s %(message)s')
    live = getattr(args, 'live', False)
    pywikibot = _setup_pywikibot(live, args.bot_user, args.lang, args.family)

    from .bot import Options, ParamBot, StopRun
    from .templatescan import scaffold_table

    site = pywikibot.Site(args.lang, args.family)

    if args.command == 'scaffold':
        page = pywikibot.Page(site, args.template, ns=10)
        text = page.getOldVersion(args.oldid) if args.oldid else page.text
        table, warnings = scaffold_table(page.title(with_ns=False), text)
        if table is None:
            print(f'{page.title()} has no {{{{#invoke:Check for deprecated parameters}}}} call',
                  file=sys.stderr)
            return 1
        for warning in warnings:
            print(f'Could not turn "{warning}" into a row; add rows for it by hand.',
                  file=sys.stderr)
        print(table)
        return 0

    options = Options(
        bot_user=args.bot_user,
        rules_page=args.rules_page,
        rules_file=args.rules_file,
    )
    bot = ParamBot(site, options)

    if args.command == 'check-rules':
        report = bot.check_rules()
        for line in report.setup:
            print('SETUP  ', line)
        for line in report.problems:
            print('PROBLEM', line)
        for line in report.notes:
            print('NOTE   ', line)
        return 1 if report.problems or report.setup else 0

    options.live = args.live
    options.trial = args.trial
    options.max_edits = args.max_edits
    options.cooldown_days = args.cooldown_days
    options.templates = tuple(args.template)
    options.pages = tuple(args.page)
    options.any_namespace = args.any_namespace
    options.report_page = args.report_page or options.report_page
    options.run_page = args.run_page or options.run_page
    options.out_dir = args.out_dir
    try:
        report = bot.run()
    except StopRun as e:
        logging.error('%s', e)
        return 2
    except Exception:
        return 1  # already logged, with the traceback, and put in the report
    print(report.stats_line(pywikibot.Timestamp.nowutc().strftime('%Y-%m-%d %H:%M'), args.live))
    return 0


if __name__ == '__main__':
    sys.exit(main())
