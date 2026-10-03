"""Whole runs of the bot, on a fake wiki."""

import re

import pytest
from fakes import (
    ACTIVE_OFFICEHOLDER,
    ARTICLE_TEXT,
    BOT,
    OFFICEHOLDER_CATEGORY,
    OFFICEHOLDER_REVISION,
    OFFICEHOLDER_RULES,
    TEMPLATE_EDITOR,
    FakePage,
    FakeWiki,
    edited_by,
    link_rule,
    options,
    rules_page,
    wiki_for,
)

from parambot import messages as msg
from parambot.bot import SUMMARY_LIMIT, ParamBot, StopRun, edit_summary
from parambot.fixer import TemplateRules, fix_wikitext
from parambot.messages import plain
from parambot.options import Options
from parambot.rules import parse_config

FIXED_TEXT = '{{Infobox officeholder\n| term_start = 2020\n}}'
PERSON_CATEGORY = 'Category:Pages using infobox person with unknown parameters'
FAQ = f'User:{BOT}/FAQ'
INACTIVE_OFFICEHOLDER = ('== Active ==\n== Inactive ==\n'
                         + link_rule('Infobox officeholder', OFFICEHOLDER_REVISION))
# The officeholder rules with a rename to a name the template doesn't accept.
MISSPELT_RULES = OFFICEHOLDER_RULES.replace(
    '|}', '|-\n| {{para|termend}} || {{para|term_ending}}\n|}')


def article(title, text=ARTICLE_TEXT, **kwargs):
    return FakePage(title, text, **kwargs)


def only_report(tmp_path):
    reports = list(tmp_path.glob('report-*.mediawiki'))
    assert len(reports) == 1
    return reports[0].read_text(encoding='utf-8')


def only_diff(tmp_path):
    return next(tmp_path.glob('edits-*.diff')).read_text(encoding='utf-8')


def index(opts, text):
    return {opts.rules_page: FakePage(opts.rules_page, text, protection=TEMPLATE_EDITOR)}


# -- dry runs --------------------------------------------------------------

def test_dry_run_proposes_fixes_without_editing(tmp_path):
    opts = options(out_dir=str(tmp_path))
    jane = article('Jane Example')
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, jane)
    report = ParamBot(wiki, opts).run()
    assert (report.categories_polled, report.categories_populated, report.edits) == (1, 1, 1)
    assert jane.saved == []
    assert not wiki.logged_in
    diff = only_diff(tmp_path)
    assert '-| termstart = 2020' in diff and '+| term_start = 2020' in diff
    assert '# Summary: Fixing deprecated parameters restored in' in diff
    assert 'would have made (dry run) 1 edit.' in only_report(tmp_path)


def test_sandbox_skipped_by_default(tmp_path):
    opts = options(out_dir=str(tmp_path), pages=('User:Example/sandbox',))
    wiki = wiki_for(opts).add(article('User:Example/sandbox'))
    report = ParamBot(wiki, opts).run()
    assert report.skipped == [
        ('User:Example/sandbox', 'not an article; use --any-namespace to preview it in a dry run')]
    assert only_diff(tmp_path) == ''


def test_sandbox_preview_with_any_namespace(tmp_path):
    opts = options(out_dir=str(tmp_path), pages=('User:Example/sandbox',), any_namespace=True)
    wiki = wiki_for(opts).add(article('User:Example/sandbox'))
    report = ParamBot(wiki, opts).run()
    assert report.skipped == []
    assert report.edits == 1
    assert '+| term_start = 2020' in only_diff(tmp_path)


def test_missing_and_redirect_pages_are_reported(tmp_path):
    opts = options(out_dir=str(tmp_path), pages=('Nope', 'Redirect'))
    wiki = wiki_for(opts).add(article('Redirect', redirect_to=article('Target')))
    report = ParamBot(wiki, opts).run()
    assert sorted(report.skipped) == [('Nope', 'page does not exist'),
                                      ('Redirect', 'page is a redirect')]


