"""Reading a template's own parameter checks from its source.

``known_params`` pulls the list of accepted parameters out of the template's
``{{#invoke:Check for unknown parameters|check|...}}`` call.  The bot uses it
to leave a rule alone while the template still accepts the old name, and to
refuse to rename anything to a name the template doesn't accept.

A wrapper template, such as Infobox military person, has no such call: it
passes an article's parameters on to another template through
``{{#invoke:Template wrapper|wrap|_template=...}}``.  ``wrapper_call`` reads
that call, and ``WrappedParams`` combines it with the other template's list.

``scaffold_table`` turns the template's
``{{#invoke:Check for deprecated parameters|check|...}}`` call into a rules
table for the rules page.
"""

import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass

import mwparserfromhell
from mwparserfromhell.nodes import Template, Text
from mwparserfromhell.wikicode import Wikicode

from .luapattern import LuaPattern, LuaPatternError
from .wikitext import normalize_category, normalize_template_name, param_name, strip_comments

__all__ = ['KnownParams', 'WrappedParams', 'Wrapper', 'known_params', 'wrapper_call',
           'categories_in', 'scaffold_table']

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

# The settings that make the unknown-parameter check accept those names.
_EXTRA_PARAMS = {'mapframe_args': MAPFRAME_PARAMS, 'pushpin_map_args': PUSHPIN_MAP_PARAMS}

_UNKNOWN_MODULE = 'Check for unknown parameters'
_DEPRECATED_MODULE = 'Check for deprecated parameters'
_WRAPPER_MODULE = 'Template wrapper'
_NOT_RULES = ('_category', 'ignoreblank', 'preview')  # settings of the deprecated check
# Module:Template wrapper's own settings, which it doesn't pass on.
_WRAPPER_SETTINGS = ('_template', '_exclude', '_reuse', '_include-positional', '_alias-map')
# The ones that name what the wrapper keeps for itself.
_KEEP_SETTINGS = ('_exclude', '_reuse')
MAX_VARIANTS = 16   # the values they can take, with {{#if:...}}: any more, the bot won't guess


class KnownParams:
    """The parameters a template accepts, per its unknown-parameter check.

    ``names`` and ``patterns`` are the check's own list.  ``extras`` are the
    names the module adds for a setting such as ``mapframe_args=y``, with that
    setting: {name: setting}.  ``unknown_text`` is the check's raw
    ``unknown=`` wikitext, which holds the category link for pages with
    unknown parameters.  ``unsure`` are names whose fate the bot can't
    tell: see WrappedParams."""

    def __init__(self, names: Iterable[str] = (), patterns: Iterable[LuaPattern] = (),
                 unknown_text: str | None = None,
                 extras: Mapping[str, str] | None = None) -> None:
        self.names = set(names)
        self.patterns = list(patterns)
        self.unknown_text = unknown_text
        self.extras = dict(extras or {})
        self.unsure: frozenset[str] = frozenset()

    def __repr__(self) -> str:
        return (f'KnownParams({len(self.names)} names, {len(self.patterns)} patterns, '
                f'{len(self.extras)} extras)')

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and (name in self.extras or self._listed(name))

    def added_by(self, name: str) -> str | None:
        """The setting, such as mapframe_args, that is the only reason the
        template accepts name.  None if its own list accepts it, or nothing
        does."""
        return None if self._listed(name) else self.extras.get(name)

    def _listed(self, name: str) -> bool:
        return name in self.names or any(p.fullmatch(name) for p in self.patterns)

    # For WrappedParams.  A template that checks its own parameters sees an
    # article's names as they are, and gets no settings from a wrapper.

    def _passed_on(self, name: str) -> str | None:
        return name

    def _settings(self) -> dict[str, str]:
        return {}

    def _check_text(self) -> str | None:
        return self.unknown_text


@dataclass(frozen=True)
class Wrapper:
    """A {{#invoke:Template wrapper|wrap|...}} call: the template it passes
    an article's parameters on to, and what it does with them on the way."""

    template: str                   # |_template=
    keeps: frozenset[str]           # |_exclude= and |_reuse=: never passed on
    aliases: Mapping[str, str]      # |_alias-map=: {wrapper's name: other template's}
    args: Mapping[str, str]         # its other settings, such as template_name
    # Kept on some pages and passed on on others, by an {{#if:...}} in
    # |_exclude= or |_reuse=, such as Infobox clergy's "name, when child=yes".
    sometimes_keeps: frozenset[str] = frozenset()

    def passes(self, name: str) -> str | None:
        """The name an article's parameter is passed on as, or None if the
        wrapper keeps it for itself.  As Module:Template wrapper does it."""
        name = self._alias(name)
        return None if name in self.keeps else name

    def _alias(self, name: str) -> str:
        if name in self.aliases:
            return self.aliases[name]
        # '#' stands for a number: foo#:bar# makes foo2 bar2, and foo bar.
        if name + '#' in self.aliases:
            return self.aliases[name + '#'].replace('#', '')
        number = re.search('[0-9]+', name)
        if number:
            alias = self.aliases.get(re.sub('[0-9]+', '#', name))
            if alias is not None:
                return alias.replace('#', number.group(0))
        return name


