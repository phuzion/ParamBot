from parambot.rules import REMOVE, parse_config

# The Infobox officeholder list as it was pasted in, plus a caption.
OFFICEHOLDER = """
{| class='wikitable'
|+ {{tl|Infobox officeholder}}
! Deprecate/Remove
! Replace with
|-
|{{para|mainwidth}}
|{{para|main_width}}
|-
|{{para|honorific prefix}}
|{{para|honorific_prefix}}
|-
|{{para|termstart#}}
|{{para|term_start#}}
|-
|{{para|spouse(s)}}
|rowspan=2|{{para|spouse}} (will use {{tl|pluralize from text}})
|-
|{{para|spouses}}
|-
|{{para|image name}}
|{{para|image}}
|-
|{{para|termstart#}}
|{{para|term_start#}}
|-
|{{para|jr/sr and state}}
|'''''remove'''''
|-
|{{para|nationality}}
|'''''remove'''''
|}
"""


def test_pasted_table():
    config = parse_config(OFFICEHOLDER)
    assert config.problems == []
    rs = config.rulesets['Infobox officeholder']
    assert rs.category == 'Category:Pages using infobox officeholder with unknown parameters'
    assert {k: r.new for k, r in rs.renames.items()} == {
        'mainwidth': 'main_width', 'honorific prefix': 'honorific_prefix',
        'spouse(s)': 'spouse', 'spouses': 'spouse', 'image name': 'image'}
    assert set(rs.removes) == {'jr/sr and state', 'nationality'}
    assert [r.old for r in rs.patterns] == ['termstart#']   # the duplicate row is merged


def test_number_placeholder():
    rs = parse_config(OFFICEHOLDER).rulesets['Infobox officeholder']
    assert rs.lookup('termstart').target == 'term_start'
    assert rs.lookup('termstart2').target == 'term_start2'
    assert rs.lookup('termstart12').target == 'term_start12'
    assert rs.lookup('termstarts') is None
    assert rs.lookup('term_start2') is None
    assert rs.lookup('nationality').rule.kind == REMOVE
    assert rs.lookup('Nationality') is None   # parameter names are case-sensitive


def test_two_numbers_and_escaping():
    config = parse_config('''
{| class="wikitable"
|+ {{tl|Infobox settlement}}
|-
| {{para|blank#_name_sec#}} || {{para|custom_label#_sec#}}
|-
| {{para|map-size#}} || {{para|map_size#}}
|-
| {{para|foo.bar}} || {{para|foo_bar}}
|-
| {{para|pushpin#_outside}} || remove
|}''')
    assert config.problems == []
    rs = config.rulesets['Infobox settlement']
    assert rs.lookup('blank2_name_sec3').target == 'custom_label2_sec3'
    assert rs.lookup('map-size1').target == 'map_size1'   # "-" is a real hyphen
    assert rs.lookup('mapxsize1') is None
    assert rs.lookup('foo.bar').target == 'foo_bar'        # "." is a real dot
    assert rs.lookup('fooxbar') is None
    assert rs.lookup('pushpin3_outside').rule.kind == REMOVE


def test_caption_forms_and_category():
    config = parse_config('''
{| class="wikitable"
|+ [[Template:Infobox NRHP]]
| {{para|a}} || {{para|b}}
|}
{| class="wikitable"
|+ Infobox person
| {{para|c}} || {{para|d}}
|}
{| class="wikitable"
|+ {{tlx|Infobox station}} watches [[:Category:Pages with odd station parameters]]
| {{para|e}} || {{para|f}}
|}''')
    assert config.problems == []
    assert set(config.rulesets) == {'Infobox NRHP', 'Infobox person', 'Infobox station'}
    assert config.rulesets['Infobox station'].category == \
        'Category:Pages with odd station parameters'


def test_merge_column():
    config = parse_config('''
{| class="wikitable"
|+ {{tl|Infobox person}}
! Old !! New !! If both are set !! Notes
|-
| {{para|alma_mater}}, {{para|alma mater}} || {{para|education}} || merge || per RfC
|-
| {{para|other_name}} || {{para|other_names}} || || merge is not wanted here
|}''')
    assert config.problems == []
    rs = config.rulesets['Infobox person']
    assert rs.renames['alma_mater'].conflict == 'merge'
    assert rs.renames['alma mater'].conflict == 'merge'
    assert rs.renames['other_name'].conflict == 'skip'   # "Notes" is only a note


