"""The bot run: poll tracking categories, fix pages, write the report."""

import difflib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import pywikibot
from pywikibot import exceptions as pwb_exc

from .fixer import fix_wikitext
from .report import Report
from .rules import parse_config
from .templatescan import known_params
from .wikitext import normalize_template_name, normalize_title, strip_comments

log = logging.getLogger('parambot')

SUMMARY_LIMIT = 450
RUN_VALUES = {'yes', 'true', 'run', 'on'}
MAX_FAILURES_IN_A_ROW = 5

# Edit protection levels on the English Wikipedia, and what they're called.
PROTECTION_NAMES = {
    'autoconfirmed': 'semi-protected',
    'extendedconfirmed': 'extended-confirmed protected',
    'templateeditor': 'template-editor protected',
    'sysop': 'fully protected',
}
# The rules page decides what the bot edits, so only people trusted to edit
# high-risk templates may change it.
RULES_PROTECTION = {'templateeditor', 'sysop'}
INDEFINITE = {'infinity', 'infinite', 'indefinite', 'never'}


@dataclass
class Options:
    bot_user: str = 'ParamBot'
    rules_page: Optional[str] = None      # default User:<bot_user>/Rules
    rules_file: Optional[str] = None      # local file instead of rules_page
    report_page: Optional[str] = None     # default User:<bot_user>/Report
    run_page: Optional[str] = None        # default User:<bot_user>/Run
    live: bool = False
    trial: bool = False                   # live without the bot flag (BRFA trial)
    max_edits: int = 100
    cooldown_days: int = 30
    namespaces: tuple = (0,)
    templates: tuple = ()                 # only these rule sets
    pages: tuple = ()                     # only these pages (skips category polling)
    any_namespace: bool = False           # dry-run previews of non-articles, e.g. sandboxes
    out_dir: str = 'out'

    def __post_init__(self):
        base = f'User:{self.bot_user}'
        self.rules_page = self.rules_page or f'{base}/Rules'
        self.report_page = self.report_page or f'{base}/Report'
        self.run_page = self.run_page or f'{base}/Run'


class StopRun(Exception):
    pass


@dataclass
class Candidate:
    page: pywikibot.Page
    rulesets: list = field(default_factory=list)


