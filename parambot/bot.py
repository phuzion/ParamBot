"""A run of the bot: poll the tracking categories, fix pages, write the report."""

import difflib
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pywikibot import exceptions as pwb_exc

from . import messages as msg
from .botpages import check_bot_pages
from .fixer import FixResult, TemplateRules, fix_wikitext
from .options import Options
from .prepare import prepare
from .report import Report
from .rules import Config, parse_config
from .wiki import Wiki, WikiPage
from .wikitext import normalize_template_name, normalize_title, strip_comments

log = logging.getLogger('parambot')

SUMMARY_LIMIT = 450
RUN_VALUES = {'yes', 'true', 'run', 'on'}
MAX_FAILURES_IN_A_ROW = 5
HISTORY_LIMIT = 50  # revisions to look through for the bot's last edit


class StopRun(Exception):
    """The bot mustn't run, or must stop: the message says why."""


@dataclass
class Candidate:
    """A page to check, and the rules that apply to it."""

    page: WikiPage
    targets: list[TemplateRules] = field(default_factory=list)


class ParamBot:
    def __init__(self, wiki: Wiki, options: Options) -> None:
        self.wiki = wiki
        self.options = options
        self.report = Report()
        self.diffs: list[str] = []

    # -- a run -------------------------------------------------------------

    def run(self) -> Report:
        """Do a run.  Raises StopRun if the bot mustn't run or was stopped."""
        self._preflight()
        try:
            self._run()
        except StopRun as stop:
            # Someone switched the bot off, or it can't start: make no more
            # wiki edits, not even the report.
            self.report.errors.append(msg.stopped_early(stop))
            self._write_report(local_only=True)
            raise
        except Exception as error:
            log.exception('Run failed')
            self.report.errors.append(msg.run_failed(error))
            self._write_report()
            raise
        self._write_report()
        return self.report

    def check_rules(self) -> Report:
        """Check the bot's pages, then every rule set against its template
        and category, without looking at any articles."""
        self.report.setup.extend(self._check_pages())
        try:
            config = self._load_config()
        except StopRun as stop:
            self.report.setup.append(str(stop))
            return self.report
        if not config.rulesets:
            self.report.setup.append(f'{self.options.rules_source} has no rules.')
        self.report.problems.extend(config.problems)
        prepared = prepare(self.wiki, config.rulesets.values(), self.report)
        self._category_sizes(_by_category(prepared.ready), prepared.wrong_category)
        return self.report

    def _preflight(self) -> None:
        options = self.options
        if options.live and options.any_namespace:
            # Articles only, as the bot request asked; other pages are for previews.
            raise StopRun(msg.ANY_NAMESPACE_LIVE)
        if options.live:
            self._check_account()
            self._check_run_page()
        problems = self._check_pages()
        if problems and options.live:
            raise StopRun(msg.pages_not_ready(problems))
        for problem in problems:
            log.warning('A live run would refuse to start: %s', problem)
        self.report.setup.extend(problems)

    def _run(self) -> None:
        config = self._load_config()
        self.report.problems.extend(config.problems)
        if not config.rulesets:
            raise StopRun(msg.no_rules(self.options.rules_source))
        rulesets = list(config.rulesets.values())
        if self.options.templates:
            wanted = {normalize_template_name(t) for t in self.options.templates}
            rulesets = [ruleset for ruleset in rulesets if ruleset.template in wanted]
        log.info('%d rule sets, %d rules', len(rulesets), sum(map(len, rulesets)))

        # Check every rule set on every run, so mistakes reach the report
        # before an article ever needs the rule.
        prepared = prepare(self.wiki, rulesets, self.report)
        if self.options.pages:
            candidates = {}
            for title in self.options.pages:
                page = self.wiki.page(title)
                candidates[page.title()] = Candidate(page, list(prepared.ready))
        else:
            candidates = self._candidates(prepared.ready, prepared.wrong_category)
        log.info('%d candidate pages', len(candidates))
        self._process_all(candidates, self.wiki.load(c.page for c in candidates.values()))

    # -- setup -------------------------------------------------------------

    def _check_account(self) -> None:
        user = self.wiki.login()
        if normalize_title(user) != normalize_title(self.options.bot_user):
            raise StopRun(msg.wrong_account(user, self.options.bot_user))
        if not self.options.trial and not self.wiki.has_right('bot'):
            raise StopRun(msg.no_bot_right(user))

    def _check_run_page(self, before: str | None = None) -> None:
        """Stop unless the Run page says yes.  Called at the start of a live
        run and again before every edit, with the page about to be edited."""
        page = self.wiki.page(self.options.run_page)  # a new object, so fetched fresh
        text = page.text if page.exists() else ''
        if strip_comments(text).strip().lower() not in RUN_VALUES:
            raise StopRun(msg.run_page_off(self.options.run_page, before))

    def _check_pages(self) -> list[str]:
        """Problems with the bot's own pages; notes go straight on the report."""
        check = check_bot_pages(self.wiki, self.options)
        self.report.notes.extend(check.notes)
        return check.problems

    def _load_config(self) -> Config:
        if self.options.rules_file:
            with open(self.options.rules_file, encoding='utf-8') as f:
                return parse_config(f.read())
        page = self.wiki.page(self.options.rules_page)
        if not page.exists():
            raise StopRun(msg.rules_page_missing(self.options.rules_page))
        return parse_config(page.text)

    # -- finding pages -----------------------------------------------------

    def _candidates(self, targets: list[TemplateRules], explained: set[str]
                    ) -> dict[str, Candidate]:
        """The pages in each populated category, with the rules for them."""
        by_category = _by_category(targets)
        self.report.categories_polled = len(by_category)
        sizes = self._category_sizes(by_category, explained)
        candidates: dict[str, Candidate] = {}
        for category, category_targets in by_category.items():
            if not sizes.get(category):
                continue
            self.report.categories_populated += 1
            log.info('%s: %d pages', category, sizes[category])
            for page in self.wiki.category_members(category, self.options.namespaces):
                candidate = candidates.setdefault(page.title(), Candidate(page))
                candidate.targets.extend(category_targets)
        return candidates

    def _category_sizes(self, by_category: dict[str, list[TemplateRules]],
                        explained: set[str]) -> dict[str, int]:
        """The number of pages in each category.  Notes categories that don't
        exist, unless the report already explains why (explained holds the
        templates whose table watches the wrong category)."""
        sizes = self.wiki.category_sizes(list(by_category))
        for category, size in sizes.items():
            if size is None:
                # Hidden tracking categories are often never created, so a
                # missing category may just be empty.
                unexplained = [t.template for t in by_category.get(category, [])
                               if t.template not in explained]
                if unexplained:
                    self.report.notes.append(msg.category_missing(category, unexplained))
        return {category: size or 0 for category, size in sizes.items()}

    # -- fixing pages ------------------------------------------------------

    def _process_all(self, candidates: dict[str, Candidate], pages: Iterable[WikiPage]
                     ) -> None:
        """Process loaded pages.  An error on one page is reported and the run
        moves on, unless pages keep failing, which means something bigger is
        wrong."""
        failures = 0
        for page in pages:
            if self.report.edits >= self.options.max_edits:
                self.report.notes.append(msg.stopped_at_max_edits(self.options.max_edits))
                break
            candidate = candidates.get(page.title())
            if candidate is None:
                log.warning('Loaded unexpected page %s', page.title())
                continue
            try:
                self._process(page, candidate.targets)
            except StopRun:
                raise
            except Exception as error:
                log.exception('Error while processing %s', page.title())
                self._skip(page.title(), msg.skip_error(error))
                failures += 1
                if failures >= MAX_FAILURES_IN_A_ROW:
                    raise RuntimeError(msg.too_many_failures(failures, error)) from error
            else:
                failures = 0

    def _process(self, page: WikiPage, targets: list[TemplateRules]) -> None:
        title = page.title()
        reason = self._not_checkable(page)
        if reason:
            self._skip(title, reason)
            return
        self.report.pages_checked += 1
        result = fix_wikitext(page.text, targets)
        for issue in result.issues:
            self.report.issue(title, issue)
        if not result.substantive:
            if self.options.pages:
                log.info('%s: nothing to fix', title)
            return
        reason = self._not_editable(page)
        if reason:
            self._skip(title, reason)
        elif self.options.live:
            self._save(page, result)
        else:
            summary = edit_summary(result, self.options.rules_page)
            self._record_diff(title, page.text, result.text, summary)
            self.report.edits += 1

    def _not_checkable(self, page: WikiPage) -> str | None:
        """Why the bot won't even look at a page, if it won't."""
        if not page.exists():
            return msg.SKIP_MISSING
        if page.isRedirectPage():
            return msg.SKIP_REDIRECT
        if not self.options.any_namespace and page.namespace() not in self.options.namespaces:
            return msg.SKIP_NOT_ARTICLE
        return None

    def _not_editable(self, page: WikiPage) -> str | None:
        """Why the bot won't edit a page it could fix, if it won't."""
        if not page.botMayEdit():
            return msg.SKIP_EXCLUDED
        recent = self._recent_bot_edit(page)
        if recent is not None:
            return msg.skip_recently_edited(self.options.bot_user, recent)
        return None

    def _save(self, page: WikiPage, result: FixResult) -> None:
        title = page.title()
        self._check_run_page(before=title)
        page.text = result.text
        try:
            summary = edit_summary(result, self.options.rules_page)
            page.save(summary=summary, minor=False, bot=True, quiet=True)
        except pwb_exc.EditConflictError:
            self._skip(title, msg.SKIP_EDIT_CONFLICT)
        except pwb_exc.LockedPageError:
            self._skip(title, msg.SKIP_PROTECTED)
        except pwb_exc.PageSaveRelatedError as error:
            self._skip(title, msg.skip_save_failed(error))
        else:
            self.report.edits += 1
            log.info('Saved %s', title)

    def _skip(self, title: str, reason: str) -> None:
        log.info('Not editing %s: %s', title, reason)
        self.report.skip(title, reason)

    def _recent_bot_edit(self, page: WikiPage) -> datetime | None:
        """When the bot last edited the page, if it did within the cooldown."""
        if not self.options.cooldown_days:
            return None
        cutoff = datetime.now(UTC) - timedelta(days=self.options.cooldown_days)
        bot = normalize_title(self.options.bot_user)
        for revision in page.revisions(total=HISTORY_LIMIT):
            when = revision.timestamp
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            if when < cutoff:
                break
            if revision.user and normalize_title(revision.user) == bot:
                return when
        return None

    def _record_diff(self, title: str, old: str, new: str, summary: str) -> None:
        diff = difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f'{title} (current)', tofile=f'{title} (proposed)', n=2)
        self.diffs.append(f'### {title}\n# Summary: {summary}\n{"".join(diff)}\n')

    # -- the report --------------------------------------------------------

    def _write_report(self, local_only: bool = False) -> None:
        """Save the report page on live runs.  Write it to out_dir instead on
        dry runs, when local_only is set, or when saving fails."""
        timestamp = datetime.now(UTC).strftime('%Y-%m-%d %H:%M')
        text = self.report.render(timestamp, self.options.live)
        if self.options.live and not local_only:
            try:
                self._save_report_page(text)
                return
            except Exception:
                log.exception('Could not save %s; writing the report locally instead',
                              self.options.report_page)
        os.makedirs(self.options.out_dir, exist_ok=True)
        stamp = datetime.now(UTC).strftime('%Y%m%d-%H%M%S')
        report_path = os.path.join(self.options.out_dir, f'report-{stamp}.mediawiki')
        diff_path = os.path.join(self.options.out_dir, f'edits-{stamp}.diff')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(text)
        with open(diff_path, 'w', encoding='utf-8') as f:
            f.write(''.join(self.diffs))
        log.info('Wrote %s and %s', report_path, diff_path)

    def _save_report_page(self, text: str) -> None:
        page = self.wiki.page(self.options.report_page)
        if page.exists() and Report.body_of(page.text) == self.report.body():
            return
        page.text = text
        page.save(summary=msg.report_summary(self.report.edits, len(self.report.issues)),
                  minor=True, bot=True, quiet=True)


def edit_summary(result: FixResult, rules_page: str) -> str:
    """The summary for an edit: each template's changes, then a link to the rules."""
    parts = []
    for template in result.templates():
        descriptions: list[str] = []
        for change in result.changes:
            if change.template == template and change.describe() not in descriptions:
                descriptions.append(change.describe())
        parts.append(f'[[Template:{template}|{template}]]: {", ".join(descriptions)}')
    return msg.edit_summary(parts, rules_page, SUMMARY_LIMIT)


def _by_category(targets: list[TemplateRules]) -> dict[str, list[TemplateRules]]:
    by_category: dict[str, list[TemplateRules]] = {}
    for target in targets:
        by_category.setdefault(target.rules.category, []).append(target)
    return by_category
