"""The example rules pages must be valid, and match each other."""

from pathlib import Path

import pytest

from parambot.options import Options
from parambot.rules import parse_config
from parambot.rulespages import read_index, template_for

EXAMPLES = Path(__file__).parent.parent / 'examples'
OPTIONS = Options()   # ParamBot's own pages
PAGES = sorted((EXAMPLES / 'rules').glob('*.mediawiki'))


def _template(path):
    """The template a file's rules are for: Infobox_person.mediawiki is Infobox person."""
    return path.stem.replace('_', ' ')


def test_the_index_lists_every_example_page():
    listing = read_index((EXAMPLES / 'rules.mediawiki').read_text(encoding='utf-8'), OPTIONS)
    assert listing.problems == []
    listed = {template_for(title, OPTIONS.rules_page) for title in listing.pages}
    assert listed == set(map(_template, PAGES))
    assert all(page.revision for page in listing.pages.values())
    assert not listing.pages[f'{OPTIONS.rules_page}/Infobox organization'].active


@pytest.mark.parametrize('path', PAGES, ids=_template)
def test_example_rules_pages_are_valid(path):
    config = parse_config(path.read_text(encoding='utf-8'), _template(path))
    assert config.problems == []
    assert list(config.rulesets) == [_template(path)]
    assert len(config.rulesets[_template(path)])