class ParamBot:
    def __init__(self, site, options):
        self.site = site
        self.options = options
        self.report = Report()
        self.diffs = []
        self._prepared = set()

    # -- entry point -----------------------------------------------------

    def run(self):
        opts = self.options
        if opts.live and opts.any_namespace:
            # Articles only, as the bot request asked; other pages are for previews.
            raise StopRun('--any-namespace is for dry runs only')
        if opts.live:
            self._check_account()
            self._check_run_page()
        setup = self._check_pages()
        if setup and opts.live:
            raise StopRun("Not running, because of problems with the bot's pages:\n- "
                          + '\n- '.join(setup))
        for problem in setup:
            log.warning('A live run would refuse to start: %s', problem)
        self.report.setup.extend(setup)
        try:
            self._run()
        except StopRun as e:
            # Someone switched the bot off, or it can't start: make no more
            # wiki edits, not even the report.
            self.report.errors.append(f'Stopped early: {e}')
            self._write_report(local_only=True)
            raise
        except Exception as e:
            log.exception('Run failed')
            self.report.errors.append(
                f'The run stopped early because of an error: {type(e).__name__}: {e}')
            self._write_report()
            raise
        self._write_report()
        return self.report

    def _run(self):
        opts = self.options
        config = self._load_config()
        self.report.problems.extend(config.problems)
        if not config.rulesets:
            raise StopRun(f'{self._rules_source()} has no rules, so there is nothing to do')
        rulesets = list(config.rulesets.values())
        if opts.templates:
            wanted = {normalize_template_name(t) for t in opts.templates}
            rulesets = [rs for rs in rulesets if rs.template in wanted]
        log.info('%d rule sets, %d rules', len(rulesets), sum(len(rs) for rs in rulesets))

        # Check every rule set on every run, so mistakes reach the report
        # before an article ever needs the rule.
        self._prepare_all(rulesets)
        rulesets = [rs for rs in rulesets if not rs.disabled]

        if opts.pages:
            candidates = {}
            for title in opts.pages:
                page = pywikibot.Page(self.site, title)
                candidates[page.title()] = Candidate(page, list(rulesets))
        else:
            candidates = self._candidates(rulesets)
        log.info('%d candidate pages', len(candidates))

        pages = [c.page for c in candidates.values()]
        self._process_all(candidates, self.site.preloadpages(pages, groupsize=50))

    def _process_all(self, candidates, pages):
        """Process preloaded pages. An error on one page is reported and the
        run moves on, unless pages keep failing, which means something
        bigger is wrong."""
        failures = 0
        for page in pages:
            if self.report.edits >= self.options.max_edits:
                self.report.notes.append(
                    f'Stopped after {self.options.max_edits} edits (--max-edits).')
                break
            cand = candidates.get(page.title())
            if cand is None:
                log.warning('Preloaded unexpected page %s', page.title())
                continue
            try:
                self._process(page, cand.rulesets)
            except StopRun:
                raise
            except Exception as e:
                log.exception('Error while processing %s', page.title())
                self._skip(page.title(), f'error: {type(e).__name__}: {e}')
                failures += 1
                if failures >= MAX_FAILURES_IN_A_ROW:
                    raise RuntimeError(
                        f'{failures} pages in a row failed; the last error was '
                        f'{type(e).__name__}: {e}') from e
            else:
                failures = 0

    # -- setup -----------------------------------------------------------

    def _check_account(self):
        self.site.login()
        user = self.site.username()
        if normalize_title(user) != normalize_title(self.options.bot_user):
            raise StopRun(f'Logged in as {user!r}, expected {self.options.bot_user!r}')
        if not self.options.trial and not self.site.has_right('bot'):
            raise StopRun(f'{user} does not have the bot right; use --trial for BRFA trial edits')

    def _check_run_page(self, before=None):
        """Stop unless the run page says yes.  Called at the start of a live
        run and again before every edit."""
        value = strip_comments(self._run_page_text()).strip().lower()
        if value not in RUN_VALUES:
            if before:
                raise StopRun(f'{self.options.run_page} no longer says "yes"; '
                              f'stopped before editing {before}')
            raise StopRun(f'{self.options.run_page} does not say "yes"; not running')

    def _run_page_text(self):
        # A new Page object each time, so the text is fetched fresh.
        page = pywikibot.Page(self.site, self.options.run_page)
        return page.text if page.exists() else ''

    def _rules_source(self):
        return self.options.rules_file or self.options.rules_page

    def _load_config(self):
        if self.options.rules_file:
            with open(self.options.rules_file, encoding='utf-8') as f:
                text = f.read()
        else:
            page = pywikibot.Page(self.site, self.options.rules_page)
            if not page.exists():
                raise StopRun(f'Rules page {self.options.rules_page} does not exist')
            text = page.text
        return parse_config(text)

    def _load_pages(self, titles):
        """Return {title: Page} for titles, loaded in one batch with their
        text, protection and templates."""
        pages = {title: pywikibot.Page(self.site, title) for title in titles}
        loaded = {p.title(): p for p in self.site.preloadpages(list(pages.values()),
                                                               templates=True)}
        return {title: loaded.get(page.title(), page) for title, page in pages.items()}

    def _check_pages(self):
        """Check the bot's own pages on the wiki.  Return the problems that
        stop a live run; add anything less serious to the report's notes."""
        opts = self.options
        user_page = f'User:{opts.bot_user}'
        instructions = f'{opts.rules_page}/Instructions'
        titles = [user_page, opts.run_page, opts.report_page, instructions]
        if not opts.rules_file:
            titles.append(opts.rules_page)
        pages = self._load_pages(titles)
        problems = []

        def usable(title, what):
            page = pages[title]
            if not page.exists():
                problems.append(f'{title} ({what}) does not exist. Create it.')
            elif page.isRedirectPage():
                problems.append(f'{title} ({what}) is a redirect. It must be the page itself.')
            elif page.content_model != 'wikitext':
                problems.append(f'{title} ({what}) must be an ordinary wikitext page, not '
                                f'{page.content_model}.')
            else:
                return page
            return None

        def edit_protection(page):
            level, expiry = page.protection().get('edit', ('', 'infinity'))
            return level, expiry

        page = usable(user_page, "the bot's user page")
        if page is not None and not any(t.title() == 'Template:Bot' for t in page.templates()):
            problems.append(f"{user_page} doesn't use {{{{bot}}}} to name the bot's operator, "
                            'which bot policy requires.')

        if not opts.rules_file:
            page = usable(opts.rules_page, 'the rules page')
            if page is not None:
                level, expiry = edit_protection(page)
                if level not in RULES_PROTECTION:
                    current = PROTECTION_NAMES.get(level, f'{level} protected') if level \
                        else 'not protected'
                    problems.append(
                        f'{opts.rules_page} (the rules page) is {current}. It decides what the '
                        'bot edits, so it must be template-editor protected or higher. Ask at '
                        'Wikipedia:Requests for page protection.')
                elif expiry not in INDEFINITE:
                    self.report.notes.append(
                        f"{opts.rules_page}'s protection expires {expiry}, and the bot won't "
                        'run after that. Ask for indefinite protection.')

        page = usable(opts.run_page, 'the Run page')
        if page is not None:
            level, _ = edit_protection(page)
            if level in RULES_PROTECTION:
                self.report.notes.append(
                    f'{opts.run_page} is {PROTECTION_NAMES[level]}, so most editors can\'t use '
                    "it to stop the bot. It's meant to be open to everyone.")

        page = usable(opts.report_page, 'the report page')
        if page is not None:
            if opts.live:
                if not page.has_permission('edit'):
                    problems.append(f'{opts.bot_user} cannot edit {opts.report_page} (the '
                                    'report page). Check its protection.')
            else:
                level, _ = edit_protection(page)
                if level in RULES_PROTECTION:
                    problems.append(
                        f'{opts.report_page} (the report page) is {PROTECTION_NAMES[level]}, so '
                        'the bot probably cannot edit it. Lower its protection.')

        if not pages[instructions].exists():
            self.report.notes.append(
                f'{instructions} (the instructions for rule writers) does not exist. Copy '
                'docs/rules-instructions.wiki there.')
        return problems

    def check_rules(self):
        """Check the bot's pages, then every rule set against its template
        and category, without looking at any articles."""
        self.report.setup.extend(self._check_pages())
        try:
            config = self._load_config()
        except StopRun as e:
            self.report.setup.append(str(e))
            return self.report
        if not config.rulesets:
            self.report.setup.append(f'{self._rules_source()} has no rules.')
        self.report.problems.extend(config.problems)
        self._prepare_all(config.rulesets.values())
        by_category = {}
        for rs in config.rulesets.values():
            if not rs.disabled:
                by_category.setdefault(rs.category, []).append(rs)
        self._category_sizes(by_category)
        return self.report

    def _category_sizes(self, by_category):
        """Return {category: number of pages}; report categories that don't
        exist."""
        sizes = {}
        titles = list(by_category)
        for i in range(0, len(titles), 50):
            batch = titles[i:i + 50]
            data = self.site.simple_request(
                action='query', prop='categoryinfo', titles='|'.join(batch)).submit()
            for info in data['query']['pages'].values():
                if 'categoryinfo' in info:
                    sizes[info['title']] = info['categoryinfo'].get('pages', 0)
                elif 'missing' in info:
                    # Hidden tracking categories are often never created, so
                    # a missing page with no members may just be empty.
                    sizes[info['title']] = 0
                    self.report.notes.append(
                        f'{info["title"]} has no page and no members. If the '
                        'template uses a different category, put a link to it in the '
                        'caption of the table for ' + ', '.join(
                            rs.template for rs in by_category.get(info['title'], [])))
        return sizes

    def _candidates(self, rulesets):
        by_category = {}
        for rs in rulesets:
            by_category.setdefault(rs.category, []).append(rs)
        self.report.categories_polled = len(by_category)
        sizes = self._category_sizes(by_category)

        candidates = {}
        for category, sets in by_category.items():
            if not sizes.get(category):
                continue
            self.report.categories_populated += 1
            log.info('%s: %d pages', category, sizes[category])
            cat = pywikibot.Category(self.site, category)
            for page in cat.members(namespaces=list(self.options.namespaces)):
                cand = candidates.setdefault(page.title(), Candidate(page))
                cand.rulesets.extend(sets)
        return candidates

    def _prepare_all(self, rulesets):
        """Prepare rule sets, loading the templates' text in batches."""
        rulesets = [rs for rs in rulesets if id(rs) not in self._prepared]
        pages = [pywikibot.Page(self.site, rs.template, ns=10) for rs in rulesets]
        loaded = {p.title(with_ns=False): p
                  for p in self.site.preloadpages(pages, groupsize=50)}
        for rs, page in zip(rulesets, pages):
            self._prepare(rs, loaded.get(page.title(with_ns=False), page))

    def _prepare(self, rs, tpage=None):
        """Look up the template's redirects and parameter whitelist, and
        report rules that can't work."""
        if id(rs) in self._prepared:
            return
        self._prepared.add(id(rs))
        tpage = tpage or pywikibot.Page(self.site, rs.template, ns=10)
        if not tpage.exists():
            self.report.problems.append(
                f'Template:{rs.template} does not exist, so its rules are switched off. '
                "Check the spelling in the table's caption.")
            rs.disabled = True
            return
        if tpage.isRedirectPage():
            tpage = tpage.getRedirectTarget()
            rs.names.add(normalize_template_name(tpage.title(with_ns=False)))
        for redirect in tpage.redirects(namespaces=[10]):
            rs.names.add(normalize_template_name(redirect.title(with_ns=False)))
        rs.known = known_params(tpage.text)
        if rs.known is None:
            # Without the whitelist a backwards rule (new = old) would break
            # every page it touched, so don't guess.
            self.report.problems.append(
                f'Template:{rs.template} has no list of accepted parameters the bot can '
                'read (a {{#invoke:Check for unknown parameters|check|...}} call), so '
                'its rules are switched off.')
            rs.disabled = True
            return
        waiting = [name for name in (*rs.renames, *rs.removes) if name in rs.known]
        if waiting:
            self.report.notes.append(
                f'{rs.template}: {len(waiting)} rule(s) wait because the template still '
                f'accepts the old name ({", ".join(waiting)}). That is normal: they start '
                'working once the template drops those names. If a rule is backwards, '
                'swap its names.')
        for rule in rs.renames.values():
            if rule.new not in rs.known:
                self.report.problems.append(
                    f'{rs.template}: the rule "{rule.old} = {rule.new}" renames to a '
                    f'parameter the template does not accept. Check the spelling of '
                    f'"{rule.new}".')

    # -- per page --------------------------------------------------------

    def _skip(self, title, reason):
        log.info('Not editing %s: %s', title, reason)
        self.report.skip(title, reason)

    def _process(self, page, rulesets):
        title = page.title()
        if not page.exists():
            self._skip(title, 'page does not exist')
            return
        if page.isRedirectPage():
            self._skip(title, 'page is a redirect')
            return
        if not self.options.any_namespace and page.namespace() not in self.options.namespaces:
            self._skip(title, 'not an article; use --any-namespace to preview it in a dry run')
            return
        self.report.pages_checked += 1
        result = fix_wikitext(page.text, rulesets)
        for issue in result.issues:
            self.report.issue(title, issue)
        if not result.substantive:
            if self.options.pages:
                log.info('%s: nothing to fix', title)
            return
        if not page.botMayEdit():
            self._skip(title, 'excluded by {{bots}}/{{nobots}}')
            return
        recent = self._recent_bot_edit(page)
        if recent is not None:
            self._skip(
                title, f'{self.options.bot_user} already edited this page on {recent:%Y-%m-%d}; '
                'not repeating a fix within the cooldown in case it was reverted on purpose')
            return

        summary = self._summary(result)
        if not self.options.live:
            self._record_diff(title, page.text, result.text, summary)
            self.report.edits += 1
            return
        self._check_run_page(before=title)
        page.text = result.text
        try:
            page.save(summary=summary, minor=False, bot=True, quiet=True)
        except pwb_exc.EditConflictError:
            self._skip(title, 'edit conflict; will be retried on the next run')
        except pwb_exc.LockedPageError:
            self._skip(title, 'page is protected')
        except pwb_exc.PageSaveRelatedError as e:
            self._skip(title, f'save failed: {e}')
        else:
            self.report.edits += 1
            log.info('Saved %s', title)

    def _recent_bot_edit(self, page):
        days = self.options.cooldown_days
        if not days:
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        bot = normalize_title(self.options.bot_user)
        for rev in page.revisions(total=50):
            when = rev.timestamp
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when < cutoff:
                break
            if rev.user and normalize_title(rev.user) == bot:
                return when
        return None

    def _summary(self, result):
        parts = []
        for template in result.templates():
            descs = []
            for c in result.changes:
                if c.template == template and c.describe() not in descs:
                    descs.append(c.describe())
            parts.append(f'[[Template:{template}|{template}]]: {", ".join(descs)}')
        text = ('Fixing deprecated parameters restored in ' + '; '.join(parts))
        if len(text) > SUMMARY_LIMIT:
            text = text[:SUMMARY_LIMIT - 1].rstrip() + '…'
        return f'{text} ([[{self.options.rules_page}|rules]])'

    def _record_diff(self, title, old, new, summary):
        diff = difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f'{title} (current)', tofile=f'{title} (proposed)', n=2)
        self.diffs.append(f'### {title}\n# Summary: {summary}\n{"".join(diff)}\n')

    # -- report ----------------------------------------------------------

    def _write_report(self, local_only=False):
        """Save the report page on live runs, or write it to out_dir on dry
        runs, when local_only is set, or when saving fails."""
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
        text = self.report.render(timestamp, self.options.live)
        if self.options.live and not local_only:
            try:
                self._save_report_page(text)
                return
            except Exception:
                log.exception('Could not save %s; writing the report locally instead',
                              self.options.report_page)
        os.makedirs(self.options.out_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        report_path = os.path.join(self.options.out_dir, f'report-{stamp}.wiki')
        diff_path = os.path.join(self.options.out_dir, f'edits-{stamp}.diff')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(text)
        with open(diff_path, 'w', encoding='utf-8') as f:
            f.write(''.join(self.diffs))
        log.info('Wrote %s and %s', report_path, diff_path)

    def _save_report_page(self, text):
        page = pywikibot.Page(self.site, self.options.report_page)
        if page.exists() and Report.body_of(page.text) == self.report.body():
            return
        page.text = text
        page.save(summary=f'Updating report: {self.report.edits} edits, '
                          f'{len(self.report.issues)} pages need review',
                  minor=True, bot=True, quiet=True)
