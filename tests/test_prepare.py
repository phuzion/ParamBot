"""Checking rule sets against the templates on the wiki."""

import pytest
from fakes import OFFICEHOLDER_SOURCE, UNKNOWN_CHECK_SOURCE, FakePage, FakeWiki

from parambot import messages as msg
from parambot.fixer import fix_wikitext
from parambot.messages import plain
from parambot.prepare import category_problem, prepare, template_categories
from parambot.report import Report
from parambot.rules import parse_config
from parambot.templatescan import UNKNOWN_CHECK_MODULE, KnownParams

ANATOMY = 'Category:Anatomy infobox template using unknown parameters'
OFFICEHOLDER = 'Template:Infobox officeholder'
MODULE = FakePage(UNKNOWN_CHECK_MODULE, UNKNOWN_CHECK_SOURCE)


def table(template, *pairs, caption_extra=''):
    rows = ''.join(f'|-\n| {{{{para|{old}}}}} || {{{{para|{new}}}}}\n' for old, new in pairs)
    return f'{{|\n|+ {{{{tl|{template}}}}}{caption_extra}\n{rows}|}}\n'


def officeholder(*pairs):
    return parse_config(table('Infobox officeholder', *pairs)).rulesets['Infobox officeholder']


def run_prepare(wiki, *rulesets):
    report = Report()
    return prepare(wiki, rulesets, report), report


# -- prepare ---------------------------------------------------------------

def test_a_usable_template():
    redirect = FakePage('Template:Infobox politician')
    wiki = FakeWiki(FakePage(OFFICEHOLDER, OFFICEHOLDER_SOURCE, redirects=[redirect]))
    prepared, report = run_prepare(wiki, officeholder(('termstart', 'term_start')))
    [target] = prepared.ready
    assert target.names == {'Infobox officeholder', 'Infobox politician'}
    assert target.still_accepts('term_start') and target.rejects('termstart')
    assert (report.problems, report.notes) == ([], [])


def test_a_template_given_as_a_redirect():
    target_page = FakePage(OFFICEHOLDER, OFFICEHOLDER_SOURCE)
    wiki = FakeWiki(FakePage('Template:Infobox politician', redirect_to=target_page))
    rules = parse_config(table('Infobox politician', ('termstart', 'term_start')))
    prepared, _ = run_prepare(wiki, rules.rulesets['Infobox politician'])
    assert prepared.ready[0].names == {'Infobox politician', 'Infobox officeholder'}
    assert prepared.redirected == {'Infobox politician': 'Infobox officeholder'}


def test_rules_for_a_redirect_give_way_to_the_templates_own():
    target_page = FakePage(OFFICEHOLDER, OFFICEHOLDER_SOURCE)
    wiki = FakeWiki(target_page, FakePage('Template:Infobox politician', redirect_to=target_page))
    config = parse_config(table('Infobox politician', ('termend', 'term_end'))
                          + table('Infobox officeholder', ('termstart', 'term_start')))
    own = config.rulesets['Infobox officeholder']
    own.page = 'User:ExampleBot/Rules/Infobox officeholder'
    prepared, report = run_prepare(wiki, config.rulesets['Infobox politician'], own)
    assert [target.template for target in prepared.ready] == ['Infobox officeholder']
    assert report.problems[-1] == (
        'Template:Infobox politician redirects to Template:Infobox officeholder, which has rules '
        'of its own, so the bot ignored the Infobox politician rules. Move them to '
        'User:ExampleBot/Rules/Infobox officeholder.')


def test_rules_for_two_redirects_to_one_template_are_both_dropped():
    target_page = FakePage(OFFICEHOLDER, OFFICEHOLDER_SOURCE)
    wiki = FakeWiki(target_page, *(FakePage(f'Template:{name}', redirect_to=target_page)
                                   for name in ('Infobox politician', 'Infobox senator')))
    config = parse_config(table('Infobox politician', ('termstart', 'term_start'))
                          + table('Infobox senator', ('termend', 'term_end')))
    prepared, report = run_prepare(wiki, *config.rulesets.values())
    assert prepared.ready == []
    assert report.problems[-1] == (
        'Infobox politician and Infobox senator are the same template (Template:Infobox '
        'officeholder), so the bot ignored their rules. Put them on one page, named after '
        'Infobox officeholder.')


