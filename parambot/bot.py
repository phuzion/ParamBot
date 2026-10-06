"""A run of the bot: poll the tracking categories, fix pages, write the report."""

import difflib
import logging
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from pywikibot import exceptions as pwb_exc

from . import commit
from . import messages as msg
from .botpages import check_bot_pages
from .fixer import FixResult, TemplateRules, fix_wikitext
from .options import Options
from .prepare import Prepared, prepare
from .report import Links, Report
from .rules import Config, RuleSet
from .rulespages import read_rules_files, read_rules_pages, template_for
from .wiki import Wiki, WikiPage
from .wikitext import normalize_template_name, normalize_title, strip_comments

log = logging.getLogger('parambot')

SUMMARY_LIMIT = 500  # characters; MediaWiki cuts longer summaries
RUN_VALUES = {'yes', 'true', 'run', 'on'}
REPORT_VALUES = {'report'}   # lets a report-only run go ahead, but nothing else
_clock = time.monotonic   # seconds; tests replace it


def _now() -> datetime:
    """The time, for the report's start and end times; tests replace it."""
    return datetime.now(UTC)


class StopRun(Exception):
    """The bot mustn't run, or must stop: the message says why."""


# The wiki's error codes for a save that fails in a way every other save in
# the run would too: going on would only fail page after page.
CANNOT_EDIT_CODES = frozenset({'session-page-restricted', 'blocked', 'autoblocked',
                               'readonly'})


class CannotEdit(Exception):
    """A save failed in a way every other save would too: the message says
    why.  An error in the run, so the report says so and the operators get
    an email."""


@dataclass
class Candidate:
    """A page to check, and the rules that apply to it."""

    page: WikiPage
    targets: list[TemplateRules] = field(default_factory=list)


