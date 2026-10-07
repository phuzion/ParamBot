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


def the_jobs_args():
    command = the_job()['command']
    return _build_parser().parse_args(shlex.split(command.split('-m parambot', 1)[1]))


def run_hours(field):
    """The hours a cron hour field names, such as 1,7,13,19 or */6."""
    if field.startswith('*/'):
        return list(range(0, 24, int(field[2:])))
    return sorted(int(hour) for hour in field.split(','))


def test_the_job_runs_every_day_off_the_hour():
    # Toolforge's macros jump from @hourly to @daily, so the job names its
    # times, avoiding minute 0, when everyone else's jobs start.
    job = the_job()
    assert job['name'] == 'parambot'
    minute, hours, *every_day = job['schedule'].split()
    assert every_day == ['*', '*', '*']
    assert 0 < int(minute) < 60
    assert all(0 <= hour < 24 for hour in run_hours(hours))
    assert job['emails'] == 'onfailure'


def test_a_run_ends_before_the_next_starts():
    hours = run_hours(the_job()['schedule'].split()[1])
    gap = min((later - hour) % 24 or 24
              for hour, later in zip(hours, hours[1:] + hours[:1], strict=True))
    max_hours = the_jobs_args().max_hours
    # An hour spare, to finish the page in hand and save the report.
    assert max_hours and max_hours <= gap - 1


def test_the_jobs_command_is_one_the_bot_understands():
    assert 'PYWIKIBOT_DIR=$HOME/parambot' in the_job()['command']
    assert the_jobs_args().command == 'run'


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
