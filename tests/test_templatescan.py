import pytest

from parambot.rules import parse_config
from parambot.templatescan import _pattern_to_hash, known_params, scaffold_table

TEMPLATE = '''{{Infobox
| above = {{{name|}}}
}}<!-- Check for unknowns
-->{{#invoke:Check for unknown parameters|check|unknown={{main other|[[Category:Pages using infobox example with unknown parameters|_VALUE_{{PAGENAME}}]]}}|preview = Page using [[Template:Infobox example]] with unknown parameter "_VALUE_"|ignoreblank=y|mapframe_args=y
| alt | image | image_size | caption
| name | type <!-- new
      parameters -->
| regexp1 = custom_label[1-9]_sec[1-9]
}}{{#invoke:Check for deprecated parameters|check
| _category = {{main other|[[Category:Pages using infobox example with deprecated parameters|_VALUE_]]}}
| _remove = old_thing; other_thing
| imagesize = image_size
| _regexp1 = blank(%d*)_name = custom_label%1_sec1
}}<noinclude>{{documentation}}</noinclude>'''


def test_known_params():
    known = known_params(TEMPLATE)
    assert 'image_size' in known
    assert 'type' in known
    assert 'custom_label3_sec2' in known
    assert 'mapframe-zoom' in known        # from mapframe_args=y
    assert 'imagesize' not in known
    assert 'check' not in known            # the module function name
    assert 'unknown' not in known


def test_known_params_absent():
    assert known_params('{{Infobox|above={{{name|}}}}}') is None


def test_scaffold_roundtrip():
    table, warnings = scaffold_table('infobox_example', TEMPLATE)
    assert warnings == []
    assert table.startswith('{| class="wikitable"\n|+ {{tl|Infobox example}}\n')
    assert '| {{para|blank#_name}} || {{para|custom_label#_sec1}}' in table
    assert '| {{para|old_thing}} || remove' in table
    assert 'deprecated parameters' not in table   # _category is left out
    config = parse_config(table)
    assert config.problems == []
    rs = config.rulesets['Infobox example']
    assert rs.renames['imagesize'].new == 'image_size'
    assert rs.lookup('blank2_name').target == 'custom_label2_sec1'
    assert set(rs.removes) == {'old_thing', 'other_thing'}


@pytest.mark.parametrize('pattern, replacement, expected', [
    ('blank(%d*)_name', 'custom_label%1_sec1', ('blank#_name', 'custom_label#_sec1')),
    ('blank(%d*)_info_sec(%d)', 'custom_data%1_sec%2', ('blank#_info_sec#', 'custom_data#_sec#')),
    ('map%-size(%d+)', 'map_size%1', ('map-size#', 'map_size#')),
    ('image(%d?)', 'image%1', ('image#', 'image#')),
    # Not expressible with "#": left for a human.
    ('blank(%d*)_name', 'custom%1_label%1', None),       # a number used twice
    ('(%d*)blank(%d*)', 'x%2y%1', None),                  # numbers swapped
    ('[ab](%d*)', 'c%1', None),                           # a set
    ('foo.(%d*)', 'bar%1', None),                         # "." means any character
    ('mapframe-zoom(%d*)', 'zoom%1', None),               # "-" is a quantifier
    ('%a+(%d*)', 'x%1', None),                            # a class
    ('foo', 'bar', None),                                 # no number at all
])
def test_pattern_conversion(pattern, replacement, expected):
    assert _pattern_to_hash(pattern, replacement) == expected


def test_scaffold_reports_unconvertible_patterns():
    source = '''{{#invoke:Check for deprecated parameters|check
| a = b
| _regexp1 = [ab](%d*) = c%1
}}'''
    table, warnings = scaffold_table('T', source)
    assert warnings == ['_regexp1 = [ab](%d*) = c%1']
    assert '<!-- Could not turn "_regexp1 = [ab](%d*) = c%1" into a row.' in table
    assert parse_config(table).rulesets['T'].renames['a'].new == 'b'


def test_scaffold_without_deprecated_check():
    assert scaffold_table('X', '{{Infobox}}') == (None, [])
