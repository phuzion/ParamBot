"""Reading the rules page.

The format is documented for rule writers in docs/rules-instructions.mediawiki,
which is meant to go on the wiki next to the rules page.  The bot reads two
things from the page and ignores everything else (including anything inside
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

Rules for the same template are combined, wherever they appear on the page.
Anything that can't be used is skipped and described in Config.problems.
"""

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


@dataclass
class RuleSet:
    """One template's rules, as written on the rules page."""

    template: str
    category: str                        # the category to watch
    category_explicit: bool = False      # a table's caption named the category
    has_table: bool = False              # not only one-line rules
    renames: dict[str, Rule] = field(default_factory=dict)   # by old name
    removes: dict[str, Rule] = field(default_factory=dict)   # by name
    patterns: list[Rule] = field(default_factory=list)       # names with "#", in order

    def lookup(self, name: str) -> Match | None:
        """The rule for a parameter name, if there is one.  Exact names win
        over names with "#"."""
        rule = self.renames.get(name)
        if rule is not None:
            return Match(rule, rule.new)
        rule = self.removes.get(name)
        if rule is not None:
            return Match(rule, None)
        for rule in self.patterns:
            assert rule.pattern is not None
            if not rule.pattern.fullmatch(name):
                continue
            if rule.kind == REMOVE:
                return Match(rule, None)
            assert rule.replacement is not None
            target = rule.pattern.sub(name, rule.replacement)
            if target != name:
                return Match(rule, target)
        return None

    @property
    def rules(self) -> list[Rule]:
        return [*self.renames.values(), *self.removes.values(), *self.patterns]

    def __len__(self) -> int:
        return len(self.renames) + len(self.removes) + len(self.patterns)


@dataclass
class Config:
    rulesets: dict[str, RuleSet] = field(default_factory=dict)   # by template name
    problems: list[str] = field(default_factory=list)


def parse_config(text: str) -> Config:
    config = Config()
    code = mwparserfromhell.parse(text)
    for table in tables_in(code):
        _read_table(table, config)
    for template in code.filter_templates():
        if normalize_template_name(template.name) == AWB_TEMPLATE:
            _read_one_line_rule(template, config)
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

def _read_table(table: Table, config: Config) -> None:
    data = [row for row in table.rows if not _is_header(row)]
    if table.caption is None:
        # Only complain about tables that look like rules.
        if any(_has_para(row.column(0)) for row in data):
            config.problems.append(msg.table_without_caption(table.tag))
        return
    names, category = _caption_target(table.caption)
    if not names:
        config.problems.append(msg.caption_without_template(table.caption))
        return
    if len(set(names)) > 1:
        config.problems.append(msg.caption_with_several_templates(names))
    ruleset = _ruleset_for(config, names[0], category)
    ruleset.has_table = True
    conflict_column = _conflict_column(table)
    for row in data:
        _read_row(row, ruleset, conflict_column, config.problems)


def _caption_target(caption: Wikicode) -> tuple[list[str], str | None]:
    """The templates a caption names, and the category it links to, if any."""
    category = None
    for link in caption.filter_wikilinks():
        title = _link_title(link)
        if re.match(r'category\s*:', title, re.IGNORECASE):
            category = title
            caption.remove(link)
    names = _template_links(caption)
    if not names:
        text = ' '.join(caption.strip_code().split()).lstrip('+').strip()
        names = [text] if text else []
    return [normalize_template_name(name) for name in names if name], category


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

def _read_one_line_rule(template: Template, config: Config) -> None:
    values = [strip_comments(p.value).strip() for p in template.params if not p.showkey]
    if len(values) != 3 or not values[0] or not _plain(values[1]) or not _plain(values[2]):
        config.problems.append(msg.malformed_one_line_rule(template))
        return
    name, old, new = values
    _add_rule(_ruleset_for(config, name), old, new, SKIP, config.problems)


# -- rules -----------------------------------------------------------------

def _plain(text: str) -> bool:
    """True if text can be a parameter name (no markup)."""
    return bool(text) and not any(c in text for c in '{}[]|=<>\n')


def _add_rule(ruleset: RuleSet, old: str, new: str | None, conflict: str,
              problems: list[str]) -> None:
    """Add the rule old → new (new is None for "remove"), unless it's broken."""
    problem = _rule_problem(ruleset.template, old, new)
    if problem:
        problems.append(problem)
    elif old == new:
        pass
    elif NUMBER in old:
        _add_numbered(ruleset, old, new, conflict, problems)
    elif new is None:
        _add_removal(ruleset, old, problems)
    else:
        _add_rename(ruleset, old, new, conflict, problems)


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


def _add_removal(ruleset: RuleSet, old: str, problems: list[str]) -> None:
    ruleset.removes[old] = Rule(REMOVE, old)
    if old in ruleset.renames:
        problems.append(msg.renamed_and_removed(ruleset.template, old))


def _add_rename(ruleset: RuleSet, old: str, new: str, conflict: str,
                problems: list[str]) -> None:
    existing = ruleset.renames.get(old)
    if existing is not None and existing.new != new:
        problems.append(msg.renamed_twice(ruleset.template, old, existing.new, new))
    if old in ruleset.removes:
        problems.append(msg.renamed_and_removed(ruleset.template, old))
    ruleset.renames[old] = Rule(RENAME, old, new, conflict=conflict)


def _add_numbered(ruleset: RuleSet, old: str, new: str | None, conflict: str,
                  problems: list[str]) -> None:
    """Add a rule for a name with "#", replacing any earlier one."""
    for index, existing in enumerate(ruleset.patterns):
        if existing.old == old:
            if existing.new != new:
                problems.append(msg.renamed_twice(ruleset.template, old, existing.new, new))
            del ruleset.patterns[index]
            break
    pattern = _number_pattern(old)
    if new is None:
        ruleset.patterns.append(Rule(REMOVE, old, pattern=pattern))
    else:
        ruleset.patterns.append(Rule(RENAME, old, new, pattern=pattern,
                                     replacement=_number_replacement(new), conflict=conflict))


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