class ParamBot:
    def __init__(self, wiki: Wiki, options: Options) -> None:
        self.wiki = wiki
        self.options = options
        self.report = Report(header=options.header_page, commit=commit() or '', links=Links(
            index=options.rules_page, other=(msg.PROTECTION_REQUESTS, msg.UNKNOWN_CHECK)))
        self.diffs: list[str] = []
        self._recent_edits: dict[str, datetime] | None = None   # {title: when the bot edited it}
        self._started = _clock()
        self._trial_made: int | None = None   # edits made in a BRFA trial, if there is one

    # -- a run -------------------------------------------------------------

    def run(self) -> Report:
        """Do a run.  Raises StopRun if the bot mustn't run or was stopped."""
        self.report.started = _now()
        self._start_trial()
        self._preflight()
        try:
            self._run()
        except StopRun as stop:
            # Someone switched the bot off, or it can't start: make no more
            # wiki edits, not even the report.
            self.report.errors.append(msg.stopped_early(stop))
            self._write_report(local_only=True)
            raise
        except CannotEdit as stop:
            log.error('%s', msg.plain(str(stop)))
            self.report.errors.append(str(stop))
            self._write_report()
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
            rulesets = self._rulesets()
        except StopRun as stop:
            self.report.setup.append(str(stop))
            return self.report
        prepared = prepare(self.wiki, rulesets, self.report)
        self._category_sizes(_by_category(prepared.ready), prepared.wrong_category)
        return self.report

    def _start_trial(self) -> None:
        """In a BRFA trial, find out how many of its edits have been made.
        Once they all have, carry on reporting only.  Without a count it can
        read, stop before doing anything: a count that's gone missing, or
        that's in the wrong place, could take the trial over its limit."""
        options = self.options
        if not options.trial_edits:
            return
        path = os.path.abspath(options.trial_count_file)
        log.info('BRFA trial: its count of edits is in %s', path)
        try:
            self._trial_made = read_trial_count(path)
        except FileNotFoundError as error:
            raise StopRun(msg.trial_count_missing(path)) from error
        except (OSError, ValueError) as error:
            raise StopRun(msg.trial_count_unreadable(path, error)) from error
        if options.edits_articles and self._trial_made >= options.trial_edits:
            self.options = replace(options, report_only=True)
            self.report.notes.append(msg.trial_done(options.trial_edits))

    def _trial_full(self) -> bool:
        """Whether a run that edits articles has made all the trial's edits."""
        return (self.options.edits_articles and self._trial_made is not None
                and self._trial_made >= self.options.trial_edits)

    def _count_trial_edit(self) -> None:
        """Count an edit towards the trial, at once: a run cut off halfway
        mustn't lose count."""
        if self._trial_made is None:
            return
        self._trial_made += 1
        try:
            write_trial_count(self.options.trial_count_file, self._trial_made)
        except OSError as error:
            # Without the count, a later run could go over the trial's limit.
            raise StopRun(msg.trial_count_unsaved(self.options.trial_count_file, error)) \
                from error

    def _preflight(self) -> None:
        options = self.options
        if options.report_only:
            self._check_report_only()
        elif options.live and options.any_namespace:
            # Articles only, as the bot request asked; other pages are for previews.
            raise StopRun(msg.ANY_NAMESPACE_LIVE)
        if options.saves_report:
            self._check_report_page()
            self._check_account()
            self._check_run_page()
        problems = self._check_pages()
        # A report-only run carries on, to put the problems on the report.
        if problems and options.edits_articles:
            raise StopRun(msg.pages_not_ready(problems))
        for problem in problems:
            log.warning('A live run would refuse to start: %s', msg.plain(problem))
        self.report.setup.extend(problems)

    def _run(self) -> None:
        rulesets = self._rulesets()
        log.info('%d rule sets (%d inactive), %d rules', len(rulesets),
                 sum(not ruleset.active for ruleset in rulesets), sum(map(len, rulesets)))

        # Check every rule set on every run, inactive ones included, so
        # mistakes reach the report before an article ever needs the rule.
        prepared = prepare(self.wiki, rulesets, self.report)
        active = [target for target in prepared.ready if target.rules.active]
        if self.options.pages:
            candidates = {}
            for title in self.options.pages:
                page = self.wiki.page(title)
                candidates[page.title()] = Candidate(page, list(active))
        else:
            candidates = self._candidates(active, prepared)
        log.info('%d candidate pages', len(candidates))
        # With the templates each page uses, which {{bots}} and {{nobots}}
        # are checked against: otherwise that's a request for each page.
        self._process_all(candidates, self.wiki.load((c.page for c in candidates.values()),
                                                     templates=True))

    # -- setup -------------------------------------------------------------

    def _check_report_only(self) -> None:
        """A report-only run saves the report everyone reads, so it has to
        be a full run, and put the report where it belongs."""
        options = self.options
        partial = [setting for setting, used in (
            ('--page', options.pages), ('--template', options.templates),
            ('--any-namespace', options.any_namespace), ('--rules-file', options.rules_files))
            if used]
        if partial:
            raise StopRun(msg.report_only_partial(partial))

    def _check_report_page(self) -> None:
        """Each run replaces the report page, so it mustn't be one of the
        bot's other pages.  Reporting only, it must be in the bot's own
        userspace, too: the only place it may edit without approval."""
        options = self.options
        report = normalize_title(options.report_page)
        rules_pages = normalize_title(options.rules_page) + '/'
        for title, what in options.other_pages().items():
            if normalize_title(title) == report:
                raise StopRun(msg.report_page_taken(options.report_page, what))
        if report.startswith(rules_pages):
            raise StopRun(msg.report_page_taken(options.report_page, 'a rules page'))
        if options.report_only and not self._in_own_userspace(report):
            raise StopRun(msg.report_only_elsewhere(options.report_page, options.user_page))

    def _in_own_userspace(self, title: str) -> bool:
        return normalize_title(title).startswith(normalize_title(self.options.user_page) + '/')

    def _check_account(self) -> None:
        user = self.wiki.login()
        if normalize_title(user) != normalize_title(self.options.bot_user):
            raise StopRun(msg.wrong_account(user, self.options.bot_user))
        # Reporting only needs no bot flag: it edits only the bot's own page.
        if self.options.edits_articles and not self.options.trial \
                and not self.wiki.has_right('bot'):
            raise StopRun(msg.no_bot_right(user))

    def _check_run_page(self, before: str | None = None) -> None:
        """Stop unless the Run page says yes, or, reporting only, "report".
        Called at the start of a run that saves anything, and again before
        every edit, with the page about to be edited."""
        page = self.wiki.page(self.options.run_page)  # a new object, so fetched fresh
        text = strip_comments(page.text if page.exists() else '').strip().lower()
        allowed = RUN_VALUES | REPORT_VALUES if self.options.report_only else RUN_VALUES
        if text not in allowed:
            raise StopRun(msg.run_page_off(self.options.run_page, before,
                                           self.options.report_only))

    def _check_may_save(self, title: str) -> None:
        """The last check before anything is saved.  Reporting only, nothing
        but the report page in the bot's own userspace, whatever else the run
        was told."""
        options = self.options
        if options.report_only and (
                normalize_title(title) != normalize_title(options.report_page)
                or not self._in_own_userspace(title)):
            raise RuntimeError(msg.report_only_refused_save(title, options.report_page))

    def _check_pages(self) -> list[str]:
        """Problems with the bot's own pages; notes go straight on the report."""
        check = check_bot_pages(self.wiki, self.options)
        self.report.notes.extend(check.notes)
        return check.problems

    def _rulesets(self) -> list[RuleSet]:
        """The rule sets to check, active and inactive, with the rules pages'
        problems put on the report."""
        config = self._load_config()
        self.report.links.rules_pages = {
            template_for(title, self.options.rules_page): title
            for title in (*config.pages, *config.unlisted)}
        self.report.problems.extend(config.problems)
        self.report.notes.extend(config.notes)
        if not config.rulesets:
            self.report.problems.append(msg.no_rules(self.options.rules_source))
        rulesets = list(config.rulesets.values())
        if self.options.templates:
            wanted = {normalize_template_name(t) for t in self.options.templates}
            rulesets = [ruleset for ruleset in rulesets if ruleset.template in wanted]
        inactive = [ruleset.template for ruleset in rulesets if not ruleset.active]
        if inactive:
            self.report.notes.append(msg.inactive_rules(inactive))
        return rulesets

    def _load_config(self) -> Config:
        if self.options.rules_files:
            return read_rules_files(self.options.rules_files)
        index = self.wiki.page(self.options.rules_page)
        if not index.exists():
            raise StopRun(msg.rules_page_missing(self.options.rules_page))
        return read_rules_pages(self.wiki, index, self.options)

    # -- finding pages -----------------------------------------------------

    def _candidates(self, active: list[TemplateRules], prepared: Prepared
                    ) -> dict[str, Candidate]:
        """The pages in each populated category, with the active rules for them."""
        # Every usable rule set's category is looked up, so a missing one is
        # noted even for inactive rules, but only active ones are used.
        sizes = self._category_sizes(_by_category(prepared.ready), prepared.wrong_category)
        by_category = _by_category(active)
        self.report.categories_polled = len(by_category)
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
            if self._trial_full():
                self.report.notes.append(msg.stopped_at_trial_limit(self.options.trial_edits))
                break
            if self.options.max_edits and self.report.edits >= self.options.max_edits:
                self.report.notes.append(msg.stopped_at_max_edits(self.options.max_edits))
                break
            if self._out_of_time():
                self.report.notes.append(msg.stopped_at_max_hours(self.options.max_hours or 0))
                break
            candidate = candidates.get(page.title())
            if candidate is None:
                log.warning('Loaded unexpected page %s', page.title())
                continue
            try:
                self._process(page, candidate.targets)
            except (StopRun, CannotEdit):
                raise
            except Exception as error:
                log.exception('Error while processing %s', page.title())
                self._skip(page.title(), msg.skip_error(error))
                failures += 1
                if failures >= self.options.failures_in_a_row:
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
        summary = edit_summary(result, self._rules_link(result, targets), self.options.faq_page,
                               self.options.brfa_page if self.options.in_trial else None)
        if reason:
            self._skip(title, reason)
        elif self.options.edits_articles:
            self._save(page, result, summary)
        else:
            self._record_diff(title, page.text, result.text, summary)
            self.report.edits += 1

    def _out_of_time(self) -> bool:
        """Whether the run has used up its max_hours."""
        hours = self.options.max_hours
        if not hours:
            return False
        return (_clock() - self._started) / 3600 >= hours

    def _rules_link(self, result: FixResult, targets: list[TemplateRules]) -> str:
        """What an edit summary links to: the approved revision of the rules
        page that made the changes, so readers see exactly the rules used, or
        the index if they came from more than one page."""
        used = set(result.templates())
        revisions = {target.rules.revision for target in targets if target.template in used}
        revision = revisions.pop() if len(revisions) == 1 else None
        return f'Special:Permalink/{revision}' if revision else self.options.rules_page

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

    def _save(self, page: WikiPage, result: FixResult, summary: str) -> None:
        title = page.title()
        self._check_may_save(title)
        self._check_run_page(before=title)
        page.text = result.text
        try:
            # Pywikibot tells the wiki to recreate a page deleted since it was
            # loaded, unless it's told not to.  The bot must never create one.
            page.save(summary=summary, minor=False, bot=True, quiet=True, nocreate=True)
        except pwb_exc.NoCreateError:
            self._skip(title, msg.SKIP_DELETED)
        except pwb_exc.EditConflictError:
            self._skip(title, msg.SKIP_EDIT_CONFLICT)
        except pwb_exc.LockedPageError:
            self._skip(title, msg.SKIP_PROTECTED)
        except pwb_exc.PageSaveRelatedError as error:
            # Pywikibot passes on an error it has no name for as the API's.
            error_code = getattr(getattr(error, 'reason', None), 'code', None)
            if error_code in CANNOT_EDIT_CODES:
                raise CannotEdit(msg.cannot_edit(error_code, title, self.options.bot_user)) \
                    from error
            self._skip(title, msg.skip_save_failed(error))
        else:
            self.report.edits += 1
            log.info('Saved %s', title)
            self._count_trial_edit()

    def _skip(self, title: str, reason: str) -> None:
        log.info('Not editing %s: %s', title, msg.plain(reason))
        self.report.skip(title, reason)

    def _recent_bot_edit(self, page: WikiPage) -> datetime | None:
        """When the bot last edited the page, if it did within the cooldown."""
        if not self.options.cooldown_days:
            return None
        if self._recent_edits is None:
            # One look at the bot's own edits, not at every page's history:
            # a request per page gets the bot rate-limited once there are
            # hundreds of pages.
            since = datetime.now(UTC) - timedelta(days=self.options.cooldown_days)
            self._recent_edits = self.wiki.recent_edits(self.options.bot_user, since)
        return self._recent_edits.get(page.title())

    def _record_diff(self, title: str, old: str, new: str, summary: str) -> None:
        diff = difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f'{title} (current)', tofile=f'{title} (proposed)', n=2)
        self.diffs.append(f'### {title}\n# Summary: {summary}\n{"".join(diff)}\n')

    # -- the report --------------------------------------------------------

    def _write_report(self, local_only: bool = False) -> None:
        """Save the report page on live and report-only runs.  Write it to
        out_dir instead on dry runs, when local_only is set, or when saving
        fails.  The edits a run would have made go there too."""
        options = self.options
        if options.large_run and self.report.edits > options.large_run:
            self.report.notes.append(msg.large_run(self.report.edits, options.large_run,
                                                   options.edits_articles))
        if self._trial_made is not None:
            self.report.notes.append(msg.trial_progress(self._trial_made, options.trial_edits))
        self.report.ended = _now()
        text = self.report.render(options.live, options.report_only)
        saved = False
        if options.saves_report and not local_only:
            try:
                self._save_report_page(text)
                saved = True
            except StopRun as stop:
                log.warning('Not saving %s: %s', options.report_page, msg.plain(str(stop)))
            except Exception:
                log.exception('Could not save %s; writing the report locally instead',
                              options.report_page)
        if saved and options.edits_articles:
            return
        os.makedirs(options.out_dir, exist_ok=True)
        stamp = datetime.now(UTC).strftime('%Y%m%d-%H%M%S')
        paths = []
        if not saved:
            paths.append(os.path.join(options.out_dir, f'report-{stamp}.mediawiki'))
            with open(paths[-1], 'w', encoding='utf-8') as f:
                f.write(text)
        paths.append(os.path.join(options.out_dir, f'edits-{stamp}.diff'))
        with open(paths[-1], 'w', encoding='utf-8') as f:
            f.write(''.join(self.diffs))
        log.info('Wrote %s', ' and '.join(paths))

    def _save_report_page(self, text: str) -> None:
        # Saved on every run, so that its first line always gives the
        # latest run's times, and its history is a log of the runs.
        page = self.wiki.page(self.options.report_page)
        self._check_may_save(page.title())
        if self.options.report_only:
            # Still switched on?  A live run checks before every edit instead.
            self._check_run_page(before=page.title())
        page.text = text
        page.save(summary=msg.report_summary(self.report.edits, len(self.report.issues),
                                             self.options.report_only),
                  minor=True, bot=self.wiki.has_right('bot'), quiet=True, nocreate=True)


