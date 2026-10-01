"""The settings for one run of the bot.

They come from the settings file (see settings), with command-line options
on top.  Anything that isn't set has the default here.
"""

from dataclasses import dataclass

# Edit protection levels on the English Wikipedia, weakest first.
PROTECTION_LEVELS = ('autoconfirmed', 'extendedconfirmed', 'templateeditor', 'sysop')


@dataclass
class Options:
    bot_user: str = 'ParamBot'
    # The bot's pages.  By default, subpages of User:<bot_user>.
    rules_page: str = ''
    report_page: str = ''
    run_page: str = ''
    instructions_page: str = ''     # default: <rules_page>/Instructions
    faq_page: str = ''              # every edit summary links to it
    header_page: str = ''           # the links across the top of the bot's pages and the report
    link_rule_page: str = ''        # the template the rules page lists each rules page with
    rules_files: tuple[str, ...] = ()   # read the rules from these local files instead
    live: bool = False              # edit for real; otherwise a dry run
    trial: bool = False             # live without the bot flag, for a BRFA trial
    # Save the report page, and never edit anything else, whatever else is
    # set: no bot flag or --trial needed, as the bot policy allows edits to
    # a bot's own userspace without approval.
    report_only: bool = False
    max_edits: int | None = None    # stop after this many edits; 0 or None: no limit
    # Stop starting new work after this many hours, so that a daily run
    # can't still be going when the next one starts.  0 or None: no limit.
    max_hours: float | None = 20
    cooldown_days: int = 30         # don't edit a page the bot edited this recently
    large_run: int = 500            # more edits than this gets a note on the report; 0: never
    failures_in_a_row: int = 5      # this many pages failing in a row stops the run
    # The rules page says which rules the bot uses, so a live run won't
    # start unless it's protected at least this much (see PROTECTION_LEVELS).
    rules_protection: str = 'templateeditor'
    namespaces: tuple[int, ...] = (0,)
    templates: tuple[str, ...] = ()  # only these templates' rules
    pages: tuple[str, ...] = ()      # only these pages, instead of polling categories
    any_namespace: bool = False     # let pages be outside namespaces (dry-run previews)
    out_dir: str = 'out'            # where dry runs write their diff and report

    def __post_init__(self) -> None:
        base = self.user_page
        self.rules_page = self.rules_page or f'{base}/Rules'
        self.report_page = self.report_page or f'{base}/Report'
        self.run_page = self.run_page or f'{base}/Run'
        self.instructions_page = self.instructions_page or f'{self.rules_page}/Instructions'
        self.faq_page = self.faq_page or f'{base}/FAQ'
        self.header_page = self.header_page or f'{base}/Header'
        self.link_rule_page = self.link_rule_page or f'{base}/LinkRule'
        if self.rules_protection not in PROTECTION_LEVELS:
            raise ValueError(f'rules_protection must be one of {", ".join(PROTECTION_LEVELS)}, '
                             f'not {self.rules_protection!r}')

    @property
    def edits_articles(self) -> bool:
        """A live run that isn't reporting only: the only kind that edits articles."""
        return self.live and not self.report_only

    @property
    def saves_report(self) -> bool:
        """Whether the run saves the report page, rather than a local file."""
        return self.live or self.report_only

    @property
    def user_page(self) -> str:
        return f'User:{self.bot_user}'

    def other_pages(self) -> dict[str, str]:
        """The bot's pages other than the report, which the report mustn't
        replace: {title: what it is}."""
        return {
            self.user_page: "the bot's user page",
            self.rules_page: 'the rules page',
            self.run_page: 'the Run page',
            self.instructions_page: 'the instructions for rule writers',
            self.faq_page: 'the FAQ',
            self.header_page: 'the header',
            self.link_rule_page: 'the LinkRule template',
        }

    @property
    def rules_source(self) -> str:
        """Where the rules come from, for messages."""
        return ', '.join(self.rules_files) or self.rules_page