def test_nothing_to_fix_is_not_an_edit(tmp_path):
    opts = options(out_dir=str(tmp_path))
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, article('Fine', FIXED_TEXT))
    report = ParamBot(wiki, opts).run()
    assert (report.pages_checked, report.edits, report.skipped) == (1, 0, [])


def test_only_the_chosen_templates_are_used(tmp_path):
    opts = options(out_dir=str(tmp_path), templates=('Infobox person',))
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, article('Jane Example'))
    report = ParamBot(wiki, opts).run()
    assert wiki.polled == []
    assert report.edits == 0


def test_max_edits(tmp_path):
    opts = options(out_dir=str(tmp_path), max_edits=2)
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, *(article(f'P{i}') for i in range(4)))
    report = ParamBot(wiki, opts).run()
    assert report.edits == 2
    assert report.notes[-1] == 'Stopped after 2 edits (max_edits).'


def _clock_an_hour_a_read(monkeypatch):
    hours = iter(range(1000))
    monkeypatch.setattr('parambot.bot._clock', lambda: next(hours) * 3600)


def test_a_run_stops_starting_new_work_after_max_hours(tmp_path, monkeypatch):
    # So that a daily run can't still be going when the next one starts.
    _clock_an_hour_a_read(monkeypatch)
    opts = options(out_dir=str(tmp_path), max_hours=2.5)
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, *(article(f'P{i}') for i in range(5)))
    report = ParamBot(wiki, opts).run()
    assert report.edits == 2     # an hour in, then two: the third would be 3 hours in
    assert any(plain(note).startswith('Stopped after 2.5 hours (max_hours), so that the '
                                      "next run doesn't start") for note in report.notes)


def test_max_hours_0_means_no_time_limit(tmp_path, monkeypatch):
    _clock_an_hour_a_read(monkeypatch)
    opts = options(out_dir=str(tmp_path), max_hours=0)
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, *(article(f'P{i}') for i in range(5)))
    assert ParamBot(wiki, opts).run().edits == 5


@pytest.mark.parametrize('max_edits', [None, 0])
def test_no_edit_limit_unless_one_is_given(tmp_path, max_edits):
    opts = options(out_dir=str(tmp_path), max_edits=max_edits)
    assert Options().max_edits is None
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, *(article(f'P{i}') for i in range(4)))
    report = ParamBot(wiki, opts).run()
    assert report.edits == 4
    assert not any('max_edits' in note for note in report.notes)


@pytest.mark.parametrize('live, pages, large_run, noted', [
    (False, 3, 2, 'This run would have made 3 edits, more than 2.'),
    (True, 3, 2, 'This run made 3 edits, more than 2.'),
    (True, 2, 2, None),
    (True, 3, 0, None),    # 0: never
])
def test_a_large_run_gets_a_note(tmp_path, live, pages, large_run, noted):
    # 500 by default; 2 here, to keep the test quick.
    assert Options().large_run == 500
    opts = options(live=live, out_dir=str(tmp_path), large_run=large_run)
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY,
                                   *(article(f'P{i}') for i in range(pages)))
    report = ParamBot(wiki, opts).run()
    large = [plain(note) for note in report.notes if 'more than' in note]
    if noted:
        [note] = large
        assert note.startswith(noted)
    else:
        assert large == []


# -- the rules pages -------------------------------------------------------

def test_inactive_rules_are_checked_but_not_used(tmp_path):
    opts = options(out_dir=str(tmp_path))
    wiki = wiki_for(opts, **index(opts, INACTIVE_OFFICEHOLDER),
                    **{f'{opts.rules_page}/Infobox officeholder': rules_page(
                        opts, 'Infobox officeholder', MISSPELT_RULES, OFFICEHOLDER_REVISION)})
    wiki.populate(OFFICEHOLDER_CATEGORY, article('Jane Example'))
    report = ParamBot(wiki, opts).run()
    assert (report.categories_polled, report.pages_checked, report.edits) == (0, 0, 0)
    assert only_diff(tmp_path) == ''
    assert 'Inactive, so checked but not used: Infobox officeholder.' in report.notes
    # Checked like any other rules.
    assert any('Check the spelling of "term_ending"' in plain(p) for p in report.problems)


