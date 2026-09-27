import pytest

from parambot.luapattern import LuaPattern, LuaPatternError


@pytest.mark.parametrize('pattern, name, expected', [
    ('blank(%d*)_name', 'blank_name', True),
    ('blank(%d*)_name', 'blank3_name', True),
    ('blank(%d*)_name', 'blank3_name_sec1', False),
    ('timezone(%d)_DST', 'timezone2_DST', True),
    ('timezone(%d)_DST', 'timezone22_DST', False),
    ('p[1-9]%d?', 'p12', True),
    ('p[1-9]%d?', 'p0', False),
    ('[%a_]+', 'image_size', True),
    ('[%a_]+', 'image size', False),
    ('image%.size', 'image.size', True),
    ('image%.size', 'imagexsize', False),
    ('image.size', 'imagexsize', True),
    ('%a+', 'Größe', True),
    ('[^%d]+', 'abc', True),
    ('[^%d]+', 'ab1', False),
    ('[]x]', ']', True),
])
def test_fullmatch(pattern, name, expected):
    assert bool(LuaPattern(pattern).fullmatch(name)) is expected


def test_minus_is_lazy_quantifier():
    # As in Lua, "e-" means "zero or more e, lazily".
    p = LuaPattern('mapframe-caption')
    assert p.fullmatch('mapframcaption')
    assert p.fullmatch('mapframeeecaption')
    assert not p.fullmatch('mapframe-caption')
    assert LuaPattern('mapframe%-caption').fullmatch('mapframe-caption')


def test_anchors_are_optional():
    assert LuaPattern('^foo(%d)$').fullmatch('foo1')
    assert LuaPattern('^foo(%d)$').sub('foo1', 'bar%1') == 'bar1'


@pytest.mark.parametrize('pattern, replacement, name, expected', [
    ('blank(%d*)_name', 'custom_label%1_sec1', 'blank_name', 'custom_label_sec1'),
    ('blank(%d*)_name', 'custom_label%1_sec1', 'blank4_name', 'custom_label4_sec1'),
    ('blank(%d*)_info_sec(%d)', 'custom_data%1_sec%2', 'blank2_info_sec3', 'custom_data2_sec3'),
    ('foo%d', 'x%0y', 'foo7', 'xfoo7y'),
    ('foo%d', 'x%1y', 'foo7', 'xfoo7y'),   # %1 is the whole match with no captures
    ('foo(%d)', '100%%', 'foo7', '100%'),
    ('foo(%d)', 'a\\1', 'foo7', 'a\\1'),  # backslashes are literal
])
def test_sub(pattern, replacement, name, expected):
    assert LuaPattern(pattern).sub(name, replacement) == expected


def test_sub_no_match():
    assert LuaPattern('foo(%d)').sub('bar1', 'x%1') is None


@pytest.mark.parametrize('pattern', ['%bxy', '%f[%a]', '()', '(a', 'a)', '[abc', 'a%'])
def test_unsupported(pattern):
    with pytest.raises(LuaPatternError):
        LuaPattern(pattern)


def test_bad_capture_index():
    with pytest.raises(LuaPatternError):
        LuaPattern('foo(%d)').sub('foo1', '%2')
