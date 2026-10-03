"""Finding and reading the rules pages."""

import pytest
from fakes import (
    LINK_RULE,
    OFFICEHOLDER_REVISION,
    OFFICEHOLDER_RULES,
    FakePage,
    link_rule,
    options,
    rules_page,
    wiki_for,
)

from parambot.messages import plain
from parambot.rulespages import Listed, read_index, read_rules_files, read_rules_pages, subpage

OPTS = options()
INDEX = OPTS.rules_page
PERSON_RULES = ('{| class="wikitable"\n|+ {{tl|Infobox person}}\n'
                '|-\n| {{para|alma_mater}} || {{para|education}}\n|}\n')
PERSON_REVISION = 2001


def page(template):
    return f'{INDEX}/{template}'


# -- the index -------------------------------------------------------------

def test_every_rules_page_the_index_names_is_kept_for_the_report_to_link():
    # Including Infobox housing project, whose revision the helper script left
    # as "undefined", and a plain link.
    listing = read_index('== Active ==\n' + link_rule('Infobox person', 103)
                         + link_rule('Infobox housing project', 'undefined')
                         + f'* [[{page("Infobox venue")}]]\n', OPTS)
    assert set(listing.pages) == {page('Infobox person'), page('Infobox venue')}
    assert listing.named == {page('Infobox person'), page('Infobox housing project'),
                             page('Infobox venue')}


def test_active_and_inactive_pages():
    listing = read_index(
        f'{{{{{OPTS.instructions_page}}}}}\n'
        'See [[/Archive 1]] for rules that were retired.\n'
        '== Active ==\n'
        + link_rule('Infobox settlement', 101).rstrip() + ' (updated after the RfC)\n'
        + f'* {{{{user:{OPTS.bot_user}/LinkRule| infobox_military installation |102}}}}\n'
        '=== People ===\n'
        + link_rule('Infobox person', 103)
        + '== Inactive ==\n'
        '<!-- ' + link_rule('Infobox commented out', 104) + ' -->\n'
        + link_rule('Template:Infobox organization', 105)
        + link_rule('Infobox new')
        + '== See also ==\n'
        + link_rule('Infobox not listed', 106), OPTS)
    assert listing.problems == []
    assert listing.pages == {
        page('Infobox settlement'): Listed(page('Infobox settlement'), True, 101),
        page('Infobox military installation'):
            Listed(page('Infobox military installation'), True, 102),
        page('Infobox person'): Listed(page('Infobox person'), True, 103),
        page('Infobox organization'): Listed(page('Infobox organization'), False, 105),
        page('Infobox new'): Listed(page('Infobox new'), False, None)}


def test_problems_with_the_index():
    listing = read_index(
        '== Inactive ==\n'
        '* [[/Infobox linked]]\n'
        '* {{/Infobox included}}\n'
        f'* {{{{{LINK_RULE}||2}}}}\n'
        + link_rule('Infobox bad', 'latest')
        + link_rule('Infobox twice', 3) + link_rule('Infobox twice', 4)
        + '== Archives ==\n'
        '* [[/Archive 1]]\n', OPTS)
    assert [plain(p) for p in listing.problems] == [
        f'A {{{{{LINK_RULE}}}}} on the rules page doesn\'t name a template, so the bot ignored '
        f'it: {{{{{LINK_RULE}||2}}}}',
        'The approved revision given for the Infobox bad rules is "latest", which isn\'t a '
        "revision number, so the bot isn't using them. Use the number from the page's "
        'history, such as the 1234567890 in Special:Permalink/1234567890.',
        f'{INDEX} has no "== Active ==" heading, so no rules are used.',
        f'{INDEX} lists the Infobox twice rules more than once, with different approved '
        "revisions (3 and 4), so the bot isn't using them. Keep one."]
    # Listed, but without an approved revision; the loader reports those.
    assert listing.pages == {
        page('Infobox linked'): Listed(page('Infobox linked'), False, None),
        page('Infobox included'): Listed(page('Infobox included'), False, None)}


def test_listed_under_both_headings_counts_as_inactive():
    listing = read_index('== Active ==\n' + link_rule('T', 1) + '== Inactive ==\n'
                         + link_rule('T', 1), OPTS)
    assert listing.pages == {page('T'): Listed(page('T'), False, 1)}
    assert listing.problems == [
        f'The T rules are listed under both Active and Inactive on {INDEX}. Treating them as '
        'inactive; take them off one of the two.']