def test_an_edit_to_a_rules_page_does_nothing_until_approved(tmp_path):
    opts = options(live=True, out_dir=str(tmp_path))
    title = f'{opts.rules_page}/Infobox officeholder'
    edited = rules_page(opts, 'Infobox officeholder', MISSPELT_RULES, OFFICEHOLDER_REVISION + 1,
                        history={OFFICEHOLDER_REVISION: OFFICEHOLDER_RULES})
    wiki = wiki_for(opts, **{title: edited})
    jane = article('Jane Example')
    wiki.populate(OFFICEHOLDER_CATEGORY, jane)
    report = ParamBot(wiki, opts).run()
    assert jane.saved == [FIXED_TEXT]      # by the approved rules
    assert report.problems == []           # the misspelt rule isn't read at all
    [saved] = wiki.page(opts.report_page).saved
    assert saved.startswith(f'{{{{{opts.header_page}}}}}\n<!--')
    # The template's name, linked to its rules page.
    assert (f'* The [[{title}|Infobox officeholder]] rules have changed since their approved '
            f'revision ({OFFICEHOLDER_REVISION})') in saved


def test_the_summary_links_to_the_index_when_two_rules_pages_were_used(tmp_path):
    opts = options(live=True, out_dir=str(tmp_path))
    person_rules = ('{|\n|+ {{tl|Infobox person}}\n'
                    '|-\n| {{para|alma_mater}} || {{para|education}}\n|}')
    person_source = ('{{#invoke:Check for unknown parameters|check'
                     f'|unknown=[[{PERSON_CATEGORY}|_VALUE_]]| education }}}}')
    wiki = wiki_for(opts, **index(opts, ACTIVE_OFFICEHOLDER + link_rule('Infobox person', 3001)))
    wiki.add(rules_page(opts, 'Infobox person', person_rules, 3001),
             FakePage('Template:Infobox person', person_source))
    jane = article('Jane Example', ARTICLE_TEXT + '{{Infobox person|alma_mater=X}}')
    wiki.populate(OFFICEHOLDER_CATEGORY, jane).populate(PERSON_CATEGORY, jane)
    ParamBot(wiki, opts).run()
    [summary] = jane.summaries
    assert 'alma_mater → education' in summary and 'termstart → term_start' in summary
    assert summary.endswith('([[User:ExampleBot/Rules|rules]] · [[User:ExampleBot/FAQ|FAQ]])')


# -- what stops an edit ----------------------------------------------------

def test_an_article_deleted_mid_run_is_not_recreated(tmp_path):
    opts = options(live=True, out_dir=str(tmp_path))
    deleted = article('Deleted', deleted_before_save=True)
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, deleted)
    report = ParamBot(wiki, opts).run()
    assert deleted.saved == []
    assert report.edits == 0
    assert report.skipped == [('Deleted', 'page was deleted while the bot was working on it')]


def test_nobots_is_respected(tmp_path):
    opts = options(out_dir=str(tmp_path))
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, article('Excluded', may_edit=False))
    report = ParamBot(wiki, opts).run()
    assert report.skipped == [('Excluded', msg.SKIP_EXCLUDED)]


def test_no_second_edit_within_the_cooldown(tmp_path):
    opts = options(out_dir=str(tmp_path))
    recent = article('Recent', revisions=[edited_by('Someone', 1), edited_by(BOT, 3)])
    old = article('Old', revisions=[edited_by(BOT, 45)])
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, recent, old)
    report = ParamBot(wiki, opts).run()
    assert report.edits == 1   # Old
    [(title, reason)] = report.skipped
    assert title == 'Recent'
    assert reason.startswith(f'{BOT} already edited this page on ')


def test_the_report_links_a_rules_page_nobody_has_listed(tmp_path):
    opts = options(out_dir=str(tmp_path))
    wiki = wiki_for(opts).add(rules_page(opts, 'Infobox new', OFFICEHOLDER_RULES, 3001))
    ParamBot(wiki, opts).run()
    assert (f"* The [[{opts.rules_page}/Infobox new|Infobox new]] rules page isn't listed on "
            f'[[{opts.rules_page}]]') in only_report(tmp_path)


