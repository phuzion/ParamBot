"""The settings for one run of the bot."""

from dataclasses import dataclass


@dataclass
class Options:
    bot_user: str = 'ParamBot'
    rules_page: str = ''            # default: User:<bot_user>/Rules
    rules_files: tuple[str, ...] = ()   # read the rules from these local files instead
    report_page: str = ''           # default: User:<bot_user>/Report
    run_page: str = ''              # default: User:<bot_user>/Run
    live: bool = False              # edit for real; otherwise a dry run
    trial: bool = False             # live without the bot flag, for a BRFA trial
    max_edits: int = 100
    cooldown_days: int = 30         # don't edit a page the bot edited this recently
    namespaces: tuple[int, ...] = (0,)
    templates: tuple[str, ...] = ()  # only these templates' rules
    pages: tuple[str, ...] = ()      # only these pages, instead of polling categories
    any_namespace: bool = False     # let pages be outside namespaces (dry-run previews)
    out_dir: str = 'out'            # where dry runs write their diff and report

    def __post_init__(self) -> None:
        base = f'User:{self.bot_user}'
        self.rules_page = self.rules_page or f'{base}/Rules'
        self.report_page = self.report_page or f'{base}/Report'
        self.run_page = self.run_page or f'{base}/Run'

    @property
    def user_page(self) -> str:
        return f'User:{self.bot_user}'

    @property
    def instructions_page(self) -> str:
        return f'{self.rules_page}/Instructions'

    @property
    def faq_page(self) -> str:
        """The FAQ every edit summary links to."""
        return f'User:{self.bot_user}/FAQ'

    @property
    def header_page(self) -> str:
        """The links across the top of the bot's pages, and of the report."""
        return f'User:{self.bot_user}/Header'

    @property
    def link_rule_page(self) -> str:
        """The template the rules page lists each rules page with."""
        return f'User:{self.bot_user}/LinkRule'

    @property
    def rules_source(self) -> str:
        """Where the rules come from, for messages."""
        return ', '.join(self.rules_files) or self.rules_page
