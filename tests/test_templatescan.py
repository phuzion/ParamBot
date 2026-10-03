import pytest

from parambot.rules import parse_config
from parambot.templatescan import (
    KnownParams,
    WrappedParams,
    Wrapper,
    _to_number_form,
    categories_in,
    known_params,
    scaffold_table,
    wrapper_call,
)

UNKNOWN = ('{{main other|[[Category:Pages using infobox example with unknown parameters'
           '|_VALUE_{{PAGENAME}}]]}}')
DEPRECATED = ('{{main other|[[Category:Pages using infobox example with deprecated parameters'
              '|_VALUE_]]}}')
TEMPLATE = '''{{Infobox
| above = {{{name|}}}
}}<!-- Check for unknowns
-->{{#invoke:Check for unknown parameters|check|unknown=UNKNOWN
|preview = Page using [[Template:Infobox example]] with unknown parameter "_VALUE_"
|ignoreblank=y|mapframe_args=y
| alt | image | image_size | caption
| name | type <!-- new
      parameters -->
| regexp1 = custom_label[1-9]_sec[1-9]
}}{{#invoke:Check for deprecated parameters|check
| _category = DEPRECATED
| _remove = old_thing; other_thing
| imagesize = image_size
| _regexp1 = blank(%d*)_name = custom_label%1_sec1
}}<noinclude>{{documentation}}</noinclude>'''.replace('UNKNOWN', UNKNOWN).replace(
    'DEPRECATED', DEPRECATED)


def test_known_params():
    known = known_params(TEMPLATE)
    assert 'image_size' in known
    assert 'type' in known
    assert 'custom_label3_sec2' in known
    assert 'mapframe-zoom' in known        # from mapframe_args=y
    assert 'imagesize' not in known
    assert 'check' not in known            # the module function name
    assert 'unknown' not in known


def test_unknown_category_text():
    text = known_params(TEMPLATE).unknown_text
    assert text == ('{{main other|[[Category:Pages using infobox example with unknown '
                    'parameters|_VALUE_{{PAGENAME}}]]}}')
    assert categories_in(text) == ['Category:Pages using infobox example with unknown parameters']


def test_categories_in():
    assert categories_in('[[Category:Anatomy infobox template using unknown parameters|_VALUE_X]]'
                         ' [[ category : anatomy infobox template using unknown parameters ]]'
                         ' [[:Category:Other]] [[Not a category]]') == [
        'Category:Anatomy infobox template using unknown parameters', 'Category:Other']
    assert categories_in('Found _VALUE_, ') == []


def test_why_a_name_is_accepted():
    known = known_params(TEMPLATE)
    assert 'coord' in known
    assert known.added_by('coord') == 'mapframe_args'     # only because of mapframe_args=y
    assert known.added_by('image_size') is None           # the template's own list
    assert known.added_by('custom_label3_sec2') is None   # its own pattern
    assert known.added_by('nonsense') is None             # not accepted at all
    # Listed by the template itself as well: its own list wins.
    listed = known_params('{{#invoke:Check for unknown parameters|check|mapframe_args=y| coord }}')
    assert listed.added_by('coord') is None


def test_why_a_wrapper_accepts_a_name():
    inner = KnownParams({'birth_name'}, extras={'coord': 'mapframe_args'})
    known = WrappedParams(wrapper_call(WRAPPER), inner)
    assert known.added_by('coord') == 'mapframe_args'     # passed on to the map settings
    assert known.added_by('service_years') is None        # the wrapper uses it itself
    assert known.added_by('birth_name') is None


def test_known_params_absent():
    assert known_params('{{Infobox|above={{{name|}}}}}') is None


@pytest.mark.parametrize('pattern', ['%f[%w]term', '%b()', '[%q]'])
def test_a_pattern_the_bot_cannot_read_means_no_list(pattern):
    # It might accept any name at all, so the bot can't tell what the
    # template accepts, and mustn't guess.
    source = ('{{#invoke:Check for unknown parameters|check|unknown=[[Category:X]]'
              f'| name | regexp1 = {pattern} }}}}')
    assert known_params(source) is None


# -- wrapper templates -----------------------------------------------------