def test_missing_template():
    prepared, report = run_prepare(FakeWiki(), officeholder(('a', 'b')))
    assert prepared.ready == []
    assert report.problems == [
        'Template:Infobox officeholder does not exist, so its rules are switched off. '
        'Check the spelling of its name.']


def test_template_without_a_parameter_list_is_switched_off():
    wiki = FakeWiki(FakePage(OFFICEHOLDER, '{{Infobox|above={{{name|}}}}}'))
    prepared, report = run_prepare(wiki, officeholder(('a', 'b')))
    assert prepared.ready == []
    assert 'has no list of accepted parameters' in report.problems[0]


def test_template_with_a_pattern_the_bot_cannot_read_is_switched_off():
    # The pattern might accept the old name, so applying the rules could
    # rename a parameter the template still uses.
    source = OFFICEHOLDER_SOURCE.replace(' term_end }}', ' term_end | regexp1 = %f[%a]term }}')
    wiki = FakeWiki(FakePage(OFFICEHOLDER, source))
    prepared, report = run_prepare(wiki, officeholder(('termstart', 'term_start')))
    assert prepared.ready == []
    assert 'has no list of accepted parameters' in report.problems[0]


# -- wrapper templates -----------------------------------------------------

PERSON = 'Template:Infobox person'
MILITARY_PERSON = 'Template:Infobox military person'
# Infobox person names its category after the template_name it's given.
PERSON_SOURCE = ('{{#invoke:Check for unknown parameters|check|unknown={{main other|'
                 '[[Category:Pages using {{lcfirst:{{{template_name|Infobox person}}}}} with '
                 'unknown parameters|_VALUE_]]}}| birth_name | burial_place | template_name }}')
MILITARY_PERSON_SOURCE = ('{{#invoke:Template wrapper|wrap|_template=Infobox person'
                          '|_exclude=service_years|template_name=Infobox military person}}')


def military_person(*pairs):
    return parse_config(table('Infobox military person', *pairs)).rulesets[
        'Infobox military person']


def test_a_wrapper_uses_the_list_of_the_template_it_wraps():
    wiki = FakeWiki(FakePage(PERSON, PERSON_SOURCE),
                    FakePage(MILITARY_PERSON, MILITARY_PERSON_SOURCE))
    prepared, report = run_prepare(wiki, military_person(
        ('serviceyears', 'service_years'), ('placeofburial', 'burial_place')))
    [target] = prepared.ready
    assert target.names == {'Infobox military person'}
    assert target.still_accepts('service_years') and target.still_accepts('burial_place')
    assert target.rejects('serviceyears')
    # No problems: the category, named after the wrapper, is the one it watches.
    assert (report.problems, report.notes) == ([], [])
    result = fix_wikitext('{{Infobox military person\n| serviceyears = 1959–1988\n}}',
                          prepared.ready)
    assert 'service_years' in result.text and 'serviceyears' not in result.text


def test_a_wrapper_is_followed_through_a_redirect():
    person = FakePage(PERSON, PERSON_SOURCE)
    wiki = FakeWiki(person, FakePage('Template:Infobox human', redirect_to=person),
                    FakePage(MILITARY_PERSON,
                             MILITARY_PERSON_SOURCE.replace('Infobox person', 'Infobox human')))
    prepared, report = run_prepare(wiki, military_person(('serviceyears', 'service_years')))
    assert len(prepared.ready) == 1
    assert report.problems == []


@pytest.mark.parametrize('person', [FakePage(PERSON, '{{Infobox}}'),
                                    FakePage(PERSON, exists=False)])
def test_a_wrapper_of_a_template_without_a_list_is_switched_off(person):
    wiki = FakeWiki(person, FakePage(MILITARY_PERSON, MILITARY_PERSON_SOURCE))
    prepared, report = run_prepare(wiki, military_person(('serviceyears', 'service_years')))
    assert prepared.ready == []
    assert [plain(p) for p in report.problems] == [
        'Template:Infobox military person has no list of accepted parameters the bot can read (a '
        '{{#invoke:Check for unknown parameters|check|...}} call), and neither does the template '
        'it passes its parameters on to (Template:Infobox person), so its rules are switched off.']


