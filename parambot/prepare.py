"""Checking rule sets against the live templates.

Every run, before touching any article, each rule set is checked against its
template on the wiki: the template must exist and have a list of accepted
parameters the bot can read (a wrapper template's comes from the template it
wraps), and its table must watch the category the template really uses.
Anything wrong goes on the report.  Each usable rule set becomes a
TemplateRules, which is what the fixer applies.

Inactive rule sets are checked the same way; the caller decides not to use
them.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from . import messages as msg
from .fixer import TemplateRules
from .report import Report
from .rules import RuleSet
from .templatescan import (
    KnownParams,
    WrappedParams,
    Wrapper,
    categories_in,
    known_params,
    wrapper_call,
)
from .wiki import Wiki, WikiPage
from .wikitext import normalize_template_name

log = logging.getLogger('parambot')

TEMPLATE_NAMESPACE = 10
MAX_WRAPPERS = 5   # a wrapper of a wrapper of ...: any more is surely a loop


@dataclass
class Prepared:
    ready: list[TemplateRules] = field(default_factory=list)
    # Templates whose table watches a category the template doesn't use.
    # The report already says so, so an empty category needn't be mentioned.
    wrong_category: set[str] = field(default_factory=set)
    # Rule sets named after a redirect: {name: the template it redirects to}.
    redirected: dict[str, str] = field(default_factory=dict)


@dataclass
class _Found:
    """A rule set whose template exists and lists the parameters it accepts."""

    ruleset: RuleSet
    page: WikiPage          # the template, after any redirect
    names: set[str]         # what articles may call it
    known: KnownParams


def prepare(wiki: Wiki, rulesets: Iterable[RuleSet], report: Report) -> Prepared:
    rulesets = list(rulesets)
    pages = [wiki.page(ruleset.template, ns=TEMPLATE_NAMESPACE) for ruleset in rulesets]
    loaded = {page.title(): page for page in wiki.load(pages)}
    prepared = Prepared()
    templates = [(ruleset, template) for ruleset, page in zip(rulesets, pages, strict=True)
                 if (template := _template_for(ruleset, loaded.get(page.title(), page), report,
                                               prepared)) is not None]
    found: list[_Found] = []
    params = template_params(wiki, [template for _, template in templates])
    for (ruleset, template), (known, passed_to) in zip(templates, params, strict=True):
        if known is None:
            # Without the list, a backwards rule (image_size → imagesize) would
            # break every page it touched, so don't guess.
            report.problems.append(msg.no_parameter_list(ruleset.template, passed_to))
            continue
        names = {ruleset.template}
        if ruleset.template in prepared.redirected:
            names.add(prepared.redirected[ruleset.template])
        found.append(_Found(ruleset, template, names, known))
    # Redirects and categories for all the templates at once: a request
    # for each of them gets the bot rate-limited once there are dozens.
    redirects = wiki.redirects(list(dict.fromkeys(f.page.title() for f in found)),
                               TEMPLATE_NAMESPACE)
    categories = template_categories(wiki, [f.known for f in found])
    for f, found_categories in zip(found, categories, strict=True):
        f.names |= {normalize_template_name(title) for title in redirects.get(f.page.title(), ())}
        prepared.ready.append(_check(f, found_categories, report, prepared))
    prepared.ready = _one_per_template(prepared.ready, prepared.redirected, report)
    return prepared


def _template_for(ruleset: RuleSet, page: WikiPage, report: Report,
                  prepared: Prepared) -> WikiPage | None:
    """The template a rule set is for, after any redirect, or None if it
    doesn't exist."""
    if not page.exists():
        report.problems.append(msg.template_missing(ruleset.template))
        return None
    if page.isRedirectPage():
        page = page.getRedirectTarget()
        prepared.redirected[ruleset.template] = normalize_template_name(page.title(with_ns=False))
    return page


def _check(found: _Found, categories: list[str] | None, report: Report,
           prepared: Prepared) -> TemplateRules:
    """Report what's wrong with a usable rule set, and make it ready to use."""
    ruleset, known = found.ruleset, found.known
    template = ruleset.template
    problem = category_problem(ruleset, categories)
    if problem:
        report.problems.append(problem)
        prepared.wrong_category.add(template)
    # Rules for names the template still accepts wait for it to drop them,
    # unless only a setting like mapframe_args=y makes the check accept them.
    waiting: list[str] = []
    not_needed: dict[str, list[str]] = {}   # {setting: names}
    for name in (*ruleset.renames, *ruleset.removes):
        if name in known:
            setting = known.added_by(name)
            if setting:
                not_needed.setdefault(setting, []).append(name)
            else:
                waiting.append(name)
    if waiting:
        report.notes.append(msg.rules_waiting(template, waiting))
    for setting, names in not_needed.items():
        report.notes.append(msg.rules_not_needed(template, names, setting))
    for rule in ruleset.renames.values():
        if rule.new is not None and rule.new not in known:
            report.problems.append(msg.target_not_accepted(template, rule.old, rule.new))
    return TemplateRules(ruleset, frozenset(found.names), known)


