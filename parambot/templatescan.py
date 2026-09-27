"""Reading a template's own parameter checks from its source.

``known_params`` pulls the whitelist out of the template's
``{{#invoke:Check for unknown parameters|check|...}}`` call.  The bot uses it
to leave a rule alone while the template still accepts the old name, and to
refuse to rename anything to a name the template does not accept.

``scaffold_table`` turns the template's
``{{#invoke:Check for deprecated parameters|check|...}}`` call into a rules
table for the rules page.
"""

import re

import mwparserfromhell

from .luapattern import LuaPattern, LuaPatternError
from .wikitext import normalize_template_name, param_name, strip_comments

__all__ = ['KnownParams', 'known_params', 'scaffold_table']

# Copied from Module:Check for unknown parameters, which adds these names
# when the call has |mapframe_args=y or |pushpin_map_args=y.
MAPFRAME_PARAMS = frozenset('''
    coord coordinates id qid mapframe mapframe-area_km2 mapframe-area_mi2
    mapframe-caption mapframe-coord mapframe-coordinates mapframe-custom
    mapframe-frame-coord mapframe-frame-coordinates mapframe-frame-height
    mapframe-frame-width mapframe-geomask mapframe-geomask-fill
    mapframe-geomask-fill-opacity mapframe-geomask-stroke-color
    mapframe-geomask-stroke-colour mapframe-geomask-stroke-width
    mapframe-height mapframe-id mapframe-length_km mapframe-length_mi
    mapframe-line mapframe-line-stroke-color mapframe-line-stroke-colour
    mapframe-marker mapframe-marker-color mapframe-marker-colour
    mapframe-point mapframe-population mapframe-shape mapframe-shape-fill
    mapframe-shape-fill-opacity mapframe-shape-stroke-color
    mapframe-shape-stroke-colour mapframe-stroke-color mapframe-stroke-colour
    mapframe-stroke-width mapframe-switcher mapframe-type mapframe-width
    mapframe-wikidata mapframe-zoom
'''.split())

PUSHPIN_MAP_PARAMS = frozenset('''
    coordinates pushpin_caption pushpin_relief pushpin_label
    pushpin_label_position pushpin_label_size pushpin_map pushpin_mark
    pushpin_mark_size pushpin_alt pushpin_background pushpin_map_size
'''.split())

_UNKNOWN_MODULE = 'Check for unknown parameters'
_DEPRECATED_MODULE = 'Check for deprecated parameters'


class KnownParams:
    """The parameters a template accepts, per its unknown-parameter check."""

    def __init__(self, names=(), patterns=()):
        self.names = set(names)
        self.patterns = list(patterns)

    def __repr__(self):
        return f'KnownParams({len(self.names)} names, {len(self.patterns)} patterns)'

    def __contains__(self, name):
        return name in self.names or any(p.fullmatch(name) for p in self.patterns)


def _invokes(code, module):
    """Yield {{#invoke:module|check|...}} calls in parsed wikitext."""
    for tpl in code.filter_templates(recursive=True):
        name = ' '.join(strip_comments(tpl.name).replace('_', ' ').split())
        m = re.fullmatch(r'#invoke\s*:\s*(.+)', name, re.IGNORECASE)
        if not m:
            continue
        target = re.sub(r'^module\s*:\s*', '', m.group(1), flags=re.IGNORECASE)
        if normalize_template_name(target) != module:
            continue
        if not tpl.params or tpl.params[0].showkey:
            continue
        if strip_comments(tpl.params[0].value).strip() != 'check':
            continue
        yield tpl


def known_params(source):
    """Return the KnownParams declared in a template's source, or None if the
    template has no unknown-parameter check the bot can read."""
    code = mwparserfromhell.parse(source)
    found = False
    names = set()
    patterns = []
    for tpl in _invokes(code, _UNKNOWN_MODULE):
        found = True
        for param in tpl.params[1:]:
            value = strip_comments(param.value).strip()
            if not param.showkey:
                if value and '{' not in value:
                    names.add(value)
                continue
            key = param_name(param)
            if re.fullmatch(r'regexp[1-9][0-9]*', key):
                try:
                    patterns.append(LuaPattern(value))
                except LuaPatternError:
                    # A pattern we cannot read might cover anything.
                    return None
            elif key == 'mapframe_args' and value:
                names |= MAPFRAME_PARAMS
            elif key == 'pushpin_map_args' and value:
                names |= PUSHPIN_MAP_PARAMS
    return KnownParams(names, patterns) if found else None


_NUMBER_GROUP_RE = re.compile(r'\(%d[*+?]?\)')


def _pattern_to_hash(pattern, replacement):
    """Turn a Lua pattern rule such as ``blank(%d*)_name = custom_label%1_sec1``
    into "#" form (``blank#_name``, ``custom_label#_sec1``), or return None if
    it uses anything but digit groups."""
    if '#' in pattern or '#' in replacement:
        return None
    parts = _NUMBER_GROUP_RE.split(pattern)
    groups = len(parts) - 1
    if not groups:
        return None
    literal = []
    for part in parts:
        text = []
        i = 0
        while i < len(part):
            c = part[i]
            if c == '%':
                if i + 1 >= len(part) or part[i + 1].isalnum():
                    return None                 # a class such as %a
                text.append(part[i + 1])        # %- is a real hyphen
                i += 2
            elif c in '^$().[]*+-?':
                return None                     # anything cleverer than digits
            else:
                text.append(c)
                i += 1
        literal.append(''.join(text))
    refs = [int(n) for n in re.findall(r'%([0-9])', replacement.replace('%%', ''))]
    if refs != list(range(1, groups + 1)):
        return None
    new = re.sub(r'%[0-9]', '#', replacement.replace('%%', '\0')).replace('\0', '%')
    return '#'.join(literal), new


def scaffold_table(template, source):
    """Build a rules table from the template's deprecated-parameter check.

    Returns (wikitext, warnings), or (None, []) if the template has no such
    check.  Warnings name the patterns that couldn't be turned into rows."""
    code = mwparserfromhell.parse(source)
    pairs = []
    warnings = []
    for tpl in _invokes(code, _DEPRECATED_MODULE):
        for param in tpl.params[1:]:
            if not param.showkey:
                continue
            key = param_name(param)
            value = strip_comments(param.value).strip()
            if key in ('_category', 'ignoreblank', 'preview'):
                continue
            if key == '_remove':
                pairs += [(name.strip(), None) for name in value.split(';') if name.strip()]
            elif re.fullmatch(r'_regexp[1-9][0-9]*', key):
                parts = re.split(r'\s*=\s*', value)
                converted = _pattern_to_hash(*parts) if len(parts) == 2 else None
                if converted:
                    pairs.append(converted)
                else:
                    warnings.append(f'{key} = {value}')
            elif value:
                pairs.append((key, value))
    if not pairs and not warnings:
        return None, []
    template = normalize_template_name(template)
    lines = ['{| class="wikitable"', f'|+ {{{{tl|{template}}}}}',
             '! Old parameter !! New parameter']
    for old, new in pairs:
        lines += ['|-', f'| {{{{para|{old}}}}} || ' + (f'{{{{para|{new}}}}}' if new else 'remove')]
    for warning in warnings:
        lines.append(f'<!-- Could not turn "{warning}" into a row. Add rows for it by hand. -->')
    lines.append('|}')
    return '\n'.join(lines), warnings
