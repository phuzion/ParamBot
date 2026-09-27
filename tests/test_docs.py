"""Keep the rule writers' instructions honest.

The instructions (docs/rules-instructions.wiki) are the only documentation
most rule writers will read, so their examples must actually work.
"""

import re
from pathlib import Path

import pytest

from parambot.rules import AWB_TEMPLATE, REMOVE, parse_config

DOC = (Path(__file__).parent.parent / 'docs' / 'rules-instructions.wiki').read_text(encoding='utf-8')
EXAMPLE_RE = re.compile(r'<syntaxhighlight lang="wikitext">\n(.*?)</syntaxhighlight>', re.S)
EXAMPLES = EXAMPLE_RE.findall(DOC)


def _section(heading):
    # Look for headings with the examples blanked out, since examples
    # contain headings of their own.
    masked = EXAMPLE_RE.sub(lambda m: re.sub(r'[^\n]', ' ', m.group(0)), DOC)
    m = re.search(rf'^== {re.escape(heading)} ==\n(.*?)(?=^== |\Z)', masked, re.M | re.S)
    assert m, f'no section {heading!r}'
    return DOC[m.start(1):m.end(1)]


def _examples_in(heading):
    return EXAMPLE_RE.findall(_section(heading))


def test_instructions_contain_no_live_rules():
    # If the instructions end up on the rules page itself, the bot must not
    # obey any of their examples, or complain about the doc's own tables.
    config = parse_config(DOC)
    assert config.rulesets == {}
    assert config.problems == []


def test_there_are_examples():
    assert len(EXAMPLES) >= 5


@pytest.mark.parametrize('example', EXAMPLES, ids=lambda e: e.splitlines()[0][:40])
def test_examples_are_valid(example):
    config = parse_config(example)
    assert config.problems == []
    assert config.rulesets, 'example defines no rules'
    assert all(len(rs) for rs in config.rulesets.values())


def test_adding_a_template_example():
    rs = parse_config(_examples_in('Adding a template')[0]).rulesets['Infobox settlement']
    assert {k: r.new for k, r in rs.renames.items()} == {
        'settlement_type': 'type', 'imagesize': 'image_size', 'image_caption': 'caption'}


def test_writing_rows_example_and_number_table():
    section = _section('Writing rows')
    rs = parse_config(EXAMPLE_RE.findall(section)[0]).rulesets['Infobox officeholder']
    assert rs.renames['spouse(s)'].new == 'spouse'
    assert rs.renames['spouses'].new == 'spouse'      # via rowspan
    assert rs.lookup('nationality').rule.kind == REMOVE
    rows = re.findall(r'^\| <code>([^<]+)</code> \|\| (.+)$', section, re.M)
    assert len(rows) == 4
    for old, result in rows:
        m = re.fullmatch(r'<code>([^<]+)</code>', result)
        if m:
            assert rs.lookup(old).target == m.group(1)
        else:
            assert 'no change' in result
            assert rs.lookup(old) is None


def test_merge_example():
    rs = parse_config(_examples_in('If both parameters are filled in')[0]).rulesets['Infobox person']
    assert rs.renames['alma_mater'].conflict == 'merge'
    assert rs.renames['other_name'].conflict == 'skip'


def test_category_example():
    rs = parse_config(_examples_in('A template with an unusual category')[0]).rulesets['Infobox bone']
    assert rs.category == 'Category:Anatomy infobox template using unknown parameters'
    assert rs.category_explicit


def test_one_line_example():
    example = _examples_in('The one-line format')[0]
    assert AWB_TEMPLATE in example
    rs = parse_config(example).rulesets['Infobox officeholder']
    assert rs.lookup('termstart4').target == 'term_start4'
