from parambot.fixer import Issue
from parambot.report import Report


def test_report_roundtrip():
    report = Report()
    report.issue('Foo', Issue('Infobox person', 'alma_mater', 'education', 'both set'))
    report.skip('Bar', 'excluded by {{bots}}')
    report.problems.append('Template:X does not exist')
    text = report.render('2026-09-26 00:00', live=True)
    assert '[[:Foo]]' in text
    code = '<code><nowiki>{}</nowiki></code>'
    assert f'{code.format("alma_mater")} → {code.format("education")}' in text
    assert '<nowiki>excluded by {{bots}}</nowiki>' in text
    assert Report.body_of(text) == report.body()
    # A new run with the same findings has the same body, so no save is needed.
    later = report.render('2026-09-27 00:00', live=True)
    assert later != text
    assert Report.body_of(later) == Report.body_of(text)


def test_empty_report():
    assert Report().body() == (
        '== Needs human review ==\nNone.\n\n'
        '== Not edited ==\nNone.\n\n'
        '== Rules page problems ==\nNone.\n')


def test_setup_errors_and_notes_appear_only_when_there_are_some():
    report = Report(setup=['S'], errors=['E'], notes=['N'])
    body = report.body()
    assert body.startswith('== Setup problems ==\nA live run refuses to start until these are '
                           'fixed.\n* <nowiki>S</nowiki>\n\n== Errors ==\n')
    assert body.endswith('== Notes ==\n* <nowiki>N</nowiki>\n')
