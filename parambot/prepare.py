"""Checking rule sets against the live templates.

Every run, before touching any article, each rule set is checked against its
template on the wiki: the template must exist and have a list of accepted
parameters the bot can read, and its table must watch the category the
template really uses.  Anything wrong goes on the report.  Each usable rule
set becomes a TemplateRules, which is what the fixer applies.

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
from .templatescan import KnownParams, categories_in, known_params
from .wiki import Wiki, WikiPage
from .wikitext import normalize_template_name

log = logging.getLogger('parambot')

TEMPLATE_NAMESPACE = 10


@dataclass
class Prepared:
    ready: list[TemplateRules] = field(default_factory=list)
    # Templates whose table watches a category the template doesn't use.
    # The report already says so, so an empty category needn't be mentioned.
    wrong_category: set[str] = field(default_factory=set)
    # Rule sets named after a redirect: {name: the template it redirects to}.
    redirected: dict[str, str] = field(default_factory=dict)


def prepare(wiki: Wiki, rulesets: Iterable[RuleSet], report: Report) -> Prepared:
    rulesets = list(rulesets)
    pages = [wiki.page(ruleset.template, ns=TEMPLATE_NAMESPACE) for ruleset in rulesets]
    loaded = {page.title(): page for page in wiki.load(pages)}
    prepared = Prepared()
    for ruleset, page in zip(rulesets, pages, strict=True):
        target = _prepare_one(wiki, ruleset, loaded.get(page.title(), page), report, prepared)
        if target is not None:
            prepared.ready.append(target)
    prepared.ready = _one_per_template(prepared.ready, prepared.redirected, report)
    return prepared


def _prepare_one(wiki: Wiki, ruleset: RuleSet, page: WikiPage, report: Report,
                 prepared: Prepared) -> TemplateRules | None:
    template = ruleset.template
    if not page.exists():
        report.problems.append(msg.template_missing(template))
        return None
    names = {template}
    if page.isRedirectPage():
        page = page.getRedirectTarget()
        actual = normalize_template_name(page.title(with_ns=False))
        prepared.redirected[template] = actual
        names.add(actual)
    names |= {normalize_template_name(redirect.title(with_ns=False))
              for redirect in page.redirects(namespaces=[TEMPLATE_NAMESPACE])}

    known = known_params(page.text)
    if known is None:
        # Without the list, a backwards rule (image_size → imagesize) would
        # break every page it touched, so don't guess.
        report.problems.append(msg.no_parameter_list(template))
        return None

    problem = category_problem(ruleset, template_categories(wiki, template, known))
    if problem:
        report.problems.append(problem)
        prepared.wrong_category.add(template)
    waiting = [name for name in (*ruleset.renames, *ruleset.removes) if name in known]
    if waiting:
        report.notes.append(msg.rules_waiting(template, waiting))
    for rule in ruleset.renames.values():
        if rule.new is not None and rule.new not in known:
            report.problems.append(msg.target_not_accepted(template, rule.old, rule.new))
    return TemplateRules(ruleset, frozenset(names), known)


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


def template_categories(wiki: Wiki, template: str, known: KnownParams) -> list[str] | None:
    """The categories a template puts an article in when it has an unknown
    parameter, or None if that can't be worked out."""
    text = known.unknown_text
    if not text:
        return []
    if '{{' in text:
        # Let MediaWiki expand {{main other}}, {{if empty}}, {{{template_name|}}}
        # and so on, as if for an article.
        try:
            text = wiki.expand(text)
        except Exception as error:
            log.warning("Couldn't expand Template:%s's unknown-parameter category: %s",
                        template, error)
            return None
    return categories_in(text)


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
