import textwrap

import pytest

from parambot.fixer import fix_wikitext
from parambot.rules import parse_config
from parambot.templatescan import KnownParams

RULES = '''
{| class="wikitable"
|+ {{tl|Infobox settlement}}
! Old !! New
|-
| {{para|imagesize}} || {{para|image_size}}
|-
| {{para|image_caption}} || {{para|caption}}
|-
| {{para|settlement_type}} || {{para|type}}
|-
| {{para|blank#_name}} || {{para|custom_label#_sec1}}
|-
| {{para|pushpin_outside}} || remove
|}
{| class="wikitable"
|+ {{tl|Infobox person}}
! Old !! New !! If both are set
|-
| {{para|alma_mater}} {{para|alma mater}} || {{para|education}} || merge
|}
'''


@pytest.fixture
def rulesets():
    return list(parse_config(RULES).rulesets.values())


def fix(text, rulesets):
    return fix_wikitext(textwrap.dedent(text).lstrip('\n'), rulesets)


def test_simple_rename(rulesets):
    r = fix('''
        {{Infobox settlement
        | name = Foo
        | imagesize = 250px
        }}
        ''', rulesets)
    assert r.text == textwrap.dedent('''\
        {{Infobox settlement
        | name = Foo
        | image_size = 250px
        }}
        ''')
    assert [c.describe() for c in r.changes] == ['imagesize → image_size']
    assert r.substantive
    assert r.issues == []


def test_alignment_is_kept(rulesets):
    r = fix('''
        {{Infobox settlement
        | name            = Foo
        | settlement_type = Town
        | image_caption   = A view
        }}
        ''', rulesets)
    assert r.text == textwrap.dedent('''\
        {{Infobox settlement
        | name            = Foo
        | type            = Town
        | caption         = A view
        }}
        ''')


def test_unaligned_spacing_is_kept(rulesets):
    r = fix('{{Infobox settlement|name=Foo|imagesize=250px|image_caption = A}}', rulesets)
    assert r.text == '{{Infobox settlement|name=Foo|image_size=250px|caption = A}}'


def test_template_name_variants(rulesets):
    r = fix('{{infobox_settlement |imagesize=1}}{{ Template:Infobox settlement\n|imagesize=2}}', rulesets)
    assert r.text == '{{infobox_settlement |image_size=1}}{{ Template:Infobox settlement\n|image_size=2}}'


def test_redirect_names(rulesets):
    settlement = next(rs for rs in rulesets if rs.template == 'Infobox settlement')
    settlement.names.add('Infobox city')
    r = fix('{{infobox city|imagesize=1}}{{Infobox City|imagesize=1}}', rulesets)
    # Titles are case-sensitive after the first letter.
    assert r.text == '{{infobox city|image_size=1}}{{Infobox City|imagesize=1}}'


def test_other_templates_untouched(rulesets):
    text = '{{Infobox building|imagesize=250px}}{{Cite web|imagesize=1}}'
    r = fix(text, rulesets)
    assert r.text == text
    assert not r.changed


def test_ignored_contexts(rulesets):
    text = ('<!-- {{Infobox settlement|imagesize=1}} -->'
            '<nowiki>{{Infobox settlement|imagesize=1}}</nowiki>'
            '<pre>{{Infobox settlement|imagesize=1}}</pre>'
            '<syntaxhighlight lang="wikitext">{{Infobox settlement|imagesize=1}}</syntaxhighlight>')
    assert fix(text, rulesets).text == text


def test_nested_templates(rulesets):
    r = fix('''
        {{Infobox person
        | name = X
        | module = {{Infobox settlement|embed=yes|imagesize=100px}}
        | alma_mater = [[Harvard]]
        }}
        ''', rulesets)
    assert '{{Infobox settlement|embed=yes|image_size=100px}}' in r.text
    assert '| education = [[Harvard]]' in r.text


def test_value_with_nested_template_and_newlines(rulesets):
    r = fix('''
        {{Infobox settlement
        | image_caption = {{hlist
          |a
          |b}}
        }}
        ''', rulesets)
    assert '| caption = {{hlist\n  |a\n  |b}}\n' in r.text


def test_new_param_empty(rulesets):
    r = fix('''
        {{Infobox settlement
        | name       = Foo
        | image_size =
        | imagesize  = 250px
        }}
        ''', rulesets)
    assert r.text == textwrap.dedent('''\
        {{Infobox settlement
        | name       = Foo
        | image_size = 250px
        }}
        ''')
    assert r.changes[0].action == 'filled'


