"""Read-only checks against the real English Wikipedia.

The rest of the tests use a fake wiki, so these catch the ways the real one
differs.  They don't run with plain ``pytest``: run them with

    pytest -m live

before deploying, or let the weekly "Live" workflow on GitHub run them.  They
read a few dozen pages, at least a second apart, and never edit.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from parambot import commit
from parambot.cli import _user_agent
from parambot.prepare import module_map_params
from parambot.settings import READ_DELAY
from parambot.wiki import Wiki

pytestmark = pytest.mark.live

ROOT = Path(__file__).parent.parent
RULES = 'User:ParamBot/Rules'


@pytest.fixture(scope='module')
def wiki():
    import pywikibot
    from pywikibot import config

    config.user_agent_format = _user_agent('', 'en', 'wikipedia', 'ParamBot', commit())
    config.minthrottle = READ_DELAY
    return Wiki(pywikibot.Site('en', 'wikipedia'))


def test_check_rules_runs_against_the_real_wiki(tmp_path):
    # As a person would run it: no user-config.py, nothing saved.
    env = {**os.environ, 'PYWIKIBOT_DIR': str(tmp_path)}
    env.pop('PYWIKIBOT_NO_USER_CONFIG', None)   # the bot must manage without it
    result = subprocess.run([sys.executable, '-m', 'parambot', 'check-rules'], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=900)
    # 1 means it found rules problems to report, which is fine here.
    assert result.returncode in (0, 1), result.stderr
    assert 'INFO ParamBot' in result.stderr
    assert 'Traceback' not in result.stderr


def test_the_modules_map_parameters_can_be_read(wiki):
    # If this fails, Module:Check for unknown parameters has changed shape,
    # and every run is switching off the rules of templates using
    # mapframe_args or pushpin_map_args, until map_params is updated.
    names = module_map_params(wiki)
    assert names is not None
    assert {'mapframe-zoom', 'coordinates'} <= names['mapframe_args']
    assert {'pushpin_map', 'coordinates'} <= names['pushpin_map_args']


def test_the_rules_pages_are_found(wiki):
    subpages = wiki.subpages(RULES)
    assert f'{RULES}/Instructions' in subpages
    assert len(subpages) > 10


def test_pages_load_and_a_missing_one_says_so(wiki):
    found = wiki.load_titles(['User:ParamBot/Run', 'User:ParamBot/No such page here'])
    assert found['User:ParamBot/Run'].exists()
    assert not found['User:ParamBot/No such page here'].exists()


def test_a_revision_is_read_by_its_id(wiki):
    rules = wiki.load_titles([RULES])[RULES]
    revid = rules.latest_revision_id
    found = wiki.revisions([revid, 99999999999])
    assert set(found) == {revid}       # the second doesn't exist
    revision = found[revid]
    assert (revision.title, revision.model, revision.latest) == (RULES, 'wikitext', revid)
    assert revision.text == rules.text


def test_category_sizes_and_a_missing_category(wiki):
    real = 'Category:Pages using infobox person with unknown parameters'
    made_up = 'Category:ParamBot test category that does not exist'
    sizes = wiki.category_sizes([real, made_up])
    assert isinstance(sizes.get(real, 0), int)
    assert sizes[made_up] is None


def test_texts_are_expanded_together_as_in_an_article(wiki):
    assert wiki.expand_all(['{{main other|in an article}}', 'plain']) == [
        'in an article', 'plain']


def test_template_redirects_are_found(wiki):
    found = wiki.redirects(['Template:Infobox person'], 10)
    assert len(found['Template:Infobox person']) > 5


def test_the_bots_recent_edits(wiki):
    edits = wiki.recent_edits('ParamBot', datetime.now(UTC) - timedelta(days=365))
    assert 'User:ParamBot/Report' in edits