def test_hundreds_of_articles_cost_no_request_each(tmp_path):
    # A request per article (its history, for the cooldown) would get the
    # bot rate-limited once there were hundreds of them.
    opts = options(out_dir=str(tmp_path), max_edits=1000)
    pages = [article(f'Article {i}', revisions=[edited_by(BOT, 45)]) for i in range(500)]
    recent = article('Recent', revisions=[edited_by(BOT, 3)])
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, *pages, recent)
    report = ParamBot(wiki, opts).run()
    assert report.edits == 500
    assert [title for title, _ in report.skipped] == ['Recent']
    # The article loads need their templates, for the {{bots}} check.
    assert wiki.requests == {'load': 1, 'redirects': 1, 'load with templates': 1,
                             'recent_edits': 1, 'subpages': 1}


def test_error_on_one_page_is_reported_and_the_run_continues(tmp_path):
    opts = options(out_dir=str(tmp_path))
    wiki = wiki_for(opts).populate(
        OFFICEHOLDER_CATEGORY, article('A'), article('B', broken=True), article('C'))
    report = ParamBot(wiki, opts).run()
    assert report.edits == 2
    assert [(title, plain(reason)) for title, reason in report.skipped] == [
        ('B', 'error: ConnectionError: API timed out')]


@pytest.mark.parametrize('failures', [5, 2])
def test_repeated_errors_stop_the_run(tmp_path, failures):
    opts = options(out_dir=str(tmp_path), failures_in_a_row=failures)
    broken = [article(f'P{i}', broken=True) for i in range(failures + 3)]
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, *broken)
    with pytest.raises(RuntimeError, match=f'{failures} pages in a row failed'):
        ParamBot(wiki, opts).run()
    assert f'{failures} pages in a row failed' in only_report(tmp_path)


def test_a_success_resets_the_error_count(tmp_path):
    opts = options(out_dir=str(tmp_path))
    bad = opts.failures_in_a_row - 1
    pages = ([article(f'X{i}', broken=True) for i in range(bad)] + [article('Good')]
             + [article(f'Y{i}', broken=True) for i in range(bad)])
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, *pages)
    assert ParamBot(wiki, opts).run().edits == 1


# -- live runs -------------------------------------------------------------

def test_live_run_edits_and_saves_the_report(tmp_path):
    opts = options(live=True, out_dir=str(tmp_path))
    jane = article('Jane Example')
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, jane)
    report = ParamBot(wiki, opts).run()
    assert wiki.logged_in
    assert report.edits == 1
    assert jane.saved == [FIXED_TEXT]
    assert jane.summaries == [
        'Fixing deprecated parameters restored in [[Template:Infobox officeholder|Infobox '
        'officeholder]]: termstart → term_start '
        f'([[Special:Permalink/{OFFICEHOLDER_REVISION}|rules]] · [[{FAQ}|FAQ]])']
    report_page = wiki.page(opts.report_page)
    assert len(report_page.saved) == 1
    assert 'made 1 edit.' in report_page.saved[0]
    assert list(tmp_path.iterdir()) == []


def test_unchanged_report_is_not_saved_again(tmp_path, monkeypatch):
    opts = options(live=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts)
    ParamBot(wiki, opts).run()
    ParamBot(wiki, opts).run()
    # Not for a new commit of the bot alone, either.
    monkeypatch.setattr('parambot.bot.commit', lambda: 'abcdef0')
    ParamBot(wiki, opts).run()
    assert len(wiki.page(opts.report_page).saved) == 1


def test_the_report_says_which_commit_of_the_bot_wrote_it(tmp_path, monkeypatch):
    monkeypatch.setattr('parambot.bot.commit', lambda: '24cef13')
    opts = options(live=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts)
    ParamBot(wiki, opts).run()
    [saved] = wiki.page(opts.report_page).saved
    assert saved.endswith('\n<!-- ParamBot 24cef13 -->')


