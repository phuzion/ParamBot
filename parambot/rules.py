"""Reading a rules page.

Each template's rules are on a page of their own (rulespages finds them).
The format is documented for rule writers in docs/rules-instructions.mediawiki,
which is meant to go on the wiki next to the rules pages.  The bot reads two
things from a page and ignores everything else (including anything inside
comments, <nowiki>, <pre> or <syntaxhighlight>):

1. Wikitables whose caption names a template::

       {| class="wikitable"
       |+ {{tl|Infobox officeholder}}
       ! Old parameter !! New parameter
       |-
       | {{para|imagesize}} || {{para|image_size}}
       |-
       | {{para|termstart#}} || {{para|term_start#}}
       |-
       | {{para|nationality}} || remove
       |}

   Column 1 holds the old names, column 2 the new name or "remove".  "#"
   stands for no number or any number.  A column headed "If both are set"
   can say "merge"; other extra columns are notes.  A category link in the
   caption sets the category to watch.  rowspan and colspan work, and text
   in a cell besides the {{para}} names is a note.

2. Lines in the format of Wikipedia:AutoWikiBrowser/Rename template
   parameters::

       {{AWB rename template parameter|Infobox settlement|imagesize|image_size}}

On a template's own rules page every table is for that template, so the
caption is optional there, and a table or line for any other template is
ignored.

Rules for the same template are combined, wherever they appear on the page.
Rows for the same old name must agree: if they give different new names,
neither is used, and if only some of them say "merge", the bot doesn't merge.
Anything that can't be used is skipped and described in Config.problems.
"""

import dataclasses
import re
from dataclasses import dataclass, field

import mwparserfromhell
from mwparserfromhell.nodes import Tag, Template, Wikilink
from mwparserfromhell.wikicode import Wikicode

from . import messages as msg
from .luapattern import LuaPattern
from .wikitable import Row, Table, cell_text, tables_in
from .wikitext import (
    default_unknown_category,
    normalize_category,
    normalize_template_name,
    strip_comments,
)

__all__ = ['Rule', 'Match', 'RuleSet', 'Config', 'parse_config']

AWB_TEMPLATE = msg.AWB_TEMPLATE
NUMBER = '#'                 # stands for no number or any number
MAX_NUMBERS = 9              # Lua patterns allow nine captures
DEFAULT_SEPARATOR = '<br />'

RENAME = 'rename'
REMOVE = 'remove'
SKIP = 'skip'                # what to do when old and new are both set
MERGE = 'merge'

# Templates that link to a template, as used in captions: {{tl|Infobox foo}}.
_TEMPLATE_LINKS = {'Tl', 'Tlx', 'Tlp', 'Tlc', 'Tlg', 'Tl2', 'Tlf', 'Tls', 'Template link'}
_NAME_TAGS = ('code', 'kbd', 'tt', 'samp')
_REMOVE_RE = re.compile(r'^\W*(remove|delete)\b', re.IGNORECASE)
_CONFLICT_HEADER_RE = re.compile(r'\bboth\b|\bmerge\b|\bconflict', re.IGNORECASE)
_NOT_MERGE_RE = re.compile(r'^(skip|review|leave|no|-|—)')
_LUA_MAGIC = set('^$()%.[]*+-?')


@dataclass(frozen=True)
class Rule:
    kind: str                            # RENAME or REMOVE
    old: str                             # the old name as written, possibly with "#"
    new: str | None = None               # the new name as written, possibly with "#"
    pattern: LuaPattern | None = None    # for names with "#"
    replacement: str | None = None       # Lua replacement, for renames with "#"
    conflict: str = SKIP                 # SKIP or MERGE
    separator: str = DEFAULT_SEPARATOR   # between merged values

    def describe(self) -> str:
        if self.kind == REMOVE:
            return f'remove {self.old}'
        return f'{self.old} → {self.new}'


@dataclass
class Match:
    rule: Rule
    target: str | None                   # the new name; None for removals
    # Other rules with "#" that match the same name but would do something
    # else.  If there are any, the bot shouldn't guess which was meant.
    others: tuple[Rule, ...] = ()