# Like Infobox military person and Infobox person.
WRAPPER = '''<includeonly>{{#invoke:Template wrapper|wrap|_template = Infobox person
| _alias-map = other_name:other_names, relations:relatives, office#:post#
| _exclude   = allegiance, service_years, <!-- for now --> battles
| _reuse     = known_for
| template_name = Infobox military person
| embed_title = Military career
}}</includeonly><noinclude>{{Documentation}}</noinclude>'''
WRAPPED = ('{{#invoke:Check for unknown parameters|check|unknown={{main other|'
           '[[Category:Pages using {{if empty|{{lcfirst:{{{template_name|}}}}}'
           '|infobox person}} with unknown parameters|_VALUE_{{PAGENAME}}]]}}'
           '| birth_name | other_names | relatives | known_for | template_name | embed_title'
           '| regexp1 = post[0-9]+ }}')


def test_wrapper_call():
    assert wrapper_call(WRAPPER) == Wrapper(
        template='Infobox person',
        keeps=frozenset({'allegiance', 'service_years', 'battles', 'known_for'}),
        aliases={'other_name': 'other_names', 'relations': 'relatives', 'office#': 'post#'},
        args={'template_name': 'Infobox military person', 'embed_title': 'Military career'})


@pytest.mark.parametrize('name, passed', [
    ('birth_name', 'birth_name'),     # passed on as it is
    ('other_name', 'other_names'),    # an alias
    ('office2', 'post2'),             # a numbered alias
    ('office', 'post'),               # ... without its number
    ('service_years', None),          # excluded: the wrapper uses it itself
    ('known_for', None),              # reused: the same
])
def test_what_a_wrapper_passes_on(name, passed):
    assert wrapper_call(WRAPPER).passes(name) == passed


def test_a_wrapper_accepts_what_it_keeps_and_what_it_passes_on_that_is_accepted():
    known = WrappedParams(wrapper_call(WRAPPER), known_params(WRAPPED))
    for name in ('birth_name', 'other_name', 'other_names', 'office3', 'post3',
                 'service_years', 'battles', 'known_for'):
        assert name in known, name
    for name in ('serviceyears', 'birthname', 'office', 'relations2'):
        assert name not in known, name


def test_a_wrapper_gives_the_template_it_wraps_its_category():
    known = WrappedParams(wrapper_call(WRAPPER), known_params(WRAPPED))
    assert known.unknown_text == (
        '{{main other|[[Category:Pages using {{if empty|{{lcfirst:Infobox military person}}'
        '|infobox person}} with unknown parameters|_VALUE_{{PAGENAME}}]]}}')


def test_a_wrapper_of_a_wrapper():
    outer = wrapper_call('{{#invoke:Template wrapper|wrap|_template=Infobox military person'
                         '|_exclude=regiment|_alias-map=born_as:birth_name'
                         '|template_name=Infobox soldier}}')
    known = WrappedParams(outer, WrappedParams(wrapper_call(WRAPPER), known_params(WRAPPED)))
    for name in ('regiment', 'born_as', 'service_years', 'other_name', 'birth_name'):
        assert name in known, name
    assert 'serviceyears' not in known
    # The outer wrapper's template_name wins.
    assert '{{lcfirst:Infobox soldier}}' in known.unknown_text


@pytest.mark.parametrize('source', [
    '{{Infobox|above={{{name|}}}}}',                                   # not a wrapper
    '{{#invoke:Template wrapper|list|_template=Infobox person}}',       # only shows a call
    '{{#invoke:Template wrapper|wrap|template_name=Infobox person}}',   # wraps nothing
    '{{#invoke:Template wrapper|wrap|_template={{{type|Infobox person}}}}}',
    '{{#invoke:Template wrapper|wrap|_template=Infobox person|_exclude={{{keep|}}}}}',
    '{{#if:{{{a|}}}|{{#invoke:Template wrapper|wrap|_template=A}}'
    '|{{#invoke:Template wrapper|wrap|_template=B}}}}',                # it picks one
])
def test_wrappers_the_bot_cannot_read(source):
    assert wrapper_call(source) is None


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
    assert _to_number_form(pattern, replacement) == expected


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