def test_no_commit_no_comment(tmp_path, monkeypatch):
    # Not running from a git checkout.
    monkeypatch.setattr('parambot.bot.commit', lambda: None)
    opts = options(live=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts)
    ParamBot(wiki, opts).run()
    [saved] = wiki.page(opts.report_page).saved
    assert '<!-- ParamBot' not in saved


def test_live_run_needs_the_right_account(tmp_path):
    opts = options(live=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts)
    wiki.user = 'Someone'
    with pytest.raises(StopRun, match="Logged in as 'Someone', expected 'ExampleBot'"):
        ParamBot(wiki, opts).run()
    wiki.user, wiki.rights = BOT, set()
    with pytest.raises(StopRun, match='does not have the bot right'):
        ParamBot(wiki, opts).run()


def test_trial_runs_need_no_bot_right(tmp_path):
    opts = options(live=True, trial=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts)
    wiki.rights = set()
    ParamBot(wiki, opts).run()
    assert wiki.page(opts.report_page).saved


# -- reporting only --------------------------------------------------------

def test_reporting_only_saves_the_report_and_nothing_else(tmp_path):
    # Even with --live, and with neither the bot flag nor --trial.
    opts = options(live=True, report_only=True, out_dir=str(tmp_path))
    jane = article('Jane Example')
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, jane)
    wiki.rights = set()
    ParamBot(wiki, opts).run()
    assert wiki.logged_in
    assert jane.saved == []
    report_page = wiki.page(opts.report_page)
    [saved] = report_page.saved
    assert 'would have made (reporting only) 1 edit.' in saved
    assert report_page.summaries == [
        'Updating report (reporting only): 1 edit it would make, 0 pages need review']
    # The edit it would have made goes to a file, for the operators.
    [diff] = tmp_path.glob('edits-*.diff')
    assert '### Jane Example' in diff.read_text(encoding='utf-8')
    assert list(tmp_path.glob('report-*')) == []


@pytest.mark.parametrize('run_page, runs', [('yes', True), ('report', True), ('Report', True),
                                            ('no', False), ('', False)])
def test_reporting_only_obeys_the_run_page(tmp_path, run_page, runs):
    opts = options(report_only=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts, **{opts.run_page: FakePage(opts.run_page, run_page)})
    if runs:
        ParamBot(wiki, opts).run()
        assert wiki.page(opts.report_page).saved
    else:
        with pytest.raises(StopRun, match='does not say "yes" or "report"; not running'):
            ParamBot(wiki, opts).run()
        assert wiki.page(opts.report_page).saved == []


def test_report_on_the_run_page_does_not_let_a_live_run_edit(tmp_path):
    opts = options(live=True, out_dir=str(tmp_path))
    jane = article('Jane Example')
    wiki = wiki_for(opts, **{opts.run_page: FakePage(opts.run_page, 'report')})
    wiki.populate(OFFICEHOLDER_CATEGORY, jane)
    with pytest.raises(StopRun, match='does not say "yes"; not running'):
        ParamBot(wiki, opts).run()
    assert jane.saved == []


def test_reporting_only_switched_off_mid_run_saves_nothing(tmp_path):
    opts = options(report_only=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, article('Jane Example'))
    members = wiki.category_members

    def switched_off_while_polling(*args):
        wiki.page(opts.run_page).text = 'no'
        return members(*args)
    wiki.category_members = switched_off_while_polling
    ParamBot(wiki, opts).run()
    assert wiki.page(opts.report_page).saved == []
    assert len(list(tmp_path.glob('report-*.mediawiki'))) == 1   # written locally instead


@pytest.mark.parametrize('changes, refused', [
    ({'pages': ('Jane Example',)}, '--page'),
    ({'templates': ('Infobox officeholder',)}, '--template'),
    ({'any_namespace': True}, '--any-namespace'),
    ({'rules_files': ('rules.mediawiki',)}, '--rules-file'),
])
def test_reporting_only_needs_a_full_run(tmp_path, changes, refused):
    # A partial report would replace the full one everyone reads.
    opts = options(report_only=True, out_dir=str(tmp_path), **changes)
    wiki = wiki_for(opts)
    with pytest.raises(StopRun, match=f"--report-only doesn't work with {refused}"):
        ParamBot(wiki, opts).run()
    assert not wiki.logged_in


