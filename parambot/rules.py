"""Reading the rules page.

The format is documented for rule writers in docs/rules-instructions.wiki,
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
"""

import re
from dataclasses import dataclass, field
from typing import Optional

import mwparserfromhell
from mwparserfromhell.nodes import Tag

from .luapattern import LuaPattern
from .wikitext import (
    default_unknown_category,
    normalize_category,
    normalize_template_name,
    strip_comments,
)

__all__ = ['Rule', 'RuleSet', 'Config', 'parse_config']

AWB_TEMPLATE = 'AWB rename template parameter'
NUMBER = '#'
DEFAULT_SEPARATOR = '<br />'

# Templates that link to a template, as used in captions: {{tl|Infobox foo}}.
_TEMPLATE_LINKS = {'Tl', 'Tlx', 'Tlp', 'Tlc', 'Tlg', 'Tl2', 'Tlf', 'Tls', 'Template link'}
_NAME_TAGS = ('code', 'kbd', 'tt', 'samp')
_REMOVE_RE = re.compile(r'^\W*(remove|delete)\b', re.IGNORECASE)
_CONFLICT_HEADER_RE = re.compile(r'\bboth\b|\bmerge\b|\bconflict', re.IGNORECASE)
_LUA_MAGIC = set('^$()%.[]*+-?')

RENAME = 'rename'
REMOVE = 'remove'


@dataclass(frozen=True)
class Rule:
    kind: str                            # RENAME or REMOVE
    old: str                             # name as written, possibly with "#"
    new: Optional[str] = None            # new name as written, possibly with "#"
    pattern: Optional[LuaPattern] = None # for names with "#"
    replacement: Optional[str] = None    # Lua replacement for pattern renames
    conflict: str = 'skip'               # or 'merge'
    separator: str = DEFAULT_SEPARATOR

    def describe(self):
        if self.kind == REMOVE:
            return f'remove {self.old}'
        return f'{self.old} → {self.new}'


@dataclass
class Match:
    rule: Rule
    target: Optional[str]                # None for removals


@dataclass
class RuleSet:
    template: str
    category: str
    renames: dict = field(default_factory=dict)   # old name -> Rule
    removes: dict = field(default_factory=dict)   # name -> Rule
    patterns: list = field(default_factory=list)  # Rules for names with "#", in order
    # Filled in by the bot at run time.
    names: set = field(default_factory=set)       # template name + redirects
    known: object = None                          # KnownParams or None
    disabled: bool = False                        # e.g. the template is missing

    def __post_init__(self):
        self.names.add(self.template)

    def lookup(self, name):
        rule = self.renames.get(name)
        if rule is not None:
            return Match(rule, rule.new)
        rule = self.removes.get(name)
        if rule is not None:
            return Match(rule, None)
        for rule in self.patterns:
            if not rule.pattern.fullmatch(name):
                continue
            if rule.kind == REMOVE:
                return Match(rule, None)
            target = rule.pattern.sub(name, rule.replacement)
            if target != name:
                return Match(rule, target)
        return None

    @property
    def rules(self):
        return [*self.renames.values(), *self.removes.values(), *self.patterns]

    def __len__(self):
        return len(self.renames) + len(self.removes) + len(self.patterns)


@dataclass
class Config:
    rulesets: dict = field(default_factory=dict)  # template name -> RuleSet
    problems: list = field(default_factory=list)  # human-readable strings

    def by_category(self):
        out = {}
        for rs in self.rulesets.values():
            out.setdefault(rs.category, []).append(rs)
        return out


def parse_config(text):
    config = Config()
    code = mwparserfromhell.parse(text)
    for table in code.filter_tags(matches=lambda n: n.tag == 'table'):
        _parse_table(table, config)
    for tpl in code.filter_templates():
        if normalize_template_name(tpl.name) == AWB_TEMPLATE:
            _parse_awb(tpl, config)
    for rs in config.rulesets.values():
        _resolve_chains(rs, config.problems)
    return config