@pytest.mark.parametrize('kept, problems', [
    # Like Infobox clergy and Infobox medical person: Infobox person accepts
    # name too, so it doesn't matter which pages the wrapper keeps it on.
    ('birth_name', []),
    ('crest', ['Template:Infobox military person keeps "crest" for itself on some pages only '
               '(an {{#if:...}} in its _exclude or _reuse), and passes it on to a template that '
               "doesn't accept it on the rest, so the bot can't tell which parameters an article "
               'may use. Its rules are switched off.']),
])
def test_a_wrapper_that_keeps_a_name_on_some_pages(kept, problems):
    source = MILITARY_PERSON_SOURCE.replace(
        '_exclude=service_years', f'_exclude={{{{#if:{{{{{{child|}}}}}}|{kept},}}}}service_years')
    wiki = FakeWiki(FakePage(PERSON, PERSON_SOURCE), FakePage(MILITARY_PERSON, source))
    prepared, report = run_prepare(wiki, military_person(('serviceyears', 'service_years')))
    assert len(prepared.ready) == (0 if problems else 1)
    assert [plain(p) for p in report.problems] == problems


def test_many_wrappers_of_one_template_load_it_once():
    # Dozens of templates wrap Infobox settlement.
    wrappers = [FakePage(f'Template:Infobox person {i}', MILITARY_PERSON_SOURCE.replace(
        'Infobox military person', f'Infobox person {i}')) for i in range(30)]
    wiki = FakeWiki(FakePage(PERSON, PERSON_SOURCE), *wrappers)
    config = parse_config(''.join(table(f'Infobox person {i}', ('serviceyears', 'service_years'))
                                  for i in range(30)))
    prepared, report = run_prepare(wiki, *config.rulesets.values())
    assert len(prepared.ready) == 30
    assert report.problems == []
    assert wiki.requests['load'] == 2   # the 30 templates, then Infobox person


def test_wrappers_that_wrap_each_other_are_switched_off():
    wiki = FakeWiki(FakePage(MILITARY_PERSON, MILITARY_PERSON_SOURCE), FakePage(
        PERSON, '{{#invoke:Template wrapper|wrap|_template=Infobox military person}}'))
    prepared, report = run_prepare(wiki, military_person(('serviceyears', 'service_years')))
    assert prepared.ready == []
    assert ('(Template:Infobox person, then Template:Infobox military person, then '
            'Template:Infobox person, ') in report.problems[0]


def test_rules_that_wait_and_rules_that_cannot_work():
    wiki = FakeWiki(FakePage(OFFICEHOLDER, OFFICEHOLDER_SOURCE))
    prepared, report = run_prepare(
        wiki, officeholder(('term_end', 'termend'), ('termstart', 'term_strat')))
    assert len(prepared.ready) == 1
    assert [plain(note) for note in report.notes] == [
        'Infobox officeholder: 1 rule waits because the template still accepts its old name, '
        '"term_end". That is normal: the rule starts working once the template drops that '
        'name. If the rule is backwards, swap its names.']
    assert any('Check the spelling of "term_strat"' in plain(p) for p in report.problems)


def test_rules_for_map_parameters_the_check_adds_are_not_needed():
    # mapframe_args=y makes the check accept id, though nothing in the
    # template's own code mentions it.  Not coord, which the module dropped
    # from its list: that rule is needed.
    source = OFFICEHOLDER_SOURCE.replace('| name |', '| mapframe_args = y | name |')
    wiki = FakeWiki(FakePage(OFFICEHOLDER, source), MODULE)
    _, report = run_prepare(wiki, officeholder(
        ('coord', 'coordinates'), ('id', 'coordinates'), ('term_end', 'term_start')))
    assert [plain(note) for note in report.notes] == [
        'Infobox officeholder: 1 rule waits because the template still accepts its old name, '
        '"term_end". That is normal: the rule starts working once the template drops that '
        'name. If the rule is backwards, swap its names.',
        "Infobox officeholder: 1 rule isn't needed, because \"id\" is one of the map "
        'parameters that Module:Check for unknown parameters accepts for any template with '
        'mapframe_args=y. Delete the rule unless the template stops using mapframe_args.']
    assert report.problems == []