@pytest.mark.parametrize('report_page', ['Wikipedia:Sandbox', f'User talk:{BOT}/Report',
                                         f'User:{BOT}Two/Report'])
def test_reporting_only_saves_nowhere_outside_the_bots_userspace(tmp_path, report_page):
    opts = options(report_only=True, report_page=report_page, out_dir=str(tmp_path))
    wiki = wiki_for(opts)
    with pytest.raises(StopRun, match=f'only edits its own userspace.*subpage of User:{BOT}'):
        ParamBot(wiki, opts).run()
    assert not wiki.logged_in


def test_reporting_only_can_report_elsewhere_in_the_bots_userspace(tmp_path):
    opts = options(report_only=True, report_page=f'User:{BOT}/Daily report',
                   out_dir=str(tmp_path))
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, article('Jane Example'))
    ParamBot(wiki, opts).run()
    assert wiki.page(f'User:{BOT}/Daily report').saved
    assert wiki.page(f'User:{BOT}/Report').saved == []


@pytest.mark.parametrize('report_only', [True, False])
@pytest.mark.parametrize('page, what', [
    ('run_page', 'the Run page'), ('rules_page', 'the rules page'), ('faq_page', 'the FAQ'),
    ('user_page', "the bot's user page"),
])
def test_the_report_never_replaces_another_of_the_bots_pages(tmp_path, report_only, page,
                                                             what):
    taken = getattr(options(), page)
    opts = options(live=True, report_only=report_only, report_page=taken,
                   out_dir=str(tmp_path))
    wiki = wiki_for(opts)
    with pytest.raises(StopRun, match=f'set to {taken}, which is {what}'):
        ParamBot(wiki, opts).run()
    assert not wiki.logged_in
    assert wiki.page(taken).saved == []


def test_the_report_never_replaces_a_rules_page(tmp_path):
    opts = options(live=True, report_page=f'User:{BOT}/Rules/Infobox officeholder',
                   out_dir=str(tmp_path))
    with pytest.raises(StopRun, match='which is a rules page'):
        ParamBot(wiki_for(opts), opts).run()


def test_reporting_only_refuses_to_save_any_other_page(tmp_path):
    # The last check, even if the report page changed after the first.
    opts = options(report_only=True, out_dir=str(tmp_path))
    bot = ParamBot(wiki_for(opts), opts)
    bot._check_may_save(f'User:{BOT}/Report')
    for title in (f'User:{BOT}/Run', 'Wikipedia:Sandbox'):
        with pytest.raises(RuntimeError, match=f'refused to save {title}'):
            bot._check_may_save(title)
    opts.report_page = 'Wikipedia:Sandbox'
    with pytest.raises(RuntimeError, match='refused to save Wikipedia:Sandbox'):
        bot._check_may_save('Wikipedia:Sandbox')


def test_reporting_only_can_never_save_an_article(tmp_path):
    # The last check before any save, whatever else goes wrong.
    opts = options(report_only=True, out_dir=str(tmp_path))
    bot = ParamBot(wiki_for(opts), opts)
    jane = article('Jane Example')
    with pytest.raises(RuntimeError, match='refused to save Jane Example'):
        bot._save(jane, fix_wikitext(jane.text, []), 'summary')
    assert jane.saved == []


def test_reporting_only_reports_setup_problems_instead_of_stopping(tmp_path):
    opts = options(report_only=True, out_dir=str(tmp_path))
    unprotected = FakePage(opts.rules_page, ACTIVE_OFFICEHOLDER)
    wiki = wiki_for(opts, **{opts.rules_page: unprotected})
    ParamBot(wiki, opts).run()
    [saved] = wiki.page(opts.report_page).saved
    assert '== Setup problems ==' in saved
    assert '(the rules page) is not protected' in saved


def test_reporting_only_needs_the_bot_account(tmp_path):
    opts = options(report_only=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts)
    wiki.user = 'Someone'
    with pytest.raises(StopRun, match="Logged in as 'Someone', expected 'ExampleBot'"):
        ParamBot(wiki, opts).run()
    assert wiki.page(opts.report_page).saved == []