@dataclass
class RuleSet:
    """One template's rules, as written on its rules page."""

    template: str
    category: str                        # the category to watch
    category_explicit: bool = False      # a table's caption named the category
    has_table: bool = False              # not only one-line rules
    page: str = ''                       # the page the rules are on; '' for a local file
    revision: int | None = None          # the approved revision of that page
    active: bool = True                  # inactive rules are checked, but never used
    renames: dict[str, Rule] = field(default_factory=dict)   # by old name
    removes: dict[str, Rule] = field(default_factory=dict)   # by name
    patterns: list[Rule] = field(default_factory=list)       # names with "#", in order
    ignored: set[str] = field(default_factory=set)           # old names whose rows disagree
    merge_disputed: set[str] = field(default_factory=set)    # rows disagree about merging

    def lookup(self, name: str) -> Match | None:
        """The rule for a parameter name, if there is one.  Exact names win
        over names with "#".  If several names with "#" match and disagree,
        the others are listed in the match."""
        rule = self.renames.get(name)
        if rule is not None:
            return Match(rule, rule.new)
        rule = self.removes.get(name)
        if rule is not None:
            return Match(rule, None)
        matches = [m for m in (_pattern_match(rule, name) for rule in self.patterns)
                   if m is not None]
        if not matches:
            return None
        first = matches[0]
        others = tuple(m.rule for m in matches[1:] if m.target != first.target)
        return Match(first.rule, first.target, others)

    def written(self, old: str) -> Rule | None:
        """The rule for an old name exactly as written: "termstart#", not
        "termstart2"."""
        if NUMBER in old:
            return next((rule for rule in self.patterns if rule.old == old), None)
        return self.renames.get(old) or self.removes.get(old)

    def put(self, rule: Rule) -> None:
        """Add a rule, or replace the one for the same old name where it stands."""
        if rule.pattern is None:
            (self.removes if rule.kind == REMOVE else self.renames)[rule.old] = rule
            return
        for index, existing in enumerate(self.patterns):
            if existing.old == rule.old:
                self.patterns[index] = rule
                return
        self.patterns.append(rule)

    def discard(self, old: str) -> None:
        """Drop the rule for an old name as written."""
        self.renames.pop(old, None)
        self.removes.pop(old, None)
        self.patterns = [rule for rule in self.patterns if rule.old != old]

    @property
    def rules(self) -> list[Rule]:
        return [*self.renames.values(), *self.removes.values(), *self.patterns]

    def __len__(self) -> int:
        return len(self.renames) + len(self.removes) + len(self.patterns)


def _pattern_match(rule: Rule, name: str) -> Match | None:
    """What a rule with "#" does to name, if it applies to it."""
    assert rule.pattern is not None
    if not rule.pattern.fullmatch(name):
        return None
    if rule.kind == REMOVE:
        return Match(rule, None)
    assert rule.replacement is not None
    target = rule.pattern.sub(name, rule.replacement)
    return Match(rule, target) if target != name else None


@dataclass
class Config:
    rulesets: dict[str, RuleSet] = field(default_factory=dict)   # by template name
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_config(text: str, template: str | None = None) -> Config:
    """The rules in text.  template is set when text is a template's own
    rules page: every table there is for that template, and rules for any
    other template are reported and ignored."""
    config = Config()
    page_template = normalize_template_name(template) if template else None
    code = mwparserfromhell.parse(text)
    for table in tables_in(code):
        _read_table(table, config, page_template)
    for call in code.filter_templates():
        if normalize_template_name(call.name) == AWB_TEMPLATE:
            _read_one_line_rule(call, config, page_template)
    for ruleset in config.rulesets.values():
        _resolve_chains(ruleset, config.problems)
    return config


def _ruleset_for(config: Config, template: str, category: str | None = None) -> RuleSet:
    """The rule set for a template, created if need be.  A category named in
    a caption overrides the default."""
    template = normalize_template_name(template)
    ruleset = config.rulesets.get(template)
    if ruleset is None:
        default = category or default_unknown_category(template)
        ruleset = RuleSet(template, normalize_category(default), category_explicit=bool(category))
        config.rulesets[template] = ruleset
    elif category:
        category = normalize_category(category)
        if ruleset.category_explicit and category != ruleset.category:
            config.problems.append(msg.two_categories(template, ruleset.category, category))
        ruleset.category = category
        ruleset.category_explicit = True
    return ruleset


# -- tables ----------------------------------------------------------------

def _read_table(table: Table, config: Config, page_template: str | None) -> None:
    data = [row for row in table.rows if not _is_header(row)]
    target = _table_target(table, data, page_template, config.problems)
    if target is None:
        return
    template, category = target
    ruleset = _ruleset_for(config, template, category)
    ruleset.has_table = True
    conflict_column = _conflict_column(table)
    for row in data:
        _read_row(row, ruleset, conflict_column, config.problems)