@pytest.mark.parametrize('target, expected', [
    ('/Infobox foo', page('Infobox foo')),
    ('/infobox_foo', page('infobox foo')),        # subpage names are case-sensitive
    (page('Infobox foo'), page('Infobox foo')),
    (':user:ExampleBot/Rules/Infobox foo', page('Infobox foo')),
    ('/Infobox foo#Notes', page('Infobox foo')),
    ('/Infobox foo/', page('Infobox foo')),       # [[/Infobox foo/]] hides the slash
    (INDEX, None),
    ('User:Someone/Rules/Infobox foo', None),
    ('Infobox foo', None),
    ('#if:x', None),
    ('/', None),
])
def test_subpage(target, expected):
    assert subpage(target, INDEX) == expected


# -- reading the pages -----------------------------------------------------

def listing(*active, inactive=()):
    """An index listing (template, revision) pairs."""
    return ('== Active ==\n' + ''.join(link_rule(*entry) for entry in active)
            + '== Inactive ==\n' + ''.join(link_rule(*entry) for entry in inactive))


OFFICEHOLDER = ('Infobox officeholder', OFFICEHOLDER_REVISION)
PERSON = ('Infobox person', PERSON_REVISION)


def person(text=PERSON_RULES, revid=PERSON_REVISION, **kwargs):
    return rules_page(OPTS, 'Infobox person', text, revid, **kwargs)


def read(index_text, *pages):
    index = FakePage(INDEX, index_text)
    wiki = wiki_for(OPTS, **{INDEX: index}).add(*pages)
    return read_rules_pages(wiki, index, OPTS)


def test_approved_revisions_are_read():
    config = read(listing(OFFICEHOLDER, inactive=[PERSON]), person())
    assert (config.problems, config.notes) == ([], [])
    rulesets = config.rulesets
    assert (rulesets['Infobox officeholder'].active, rulesets['Infobox officeholder'].revision) \
        == (True, OFFICEHOLDER_REVISION)
    assert (rulesets['Infobox person'].active, rulesets['Infobox person'].page) \
        == (False, page('Infobox person'))


def test_newer_edits_are_not_used_until_approved():
    changed = PERSON_RULES.replace('education', 'eduction')
    config = read(listing(PERSON), person(changed, 2002, history={PERSON_REVISION: PERSON_RULES}))
    assert config.rulesets['Infobox person'].renames['alma_mater'].new == 'education'
    assert config.problems == []
    assert config.notes[-1:] == [   # after the note that Infobox officeholder isn't listed
        f'The Infobox person rules have changed since their approved revision '
        f'({PERSON_REVISION}); the bot is still using that one. Review the changes at '
        f'Special:Diff/{PERSON_REVISION}/2002, and if they\'re right, change the revision on '
        f'{INDEX} to 2002.']


def test_a_rules_page_the_index_does_not_list_is_noted():
    # Such as a new template's rules, waiting for a template editor.  Not the
    # instructions, the pages the index lists, or a redirect left by a move.
    new = rules_page(OPTS, 'Infobox new', PERSON_RULES, 3001)
    moved = rules_page(OPTS, 'Infobox moved', redirect_to=new)
    config = read(listing(OFFICEHOLDER, inactive=[PERSON]), person(), new, moved)
    assert config.unlisted == [page('Infobox new')]
    assert config.notes == [
        f"The Infobox new rules page isn't listed on {INDEX}, so the bot isn't using it. Once "
        'a template editor has checked it, they can list it under "== Active ==" or '
        '"== Inactive ==".']
    assert set(config.rulesets) == {'Infobox officeholder', 'Infobox person'}


def test_a_page_listed_outside_the_headings_is_not_listed():
    index = listing(OFFICEHOLDER) + f'== See also ==\n* [[{page("Infobox person")}]]\n'
    config = read(index, person())
    assert config.unlisted == [page('Infobox person')]


def test_a_failed_look_for_unlisted_pages_does_not_stop_the_run(monkeypatch):
    def broken(wiki, title):
        raise ConnectionError('API timed out')
    monkeypatch.setattr('fakes.FakeWiki.subpages', broken)
    config = read(listing(OFFICEHOLDER), rules_page(OPTS, 'Infobox new', PERSON_RULES, 3001))
    assert (config.unlisted, config.notes) == ([], [])
    assert set(config.rulesets) == {'Infobox officeholder'}


def test_several_unlisted_rules_pages():
    config = read(listing(OFFICEHOLDER), person(),
                  rules_page(OPTS, 'Infobox venue', PERSON_RULES, 3002))
    assert plain(config.notes[0]).startswith(
        f"2 rules pages aren't listed on {INDEX}, so the bot isn't using them: Infobox person "
        'and Infobox venue.')


