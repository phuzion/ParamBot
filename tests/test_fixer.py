import textwrap
from dataclasses import replace

import pytest

from parambot.fixer import TemplateRules, fix_wikitext
from parambot.messages import plain
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
def targets():
    return [TemplateRules.unchecked(rs) for rs in parse_config(RULES).rulesets.values()]


def with_settlement(targets, **changes):
    """targets, with the Infobox settlement ones changed."""
    return [replace(t, **changes) if t.template == 'Infobox settlement' else t for t in targets]


def fix(text, targets):
    return fix_wikitext(textwrap.dedent(text).lstrip('\n'), targets)


def test_simple_rename(targets):
    r = fix('''
        {{Infobox settlement
        | name = Foo
        | imagesize = 250px
        }}
        ''', targets)
    assert r.text == textwrap.dedent('''\
        {{Infobox settlement
        | name = Foo
        | image_size = 250px
        }}
        ''')
    assert [c.describe() for c in r.changes] == ['imagesize → image_size']
    assert r.substantive
    assert r.issues == []


def test_alignment_is_kept(targets):
    r = fix('''
        {{Infobox settlement
        | name            = Foo
        | settlement_type = Town
        | image_caption   = A view
        }}
        ''', targets)
    assert r.text == textwrap.dedent('''\
        {{Infobox settlement
        | name            = Foo
        | type            = Town
        | caption         = A view
        }}
        ''')


def test_unaligned_spacing_is_kept(targets):
    r = fix('{{Infobox settlement|name=Foo|imagesize=250px|image_caption = A}}', targets)
    assert r.text == '{{Infobox settlement|name=Foo|image_size=250px|caption = A}}'


def test_template_name_variants(targets):
    r = fix('{{infobox_settlement |imagesize=1}}'
            '{{ Template:Infobox settlement\n|imagesize=2}}', targets)
    assert r.text == ('{{infobox_settlement |image_size=1}}'
                      '{{ Template:Infobox settlement\n|image_size=2}}')


def test_redirect_names(targets):
    targets = with_settlement(targets, names=frozenset({'Infobox settlement', 'Infobox city'}))
    r = fix('{{infobox city|imagesize=1}}{{Infobox City|imagesize=1}}', targets)
    # Titles are case-sensitive after the first letter.
    assert r.text == '{{infobox city|image_size=1}}{{Infobox City|imagesize=1}}'


def test_other_templates_untouched(targets):
    text = '{{Infobox building|imagesize=250px}}{{Cite web|imagesize=1}}'
    r = fix(text, targets)
    assert r.text == text
    assert not r.changed


def test_ignored_contexts(targets):
    text = ('<!-- {{Infobox settlement|imagesize=1}} -->'
            '<nowiki>{{Infobox settlement|imagesize=1}}</nowiki>'
            '<pre>{{Infobox settlement|imagesize=1}}</pre>'
            '<syntaxhighlight lang="wikitext">{{Infobox settlement|imagesize=1}}</syntaxhighlight>')
    assert fix(text, targets).text == text


def test_nested_templates(targets):
    r = fix('''
        {{Infobox person
        | name = X
        | module = {{Infobox settlement|embed=yes|imagesize=100px}}
        | alma_mater = [[Harvard]]
        }}
        ''', targets)
    assert '{{Infobox settlement|embed=yes|image_size=100px}}' in r.text
    assert '| education = [[Harvard]]' in r.text


def test_value_with_nested_template_and_newlines(targets):
    r = fix('''
        {{Infobox settlement
        | image_caption = {{hlist
          |a
          |b}}
        }}
        ''', targets)
    assert '| caption = {{hlist\n  |a\n  |b}}\n' in r.text


def test_new_param_empty(targets):
    r = fix('''
        {{Infobox settlement
        | name       = Foo
        | image_size =
        | imagesize  = 250px
        }}
        ''', targets)
    assert r.text == textwrap.dedent('''\
        {{Infobox settlement
        | name       = Foo
        | image_size = 250px
        }}
        ''')
    assert r.changes[0].action == 'filled'


def test_new_param_empty_with_comment(targets):
    r = fix('''
        {{Infobox settlement
        | image_size = <!-- default 250px -->
        | imagesize = 200px
        }}
        ''', targets)
    assert '| image_size = 200px <!-- default 250px -->\n' in r.text
    assert 'imagesize' not in r.text


