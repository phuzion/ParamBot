"""Keep the README in step with the files it describes."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
README = (ROOT / 'README.md').read_text(encoding='utf-8')


def test_links_to_files_exist():
    links = re.findall(r'\]\(([^)#\s]+)\)', README)
    local = [link for link in links if not link.startswith(('http://', 'https://'))]
    assert local, 'expected some links to files'
    missing = [link for link in local if not (ROOT / link).exists()]
    assert missing == []


def test_mentioned_files_exist():
    # Paths written as `code`, such as `examples/rules.mediawiki`.
    paths = re.findall(r'`((?:parambot|docs|examples|deploy|tests)/[\w./-]+)`', README)
    missing = [path for path in paths if not (ROOT / path).exists()]
    assert missing == []


def test_project_layout_lists_every_module():
    layout = README.split('## Project layout', 1)[1].split('\n## ', 1)[0]
    listed = set(re.findall(r'`(parambot/\w+\.py)`', layout))
    modules = {f'parambot/{p.name}' for p in (ROOT / 'parambot').glob('*.py')
               if p.name not in ('__init__.py', '__main__.py')}
    assert listed == modules