def template_params(wiki: Wiki, pages: list[WikiPage]
                    ) -> list[tuple[KnownParams | None, list[str]]]:
    """For each template, the parameters it accepts, or None if the bot
    can't tell, and the templates it passes them on to, if it's a wrapper.

    The templates that wrappers pass their parameters on to are loaded
    together, a level of wrapping at a time, each one once: dozens of
    wrappers pass theirs on to Infobox settlement."""
    current = list(pages)
    wrappers: list[list[Wrapper]] = [[] for _ in pages]
    known: list[KnownParams | None] = [None] * len(pages)
    pending = list(range(len(pages)))
    while pending:
        follow: dict[int, str] = {}   # {index: the template its wrapper passes on to}
        for i in pending:
            known[i] = known_params(current[i].text)
            if known[i] is not None:
                continue
            wrapper = wrapper_call(current[i].text)
            if wrapper is None or len(wrappers[i]) == MAX_WRAPPERS:
                continue
            wrappers[i].append(wrapper)
            follow[i] = wrapper.template
        wrapped = _load_templates(wiki, set(follow.values()))
        pending = []
        for i, name in follow.items():
            page = wrapped[name]
            if page is not None:
                current[i] = page
                pending.append(i)
    results: list[tuple[KnownParams | None, list[str]]] = []
    for found, its_wrappers in zip(known, wrappers, strict=True):
        if found is not None:
            for wrapper in reversed(its_wrappers):
                found = WrappedParams(wrapper, found)
        results.append((found, [wrapper.template for wrapper in its_wrappers]))
    return results


def _load_templates(wiki: Wiki, names: set[str]) -> dict[str, WikiPage | None]:
    """{name: the template, after any redirect, or None if it doesn't exist}."""
    if not names:
        return {}
    pages = {name: wiki.page(name, ns=TEMPLATE_NAMESPACE) for name in sorted(names)}
    loaded = {page.title(): page for page in wiki.load(pages.values())}
    templates: dict[str, WikiPage | None] = {}
    for name, page in pages.items():
        page = loaded.get(page.title(), page)
        if page.exists() and page.isRedirectPage():
            page = page.getRedirectTarget()
        templates[name] = page if page.exists() else None
    return templates


def _one_per_template(ready: list[TemplateRules], redirected: dict[str, str],
                      report: Report) -> list[TemplateRules]:
    """Rule sets for the same template under different names, such as
    Infobox town and Infobox settlement, which it redirects to.  Only one set
    of rules can apply to a call of the template, so don't guess: keep the one
    named after the template itself, if there is one, and drop the others."""
    by_template: dict[str, list[TemplateRules]] = {}
    for target in ready:
        actual = redirected.get(target.template, target.template)
        by_template.setdefault(actual, []).append(target)
    dropped: set[int] = set()
    for actual, targets in by_template.items():
        if len(targets) == 1:
            continue
        own = next((t for t in targets if t.template == actual), None)
        if own is None:
            names = [target.template for target in targets]
            report.problems.append(msg.same_template_twice(names, actual))
            dropped |= {id(target) for target in targets}
            continue
        for target in targets:
            if target is not own:
                report.problems.append(
                    msg.rules_for_a_redirect(target.template, actual, own.rules.page))
                dropped.add(id(target))
    return [target for target in ready if id(target) not in dropped]


def template_categories(wiki: Wiki, knowns: list[KnownParams]) -> list[list[str] | None]:
    """For each template, the categories it puts an article in when it has
    an unknown parameter, or None if that can't be worked out."""
    texts = [known.unknown_text or '' for known in knowns]
    # Let MediaWiki expand {{main other}}, {{if empty}}, {{{template_name|}}}
    # and so on, as if for an article: all of them in as few requests as it can.
    to_expand = [i for i, text in enumerate(texts) if '{{' in text]
    expanded: dict[int, str | None] = dict.fromkeys(to_expand)
    if to_expand:
        try:
            expanded.update(zip(to_expand, wiki.expand_all([texts[i] for i in to_expand]),
                                strict=True))
        except Exception as error:
            log.warning("Couldn't expand the templates' unknown-parameter categories: %s", error)
    categories: list[list[str] | None] = []
    for i, text in enumerate(texts):
        result = expanded.get(i, text)
        categories.append(None if result is None else categories_in(result))
    return categories


def category_problem(ruleset: RuleSet, found: list[str] | None) -> str | None:
    """A report problem if the rule set watches a category the template
    doesn't use, else None."""
    if found is None or ruleset.category in found:
        return None
    if not found:
        return msg.no_category(ruleset.template)
    if ruleset.category_explicit:
        return msg.caption_category_wrong(ruleset.template, ruleset.category, found[0])
    return msg.unusual_category(ruleset.template, ruleset.category, found[0], ruleset.has_table)