def test_new_param_empty_with_comment(rulesets):
    r = fix('''
        {{Infobox settlement
        | image_size = <!-- default 250px -->
        | imagesize = 200px
        }}
        ''', rulesets)
    assert '| image_size = 200px <!-- default 250px -->\n' in r.text
    assert 'imagesize' not in r.text


def test_same_value_duplicate(rulesets):
    r = fix('''
        {{Infobox settlement
        | image_size = 250px
        | imagesize = 250px
        }}
        ''', rulesets)
    assert r.text == '{{Infobox settlement\n| image_size = 250px\n}}\n'
    assert r.changes[0].action == 'duplicate'
    assert r.substantive


def test_conflict_is_reported_not_changed(rulesets):
    text = '''
        {{Infobox settlement
        | image_size = 250px
        | imagesize = 300px
        }}
        '''
    r = fix(text, rulesets)
    assert not r.changed
    assert len(r.issues) == 1
    assert r.issues[0].param == 'imagesize'
    assert 'both set' in r.issues[0].reason


def test_conflict_merge(rulesets):
    r = fix('''
        {{Infobox person
        | education  = BA in Engineering
        | alma_mater = [[NYU]]
        }}
        ''', rulesets)
    assert r.text == '{{Infobox person\n| education  = BA in Engineering<br />[[NYU]]\n}}\n'
    assert r.changes[0].action == 'merged'


def test_two_old_names_same_target(rulesets):
    r = fix('''
        {{Infobox person
        | alma_mater = [[Harvard]]
        | alma mater = [[Harvard]]
        }}
        ''', rulesets)
    assert r.text == '{{Infobox person\n| education = [[Harvard]]\n}}\n'


def test_blank_old_param_is_cosmetic(rulesets):
    r = fix('''
        {{Infobox settlement
        | name = Foo
        | imagesize =
        }}
        ''', rulesets)
    assert r.changed
    assert not r.substantive


def test_blank_old_with_new_present(rulesets):
    r = fix('{{Infobox settlement|image_size=250px|imagesize=}}', rulesets)
    assert r.text == '{{Infobox settlement|image_size=250px}}'
    assert not r.substantive


def test_cosmetic_rides_along_with_real_fix(rulesets):
    r = fix('{{Infobox settlement|imagesize=|image_caption=A}}', rulesets)
    assert r.text == '{{Infobox settlement|image_size=|caption=A}}'
    assert r.substantive


def test_pattern_rule(rulesets):
    r = fix('{{Infobox settlement|blank_name=Area|blank2_name=Zone}}', rulesets)
    assert r.text == '{{Infobox settlement|custom_label_sec1=Area|custom_label2_sec1=Zone}}'


def test_remove_rule(rulesets):
    r = fix('{{Infobox settlement\n| name = Foo\n| pushpin_outside = yes\n}}', rulesets)
    assert r.text == '{{Infobox settlement\n| name = Foo\n}}'
    assert r.substantive


def test_positional_params_untouched(rulesets):
    text = '{{Infobox settlement|imagesize}}'
    assert fix(text, rulesets).text == text


def test_param_name_with_comment(rulesets):
    text = '{{Infobox settlement|imagesize<!--x-->=1}}'
    r = fix(text, rulesets)
    assert r.text == text
    assert 'comment' in r.issues[0].reason


def test_known_params_old_still_accepted(rulesets):
    settlement = next(rs for rs in rulesets if rs.template == 'Infobox settlement')
    settlement.known = KnownParams({'imagesize', 'image_size', 'caption'})
    r = fix('{{Infobox settlement|imagesize=1|image_caption=A}}', rulesets)
    # imagesize still works, so it is left for the deprecation run.
    assert r.text == '{{Infobox settlement|imagesize=1|caption=A}}'


def test_known_params_target_not_accepted(rulesets):
    settlement = next(rs for rs in rulesets if rs.template == 'Infobox settlement')
    settlement.known = KnownParams({'caption'})
    r = fix('{{Infobox settlement|imagesize=1}}', rulesets)
    assert not r.changed
    assert 'does not accept "image_size"' in r.issues[0].reason


def test_idempotent(rulesets):
    text = '{{Infobox settlement\n| imagesize = 1\n| image_caption = A\n}}'
    once = fix(text, rulesets)
    twice = fix_wikitext(once.text, rulesets)
    assert not twice.changed