class WrappedParams(KnownParams):
    """The parameters a wrapper template accepts: the names it keeps for
    itself, and the names the template it wraps accepts once the wrapper
    has passed them on.

    ``unknown_text`` is the wrapped template's, with the settings the
    wrapper gives it filled in, since its category is often named after
    ``template_name``.

    A name the wrapper keeps only sometimes is accepted either way if the
    wrapped template accepts it too, so it's treated as passed on.  If the
    wrapped template doesn't, the article may or may not use the name, and
    it's in ``unsure``."""

    def __init__(self, wrapper: Wrapper, inner: KnownParams) -> None:
        super().__init__()
        self.wrapper, self.inner = wrapper, inner
        self.unknown_text = _fill_in(self._check_text(), self._settings())
        self.unsure = inner.unsure | {name for name in wrapper.sometimes_keeps
                                      if name not in inner}

    def __repr__(self) -> str:
        return f'WrappedParams({self.wrapper.template!r}, {self.inner!r})'

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        passed = self.wrapper.passes(name)
        return passed is None or passed in self.inner

    def added_by(self, name: str) -> str | None:
        passed = self.wrapper.passes(name)
        return None if passed is None else self.inner.added_by(passed)

    def _passed_on(self, name: str) -> str | None:
        passed = self.wrapper.passes(name)
        return None if passed is None else self.inner._passed_on(passed)

    def _settings(self) -> dict[str, str]:
        # A wrapper's settings go to the template it wraps, and override
        # that template's own settings, if it's a wrapper too.
        settings = self.inner._settings()
        for name, value in self.wrapper.args.items():
            passed = self.inner._passed_on(name)
            if passed is not None:
                settings[passed] = value
        return settings

    def _check_text(self) -> str | None:
        return self.inner._check_text()


def _fill_in(text: str | None, args: Mapping[str, str]) -> str | None:
    """text with each {{{name|default}}} given in args replaced by its value."""
    if not text or not args:
        return text
    code = mwparserfromhell.parse(text)
    for argument in code.filter_arguments(recursive=True):
        name = strip_comments(argument.name).strip()
        if name in args:
            # ValueError: in the default of an argument already replaced.
            with suppress(ValueError):
                code.replace(argument, args[name])
    return str(code)


def wrapper_call(source: str) -> Wrapper | None:
    """The template source's {{#invoke:Template wrapper|wrap|...}} call, or
    None if it has none, or has one the bot can't read."""
    calls = list(_invokes(mwparserfromhell.parse(source), _WRAPPER_MODULE, 'wrap'))
    if len(calls) != 1:
        return None   # more than one: it picks a template the bot can't tell
    settings: dict[str, str] = {}
    for param in calls[0].params[1:]:
        if param.showkey and not param_name(param).isdigit():   # positional ones aren't used
            settings[param_name(param)] = strip_comments(param.value).strip()
    settings = {key: value for key, value in settings.items() if value}
    template = settings.get('_template')
    if not template or any('{' in settings.get(key, '') for key in _WRAPPER_SETTINGS
                           if key not in _KEEP_SETTINGS):
        return None
    # Each value the names it keeps can take, from one article to another.
    kept: list[set[str]] = [set()]
    for key in _KEEP_SETTINGS:
        variants = _variants(settings.get(key, ''))
        if variants is None or len(kept) * len(variants) > MAX_VARIANTS:
            return None
        kept = [names | set(_list(variant)) for names in kept for variant in variants]
    always = set.intersection(*kept)
    aliases: dict[str, str] = {}
    for pair in _list(settings.get('_alias-map', '')):
        m = re.match(r'(.*?)\s*:\s*(.+)', pair)
        if m and m.group(1):
            aliases[m.group(1)] = m.group(2)
    return Wrapper(
        template=normalize_template_name(template),
        keeps=frozenset(always),
        aliases=aliases,
        args={key: value for key, value in settings.items() if key not in _WRAPPER_SETTINGS},
        sometimes_keeps=frozenset(set.union(*kept) - always))


def _variants(value: str) -> list[str] | None:
    """The values a wrapper setting can take: just the one, unless it has
    {{#if:...}} or {{#ifeq:...}} parts, which choose for each article.  None
    if it has anything else in braces, which the bot can't read."""
    variants = ['']
    for node in mwparserfromhell.parse(value).nodes:
        branches = [str(node)] if isinstance(node, Text) else _branches(node)
        if branches is None or len(variants) * len(branches) > MAX_VARIANTS:
            return None
        variants = [variant + branch for variant in variants for branch in branches]
    return variants


def _branches(node: object) -> list[str] | None:
    """The text each branch of an {{#if:...}} or {{#ifeq:...}} gives, or
    None if node is anything else, or has braces in its branches."""
    if not isinstance(node, Template):
        return None
    name = str(node.name).strip().lower()
    if name.startswith('#if:'):
        first = 0
    elif name.startswith('#ifeq:'):
        first = 1   # what it compares with
    else:
        return None
    params = node.params[first:first + 2]
    if any(param.showkey or '{' in str(param.value) for param in params):
        return None
    branches = [str(param.value) for param in params]
    return branches + [''] * (2 - len(branches))


def _list(value: str) -> list[str]:
    """A wrapper setting's comma-separated names."""
    return [item.strip() for item in value.split(',') if item.strip()]


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
            elif key in _EXTRA_PARAMS and value:
                for extra in _EXTRA_PARAMS[key]:
                    known.extras.setdefault(extra, key)
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


def _invokes(code: Wikicode, module: str, function: str = 'check') -> Iterator[Template]:
    """The {{#invoke:module|function|...}} calls in parsed wikitext."""
    for call in code.filter_templates(recursive=True):
        name = ' '.join(strip_comments(call.name).replace('_', ' ').split())
        m = re.fullmatch(r'#invoke\s*:\s*(.+)', name, re.IGNORECASE)
        if not m:
            continue
        target = re.sub(r'^module\s*:\s*', '', m.group(1), flags=re.IGNORECASE)
        if (normalize_template_name(target) == module and call.params
                and not call.params[0].showkey
                and strip_comments(call.params[0].value).strip() == function):
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
