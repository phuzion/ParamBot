"""Reading a template's own parameter checks from its source.

``known_params`` pulls the list of accepted parameters out of the template's
``{{#invoke:Check for unknown parameters|check|...}}`` call.  The bot uses it
to leave a rule alone while the template still accepts the old name, and to
refuse to rename anything to a name the template doesn't accept.

``scaffold_table`` turns the template's
``{{#invoke:Check for deprecated parameters|check|...}}`` call into a rules
table for the rules page.
"""

import re
from collections.abc import Iterable, Iterator

import mwparserfromhell
from mwparserfromhell.nodes import Template
from mwparserfromhell.wikicode import Wikicode

from .luapattern import LuaPattern, LuaPatternError
from .wikitext import normalize_category, normalize_template_name, param_name, strip_comments

__all__ = ['KnownParams', 'known_params', 'categories_in', 'scaffold_table']

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
_NOT_RULES = ('_category', 'ignoreblank', 'preview')  # settings of the deprecated check


class KnownParams:
    """The parameters a template accepts, per its unknown-parameter check.

    ``unknown_text`` is the check's raw ``unknown=`` wikitext, which holds
    the category link for pages with unknown parameters."""

    def __init__(self, names: Iterable[str] = (), patterns: Iterable[LuaPattern] = (),
                 unknown_text: str | None = None) -> None:
        self.names = set(names)
        self.patterns = list(patterns)
        self.unknown_text = unknown_text

    def __repr__(self) -> str:
        return f'KnownParams({len(self.names)} names, {len(self.patterns)} patterns)'

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and (
            name in self.names or any(p.fullmatch(name) for p in self.patterns))


def known_params(source: str) -> KnownParams | None:
    """The KnownParams declared in a template's source, or None if the
    template has no unknown-parameter check the bot can read."""
    calls = list(_invokes(mwparserfromhell.parse(source), _UNKNOWN_MODULE))
    if not calls:
        return None
    known = KnownParams()
    for call in calls:
        if known.unknown_text is None and call.has('unknown'):
            known.unknown_text = str(call.get('unknown').value).strip() or None
        for param in call.params[1:]:
            value = strip_comments(param.value).strip()
            if not param.showkey:
                if value and '{' not in value:
                    known.names.add(value)
                continue
            key = param_name(param)
            if re.fullmatch(r'regexp[1-9][0-9]*', key):
                try:
                    known.patterns.append(LuaPattern(value))
                except LuaPatternError:
                    return None  # a pattern we can't read might cover anything
            elif key == 'mapframe_args' and value:
                known.names |= MAPFRAME_PARAMS
            elif key == 'pushpin_map_args' and value:
                known.names |= PUSHPIN_MAP_PARAMS
    return known


_CATEGORY_LINK_RE = re.compile(r'\[\[\s*:?\s*category\s*:\s*([^|\]]+)', re.IGNORECASE)


def categories_in(wikitext: str) -> list[str]:
    """The categories linked in (expanded) wikitext, normalized, in order."""
    out: list[str] = []
    for name in _CATEGORY_LINK_RE.findall(wikitext):
        category = normalize_category(name)
        if category not in out:
            out.append(category)
    return out


def _invokes(code: Wikicode, module: str) -> Iterator[Template]:
    """The {{#invoke:module|check|...}} calls in parsed wikitext."""
    for call in code.filter_templates(recursive=True):
        name = ' '.join(strip_comments(call.name).replace('_', ' ').split())
        m = re.fullmatch(r'#invoke\s*:\s*(.+)', name, re.IGNORECASE)
        if not m:
            continue
        target = re.sub(r'^module\s*:\s*', '', m.group(1), flags=re.IGNORECASE)
        if (normalize_template_name(target) == module and call.params
                and not call.params[0].showkey
                and strip_comments(call.params[0].value).strip() == 'check'):
            yield call


# -- scaffolding a rules table ---------------------------------------------

def scaffold_table(template: str, source: str) -> tuple[str | None, list[str]]:
    """Build a rules table from the template's deprecated-parameter check.

    Returns (wikitext, warnings), or (None, []) if the template has no such
    check.  Warnings name the patterns that couldn't be turned into rows."""
    pairs, warnings = _deprecated_pairs(mwparserfromhell.parse(source))
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


def _deprecated_pairs(code: Wikicode) -> tuple[list[tuple[str, str | None]], list[str]]:
    """(old, new) pairs from the deprecated-parameter checks (new is None for
    removals), and the patterns that couldn't be converted."""
    pairs: list[tuple[str, str | None]] = []
    warnings: list[str] = []
    for call in _invokes(code, _DEPRECATED_MODULE):
        for param in call.params[1:]:
            key = param_name(param)
            value = strip_comments(param.value).strip()
            if not param.showkey or key in _NOT_RULES:
                continue
            if key == '_remove':
                pairs += [(name.strip(), None) for name in value.split(';') if name.strip()]
            elif re.fullmatch(r'_regexp[1-9][0-9]*', key):
                parts = re.split(r'\s*=\s*', value)
                converted = _to_number_form(parts[0], parts[1]) if len(parts) == 2 else None
                if converted:
                    pairs.append(converted)
                else:
                    warnings.append(f'{key} = {value}')
            elif value:
                pairs.append((key, value))
    return pairs, warnings


_NUMBER_GROUP_RE = re.compile(r'\(%d[*+?]?\)')


def _to_number_form(pattern: str, replacement: str) -> tuple[str, str] | None:
    """Turn a Lua pattern rule such as ``blank(%d*)_name = custom_label%1_sec1``
    into "#" form (``blank#_name``, ``custom_label#_sec1``), or None if it
    uses anything but digit groups."""
    if '#' in pattern or '#' in replacement:
        return None
    parts = _NUMBER_GROUP_RE.split(pattern)
    groups = len(parts) - 1
    literals = [_literal(part) for part in parts]
    if not groups or None in literals:
        return None
    refs = [int(n) for n in re.findall(r'%([0-9])', replacement.replace('%%', ''))]
    if refs != list(range(1, groups + 1)):
        return None
    new = re.sub(r'%[0-9]', '#', replacement.replace('%%', '\0')).replace('\0', '%')
    return '#'.join(str(literal) for literal in literals), new


def _literal(part: str) -> str | None:
    """A piece of Lua pattern as plain text, or None if it's more than that."""
    text = []
    i = 0
    while i < len(part):
        c = part[i]
        if c == '%':
            if i + 1 >= len(part) or part[i + 1].isalnum():
                return None             # a class such as %a
            text.append(part[i + 1])    # %- is a real hyphen
            i += 2
        elif c in '^$().[]*+-?':
            return None                 # anything cleverer than digits
        else:
            text.append(c)
            i += 1
    return ''.join(text)
