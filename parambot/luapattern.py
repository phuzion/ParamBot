"""Lua patterns, as used by Module:Check for deprecated parameters and
Module:Check for unknown parameters, translated into Python regexes.

Templates on the English Wikipedia describe parameter families with Lua
patterns (``blank(%d*)_name = custom_label%1_sec1``).  Rules copied from a
template are kept in that syntax so they can be pasted verbatim, and are
translated here.  Only the parts of the Lua pattern language that make sense
for parameter names are supported; ``%b``, ``%f`` and position captures raise
``LuaPatternError``.

Character classes follow mw.ustring, where %a, %d, %s and %w are
Unicode-aware.  %l, %u and everything inside ``[...]`` sets use the ASCII
forms, which is enough for parameter names.
"""

import re

__all__ = ['LuaPattern', 'LuaPatternError']


class LuaPatternError(ValueError):
    pass


# Classes outside a set.
_CLASSES = {
    'a': r'[^\W\d_]',
    'd': r'\d',
    'l': r'[a-z]',
    'u': r'[A-Z]',
    's': r'\s',
    'w': r'[^\W_]',
    'x': r'[0-9A-Fa-f]',
    'p': r'[!-/:-@\[-`{-~]',
    'c': r'[\x00-\x1f\x7f]',
    'A': r'[\W\d_]',
    'D': r'\D',
    'S': r'\S',
    'W': r'[\W_]',
    'X': r'[^0-9A-Fa-f]',
    'P': r'[^!-/:-@\[-`{-~]',
    'C': r'[^\x00-\x1f\x7f]',
}

# Classes inside a set (the text that goes between the brackets).
_SET_CLASSES = {
    'a': 'a-zA-Z',
    'd': '0-9',
    'l': 'a-z',
    'u': 'A-Z',
    's': r'\s',
    'w': 'a-zA-Z0-9',
    'x': '0-9A-Fa-f',
    'p': r'!-/:-@\[-`{-~',
    'c': r'\x00-\x1f\x7f',
}

_QUANTIFIERS = {'*': '*', '+': '+', '?': '?', '-': '*?'}


def _escape_in_set(ch):
    return '\\' + ch if ch in '\\]^-[' else ch


class LuaPattern:
    """A Lua pattern that must match a whole parameter name."""

    def __init__(self, source):
        self.source = source
        self.groups = 0
        self.regex = re.compile(self._translate(source), re.DOTALL)

    def __repr__(self):
        return f'LuaPattern({self.source!r})'

    def __eq__(self, other):
        return isinstance(other, LuaPattern) and other.source == self.source

    def __hash__(self):
        return hash(self.source)

    def fullmatch(self, name):
        return self.regex.fullmatch(name)

    def check_replacement(self, replacement):
        """Raise LuaPatternError if replacement is malformed or refers to a
        capture the pattern does not have."""
        for m in re.finditer(r'%(.?)', replacement.replace('%%', '')):
            ref = m.group(1)
            if not ref.isdigit():
                raise LuaPatternError(f'invalid use of % in replacement {replacement!r}')
            if int(ref) > max(self.groups, 1):
                raise LuaPatternError(
                    f'invalid capture index %{ref} in replacement {replacement!r}')

    def sub(self, name, replacement):
        """Return ``replacement`` expanded against ``name``, or None if the
        pattern does not match the whole name."""
        m = self.fullmatch(name)
        if m is None:
            return None
        out = []
        i = 0
        while i < len(replacement):
            ch = replacement[i]
            if ch != '%':
                out.append(ch)
                i += 1
                continue
            if i + 1 >= len(replacement):
                raise LuaPatternError(f'trailing % in replacement {replacement!r}')
            nxt = replacement[i + 1]
            if nxt == '%':
                out.append('%')
            elif nxt.isdigit():
                idx = int(nxt)
                if idx == 0 or (idx == 1 and self.groups == 0):
                    out.append(m.group(0))
                elif idx <= self.groups:
                    out.append(m.group(idx) or '')
                else:
                    raise LuaPatternError(
                        f'invalid capture index %{idx} in replacement {replacement!r}')
            else:
                raise LuaPatternError(f'invalid use of % in replacement {replacement!r}')
            i += 2
        return ''.join(out)

    def _translate(self, src):
        out = []
        i = 0
        n = len(src)
        depth = 0
        if src.startswith('^'):
            i = 1
        end = n
        if src.endswith('$') and not src.endswith('%$'):
            end = n - 1
        while i < end:
            ch = src[i]
            if ch == '(':
                if i + 1 < end and src[i + 1] == ')':
                    raise LuaPatternError(f'position captures are not supported: {src!r}')
                out.append('(')
                depth += 1
                self.groups += 1
                i += 1
                continue
            if ch == ')':
                if depth == 0:
                    raise LuaPatternError(f'unbalanced ) in {src!r}')
                out.append(')')
                depth -= 1
                i += 1
                continue
            # A single-character item, which may take a quantifier.
            if ch == '%':
                if i + 1 >= end:
                    raise LuaPatternError(f'pattern ends with % in {src!r}')
                nxt = src[i + 1]
                if nxt in 'bf':
                    raise LuaPatternError(f'%{nxt} is not supported: {src!r}')
                if nxt.isdigit():
                    out.append(f'(?:\\{nxt})')
                    i += 2
                    continue
                item = _CLASSES.get(nxt) or re.escape(nxt)
                i += 2
            elif ch == '[':
                item, i = self._translate_set(src, i, end)
            elif ch == '.':
                item = '.'
                i += 1
            else:
                item = re.escape(ch)
                i += 1
            if i < end and src[i] in _QUANTIFIERS:
                item += _QUANTIFIERS[src[i]]
                i += 1
            out.append(item)
        if depth:
            raise LuaPatternError(f'unfinished capture in {src!r}')
        return ''.join(out)

    @staticmethod
    def _translate_set(src, i, end):
        """Translate the set starting at src[i] == '['; return (regex, next index)."""
        j = i + 1
        parts = ['[']
        if j < end and src[j] == '^':
            parts.append('^')
            j += 1
        first = True
        while j < end:
            ch = src[j]
            if ch == ']' and not first:
                parts.append(']')
                return ''.join(parts), j + 1
            first = False
            if ch == '%':
                if j + 1 >= end:
                    break
                nxt = src[j + 1]
                if nxt in _SET_CLASSES:
                    parts.append(_SET_CLASSES[nxt])
                elif nxt.isalpha():
                    raise LuaPatternError(f'%{nxt} is not supported inside a set: {src!r}')
                else:
                    parts.append(_escape_in_set(nxt))
                j += 2
                continue
            if j + 2 < end and src[j + 1] == '-' and src[j + 2] != ']':
                parts.append(_escape_in_set(ch) + '-' + _escape_in_set(src[j + 2]))
                j += 3
                continue
            parts.append(_escape_in_set(ch))
            j += 1
        raise LuaPatternError(f'malformed set in {src!r}')
