"""The report history page: a line for each run."""

from datetime import UTC, datetime, timedelta

import pytest

from parambot.history import MARKER, MAX_ROWS, history_row, updated_page

STARTED = datetime(2026, 10, 27, 4, 0, tzinfo=UTC)


def row(result='finished', minutes=12):
    return history_row(started=STARTED, ended=STARTED + timedelta(minutes=minutes), mode='live',
                       categories='3 of 41', checked=57, edits=52, needing_review=2,
                       result=result)


def test_a_row_is_one_line_of_the_table():
    assert row() == ('|-\n| 2026-10-27 04:00 || 2026-10-27 04:12 || 12 minutes || live || 3 of 41 '
                     '|| 57 || 52 || 2 || finished\n')


@pytest.mark.parametrize('old', [None, '', 'Placeholder.', f'{MARKER}\nno table end'])
def test_a_page_without_the_table_is_started_afresh(old):
    text = updated_page(old, row(), header='User:ExampleBot/Header', intro='Every run.')
    assert text.startswith('{{User:ExampleBot/Header}}\nEvery run.\n\n{| class="wikitable"\n')
    assert text.endswith(f'{MARKER}\n{row()}|}}\n')


def test_new_runs_go_at_the_top_and_the_rest_is_kept():
    first = updated_page(None, row('first'), header='', intro='Intro.')
    edited = first.replace('Intro.', 'Intro, edited by hand.') + 'A note below.\n'
    text = updated_page(edited, row('second'), header='', intro='Intro.')
    assert 'Intro, edited by hand.' in text
    assert text.index('second') < text.index('first')
    assert text.endswith('|}\nA note below.\n')


def test_the_oldest_rows_go():
    text = None
    for n in range(MAX_ROWS + 5):
        text = updated_page(text, row(f'run {n}'), header='', intro='')
    assert text.count('|-\n') == MAX_ROWS
    assert f'run {MAX_ROWS + 4}' in text
    assert 'run 4\n' not in text and 'run 5\n' in text


@pytest.mark.parametrize('minutes, shown', [(14, '14 minutes'), (0.5, 'under a minute'),
                                            (125, '2 hours 5 minutes')])
def test_a_row_says_how_long_the_run_took_as_the_report_does(minutes, shown):
    # The same words as the report's "taking 14 minutes" (messages.duration).
    assert f' || {shown} || live || ' in row(minutes=minutes)