def test_a_rules_page_needs_no_caption():
    rules = ('{| class="wikitable"\n! Old !! New\n'
             '|-\n| {{para|alma_mater}} || {{para|education}}\n|}')
    config = read(listing(PERSON), person(rules))
    assert config.problems == []
    assert config.rulesets['Infobox person'].renames['alma_mater'].new == 'education'


@pytest.mark.parametrize('pinned, pages, expected', [
    (9999, [person()], "Revision 9999, the approved revision of the Infobox person rules, "
                       "doesn't exist or was deleted"),
    (OFFICEHOLDER_REVISION, [person()],
     f'Revision {OFFICEHOLDER_REVISION} is a revision of User:ExampleBot/Rules/Infobox '
     'officeholder, not of the Infobox person rules'),
    (PERSON_REVISION, [person(revid=2002, history={PERSON_REVISION: None})],
     f'The text of revision {PERSON_REVISION} of the Infobox person rules is hidden'),
    (PERSON_REVISION, [person(model='json')],
     'The Infobox person rules page must be an ordinary wikitext page, not json'),
    (PERSON_REVISION, [person('Nothing yet.')],
     f'Revision {PERSON_REVISION} of the Infobox person rules page has nothing the bot could '
     'read'),
])
def test_unusable_revisions(pinned, pages, expected):
    config = read(listing(('Infobox person', pinned)), *pages)
    assert config.rulesets == {}
    [problem] = config.problems
    assert expected in problem


def test_pages_listed_without_a_revision():
    config = read(listing(('Infobox person', ''), ('Infobox missing', ''))
                  + '* [[/Infobox officeholder]]\n', person())
    assert config.rulesets == {}
    assert [plain(p) for p in config.problems] == [
        f"The Infobox person rules have no approved revision on {INDEX}, so the bot isn't "
        f'using them. If their current version is right, list them as '
        f'{{{{{LINK_RULE}|Infobox person|{PERSON_REVISION}}}}}.',
        f'The Infobox missing rules are listed on {INDEX}, but their page does not exist. '
        'Create it, or take it off the list.',
        f"The Infobox officeholder rules have no approved revision on {INDEX}, so the bot isn't "
        f'using them. If their current version is right, list them as '
        f'{{{{{LINK_RULE}|Infobox officeholder|{OFFICEHOLDER_REVISION}}}}}.']


def test_rules_for_other_templates_are_ignored():
    rules = OFFICEHOLDER_RULES + '* {{AWB rename template parameter|Infobox officeholder|a|b}}\n'
    config = read(listing(PERSON), person(PERSON_RULES + rules))
    assert set(config.rulesets) == {'Infobox person'}
    assert set(config.rulesets['Infobox person'].renames) == {'alma_mater'}
    assert config.problems == [
        'The rules page for Infobox person has a table for Infobox officeholder, so the bot '
        "ignored that table. Each template's rules go on a page of their own.",
        'The rules page for Infobox person has a one-line rule for Infobox officeholder, so the '
        "bot ignored it. Each template's rules go on a page of their own."]


def test_rules_written_on_the_index_are_ignored():
    config = read(listing(OFFICEHOLDER) + PERSON_RULES)
    assert set(config.rulesets) == {'Infobox officeholder'}
    [problem] = config.problems
    assert problem.startswith(f'{INDEX} has rules written on it (for Infobox person)')
    assert f'list that page with {{{{{LINK_RULE}|Infobox person|REVISION}}}}' in plain(problem)


# -- local files -----------------------------------------------------------

def test_rules_files_and_directories(tmp_path):
    (tmp_path / 'person.mediawiki').write_text(PERSON_RULES, encoding='utf-8')
    (tmp_path / 'notes.txt').write_text(OFFICEHOLDER_RULES, encoding='utf-8')
    other = tmp_path / 'officeholder.wiki'
    other.write_text(OFFICEHOLDER_RULES, encoding='utf-8')
    config = read_rules_files([str(tmp_path), str(other)])
    assert config.problems == []
    assert set(config.rulesets) == {'Infobox person', 'Infobox officeholder'}
    assert all(rs.active and (rs.page, rs.revision) == ('', None)
               for rs in config.rulesets.values())


def test_a_template_in_two_files_is_ignored(tmp_path):
    for name in ('a.mediawiki', 'b.mediawiki'):
        (tmp_path / name).write_text(PERSON_RULES, encoding='utf-8')
    config = read_rules_files([str(tmp_path)])
    assert config.rulesets == {}
    assert 'Infobox person has rules on two pages' in config.problems[0]
