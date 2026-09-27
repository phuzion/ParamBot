"""Reading wikitables parsed by mwparserfromhell.

mwparserfromhell turns table markup into tags but leaves some of the meaning
to the reader.  read_table sorts that out:

- "|+ caption" arrives as an ordinary cell whose text starts with "+";
- header cells before the first "|-" aren't inside any row;
- rowspan and colspan are plain attributes, so the rows have to be laid out
  on a grid to know which column each cell is in.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from mwparserfromhell.nodes import Node, Tag
from mwparserfromhell.wikicode import Wikicode

MAX_SPAN = 100


@dataclass
class Row:
    cells: list[Tag]             # the cells written in this row
    columns: list[Tag | None]    # the cell in each column, after rowspan and colspan

    @property
    def header(self) -> bool:
        """True if every cell written in the row is a header (!) cell."""
        return bool(self.cells) and all(cell.tag == 'th' for cell in self.cells)

    def column(self, index: int) -> Tag | None:
        return self.columns[index] if index < len(self.columns) else None


@dataclass
class Table:
    tag: Tag                     # the whole table, as parsed
    caption: Wikicode | None     # the text after "|+", if there is a caption
    rows: list[Row]


def tables_in(code: Wikicode) -> Iterator[Table]:
    for tag in code.filter_tags(matches=_is_table):
        yield read_table(tag)


def read_table(tag: Tag) -> Table:
    caption, rows = _split(tag)
    return Table(tag, caption, list(_lay_out(rows)))


def cell_text(cell: Tag | None) -> str:
    """A cell's text without markup, on one line."""
    return ' '.join(cell.contents.strip_code().split()) if cell is not None else ''


def _is_table(node: Node) -> bool:
    return isinstance(node, Tag) and node.tag == 'table'


def _cells(nodes: list[Node]) -> list[Tag]:
    return [n for n in nodes if isinstance(n, Tag) and n.tag in ('td', 'th')]


def _split(table: Tag) -> tuple[Wikicode | None, list[list[Tag]]]:
    """The caption, and the cells of each row."""
    caption = None
    loose: list[Tag] = []
    rows: list[list[Tag]] = []
    for node in table.contents.nodes:
        if not isinstance(node, Tag):
            continue
        if node.tag == 'tr':
            rows.append(_cells(node.contents.nodes))
        elif node.tag in ('td', 'th') and not rows:
            if (caption is None and not loose and node.tag == 'td'
                    and str(node.contents).lstrip().startswith('+')):
                caption = node.contents
            else:
                loose.append(node)
    if loose:
        rows.insert(0, loose)
    return caption, rows


def _span(cell: Tag, name: str) -> int:
    for attr in cell.attributes:
        if str(attr.name).strip().lower() == name:
            try:
                return max(1, min(int(str(attr.value).strip()), MAX_SPAN))
            except ValueError:
                return 1
    return 1


def _lay_out(rows: list[list[Tag]]) -> Iterator[Row]:
    carried: dict[int, list] = {}  # column -> [cell, rows it still covers]
    for cells in rows:
        placed: dict[int, Tag] = {}
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
        yield Row(cells, [placed.get(i) for i in range(width)])