# Problem messages end up on the report page, where the people who wrote the
# rules read them, so they say what was ignored and how to fix it.

def _plain(text):
    """True if text can be a parameter name (no markup)."""
    return bool(text) and not any(c in text for c in '{}[]|=<>\n')


def _excerpt(node, limit=60):
    text = ' '.join(str(node).split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _ruleset_for(config, template, category=None):
    template = normalize_template_name(template)
    rs = config.rulesets.get(template)
    if rs is None:
        rs = RuleSet(template, normalize_category(category or default_unknown_category(template)))
        config.rulesets[template] = rs
    elif category:
        category = normalize_category(category)
        if category != rs.category:
            config.problems.append(
                f'{template}: two tables give different categories to watch '
                f'("{rs.category}" and "{category}"). Using "{category}"; '
                'delete the wrong one.')
            rs.category = category
    return rs


# -- tables ------------------------------------------------------------------

def _cells(nodes):
    return [n for n in nodes if isinstance(n, Tag) and n.tag in ('td', 'th')]


def _split_table(table):
    """Return (caption Wikicode or None, rows), each row a list of cells."""
    caption = None
    loose = []
    rows = []
    for node in table.contents.nodes:
        if not isinstance(node, Tag):
            continue
        if node.tag == 'tr':
            rows.append(_cells(node.contents.nodes))
        elif node.tag in ('td', 'th') and not rows:
            # mwparserfromhell reads "|+ caption" as a cell starting with "+".
            if (caption is None and not loose and node.tag == 'td'
                    and str(node.contents).lstrip().startswith('+')):
                caption = node.contents
            else:
                loose.append(node)
    if loose:
        rows.insert(0, loose)
    return caption, rows


def _span(cell, name):
    for attr in cell.attributes:
        if str(attr.name).strip().lower() == name:
            try:
                return max(1, min(int(str(attr.value).strip()), 100))
            except ValueError:
                return 1
    return 1


def _grid(rows):
    """Expand rowspan and colspan.  Yield (original cells, cell per column)."""
    carried = {}  # column -> [cell, rows left]
    for cells in rows:
        placed = {}
        for col, entry in list(carried.items()):
            placed[col] = entry[0]
            entry[1] -= 1
            if entry[1] == 0:
                del carried[col]
        col = 0
        for cell in cells:
            while col in placed:
                col += 1
            rowspan, colspan = _span(cell, 'rowspan'), _span(cell, 'colspan')
            for k in range(colspan):
                placed[col + k] = cell
                if rowspan > 1:
                    carried[col + k] = [cell, rowspan - 1]
            col += colspan
        width = max(placed) + 1 if placed else 0
        yield cells, [placed.get(i) for i in range(width)]


def _has_para(cell):
    return cell is not None and any(
        normalize_template_name(t.name) == 'Para' for t in cell.contents.filter_templates())


def _is_header(cells):
    return bool(cells) and all(c.tag == 'th' for c in cells) and not any(map(_has_para, cells))


def _cell_names(cell):
    """The parameter names written in a cell: its {{para}}s, else its
    <code>s, else all of its text."""
    if cell is None:
        return []
    names = []
    for tpl in cell.contents.filter_templates(recursive=False):
        if normalize_template_name(tpl.name) == 'Para' and tpl.has('1'):
            name = strip_comments(tpl.get('1').value).strip()
            if name:
                names.append(name)
    if names:
        return names
    for tag in cell.contents.filter_tags(recursive=False, matches=lambda n: n.tag in _NAME_TAGS):
        name = tag.contents.strip_code().strip()
        if name:
            names.append(name)
    if names:
        return names
    text = ' '.join(strip_comments(cell.contents.strip_code()).split())
    return [text] if text else []


def _is_remove(cell):
    return (cell is not None and not _has_para(cell)
            and bool(_REMOVE_RE.match(cell.contents.strip_code().strip())))


def _caption_target(caption):
    """Return (template name or '', category or None, problem or None)."""
    category = None
    for link in caption.filter_wikilinks():
        title = str(link.title).strip().lstrip(':').strip()
        if re.match(r'category\s*:', title, re.IGNORECASE):
            category = title
            caption.remove(link)
    names = []
    for tpl in caption.filter_templates(recursive=False):
        if normalize_template_name(tpl.name) in _TEMPLATE_LINKS and tpl.has('1'):
            names.append(strip_comments(tpl.get('1').value).strip())
    if not names:
        for link in caption.filter_wikilinks():
            title = str(link.title).strip().lstrip(':').strip()
            if re.match(r'template\s*:', title, re.IGNORECASE):
                names.append(title)
    if not names:
        text = ' '.join(strip_comments(caption.strip_code()).split()).lstrip('+').strip()
        if text:
            names.append(text)
    names = [normalize_template_name(n) for n in names if n]
    if not names:
        return '', category, 'its caption doesn\'t name a template'
    if len(set(names)) > 1:
        return names[0], category, (
            f'its caption names more than one template ({", ".join(names)}); using '
            f'"{names[0]}". Use one table per template.')
    return names[0], category, None


def _parse_table(table, config):
    problems = config.problems
    caption, rows = _split_table(table)
    grid = list(_grid(rows))
    data = [(cells, row) for cells, row in grid if not _is_header(cells)]

    if caption is None:
        # Only complain about tables that look like rules.
        if any(_has_para(row[0] if row else None) for _, row in data):
            problems.append(
                'A table of parameters has no caption naming its template, so the bot '
                'ignored it. Add a line like "|+ {{tl|Infobox foo}}" straight after "{|". '
                f'The table starts: {_excerpt(table)}')
        return

    template, category, problem = _caption_target(caption)
    if not template:
        problems.append(f'A table was ignored because {problem}. Its caption is: '
                        f'{_excerpt(caption)}')
        return
    if problem:
        problems.append(f'{template}: {problem}')
    rs = _ruleset_for(config, template, category)

    conflict_col = None
    for cells, row in grid:
        if _is_header(cells):
            for i, cell in enumerate(row):
                if i >= 2 and cell is not None and _CONFLICT_HEADER_RE.search(
                        cell.contents.strip_code()):
                    conflict_col = i
            break

    for cells, row in data:
        old_cell = row[0] if row else None
        new_cell = row[1] if len(row) > 1 else None
        olds = _cell_names(old_cell)
        if not olds:
            if _cell_names(new_cell):
                problems.append(f'{template}: a row has a new name but no old name, so the '
                                'bot ignored it.')
            continue
        conflict = 'skip'
        if conflict_col is not None and conflict_col < len(row) and row[conflict_col] is not None:
            said = ' '.join(row[conflict_col].contents.strip_code().split()).lower()
            if 'merge' in said:
                conflict = 'merge'
            elif said and not re.match(r'^(skip|review|leave|no|-|—)', said):
                problems.append(f'{template}: in the row for "{olds[0]}", the '
                                f'"If both are set" column says "{said}". Write "merge" '
                                'or leave it empty. Treating it as empty.')
        if _is_remove(new_cell):
            new = None
        else:
            news = _cell_names(new_cell)
            if not news:
                problems.append(
                    f'{template}: the row for "{olds[0]}" has no new name, so the bot '
                    'ignored it. If the parameter was removed with no replacement, write '
                    '"remove".')
                continue
            if len(news) > 1:
                problems.append(
                    f'{template}: the row for "{olds[0]}" has more than one new name '
                    f'({", ".join(news)}), so the bot ignored it. Give each row one new name.')
                continue
            new = news[0]
        for old in olds:
            _add_pair(rs, old, new, conflict, problems)


# -- rules -------------------------------------------------------------------

def _hash_pattern(old):
    return LuaPattern(''.join(
        '(%d*)' if c == NUMBER else '%' + c if c in _LUA_MAGIC else c for c in old))


def _hash_replacement(new):
    out = []
    n = 0
    for c in new:
        if c == NUMBER:
            n += 1
            out.append(f'%{n}')
        else:
            out.append('%%' if c == '%' else c)
    return ''.join(out)


def _add_pair(rs, old, new, conflict, problems):
    """Add the rule old -> new (new is None for "remove")."""
    template = rs.template
    for name in (old, new):
        if name is None:
            continue
        if not _plain(name):
            problems.append(
                f'{template}: the bot ignored "{old}" → "{new or "remove"}". Parameter '
                'names can\'t contain markup such as {{ }}, [[ ]], | or <tags>.')
            return
        if ',' in name or ';' in name:
            problems.append(
                f'{template}: "{name}" looks like several names, so the bot ignored that '
                'row. Write each name as {{para|name}}.')
            return
    if old == new:
        return
    numbers = old.count(NUMBER)
    if new is not None and new.count(NUMBER) != numbers:
        problems.append(
            f'{template}: "{old}" → "{new}" has "#" in only one of the names, so the bot '
            'ignored it. "#" stands for the number in names like term_start2, so use it '
            'in both names or in neither.')
        return
    if numbers > 9:
        problems.append(f'{template}: "{old}" has more than nine "#"s, so the bot ignored it.')
        return

    if numbers == 0 and new is None:
        rs.removes[old] = Rule(REMOVE, old)
        if old in rs.renames:
            problems.append(f'{template}: "{old}" is both renamed and removed. Delete one.')
        return
    if numbers == 0:
        existing = rs.renames.get(old)
        if existing is not None and existing.new != new:
            problems.append(
                f'{template}: "{old}" is renamed to both "{existing.new}" and "{new}". '
                f'Using "{new}"; delete the wrong row.')
        if old in rs.removes:
            problems.append(f'{template}: "{old}" is both renamed and removed. Delete one.')
        rs.renames[old] = Rule(RENAME, old, new, conflict=conflict)
        return

    for i, existing in enumerate(rs.patterns):
        if existing.old == old:
            if existing.new != new:
                problems.append(
                    f'{template}: "{old}" is given two different new names '
                    f'("{existing.new or "remove"}" and "{new or "remove"}"). Using '
                    f'"{new or "remove"}"; delete the wrong row.')
            del rs.patterns[i]
            break
    if new is None:
        rs.patterns.append(Rule(REMOVE, old, pattern=_hash_pattern(old)))
    else:
        rs.patterns.append(Rule(RENAME, old, new, pattern=_hash_pattern(old),
                                replacement=_hash_replacement(new), conflict=conflict))


def _parse_awb(tpl, config):
    positional = [p for p in tpl.params if not p.showkey]
    values = [strip_comments(p.value).strip() for p in positional]
    if (len(values) != 3 or not values[0]
            or not _plain(values[1]) or not _plain(values[2])):
        config.problems.append(
            f'An {{{{{AWB_TEMPLATE}}}}} line needs exactly three parts: template, old '
            f'name, new name. The bot ignored: {_excerpt(tpl, 120)}')
        return
    template, old, new = values
    _add_pair(_ruleset_for(config, template), old, new, 'skip', config.problems)


def _resolve_chains(rs, problems):
    """Turn a -> b, b -> c into a -> c, b -> c."""
    for old in list(rs.renames):
        rule = rs.renames[old]
        seen = {old}
        new = rule.new
        while new in rs.renames:
            if new in seen:
                problems.append(
                    f'{rs.template}: the rules for "{old}" go round in a circle '
                    '(a → b, b → a). The bot ignored that rule.')
                del rs.renames[old]
                break
            seen.add(new)
            new = rs.renames[new].new
        else:
            if new != rule.new:
                rs.renames[old] = Rule(RENAME, old, new, conflict=rule.conflict)
