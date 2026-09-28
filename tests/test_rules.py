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


def test_on_a_rules_page_every_table_is_for_its_template():
    config = parse_config('''
{| class="wikitable"
|+ Agreed at the 2025 RfC
| {{para|a}} || {{para|b}}
|}
{| class="wikitable"
|+ Infobox person
| c || d
|}
{| class="wikitable"
| {{para|e}} || {{para|f}}
|}
{| class="wikitable"
|+ Status
| Done || yes
|}''', template='infobox_person')
    assert config.problems == []
    assert set(config.rulesets) == {'Infobox person'}
    assert set(config.rulesets['Infobox person'].renames) == {'a', 'c', 'e'}


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


# -- rows that overlap -----------------------------------------------------

def test_rows_that_disagree_are_not_used():
    config = parse_config('''
{| class="wikitable"
|+ {{tl|T}}
|-
| {{para|a}} || {{para|b}}
|-
| {{para|a}} || {{para|c}}
|-
| {{para|gone}} || remove
|-
| {{para|kept}} || {{para|fine}}
|-
| {{para|n#}} || {{para|x#}}
|}
{| class="wikitable"
|+ {{tl|T}}
|-
| {{para|a}} || {{para|b}}
|-
| {{para|gone}} || {{para|here}}
|-
| {{para|n#}} || remove
|-
| {{para|kept}} || {{para|fine}}
|}''')
    rs = config.rulesets['T']
    assert [rs.lookup(name) for name in ('a', 'gone', 'n', 'n2')] == [None] * 4
    assert rs.lookup('kept').target == 'fine'     # the same rule twice is fine
    assert config.problems == [
        'T: "a" is renamed to both "b" and "c", so the bot uses neither. Delete the wrong row.',
        'T: one row renames "gone" to "here" and another removes it, so the bot uses neither. '
        'Delete the wrong row.',
        'T: one row renames "n#" to "x#" and another removes it, so the bot uses neither. '
        'Delete the wrong row.']


def test_rows_that_disagree_about_merging_are_not_merged():
    config = parse_config('''
{| class="wikitable"
|+ {{tl|Infobox person}}
! Old !! New !! If both are set
|-
| {{para|alma_mater}} || {{para|education}} || merge
|-
| {{para|other_name}} || {{para|other_names}} || merge
|-
| {{para|alma_mater}} || {{para|education}} || merge
|}
{| class="wikitable"
|+ {{tl|Infobox person}}
|-
| {{para|alma_mater}} || {{para|education}}
|}
* {{AWB rename template parameter|Infobox person|other_name|other_names}}
* {{AWB rename template parameter|Infobox person|alma_mater|education}}
''')
    rs = config.rulesets['Infobox person']
    assert rs.renames['alma_mater'].conflict == 'skip'
    assert rs.renames['other_name'].conflict == 'skip'
    assert rs.renames['alma_mater'].new == 'education'   # still renamed
    assert config.problems == [
        'Infobox person: only some of the rows for "alma_mater" say merge, so the bot won\'t '
        'merge it. Make the rows agree.',
        'Infobox person: only some of the rows for "other_name" say merge, so the bot won\'t '
        'merge it. Make the rows agree.']


NUMBERED = '''
{| class="wikitable"
|+ {{tl|T}}
|-
| {{para|image1#}} || {{para|picture#}}
|-
| {{para|image#}} || {{para|photo#}}
|-
| {{para|image1#}} || {{para|picture#}}
|-
| {{para|image12}} || {{para|photo12}}
|}'''


def test_a_repeated_number_rule_keeps_its_place():
    rs = parse_config(NUMBERED).rulesets['T']
    assert [r.old for r in rs.patterns] == ['image1#', 'image#']


def test_a_name_matched_by_two_number_rules():
    rs = parse_config(NUMBERED).rulesets['T']
    match = rs.lookup('image13')
    assert (match.rule.old, match.target) == ('image1#', 'picture3')
    assert [r.old for r in match.others] == ['image#']       # which would give photo13
    assert rs.lookup('image3').others == ()                  # only image# matches
    assert rs.lookup('image12').target == 'photo12'          # an exact name settles it
    assert rs.lookup('image12').others == ()


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
    assert 'dup' not in rs.renames
    assert 'T1' in config.rulesets   # the first template in the caption is used