def _table_target(table: Table, data: list[Row], page_template: str | None,
                  problems: list[str]) -> tuple[str, str | None] | None:
    """The template a table is for, and the category its caption links to,
    if any.  None if the table isn't rules, or can't be used."""
    looks_like_rules = any(_has_para(row.column(0)) for row in data)
    if table.caption is None:
        if page_template is not None and looks_like_rules:
            return page_template, None
        if looks_like_rules:
            # Only complain about tables that look like rules.
            problems.append(msg.table_without_caption(table.tag))
        return None
    links, text, category = _read_caption(table.caption)
    if page_template is not None:
        return _page_table_target(page_template, links, text, category, looks_like_rules,
                                  problems)
    names = links or ([text] if text else [])
    if not names:
        problems.append(msg.caption_without_template(table.caption))
        return None
    if len(set(names)) > 1:
        problems.append(msg.caption_with_several_templates(names))
    return names[0], category


def _page_table_target(page_template: str, links: list[str], text: str, category: str | None,
                       looks_like_rules: bool, problems: list[str]
                       ) -> tuple[str, str | None] | None:
    """On a template's own rules page, every table is for that template.  A
    table counts as rules if its caption names the template or a category,
    or if it holds {{para}} names.  One whose caption links to another
    template is reported and ignored."""
    if links:
        if links[0] != page_template:
            problems.append(msg.table_for_another_template(page_template, links[0]))
            return None
        if len(set(links)) > 1:
            problems.append(msg.caption_with_several_templates(links))
        return page_template, category
    if text == page_template or category or looks_like_rules:
        return page_template, category
    return None


def _read_caption(caption: Wikicode) -> tuple[list[str], str, str | None]:
    """What a caption names: the templates it links to (with {{tl|...}} and
    the like), its plain text (for a caption that names a template without
    a link), and the category it links to, if any."""
    category = None
    for link in caption.filter_wikilinks():
        title = _link_title(link)
        if re.match(r'category\s*:', title, re.IGNORECASE):
            category = title
            caption.remove(link)
    links = [normalize_template_name(name) for name in _template_links(caption) if name]
    text = ' '.join(caption.strip_code().split()).lstrip('+').strip()
    return links, normalize_template_name(text), category


def _template_links(caption: Wikicode) -> list[str]:
    """Templates named with {{tl|...}} and friends, else with [[Template:...]]."""
    names = [strip_comments(t.get('1').value).strip()
             for t in caption.filter_templates(recursive=False)
             if normalize_template_name(t.name) in _TEMPLATE_LINKS and t.has('1')]
    if names:
        return names
    titles = [_link_title(link) for link in caption.filter_wikilinks()]
    return [title for title in titles if re.match(r'template\s*:', title, re.IGNORECASE)]


def _link_title(link: Wikilink) -> str:
    return str(link.title).strip().lstrip(':').strip()


def _conflict_column(table: Table) -> int | None:
    """The column headed "If both are set", if there is one."""
    header = next((row for row in table.rows if _is_header(row)), None)
    if header is None:
        return None
    column = None
    for index, cell in enumerate(header.columns):
        if index >= 2 and _CONFLICT_HEADER_RE.search(cell_text(cell)):
            column = index
    return column


def _read_row(row: Row, ruleset: RuleSet, conflict_column: int | None,
              problems: list[str]) -> None:
    template = ruleset.template
    olds = _cell_names(row.column(0))
    new_cell = row.column(1)
    if not olds:
        if _cell_names(new_cell):
            problems.append(msg.new_name_without_old(template))
        return
    conflict = _row_conflict(row, conflict_column, template, olds[0], problems)
    new = None
    if not _is_remove(new_cell):
        news = _cell_names(new_cell)
        if not news:
            problems.append(msg.no_new_name(template, olds[0]))
            return
        if len(news) > 1:
            problems.append(msg.several_new_names(template, olds[0], news))
            return
        new = news[0]
    for old in olds:
        _add_rule(ruleset, old, new, conflict, problems)


def _row_conflict(row: Row, column: int | None, template: str, old: str,
                  problems: list[str]) -> str:
    """What the row's "If both are set" cell asks for."""
    said = cell_text(row.column(column)).lower() if column is not None else ''
    if 'merge' in said:
        return MERGE
    if said and not _NOT_MERGE_RE.match(said):
        problems.append(msg.unclear_conflict_cell(template, old, said))
    return SKIP


def _has_para(cell: Tag | None) -> bool:
    return cell is not None and any(
        normalize_template_name(t.name) == 'Para' for t in cell.contents.filter_templates())


def _is_header(row: Row) -> bool:
    """A header row, unless its header cells hold parameter names."""
    return row.header and not any(_has_para(cell) for cell in row.cells)