def test_extra_columns_without_a_conflict_header_are_notes():
    config = parse_config('''
{| class="wikitable"
|+ {{tl|T}}
| {{para|a}} || {{para|b}} || merge? no idea
|}''')
    assert config.problems == []
    assert config.rulesets['T'].renames['a'].conflict == 'skip'


def test_plain_text_and_code_cells():
    config = parse_config('''
{| class="wikitable"
|+ {{tl|T}}
| honorific prefix || honorific_prefix
|-
| <code>imagesize</code> (typo) || <code>image_size</code>
|}''')
    rs = config.rulesets['T']
    assert {k: r.new for k, r in rs.renames.items()} == {
        'honorific prefix': 'honorific_prefix', 'imagesize': 'image_size'}


def test_other_tables_are_ignored():
    config = parse_config('''
{| class="wikitable"
! Template !! Status
|-
| Infobox settlement || done
|}''')
    assert config.rulesets == {}
    assert config.problems == []


def test_ignored_contexts():
    table = '{| class="wikitable"\n|+ {{tl|T}}\n| {{para|a}} || {{para|b}}\n|}'
    for wrapped in (f'<!--\n{table}\n-->', f'<nowiki>{table}</nowiki>', f'<pre>{table}</pre>',
                    f'<syntaxhighlight lang="wikitext">\n{table}\n</syntaxhighlight>'):
        config = parse_config(wrapped)
        assert config.rulesets == {} and config.problems == [], wrapped


def test_awb_format():
    config = parse_config('''
* <code>{{AWB rename template parameter|Infobox person|alma_mater|education}}</code>
* <code>{{AWB rename template parameter|infobox_person|termstart#|term_start#}}</code>
''')
    rs = config.rulesets['Infobox person']
    assert rs.renames['alma_mater'].new == 'education'
    assert rs.lookup('termstart3').target == 'term_start3'


def test_tables_for_the_same_template_are_combined():
    config = parse_config('''
{| class="wikitable"
|+ {{tl|T}}
| {{para|a}} || {{para|b}}
|}
{| class="wikitable"
|+ {{tl|t}}
| {{para|c}} || {{para|d}}
|}
* {{AWB rename template parameter|T|e|f}}''')
    assert set(config.rulesets['T'].renames) == {'a', 'c', 'e'}


def test_chains_are_resolved():
    rs = parse_config('{|\n|+ {{tl|T}}\n| {{para|a}} || {{para|b}}\n|-\n'
                      '| {{para|b}} || {{para|c}}\n|}').rulesets['T']
    assert rs.renames['a'].new == 'c'
    assert rs.renames['b'].new == 'c'


def test_problems_for_common_mistakes():
    config = parse_config('''
{| class="wikitable"
! Old !! New
|-
| {{para|no_caption}} || {{para|oops}}
|}
{| class="wikitable"
|+ {{tl|T}}
! Old !! New !! If both are set
|-
| {{para|empty_new}} ||
|-
| {{para|two}} || {{para|x}} {{para|y}}
|-
| {{para|numbered#}} || {{para|not_numbered}}
|-
| {{para|a}} || {{para|b}} || fight
|-
| || {{para|orphan}}
|-
| a, b || c
|-
| {{para|dup}} || {{para|one}}
|-
| {{para|dup}} || {{para|two}}
|}
{| class="wikitable"
|+ {{tl|T1}} and {{tl|T2}}
| {{para|p}} || {{para|q}}
|}
{| class="wikitable"
|+ <!-- nothing here -->
| {{para|p}} || {{para|q}}
|}
* {{AWB rename template parameter|T|only two}}
''')
    problems = config.problems

    def one(fragment):
        found = [p for p in problems if fragment in p]
        assert found, f'no problem mentioning {fragment!r} in {problems}'
        return found[0]

    one('has no caption naming its template')
    one('"empty_new" has no new name')
    one('more than one new name (x, y)')
    one('"numbered#" → "not_numbered" has "#" in only one of the names')
    one('says "fight"')
    one('a new name but no old name')
    one('"a, b" looks like several names')
    one('"dup" is renamed to both "one" and "two"')
    one('names more than one template (T1, T2)')
    one("caption doesn't name a template")
    one('needs exactly three parts')
    assert len(problems) == 11
    rs = config.rulesets['T']
    assert rs.renames['a'].conflict == 'skip'
    assert rs.renames['dup'].new == 'two'
    assert 'T1' in config.rulesets   # the first template in the caption is used
