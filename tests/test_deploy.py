"""Keep the files for Toolforge in step with the code."""

import re
import shlex
from collections import defaultdict
from pathlib import Path

import pytest

from parambot.cli import _build_parser

yaml = pytest.importorskip('yaml')

ROOT = Path(__file__).parent.parent
JOBS = yaml.safe_load((ROOT / 'deploy' / 'jobs.yaml').read_text(encoding='utf-8'))
WORKFLOW = yaml.safe_load((ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8'))


def the_job():
    [job] = JOBS
    return job


def test_the_job_runs_daily_with_a_toolforge_macro():
    # Toolforge asks for its macros, which spread jobs through the day.
    job = the_job()
    assert job['name'] == 'parambot'
    assert job['schedule'] in {'@hourly', '@daily', '@weekly', '@monthly'}
    assert job['emails'] == 'onfailure'


def test_the_jobs_command_is_one_the_bot_understands():
    command = the_job()['command']
    assert 'PYWIKIBOT_DIR=$HOME/parambot' in command
    args = shlex.split(command.split('-m parambot', 1)[1])
    parsed = _build_parser().parse_args(args)
    assert parsed.command == 'run'


def test_the_jobs_python_is_one_ci_tests():
    image = the_job()['image']
    version = re.fullmatch(r'python(\d+\.\d+)', image)
    assert version, f'{image} is not a Python image'
    tested = {str(v) for v in WORKFLOW['jobs']['test']['strategy']['matrix']['python']}
    assert version.group(1) in tested


def test_the_example_user_config_is_valid():
    # Run as Pywikibot runs it, with its usernames to fill in.
    settings = {'usernames': defaultdict(dict)}
    exec(compile((ROOT / 'deploy' / 'user-config.example.py').read_text(encoding='utf-8'),
                 'user-config.example.py', 'exec'), settings)
    assert (settings['family'], settings['mylang']) == ('wikipedia', 'en')
    assert settings['usernames']['wikipedia']['en'] == 'ParamBot'
    # Pywikibot 11.8 renamed maxlag, and each version warns about the other name.
    assert 'maxlag' not in settings
