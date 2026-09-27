"""Applying rule sets to a page's wikitext.

Only parameter names are changed; values are moved only when the old
parameter has to be folded into an existing new one.  Cases the bot cannot
settle on its own are returned as issues for the report page.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import mwparserfromhell

from .rules import REMOVE
from .wikitext import is_blank, normalize_template_name, param_name, same_value, split_ws

__all__ = ['Change', 'Issue', 'FixResult', 'fix_wikitext']

RENAMED = 'renamed'
FILLED = 'filled'            # new parameter was empty; old value moved into it
DUPLICATE = 'duplicate'      # both set to the same value; old one removed
MERGED = 'merged'            # both set; old value appended to new one
REMOVED = 'removed'          # "remove" rule
EMPTY = 'empty'              # old parameter was empty; removed


@dataclass
class Change:
    template: str
    old: str
    new: Optional[str]
    action: str
    # False when the edit would not change what the page displays or which
    # tracking categories it is in (the old parameter was empty).
    substantive: bool

    def describe(self):
        if self.action in (RENAMED, FILLED):
            return f'{self.old} → {self.new}'
        if self.action == DUPLICATE:
            return f'removed {self.old} (duplicate of {self.new})'
        if self.action == MERGED:
            return f'merged {self.old} into {self.new}'
        if self.action == EMPTY:
            return f'removed empty {self.old}'
        return f'removed {self.old}'


@dataclass
class Issue:
    template: str
    param: str
    target: Optional[str]
    reason: str


@dataclass
class FixResult:
    original: str
    text: str
    changes: list = field(default_factory=list)
    issues: list = field(default_factory=list)

    @property
    def changed(self):
        return self.text != self.original

    @property
    def substantive(self):
        return self.changed and any(c.substantive for c in self.changes)

    def templates(self):
        return sorted({c.template for c in self.changes})


def fix_wikitext(text, rulesets):
    """Apply rule sets to wikitext and return a FixResult."""
    index = {}
    for rs in rulesets:
        for name in rs.names:
            index[name] = rs
    result = FixResult(original=text, text=text)
    code = mwparserfromhell.parse(text)
    for tpl in code.filter_templates(recursive=True):
        rs = index.get(normalize_template_name(tpl.name))
        if rs is not None:
            _fix_template(tpl, rs, result)
    result.text = str(code)
    return result


def _fix_template(tpl, rs, result):
    known = rs.known

    def issue(param, target, reason):
        result.issues.append(Issue(rs.template, param, target, reason))

    def change(old, new, action, substantive):
        result.changes.append(Change(rs.template, old, new, action, substantive))

    # The = signs are lined up at a column if names of different lengths
    # were padded to reach it.
    padded = defaultdict(set)
    for q in tpl.params:
        if q.showkey and '\n' not in str(q.name):
            padded[len(str(q.name))].add(len(str(q.name).strip()))

    for param in list(tpl.params):
        if not param.showkey or not any(p is param for p in tpl.params):
            continue
        name = param_name(param)
        match = rs.lookup(name)
        if match is None:
            continue
        if known is not None and name in known:
            # Still accepted by the template: not broken, so not ours to fix.
            continue
        if '<!--' in str(param.name):
            issue(name, match.target, 'parameter name contains a comment')
            continue
        blank = is_blank(param.value)

        if match.rule.kind == REMOVE:
            tpl.remove(param)
            change(name, None, EMPTY if blank else REMOVED, not blank)
            continue

        target = match.target
        if known is not None and target not in known:
            issue(name, target, f'the template does not accept "{target}"; check the rule')
            continue

        existing = [q for q in tpl.params
                    if q is not param and q.showkey and param_name(q) == target]
        if not existing:
            raw = str(param.name)
            param.name = _renamed(raw, target, len(padded[len(raw)]) > 1)
            change(name, target, RENAMED, not blank)
            continue

        dest = existing[-1]  # MediaWiki uses the last of duplicated parameters
        if blank:
            tpl.remove(param)
            change(name, target, EMPTY, False)
        elif is_blank(dest.value):
            dest.value = _filled(str(dest.value), str(param.value))
            tpl.remove(param)
            change(name, target, FILLED, True)
        elif same_value(param.value, dest.value):
            tpl.remove(param)
            change(name, target, DUPLICATE, True)
        elif match.rule.conflict == 'merge':
            dest.value = _merged(str(dest.value), str(param.value), match.rule.separator)
            tpl.remove(param)
            change(name, target, MERGED, True)
        else:
            issue(name, target, f'"{name}" and "{target}" are both set, to different values')


def _renamed(raw, new, aligned=False):
    """Rename a raw parameter name, keeping its whitespace and, where the
    names were padded to line up the = signs, the alignment."""
    lead, core, trail = split_ws(raw)
    if trail and '\n' not in trail and (aligned or len(trail) > 1):
        trail = ' ' * max(1, len(core) + len(trail) - len(new))
    return lead + new + trail


def _filled(dest, src):
    """Put src's content into the empty value dest, keeping dest's layout
    and any comment it holds."""
    d_lead, d_core, d_trail = split_ws(dest)
    s_lead, s_core, _ = split_ws(src)
    lead = s_lead if '\n' in s_lead else (d_lead or s_lead)
    core = s_core + (' ' + d_core if d_core else '')
    return lead + core + d_trail


def _merged(dest, src, separator):
    d_lead, d_core, d_trail = split_ws(dest)
    s_core = split_ws(src)[1]
    return d_lead + d_core + separator + s_core + d_trail