def test_any_namespace_refused_live():
    wiki = FakeWiki()
    with pytest.raises(StopRun, match='dry runs only'):
        ParamBot(wiki, options(live=True, any_namespace=True)).run()
    assert not wiki.logged_in


def test_switched_off_before_the_run_does_nothing(tmp_path):
    opts = options(live=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts, **{opts.run_page: FakePage(opts.run_page, 'no')})
    with pytest.raises(StopRun, match='not running'):
        ParamBot(wiki, opts).run()
    assert wiki.polled == []
    assert list(tmp_path.iterdir()) == []


def test_switched_off_mid_run_makes_no_more_wiki_edits(tmp_path):
    opts = options(live=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts)

    def switch_off():
        wiki.page(opts.run_page).text = 'no <!-- switched off mid-run -->'
    first, second = article('First', on_save=switch_off), article('Second')
    wiki.populate(OFFICEHOLDER_CATEGORY, first, second)
    with pytest.raises(StopRun, match='stopped before editing Second'):
        ParamBot(wiki, opts).run()
    assert first.saved == [FIXED_TEXT]
    assert second.saved == []
    assert wiki.page(opts.report_page).saved == []   # not even the report
    assert 'stopped before editing Second' in only_report(tmp_path)


def test_live_run_refuses_to_start_and_lists_every_problem(tmp_path):
    opts = options(live=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts, **{opts.rules_page: FakePage(opts.rules_page, 'x'),
                             opts.report_page: None})
    with pytest.raises(StopRun) as stopped:
        ParamBot(wiki, opts).run()
    message = str(stopped.value)
    assert message.startswith("Not running, because of problems with the bot's pages:")
    assert f'{opts.rules_page} (the rules page) is not protected' in message
    assert f'{opts.report_page} (the report page) does not exist' in message
    assert wiki.polled == []
    assert list(tmp_path.iterdir()) == []   # nothing written anywhere


def test_dry_run_carries_on_and_reports_setup_problems(tmp_path):
    opts = options(out_dir=str(tmp_path))
    unprotected = FakePage(opts.rules_page, ACTIVE_OFFICEHOLDER)
    report = ParamBot(wiki_for(opts, **{opts.rules_page: unprotected}), opts).run()
    assert report.edits == 0   # nothing in the category, but the rules were read
    text = only_report(tmp_path)
    assert '== Setup problems ==' in text
    assert 'is not protected' in text


# -- failures --------------------------------------------------------------

def test_crash_still_writes_the_report(tmp_path):
    opts = options(out_dir=str(tmp_path), rules_files=(str(tmp_path / 'missing.mediawiki'),))
    with pytest.raises(FileNotFoundError):
        ParamBot(wiki_for(opts), opts).run()
    report = only_report(tmp_path)
    assert '== Errors ==' in report
    assert 'FileNotFoundError' in report


def test_live_crash_saves_the_report_page(tmp_path):
    opts = options(live=True, out_dir=str(tmp_path))
    wiki = wiki_for(opts)
    wiki.fail_polling = ConnectionError('API down')
    with pytest.raises(ConnectionError):
        ParamBot(wiki, opts).run()
    [saved] = wiki.page(opts.report_page).saved
    assert 'ConnectionError: <nowiki>API down</nowiki>' in saved
    assert list(tmp_path.glob('report-*')) == []


def test_live_report_falls_back_to_a_local_file(tmp_path):
    opts = options(live=True, out_dir=str(tmp_path))
    unsaveable = FakePage(opts.report_page, 'x', save_error=ConnectionError('wiki unreachable'))
    wiki = wiki_for(opts, **{opts.report_page: unsaveable})
    wiki.fail_polling = ConnectionError('API down')
    with pytest.raises(ConnectionError):
        ParamBot(wiki, opts).run()
    assert 'ConnectionError: <nowiki>API down</nowiki>' in only_report(tmp_path)


