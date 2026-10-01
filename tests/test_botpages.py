"""Checks on the bot's own pages."""

import pytest
from fakes import FakePage, options, wiki_for

from parambot.botpages import check_bot_pages, protection_expiry, too_weak
from parambot.messages import plain

OPTS = options()
RULES, RUN, REPORT = OPTS.rules_page, OPTS.run_page, OPTS.report_page
INSTRUCTIONS, LINK_RULE, FAQ = OPTS.instructions_page, OPTS.link_rule_page, OPTS.faq_page
HEADER = OPTS.header_page


def check(opts=OPTS, **changes):
    wiki = wiki_for(opts, **changes)
    return check_bot_pages(wiki, opts), wiki


def test_correctly_set_up_pages_pass():
    result, wiki = check()
    assert (result.problems, result.notes) == ([], [])
    assert set(wiki.loaded_titles) == {'User:ExampleBot', RULES, RUN, REPORT, INSTRUCTIONS,
                                       LINK_RULE, FAQ, HEADER}


@pytest.mark.parametrize('protection, expected', [
    ({}, 'is not protected'),
    ({'edit': ('autoconfirmed', 'infinity')}, 'is semi-protected'),
    ({'edit': ('extendedconfirmed', 'infinity')}, 'is extended-confirmed protected'),
    ({'move': ('sysop', 'infinity')}, 'is not protected'),    # move protection isn't enough
])
def test_rules_page_must_be_template_editor_protected(protection, expected):
    result, _ = check(**{RULES: FakePage(RULES, protection=protection)})
    [problem] = result.problems
    assert expected in problem
    assert 'template-editor protected or higher' in problem


@pytest.mark.parametrize('level', ['templateeditor', 'sysop'])
def test_template_editor_protection_or_higher_passes(level):
    result, _ = check(**{RULES: FakePage(RULES, protection={'edit': (level, 'infinity')})})
    assert result.problems == []


def test_expiring_protection_is_a_note():
    result, _ = check(**{RULES: FakePage(
        RULES, protection={'edit': ('templateeditor', '2026-12-01T00:00:00Z')})})
    assert result.problems == []
    assert 'expires 2026-12-01T00:00:00Z' in result.notes[0]


EXPIRY = '2026-12-01T00:00:00Z'


@pytest.mark.parametrize('protection, weak, expiry', [
    ({}, 'not protected', None),
    ({'edit': ('autoconfirmed', EXPIRY)}, 'semi-protected', EXPIRY),
    ({'edit': ('sysop', 'infinity')}, None, None),
    ({'edit': ('templateeditor', EXPIRY)}, None, EXPIRY),
])
def test_protection_helpers(protection, weak, expiry):
    page = FakePage('User:ExampleBot/Rules/T', protection=protection)
    assert (too_weak(page, 'templateeditor'), protection_expiry(page)) == (weak, expiry)


@pytest.mark.parametrize('required, level, needed', [
    ('autoconfirmed', None, 'semi-protected or higher'),
    ('extendedconfirmed', 'autoconfirmed', 'extended-confirmed protected or higher'),
    ('templateeditor', 'extendedconfirmed', 'template-editor protected or higher'),
    ('sysop', 'templateeditor', 'fully protected.'),
])
def test_the_protection_the_rules_page_needs_is_a_setting(required, level, needed):
    # The rules page is protected one level too weakly for the setting...
    opts = options(rules_protection=required)
    protection = {'edit': (level, 'infinity')} if level else {}
    result, _ = check(opts, **{RULES: FakePage(RULES, protection=protection)})
    [problem] = result.problems
    assert f'must be {needed}' in problem
    # ...and one level up is enough.
    stronger = 'autoconfirmed' if level is None else {
        'autoconfirmed': 'extendedconfirmed', 'extendedconfirmed': 'templateeditor',
        'templateeditor': 'sysop'}[level]
    result, _ = check(opts, **{RULES: FakePage(
        RULES, protection={'edit': (stronger, 'infinity')})})
    assert result.problems == []


def test_an_unknown_protection_level_is_too_weak():
    page = FakePage(RULES, protection={'edit': ('superprotect', 'infinity')})
    assert too_weak(page, 'autoconfirmed') == 'superprotect protected'


def test_the_protection_setting_must_be_a_level():
    with pytest.raises(ValueError, match='rules_protection must be one of'):
        options(rules_protection='template-editor')


def test_local_rules_file_skips_the_rules_page(tmp_path):
    result, wiki = check(options(rules_files=(str(tmp_path / 'rules.mediawiki'),)),
                         **{RULES: None})
    assert result.problems == []
    assert RULES not in wiki.loaded_titles


@pytest.mark.parametrize('title, page, expected', [
    ('User:ExampleBot', None, "User:ExampleBot (the bot's user page) does not exist"),
    ('User:ExampleBot', FakePage('User:ExampleBot'), "doesn't use {{bot}}"),
    (RULES, None, f'{RULES} (the rules page) does not exist'),
    (RULES, FakePage(RULES, redirect_to=FakePage('User:ExampleBot/Elsewhere'),
                     protection={'edit': ('sysop', 'infinity')}),
     f'{RULES} (the rules page) is a redirect'),
    (RUN, None, f'{RUN} (the Run page) does not exist'),
    (REPORT, FakePage(REPORT, model='json'), 'must be an ordinary wikitext page, not json'),
    (REPORT, FakePage(REPORT, protection={'edit': ('sysop', 'infinity')}),
     'the bot probably cannot edit it'),
])
def test_broken_pages_are_problems(title, page, expected):
    result, _ = check(**{title: page})
    [problem] = result.problems
    assert expected in plain(problem)


def test_live_run_checks_the_bot_can_edit_the_report():
    result, _ = check(options(live=True), **{REPORT: FakePage(REPORT, editable=False)})
    assert result.problems == [
        'ExampleBot cannot edit User:ExampleBot/Report (the report page). Check its protection.']


def test_protected_run_page_and_missing_helper_pages_are_notes():
    result, _ = check(**{RUN: FakePage(RUN, 'yes', protection={'edit': ('sysop', 'infinity')}),
                         INSTRUCTIONS: None, LINK_RULE: None, FAQ: None, HEADER: None})
    assert result.problems == []
    notes = '\n'.join(result.notes)
    assert "most editors can't use it to stop the bot" in notes
    assert 'Instructions (the instructions for rule writers) does not exist' in notes
    assert f'{LINK_RULE} (the template that shows the list of rules pages) does not exist' \
        in notes
    assert f'{FAQ} (the FAQ every edit summary links to) does not exist' in notes
    assert f"{HEADER} (the links across the top of the bot's pages and the report) does not " \
        'exist' in notes
