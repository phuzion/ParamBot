import inspect
import re
import typing
from datetime import datetime

import pytest

from parambot import messages as msg
from parambot.fixer import Issue
from parambot.report import Links, Report

RULES = 'User:ExampleBot/Rules'
LINKS = Links(index=RULES, other=('Wikipedia:Requests for page protection',),
              rules_pages={'Infobox person': f'{RULES}/Infobox person',
                           'Infobox street': f'{RULES}/Infobox street'})


def test_report_roundtrip():
    report = Report()
    report.issue('Foo', Issue('Infobox person', 'alma_mater', 'education', 'both set'))
    report.skip('Bar', msg.SKIP_EXCLUDED)
    report.problems.append('Template:X does not exist')
    text = report.render('2026-09-26 00:00', live=True)
    assert '[[:Foo]]' in text
    assert '{{para|alma_mater}} → {{para|education}}' in text
    assert '* [[:Bar]]: excluded by {{tl|bots}}/{{tl|nobots}}' in text
    assert Report.body_of(text) == report.body()
    # A new run with the same findings has the same body, so no save is needed.
    later = report.render('2026-09-27 00:00', live=True)
    assert later != text
    assert Report.body_of(later) == Report.body_of(text)


def test_empty_report():
    assert Report().body() == (
        '== Needs human review ==\nNone.\n\n'
        '== Not edited ==\nNone.\n\n'
        '== Rules page problems ==\nNone.\n')


def test_setup_errors_and_notes_appear_only_when_there_are_some():
    report = Report(setup=['S'], errors=['E'], notes=['N'])
    body = report.body()
    assert body.startswith('== Setup problems ==\nA live run refuses to start until these are '
                           'fixed.\n* S\n\n== Errors ==\n')
    assert body.endswith('== Notes ==\n* N\n')


# -- the header and links --------------------------------------------------

def test_the_report_starts_with_the_header():
    text = Report(header='User:ExampleBot/Header').render('2026-09-30 00:00', live=True)
    assert text.startswith('{{User:ExampleBot/Header}}\n<!-- This page is rewritten')
    assert Report.body_of(text) == Report().body()


def test_a_problem_links_to_the_rules_page_it_is_about():
    # The bot's own sentences go on the report as they are.
    assert LINKS.wikitext('Infobox street: a row has a new name but no old name.') == (
        f'[[{RULES}/Infobox street|Infobox street]]: a row has a new name but no old name.')


def test_rules_pages_templates_the_index_and_diffs_are_linked():
    text = LINKS.wikitext(
        f'{RULES}/Infobox person has changed; review Special:Diff/10/12, then change the '
        f'revision on {RULES}. Template:Infobox person wraps nothing. Ask at Wikipedia:Requests '
        'for page protection.')
    assert text == (
        f'[[{RULES}/Infobox person|Infobox person]] has changed; review [[Special:Diff/10/12]], '
        f'then change the revision on [[{RULES}]]. [[Template:Infobox person]] wraps nothing. '
        'Ask at [[Wikipedia:Requests for page protection]].')


def test_only_whole_names_are_linked():
    # Not "Infobox persons" or "Infobox person/doc", a rules page the report
    # doesn't know, or an example revision.
    text = (f'Infobox persons, Infobox person/doc and {RULES}/Infobox other are fine; see '
            'Special:Permalink/1234567890.')
    assert LINKS.wikitext(text) == text


def test_a_name_that_cannot_be_a_title_is_not_linked():
    links = Links(rules_pages={'Bad]]name': f'{RULES}/Bad]]name'})
    assert links.wikitext('Bad]]name: oops') == 'Bad&#93;&#93;name: oops'
    assert links.rules_link('Bad]]name') == ''


# -- what each marked part of a message becomes ----------------------------

def test_parameters_are_shown_with_para():
    text = msg.target_not_accepted('Infobox street', 'widthh', 'width')
    assert LINKS.wikitext(text) == (
        f'[[{RULES}/Infobox street|Infobox street]]: the rule {{{{para|widthh}}}} → '
        '{{para|width}} renames to a parameter the template does not accept. Check the '
        'spelling of {{para|width}}.')
    # On the console, in quotes.
    assert msg.plain(text) == (
        'Infobox street: the rule "widthh" → "width" renames to a parameter the template does '
        'not accept. Check the spelling of "width".')


def test_a_name_that_cannot_go_in_para_is_shown_as_code():
    # Rules pages can hold anything, and some of it is reported.
    for name in ('a|b', 'a=b', '{{x}}', '</nowiki>'):
        assert '{{para' not in LINKS.wikitext(f'odd {msg.para(name)}')
    assert LINKS.wikitext(msg.para('a|b')) == '<code><nowiki>a|b</nowiki></code>'


