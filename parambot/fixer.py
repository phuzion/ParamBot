"""Applying a template's rules to a page's wikitext.

Only parameter names are changed; values are moved only when the old
parameter has to be folded into an existing new one.  Cases the bot cannot
settle on its own are returned as issues for the report page.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

import mwparserfromhell
from mwparserfromhell.nodes import Template
from mwparserfromhell.nodes.extras import Parameter

from . import messages as msg
from .rules import MERGE, REMOVE, Rule, RuleSet
from .templatescan import KnownParams
from .wikitext import is_blank, normalize_template_name, param_name, same_value, split_ws

__all__ = ['TemplateRules', 'Change', 'Issue', 'FixResult', 'fix_wikitext']

# What happened to an old parameter.
RENAMED = 'renamed'
FILLED = 'filled'            # the new parameter was empty; the old value was moved into it
DUPLICATE = 'duplicate'      # both were set to the same value; the old one was removed
MERGED = 'merged'            # both were set; the old value was appended to the new one
REMOVED = 'removed'          # a "remove" rule
EMPTY = 'empty'              # the old parameter was empty and was removed


@dataclass(frozen=True)
class TemplateRules:
    """A template's rules, ready to apply."""

    rules: RuleSet
    names: frozenset[str]              # the template's name and its redirects
    known: KnownParams | None = None   # the parameters it accepts; None if not checked

    @classmethod
    def unchecked(cls, rules: RuleSet) -> 'TemplateRules':
        """The rules on their own, for use without the wiki: no redirects, and
        no check against the template's accepted parameters."""
        return cls(rules, frozenset({rules.template}))

    @property
    def template(self) -> str:
        return self.rules.template

    def still_accepts(self, name: str) -> bool:
        """True if the template is known to accept name."""
        return self.known is not None and name in self.known

    def rejects(self, name: str) -> bool:
        """True if the template is known not to accept name."""
        return self.known is not None and name not in self.known


@dataclass
class Change:
    template: str
    old: str
    new: str | None
    action: str
    # False when the edit would not change what the page displays or which
    # tracking categories it is in (the old parameter was empty).
    substantive: bool

    def describe(self) -> str:
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
    target: str | None
    reason: str


@dataclass
class FixResult:
    original: str
    text: str
    changes: list[Change] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.text != self.original

    @property
    def substantive(self) -> bool:
        return self.changed and any(c.substantive for c in self.changes)

    def templates(self) -> list[str]:
        return sorted({c.template for c in self.changes})


def fix_wikitext(text: str, targets: Iterable[TemplateRules]) -> FixResult:
    """Apply each template's rules to its calls in wikitext."""
    by_name = {name: target for target in targets for name in target.names}
    result = FixResult(original=text, text=text)
    code = mwparserfromhell.parse(text)
    for call in code.filter_templates(recursive=True):
        target = by_name.get(normalize_template_name(call.name))
        if target is not None:
            _CallFixer(call, target, result).fix()
    result.text = str(code)
    return result


class _CallFixer:
    """Applies one template's rules to one call of it."""

    def __init__(self, call: Template, target: TemplateRules, result: FixResult) -> None:
        self.call = call
        self.target = target
        self.result = result
        # Name widths whose = signs line up because names of different
        # lengths were padded to reach them.
        padded: dict[int, set[int]] = defaultdict(set)
        for param in call.params:
            if param.showkey and '\n' not in str(param.name):
                padded[len(str(param.name))].add(len(str(param.name).strip()))
        self.aligned_widths = {width for width, lengths in padded.items() if len(lengths) > 1}

    def fix(self) -> None:
        for param in list(self.call.params):
            if param.showkey and any(p is param for p in self.call.params):
                self._fix_param(param)

    def _fix_param(self, param: Parameter) -> None:
        name = param_name(param)
        match = self.target.rules.lookup(name)
        if match is None or self.target.still_accepts(name):
            return  # no rule, or the template still accepts it, so nothing is broken
        if '<!--' in str(param.name):
            self._issue(name, match.target, msg.name_has_comment())
        elif match.rule.kind == REMOVE:
            self._remove(param, name)
        else:
            assert match.target is not None
            self._rename(param, name, match.target, match.rule)

    def _remove(self, param: Parameter, name: str) -> None:
        blank = is_blank(param.value)
        self.call.remove(param)
        self._change(name, None, EMPTY if blank else REMOVED, not blank)

    def _rename(self, param: Parameter, name: str, new: str, rule: Rule) -> None:
        if self.target.rejects(new):
            self._issue(name, new, msg.target_rejected(new))
            return
        existing = [p for p in self.call.params
                    if p is not param and p.showkey and param_name(p) == new]
        if not existing:
            raw = str(param.name)
            param.name = _renamed(raw, new, len(raw) in self.aligned_widths)
            self._change(name, new, RENAMED, not is_blank(param.value))
        else:
            # MediaWiki uses the last of duplicated parameters.
            self._fold_into(param, existing[-1], name, new, rule)

    def _fold_into(self, param: Parameter, dest: Parameter, name: str, new: str,
                   rule: Rule) -> None:
        """The new parameter is already there: fold the old one into it."""
        if is_blank(param.value):
            self.call.remove(param)
            self._change(name, new, EMPTY, False)
        elif is_blank(dest.value):
            dest.value = _filled(str(dest.value), str(param.value))
            self.call.remove(param)
            self._change(name, new, FILLED, True)
        elif same_value(param.value, dest.value):
            self.call.remove(param)
            self._change(name, new, DUPLICATE, True)
        elif rule.conflict == MERGE:
            dest.value = _merged(str(dest.value), str(param.value), rule.separator)
            self.call.remove(param)
            self._change(name, new, MERGED, True)
        else:
            self._issue(name, new, msg.both_set(name, new))

    def _change(self, old: str, new: str | None, action: str, substantive: bool) -> None:
        self.result.changes.append(Change(self.target.template, old, new, action, substantive))

    def _issue(self, param: str, target: str | None, reason: str) -> None:
        self.result.issues.append(Issue(self.target.template, param, target, reason))


def _renamed(raw: str, new: str, aligned: bool = False) -> str:
    """Rename a raw parameter name, keeping its whitespace and, where the
    names were padded to line up the = signs, the alignment."""
    lead, core, trail = split_ws(raw)
    if trail and '\n' not in trail and (aligned or len(trail) > 1):
        trail = ' ' * max(1, len(core) + len(trail) - len(new))
    return lead + new + trail


def _filled(dest: str, src: str) -> str:
    """Put src's content into the empty value dest, keeping dest's layout
    and any comment it holds."""
    d_lead, d_core, d_trail = split_ws(dest)
    s_lead, s_core, _ = split_ws(src)
    lead = s_lead if '\n' in s_lead else (d_lead or s_lead)
    core = s_core + (' ' + d_core if d_core else '')
    return lead + core + d_trail


def _merged(dest: str, src: str, separator: str) -> str:
    d_lead, d_core, d_trail = split_ws(dest)
    s_core = split_ws(src)[1]
    return d_lead + d_core + separator + s_core + d_trail