def edit_summary(result: FixResult, rules_page: str, faq_page: str,
                 brfa: str | None = None) -> str:
    """The summary for an edit: each template's changes, then links to the
    rules and the FAQ.  During a BRFA trial, brfa is the request, which the
    summary links to first."""
    parts = []
    for template in result.templates():
        descriptions: list[str] = []
        for change in result.changes:
            if change.template == template and change.describe() not in descriptions:
                descriptions.append(change.describe())
        parts.append(f'[[Template:{template}|{template}]]: {", ".join(descriptions)}')
    return msg.edit_summary(parts, rules_page, faq_page, SUMMARY_LIMIT, brfa)


def _by_category(targets: list[TemplateRules]) -> dict[str, list[TemplateRules]]:
    by_category: dict[str, list[TemplateRules]] = {}
    for target in targets:
        by_category.setdefault(target.rules.category, []).append(target)
    return by_category


def read_trial_count(path: str) -> int:
    """How many trial edits have been made, from the count file.  Raises
    FileNotFoundError if there's no such file, and ValueError if it doesn't
    hold a count."""
    with open(path, encoding='utf-8') as f:
        text = f.read()
    made = int(text.strip())
    if made < 0:
        raise ValueError(f'a count below 0: {made}')
    return made


def write_trial_count(path: str, made: int) -> None:
    """Save the count, replacing the file in one go, so that it's never
    left half-written."""
    temporary = f'{path}.tmp'
    with open(temporary, 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'{made}\n')
    os.replace(temporary, path)