@pytest.mark.parametrize('module', [
    FakePage(UNKNOWN_CHECK_MODULE, exists=False),
    FakePage(UNKNOWN_CHECK_MODULE, 'return {}'),     # changed beyond recognition
    FakePage(UNKNOWN_CHECK_MODULE, broken=True),     # couldn't be read
])
def test_without_the_modules_map_parameters_map_templates_are_switched_off(module, caplog):
    # Without the module's list, the bot can't tell which names a template
    # with mapframe_args=y accepts, so it mustn't guess, or use an old copy.
    mapped = FakePage(OFFICEHOLDER, OFFICEHOLDER_SOURCE.replace(
        '| name |', '| mapframe_args = y | name |'))
    plain_template = FakePage('Template:Infobox person', PERSON_SOURCE)
    wiki = FakeWiki(mapped, plain_template, module)
    config = parse_config(table('Infobox officeholder', ('termstart', 'term_start'))
                          + table('Infobox person', ('birthname', 'birth_name')))
    prepared, report = run_prepare(wiki, *config.rulesets.values())
    # Templates that don't use those settings carry on as usual.
    assert [target.template for target in prepared.ready] == ['Infobox person']
    assert [plain(p) for p in report.problems if 'map parameters' in p] == [
        'Template:Infobox officeholder uses mapframe_args=y, which makes Module:Check for '
        "unknown parameters accept a list of map parameters too, but the bot couldn't read "
        "that list from the module, so it can't tell which parameters the template accepts, "
        'and its rules are switched off. If the module has changed, tell the operators: the '
        'bot may need updating.']
    assert any(UNKNOWN_CHECK_MODULE in m for m in caplog.messages)


def test_a_wrapper_of_a_map_template_is_switched_off_without_the_list():
    wrapped = FakePage('Template:Infobox settlement',
                       OFFICEHOLDER_SOURCE.replace('| name |', '| pushpin_map_args = y | name |'))
    wrapper = FakePage('Template:Infobox town',
                       '{{#invoke:Template wrapper|wrap|_template=Infobox settlement}}')
    wiki = FakeWiki(wrapped, wrapper)   # no module
    config = parse_config(table('Infobox town', ('termstart', 'term_start')))
    prepared, report = run_prepare(wiki, *config.rulesets.values())
    assert prepared.ready == []
    assert 'Template:Infobox town uses pushpin_map_args=y' in plain(report.problems[0])


def test_the_module_is_read_once_a_run_and_only_when_there_are_templates():
    reads = []

    class CountingWiki(FakeWiki):
        def page(self, title, ns=0):
            if title == UNKNOWN_CHECK_MODULE:
                reads.append(title)
            return super().page(title, ns)
    many = [FakePage(f'Template:Infobox {i}', OFFICEHOLDER_SOURCE.replace(
        '| name |', '| mapframe_args = y | name |')) for i in range(3)]
    config = parse_config(''.join(table(f'Infobox {i}', ('a', 'name')) for i in range(3)))
    run_prepare(CountingWiki(*many, MODULE), *config.rulesets.values())
    assert reads == [UNKNOWN_CHECK_MODULE]
    reads.clear()
    run_prepare(CountingWiki(MODULE))
    assert reads == []


def test_one_rule_that_is_not_needed():
    assert plain(msg.rules_not_needed('Infobox monastery', ['qid'], 'mapframe_args')) == (
        "Infobox monastery: 1 rule isn't needed, because \"qid\" is one of the map parameters "
        'that Module:Check for unknown parameters accepts for any template with '
        'mapframe_args=y. Delete the rule unless the template stops using mapframe_args.')


def test_several_waiting_rules_are_counted_properly():
    assert plain(msg.rules_waiting('T', ['a', 'b'])) == (
        'T: 2 rules wait because the template still accepts their old names, "a" and "b". '
        'That is normal: they start working once the template drops those names. If a rule '
        'is backwards, swap its names.')