def test_same_value_duplicate(targets):
    r = fix('''
        {{Infobox settlement
        | image_size = 250px
        | imagesize = 250px
        }}
        ''', targets)
    assert r.text == '{{Infobox settlement\n| image_size = 250px\n}}\n'
    assert r.changes[0].action == 'duplicate'
    assert r.substantive


def test_conflict_is_reported_not_changed(targets):
    text = '''
        {{Infobox settlement
        | image_size = 250px
        | imagesize = 300px
        }}
        '''
    r = fix(text, targets)
    assert not r.changed
    assert len(r.issues) == 1
    assert r.issues[0].param == 'imagesize'
    assert 'both set' in r.issues[0].reason


def test_conflict_merge(targets):
    r = fix('''
        {{Infobox person
        | education  = BA in Engineering
        | alma_mater = [[NYU]]
        }}
        ''', targets)
    assert r.text == '{{Infobox person\n| education  = BA in Engineering<br />[[NYU]]\n}}\n'
    assert r.changes[0].action == 'merged'


def test_two_old_names_same_target(targets):
    r = fix('''
        {{Infobox person
        | alma_mater = [[Harvard]]
        | alma mater = [[Harvard]]
        }}
        ''', targets)
    assert r.text == '{{Infobox person\n| education = [[Harvard]]\n}}\n'


def test_blank_old_param_is_cosmetic(targets):
    r = fix('''
        {{Infobox settlement
        | name = Foo
        | imagesize =
        }}
        ''', targets)
    assert r.changed
    assert not r.substantive


def test_blank_old_with_new_present(targets):
    r = fix('{{Infobox settlement|image_size=250px|imagesize=}}', targets)
    assert r.text == '{{Infobox settlement|image_size=250px}}'
    assert not r.substantive


def test_cosmetic_rides_along_with_real_fix(targets):
    r = fix('{{Infobox settlement|imagesize=|image_caption=A}}', targets)
    assert r.text == '{{Infobox settlement|image_size=|caption=A}}'
    assert r.substantive


def test_pattern_rule(targets):
    r = fix('{{Infobox settlement|blank_name=Area|blank2_name=Zone}}', targets)
    assert r.text == '{{Infobox settlement|custom_label_sec1=Area|custom_label2_sec1=Zone}}'


def test_remove_rule(targets):
    r = fix('{{Infobox settlement\n| name = Foo\n| pushpin_outside = yes\n}}', targets)
    assert r.text == '{{Infobox settlement\n| name = Foo\n}}'
    assert r.substantive


def test_positional_params_untouched(targets):
    text = '{{Infobox settlement|imagesize}}'
    assert fix(text, targets).text == text


def test_param_name_with_comment(targets):
    text = '{{Infobox settlement|imagesize<!--x-->=1}}'
    r = fix(text, targets)
    assert r.text == text
    assert 'comment' in r.issues[0].reason


def test_known_params_old_still_accepted(targets):
    targets = with_settlement(targets, known=KnownParams({'imagesize', 'image_size', 'caption'}))
    r = fix('{{Infobox settlement|imagesize=1|image_caption=A}}', targets)
    # imagesize still works, so it is left for the deprecation run.
    assert r.text == '{{Infobox settlement|imagesize=1|caption=A}}'


def test_known_params_target_not_accepted(targets):
    targets = with_settlement(targets, known=KnownParams({'caption'}))
    r = fix('{{Infobox settlement|imagesize=1}}', targets)
    assert not r.changed
    assert 'does not accept "image_size"' in plain(r.issues[0].reason)


def test_idempotent(targets):
    text = '{{Infobox settlement\n| imagesize = 1\n| image_caption = A\n}}'
    once = fix(text, targets)
    twice = fix_wikitext(once.text, targets)
    assert not twice.changed


def test_two_number_rules_for_one_name_are_left_for_a_human():
    rules = parse_config('''
{| class="wikitable"
|+ {{tl|T}}
|-
| {{para|image1#}} || {{para|picture#}}
|-
| {{para|image#}} || {{para|photo#}}
|}''')
    targets = [TemplateRules.unchecked(rs) for rs in rules.rulesets.values()]
    r = fix('{{T|image13=a.jpg|image2=b.jpg}}', targets)
    assert r.text == '{{T|image13=a.jpg|photo2=b.jpg}}'
    [issue] = r.issues
    assert (issue.param, issue.target) == ('image13', None)
    assert plain(issue.reason).startswith(
        'more than one "#" rule matches it ("image1#" → "picture#"; "image#" → "photo#")')
