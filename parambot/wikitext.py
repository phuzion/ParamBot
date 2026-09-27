"""Small helpers for reading template calls the way MediaWiki does.

Functions that take wikitext accept a str or any mwparserfromhell node, since
both turn into the wikitext with str().
"""

import re

from mwparserfromhell.nodes.extras import Parameter

_COMMENT_RE = re.compile(r'<!--.*?(?:-->|\Z)', re.DOTALL)
_TEMPLATE_PREFIX_RE = re.compile(r'^:?\s*template\s*:\s*', re.IGNORECASE)


def strip_comments(text: object) -> str:
    return _COMMENT_RE.sub('', str(text))


def normalize_title(name: object) -> str:
    """Normalize a page title: comments and underscores gone, whitespace
    collapsed, first letter upper-cased."""
    title = ' '.join(strip_comments(name).replace('_', ' ').split())
    return title[:1].upper() + title[1:]


def normalize_template_name(name: object) -> str:
    """Normalize the name part of a {{template call}} to a title without
    the Template: prefix, e.g. ``infobox_settlement`` -> ``Infobox settlement``."""
    title = ' '.join(strip_comments(name).replace('_', ' ').split())
    return normalize_title(_TEMPLATE_PREFIX_RE.sub('', title))


def default_unknown_category(template: str) -> str:
    """The conventional tracking category, e.g. ``Category:Pages using
    infobox settlement with unknown parameters``."""
    template = normalize_template_name(template)
    return f'Category:Pages using {template[:1].lower()}{template[1:]} with unknown parameters'


def normalize_category(name: object) -> str:
    title = re.sub(r'^:?\s*category\s*:\s*', '', normalize_title(name), flags=re.IGNORECASE)
    return 'Category:' + normalize_title(title)


def param_name(param: Parameter) -> str:
    """The name MediaWiki sees for a mwparserfromhell Parameter."""
    return strip_comments(param.name).strip()


def is_blank(value: object) -> bool:
    """True if a parameter value expands to nothing but whitespace."""
    return not strip_comments(value).strip()


def same_value(a: object, b: object) -> bool:
    """True if two parameter values are the same apart from whitespace."""
    return strip_comments(a).split() == strip_comments(b).split()


def split_ws(text: object) -> tuple[str, str, str]:
    """Split text into (leading whitespace, core, trailing whitespace).

    For an all-whitespace value the core is empty, the leading part is the
    run of spaces before the first newline and the trailing part is the rest,
    so ``' \\n'`` splits into ``(' ', '', '\\n')``.
    """
    text = str(text)
    core = text.strip()
    if not core:
        nl = text.find('\n')
        if nl == -1:
            return text, '', ''
        return text[:nl], '', text[nl:]
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return lead, core, trail