def _cell_names(cell: Tag | None) -> list[str]:
    """The parameter names written in a cell: its {{para}}s, else its
    <code>s, else all of its text."""
    if cell is None:
        return []
    names = [strip_comments(t.get('1').value).strip()
             for t in cell.contents.filter_templates(recursive=False)
             if normalize_template_name(t.name) == 'Para' and t.has('1')]
    if not any(names):
        names = [tag.contents.strip_code().strip()
                 for tag in cell.contents.filter_tags(recursive=False)
                 if tag.tag in _NAME_TAGS]
    if not any(names):
        names = [cell_text(cell)]
    return [name for name in names if name]


def _is_remove(cell: Tag | None) -> bool:
    return (cell is not None and not _has_para(cell)
            and bool(_REMOVE_RE.match(cell.contents.strip_code().strip())))


# -- one-line rules --------------------------------------------------------

def _read_one_line_rule(call: Template, config: Config, page_template: str | None) -> None:
    values = [strip_comments(p.value).strip() for p in call.params if not p.showkey]
    if len(values) != 3 or not values[0] or not _plain(values[1]) or not _plain(values[2]):
        config.problems.append(msg.malformed_one_line_rule(call))
        return
    name, old, new = values
    template = normalize_template_name(name)
    if page_template is not None and template != page_template:
        config.problems.append(msg.line_for_another_template(page_template, template))
        return
    _add_rule(_ruleset_for(config, template), old, new, SKIP, config.problems)


# -- rules -----------------------------------------------------------------

def _plain(text: str) -> bool:
    """True if text can be a parameter name (no markup)."""
    return bool(text) and not any(c in text for c in '{}[]|=<>\n')


def _add_rule(ruleset: RuleSet, old: str, new: str | None, conflict: str,
              problems: list[str]) -> None:
    """Add the rule old → new (new is None for "remove"), unless it's broken
    or another row for old disagrees with it."""
    problem = _rule_problem(ruleset.template, old, new)
    if problem:
        problems.append(problem)
        return
    if old == new or old in ruleset.ignored:
        return
    existing = ruleset.written(old)
    if existing is None:
        ruleset.put(_new_rule(old, new, conflict))
    elif existing.new != new:
        # The rows disagree about what old becomes, so don't guess.
        ruleset.discard(old)
        ruleset.ignored.add(old)
        problems.append(msg.rows_disagree(ruleset.template, old, existing.new, new))
    elif existing.kind == RENAME and existing.conflict != conflict:
        # Only some of the rows say merge.  Not merging is the safe choice.
        if old not in ruleset.merge_disputed:
            ruleset.merge_disputed.add(old)
            problems.append(msg.merge_disputed(ruleset.template, old))
        ruleset.put(dataclasses.replace(existing, conflict=SKIP))


def _rule_problem(template: str, old: str, new: str | None) -> str | None:
    for name in (old, new):
        if name is None:
            continue
        if not _plain(name):
            return msg.markup_in_name(template, old, new)
        if ',' in name or ';' in name:
            return msg.several_names_in_one(template, name)
    numbers = old.count(NUMBER)
    if new is not None and new.count(NUMBER) != numbers:
        return msg.number_in_one_name(template, old, new)
    if numbers > MAX_NUMBERS:
        return msg.too_many_numbers(template, old)
    return None


def _new_rule(old: str, new: str | None, conflict: str) -> Rule:
    """The rule old → new (new is None for "remove")."""
    if NUMBER not in old:
        return Rule(REMOVE, old) if new is None else Rule(RENAME, old, new, conflict=conflict)
    pattern = _number_pattern(old)
    if new is None:
        return Rule(REMOVE, old, pattern=pattern)
    return Rule(RENAME, old, new, pattern=pattern, replacement=_number_replacement(new),
                conflict=conflict)


def _number_pattern(old: str) -> LuaPattern:
    """termstart# -> the Lua pattern termstart(%d*)."""
    return LuaPattern(''.join(
        '(%d*)' if c == NUMBER else '%' + c if c in _LUA_MAGIC else c for c in old))


def _number_replacement(new: str) -> str:
    """term_start# -> the Lua replacement term_start%1."""
    out = []
    count = 0
    for c in new:
        if c == NUMBER:
            count += 1
            out.append(f'%{count}')
        else:
            out.append('%%' if c == '%' else c)
    return ''.join(out)


def _resolve_chains(ruleset: RuleSet, problems: list[str]) -> None:
    """Turn a → b, b → c into a → c, b → c."""
    renames = ruleset.renames
    for old in list(renames):
        rule = renames[old]
        seen = {old}
        new = rule.new
        while new in renames:
            if new in seen:
                problems.append(msg.rename_loop(ruleset.template, old))
                del renames[old]
                break
            seen.add(new)
            new = renames[new].new
        else:
            if new != rule.new:
                renames[old] = Rule(RENAME, old, new, conflict=rule.conflict)
