"""Checking rule sets against the templates on the wiki."""

from fakes import OFFICEHOLDER_SOURCE, FakePage, FakeWiki

from parambot.prepare import category_problem, prepare, template_categories
from parambot.report import Report
from parambot.rules import parse_config
from parambot.templatescan import KnownParams

ANATOMY = 'Category:Anatomy infobox template using unknown parameters'
OFFICEHOLDER = 'Template:Infobox officeholder'


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


def test_missing_template():
    prepared, report = run_prepare(FakeWiki(), officeholder(('a', 'b')))
    assert prepared.ready == []
    assert report.problems == [
        'Template:Infobox officeholder does not exist, so its rules are switched off. '
        "Check the spelling in the table's caption."]


def test_template_without_a_parameter_list_is_switched_off():
    wiki = FakeWiki(FakePage(OFFICEHOLDER, '{{Infobox|above={{{name|}}}}}'))
    prepared, report = run_prepare(wiki, officeholder(('a', 'b')))
    assert prepared.ready == []
    assert 'has no list of accepted parameters' in report.problems[0]


def test_rules_that_wait_and_rules_that_cannot_work():
    wiki = FakeWiki(FakePage(OFFICEHOLDER, OFFICEHOLDER_SOURCE))
    prepared, report = run_prepare(
        wiki, officeholder(('term_end', 'termend'), ('termstart', 'term_strat')))
    assert len(prepared.ready) == 1
    assert report.notes == [
        'Infobox officeholder: 1 rule(s) wait because the template still accepts the old name '
        '(term_end). That is normal: they start working once the template drops those names. '
        'If a rule is backwards, swap its names.']
    assert any('Check the spelling of "term_strat"' in p for p in report.problems)


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
    assert template_categories(wiki, 'Infobox bone', known) == [ANATOMY]
    assert wiki.expanded == [known.unknown_text]


def test_plain_category_text_needs_no_expansion():
    wiki = FakeWiki()
    assert template_categories(wiki, 'Infobox bone', KnownParams(unknown_text=f'[[{ANATOMY}]]')) \
        == [ANATOMY]
    assert wiki.expanded == []


def test_expansion_failure_skips_the_check():
    wiki = FakeWiki()
    wiki.expand_error = ConnectionError('down')
    known = KnownParams(unknown_text='{{main other|x}}')
    assert template_categories(wiki, 'Infobox bone', known) is None


def _bone(caption_category=''):
    extra = f' watches [[:{caption_category}]]' if caption_category else ''
    return parse_config(table('Infobox bone', ('a', 'b'), caption_extra=extra)
                        ).rulesets['Infobox bone']


def test_category_matches():
    assert category_problem(_bone(ANATOMY), [ANATOMY]) is None
    assert category_problem(_bone(), [_bone().category]) is None


def test_category_differs_from_the_default():
    problem = category_problem(_bone(), [ANATOMY])
    assert 'not the usual Category:Pages using infobox bone with unknown parameters' in problem
    assert f'Add [[:{ANATOMY}]] to the caption of the Infobox bone table' in problem


def test_category_differs_from_the_caption():
    problem = category_problem(_bone('Category:Typo category'), [ANATOMY])
    assert 'caption says to watch Category:Typo category' in problem
    assert f"Change the caption's category link to [[:{ANATOMY}]]" in problem


def test_one_line_rules_are_told_to_use_a_table():
    rules = parse_config('* {{AWB rename template parameter|Infobox bone|a|b}}')
    problem = category_problem(rules.rulesets['Infobox bone'], [ANATOMY])
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