def test_no_rules_is_reported(tmp_path):
    rules = tmp_path / 'rules.mediawiki'
    rules.write_text('Nothing here yet.', encoding='utf-8')
    opts = options(out_dir=str(tmp_path), rules_files=(str(rules),))
    report = ParamBot(wiki_for(opts), opts).run()
    assert report.problems == [f'{rules} has no rules the bot can use.']
    assert report.edits == 0


# -- check-rules -----------------------------------------------------------

def test_check_rules_looks_at_no_articles():
    opts = options()
    wiki = wiki_for(opts).populate(OFFICEHOLDER_CATEGORY, article('Jane Example'))
    report = ParamBot(wiki, opts).check_rules()
    assert (report.setup, report.problems, report.pages_checked) == ([], [], 0)
    assert wiki.polled == [OFFICEHOLDER_CATEGORY]


def test_check_rules_reports_a_missing_rules_page():
    opts = options()
    report = ParamBot(wiki_for(opts, **{opts.rules_page: None}), opts).check_rules()
    assert f'{opts.rules_page} (the rules page) does not exist. Create it.' in report.setup
    assert f'Rules page {opts.rules_page} does not exist' in report.setup


def test_check_rules_checks_inactive_rules():
    opts = options()
    wiki = wiki_for(opts, **index(opts, INACTIVE_OFFICEHOLDER))
    report = ParamBot(wiki, opts).check_rules()
    assert report.notes == ['Inactive, so checked but not used: Infobox officeholder.']
    assert wiki.polled == [OFFICEHOLDER_CATEGORY]


# -- edit summaries --------------------------------------------------------

def _rules(*tables):
    return [TemplateRules.unchecked(rs) for rs in parse_config(''.join(tables)).rulesets.values()]


def _table(template, *pairs):
    rows = ''.join(f'|-\n| {{{{para|{old}}}}} || {{{{para|{new}}}}}\n' for old, new in pairs)
    return f'{{|\n|+ {{{{tl|{template}}}}}\n{rows}|}}\n'


def test_edit_summary():
    targets = _rules(
        _table('Infobox settlement', ('imagesize', 'image_size'), ('image_caption', 'caption')),
        _table('Infobox person', ('other_name', 'other_names')))
    result = fix_wikitext(
        '{{Infobox person|other_name=A|module={{Infobox settlement|imagesize=1|image_caption=B}}}}'
        '{{Infobox settlement|imagesize=2}}', targets)
    assert edit_summary(result, 'User:ExampleBot/Rules', FAQ) == (
        'Fixing deprecated parameters restored in '
        '[[Template:Infobox person|Infobox person]]: other_name → other_names; '
        '[[Template:Infobox settlement|Infobox settlement]]: imagesize → image_size, '
        'image_caption → caption '
        '([[User:ExampleBot/Rules|rules]] · [[User:ExampleBot/FAQ|FAQ]])')


def test_a_long_edit_summary_is_cut_between_changes():
    renames = [(f'param{i}', f'new_param{i}') for i in range(60)]
    text = '{{T|' + '|'.join(f'{old}=x' for old, _ in renames) + '}}'
    result = fix_wikitext(text, _rules(_table('T', *renames)))
    summary = edit_summary(result, 'Special:Permalink/1234567890', FAQ)
    assert len(summary) <= SUMMARY_LIMIT
    changes, links = summary.split('…')
    assert re.search(r'param\d+ → new_param\d+$', changes)   # a whole change, then …
    assert links == ' ([[Special:Permalink/1234567890|rules]] · [[User:ExampleBot/FAQ|FAQ]])'


def test_a_long_edit_summary_leaves_no_link_broken():
    tables = [_table(f'Template number {i}', (f'param{i}', f'new_param{i}')) for i in range(12)]
    text = ''.join(f'{{{{Template number {i}|param{i}=x}}}}' for i in range(12))
    summary = edit_summary(fix_wikitext(text, _rules(*tables)), 'User:ExampleBot/Rules', FAQ)
    assert len(summary) <= SUMMARY_LIMIT
    assert '…' in summary
    assert summary.count('[[') == summary.count(']]')