def test_wrong_category_is_reported_and_remembered():
    source = OFFICEHOLDER_SOURCE.replace(
        'Pages using infobox officeholder with unknown parameters', 'Some other category')
    prepared, report = run_prepare(FakeWiki(FakePage(OFFICEHOLDER, source)),
                                   officeholder(('termstart', 'term_start')))
    assert prepared.wrong_category == {'Infobox officeholder'}
    assert 'puts articles with unknown parameters in Category:Some other category' in \
        report.problems[0]


# -- which category a template uses ----------------------------------------

def test_template_categories_are_expanded_as_for_an_article():
    wiki = FakeWiki()
    known = KnownParams(unknown_text=f'{{{{main other|[[{ANATOMY}|_VALUE_{{{{PAGENAME}}}}]]}}}}')
    assert template_categories(wiki, [known]) == [[ANATOMY]]
    assert wiki.expanded == [known.unknown_text]


def test_plain_category_text_needs_no_expansion():
    wiki = FakeWiki()
    assert template_categories(wiki, [KnownParams(unknown_text=f'[[{ANATOMY}]]'),
                                      KnownParams()]) == [[ANATOMY], []]
    assert wiki.expanded == []


def test_expansion_failure_skips_the_check():
    wiki = FakeWiki()
    wiki.expand_error = ConnectionError('down')
    knowns = [KnownParams(unknown_text='{{main other|x}}'),
              KnownParams(unknown_text=f'[[{ANATOMY}]]')]
    assert template_categories(wiki, knowns) == [None, [ANATOMY]]


def test_many_templates_need_one_request_for_redirects_and_one_for_categories():
    # A request for each template got the bot rate-limited (HTTP 429) once
    # there were 87 of them.
    names = [f'Infobox test {i}' for i in range(60)]
    wiki = FakeWiki(*(FakePage(
        f'Template:{name}',
        '{{#invoke:Check for unknown parameters|check|unknown={{main other|'
        f'[[Category:Pages using infobox test {i} with unknown parameters|_VALUE_]]}}}}| new }}}}',
        redirects=[FakePage(f'Template:Test {i}')]) for i, name in enumerate(names)))
    config = parse_config(''.join(table(name, ('old', 'new')) for name in names))
    prepared, report = run_prepare(wiki, *config.rulesets.values())
    assert len(prepared.ready) == 60
    assert prepared.ready[7].names == {'Infobox test 7', 'Test 7'}
    assert (report.problems, report.notes) == ([], [])
    assert wiki.requests == {'load': 1, 'redirects': 1, 'expand': 1}


def _bone(caption_category=''):
    extra = f' watches [[:{caption_category}]]' if caption_category else ''
    return parse_config(table('Infobox bone', ('a', 'b'), caption_extra=extra)
                        ).rulesets['Infobox bone']


def test_category_matches():
    assert category_problem(_bone(ANATOMY), [ANATOMY]) is None
    assert category_problem(_bone(), [_bone().category]) is None


def test_category_differs_from_the_default():
    problem = plain(category_problem(_bone(), [ANATOMY]))
    assert 'not the usual Category:Pages using infobox bone with unknown parameters' in problem
    assert f'Add [[:{ANATOMY}]] to the caption of the Infobox bone table' in problem


def test_category_differs_from_the_caption():
    problem = plain(category_problem(_bone('Category:Typo category'), [ANATOMY]))
    assert 'caption says to watch Category:Typo category' in problem
    assert f"Change the caption's category link to [[:{ANATOMY}]]" in problem


def test_one_line_rules_are_told_to_use_a_table():
    rules = parse_config('* {{AWB rename template parameter|Infobox bone|a|b}}')
    problem = plain(category_problem(rules.rulesets['Infobox bone'], [ANATOMY]))
    assert "One-line rules can't name a category" in problem
    assert f'a table with [[:{ANATOMY}]] in its caption' in problem


def test_template_without_a_category():
    assert "doesn't put articles with unknown parameters in any category" in \
        category_problem(_bone(), [])


def test_category_unknown_is_not_a_problem():
    assert category_problem(_bone(), None) is None


def test_explicit_category_overrides_a_default_from_another_table():
    config = parse_config(table('Infobox bone', ('a', 'b'))
                          + table('Infobox bone', ('c', 'd'), caption_extra=f' [[:{ANATOMY}]]'))
    assert config.problems == []
    assert config.rulesets['Infobox bone'].category == ANATOMY