def test_templates_are_named_with_tl():
    # Not {{nobots}} itself: on the report page, that would stop the bot
    # saving its report.
    assert LINKS.wikitext(msg.SKIP_EXCLUDED) == 'excluded by {{tl|bots}}/{{tl|nobots}}'
    assert msg.plain(msg.SKIP_EXCLUDED) == 'excluded by {{bots}}/{{nobots}}'
    # Nor {{bot}}, which would put the report in the bot categories.
    assert '{{tl|bot}}' in LINKS.wikitext(msg.user_page_without_bot_template('User:X'))


def test_code_to_copy_is_shown_as_code():
    text = msg.no_approved_revision('Infobox person', RULES, 'User:ExampleBot/LinkRule', 7)
    assert LINKS.wikitext(text).endswith(
        'list them as <code><nowiki>{{User:ExampleBot/LinkRule|Infobox person|7}}</nowiki></code>.')
    assert msg.plain(text).endswith('list them as {{User:ExampleBot/LinkRule|Infobox person|7}}.')


def test_text_from_a_rules_page_is_kept_in_nowiki():
    # Such as an "If both are set" cell saying {{yes}}, which would otherwise
    # put table styling in the middle of the report.
    text = msg.unclear_conflict_cell('Infobox person', 'alma_mater', '{{yes}} ~~~~')
    assert '"<nowiki>{{yes}} ~~~~</nowiki>"' in LINKS.wikitext(text)
    assert '"{{yes}} ~~~~"' in msg.plain(text)


def test_nothing_quoted_can_close_its_nowiki():
    assert (LINKS.wikitext(msg.quoted('</nowiki>[[Evil]]'))
            == '<nowiki>&lt;/nowiki>[[Evil]]</nowiki>')


@pytest.mark.parametrize('wikitext', [
    '{{nobots}}', '[[Category:Foo]]', '[[File:Foo.jpg]]', '~~~~', '__NOINDEX__', "''x''",
    '<b>x</b>', '<!-- x', 'a|b', 'a\nb', '&nbsp;'])
def test_wikitext_in_an_unmarked_message_does_nothing(wikitext):
    # The bot's own sentences have none of this, but anything unmarked from
    # elsewhere, such as a template's name, is made harmless anyway.
    text = LINKS.wikitext(f'odd {wikitext} text')
    for active in ('{{', '[[', '~~~', '__', "''", '<', '|', '\n', '&n'):
        assert active not in text


def _every_message():
    """(name, text) for every message function, called with sample arguments."""
    samples = {str: 'Infobox person', int: 7, float: 1.5, bool: True, list[str]: ['a', 'b'],
               Exception: ValueError('boom'), object: 'something'}
    skip = {'edit_summary', 'report_summary', 'excerpt', 'count', 'para', 'tl', 'code',
            'quoted', 'plain'}
    for name, function in inspect.getmembers(msg, inspect.isfunction):
        if name.startswith('_') or name in skip or function.__module__ != msg.__name__:
            continue
        hints = typing.get_type_hints(function)
        args = [datetime(2026, 9, 30) if p == 'when'
                else samples.get(hints.get(p), 'Infobox person')
                for p in inspect.signature(function).parameters]
        yield name, function(*args)
    for name in dir(msg):
        if name.startswith('SKIP_') or name == 'ANY_NAMESPACE_LIVE':
            yield name, getattr(msg, name)


# What the report puts in on purpose: links, {{para}}, {{tl}}, code and <nowiki>.
_ON_PURPOSE = re.compile(r'\{\{(?:para|tl)\|[^{}|]*\}\}|<code><nowiki>.*?</nowiki></code>'
                         r'|<nowiki>.*?</nowiki>|\[\[[^\[\]{}|]+(?:\|[^\[\]{}|]+)?\]\]')


@pytest.mark.parametrize('name, text', list(_every_message()))
def test_no_message_puts_live_wikitext_on_the_report(name, text):
    rest = _ON_PURPOSE.sub('·', LINKS.wikitext(text))   # not '', which makes new neighbours
    for active in ('{{', '}}', '[[', ']]', '<', '~~~', '__', "''"):
        assert active not in rest, f'{name}: {rest}'


@pytest.mark.parametrize('n, stats, summary', [
    (1, 'Polled 1 category, 1 populated; checked 1 page; made 1 edit.',
     'Updating report: 1 edit, 1 page needs review'),
    (2, 'Polled 2 categories, 2 populated; checked 2 pages; made 2 edits.',
     'Updating report: 2 edits, 2 pages need review'),
])
def test_counts_are_singular_or_plural(n, stats, summary):
    report = Report(categories_polled=n, categories_populated=n, pages_checked=n, edits=n)
    assert report.stats_line('2026-09-30 00:00', live=True).endswith(stats)
    assert msg.report_summary(n, n) == summary


def test_the_review_table_links_each_templates_rules():
    report = Report(links=LINKS)
    report.issue('Foo', Issue('Infobox person', 'alma_mater', 'education', 'both set'))
    assert (f'[[Template:Infobox person|Infobox person]] ([[{RULES}/Infobox person|rules]])'
            in report.body())
