# ParamBot

A Wikipedia bot that puts back parameter renames that reverts have undone. It
was written for the English Wikipedia bot request
[Bot to regularly check for restored deprecated parameters](https://en.wikipedia.org/wiki/Wikipedia:Bot_requests#Bot_to_regularly_check_for_restored_deprecated_parameters).

After a deprecation cleanup, a template stops accepting its old parameter
names. Reverting an article to an older version, often to remove LLM-written
text, can bring those names back. The infobox then silently drops that
information, and the article lands in the template's *Pages using
&lt;template&gt; with unknown parameters* category. ParamBot checks those
categories daily and renames the old parameters to the new ones. It never
reverts anyone's edit and changes nothing else.

**Status:** waiting for approval at
[Wikipedia:Bots/Requests for approval/ParamBot](https://en.wikipedia.org/wiki/Wikipedia:Bots/Requests_for_approval/ParamBot).
Until then it runs daily in report-only mode and edits no articles. See
[Status](#status).

## What it does to a page

For each old parameter it finds in a call to the template:

| Old parameter | New parameter | What the bot does |
|---|---|---|
| filled in | missing | renames the old parameter |
| filled in | present but empty | moves the value into the new parameter and removes the old one |
| filled in | same value | removes the old one |
| filled in | different value | lists the page for human review, or merges the values if the rule says `merge` |
| empty | anything | nothing, unless it's editing the page anyway |

Rules can also say `remove`, for parameters that were dropped with no
replacement.

## How a run works

1. **Pre-flight checks** (live and report-only runs). It logs in as the bot
   account, checks the account has the `bot` right (unless `--trial` or
   `--report-only` is given), checks that `User:ParamBot/Run` says `yes` (or
   `report`, for a report-only run), and checks that all of its pages are set
   up properly (see [Safeguards](#safeguards)).
2. **Reads the rules.** `User:ParamBot/Rules` lists one rules page per
   template, such as `User:ParamBot/Rules/Infobox settlement`, under an
   *Active* or an *Inactive* heading, with the revision of it that has been
   approved. It reads exactly those revisions, 50 at a time, and reports any
   page listed without one.
3. **Checks every template the rules name,** active or inactive. It loads each
   template's redirects and its
   `{{#invoke:Check for unknown parameters|check|...}}` list of accepted
   parameters, and reports rules that can't work. A wrapper template, which
   passes its parameters on through `{{#invoke:Template wrapper|wrap|...}}`,
   uses the list of the template it wraps, plus the names it keeps for itself.
4. **Checks the size of each template's unknown-parameters category,** 50 at
   a time, and skips the empty ones.
5. **Fixes each article** in the categories that have pages, using the active
   rules only, then saves it, or writes a diff in a dry run.
6. **Writes the report** to `User:ParamBot/Report`, listing articles that
   need human review, articles it skipped and why, and problems in the rules.
   It starts with `{{User:ParamBot/Header}}`, and links each rules page,
   template and diff it names, and ends with a comment naming the git commit
   of the bot that wrote it, such as `<!-- ParamBot 24cef13 -->`. The report
   is only saved when its findings change: a new commit alone isn't a reason
   to save it.

## Safeguards

**What it will edit**

- **Only broken parameters.** A rule does nothing while the template still
  accepts the old name, so rules can be added before support is removed and
  switch on by themselves once it is.
- **Only to accepted names.** It never renames to a name the template doesn't
  accept, so a typo in a rule shows up on the report instead of breaking
  infoboxes.
- **No readable list, no rules.** If the bot can't read a template's list of
  accepted parameters, it switches that template's rules off and says so on
  the report. Without the list, a backwards rule such as
  `image_size → imagesize` would break every page it touched.
- **No guessing between rules.** Rows that disagree about an old name are
  both ignored, rows that disagree about `merge` don't merge, and a parameter
  that two `#` rules would change differently is left for a human. A
  template whose rules are on two pages, or under two names (a template and
  its redirect), is reported, and only the page named after the template
  itself is used.
- **No cosmetic-only edits.** If the only changes are to empty parameters,
  the page is left alone.
- **Conflicts go to humans.** If the old and new parameters have different
  values, the page is listed for review, unless that rule says `merge`.
- **Articles only.** It edits main-namespace pages only, and honours
  `{{bots}}` and `{{nobots}}`.
- **No edit wars.** It won't edit a page again within 30 days of its last
  edit there (`--cooldown-days`), in case the old parameter was put back on
  purpose. The page is listed instead.
- **Layout is kept.** It keeps the page's formatting, including lined-up `=`
  signs. It ignores template calls inside comments, `<nowiki>`, `<pre>` and
  `<syntaxhighlight>`.

**Its own pages**

Before every live run, the bot checks its pages on the wiki and refuses to
start if any of them is wrong, listing every problem at once. Dry runs and
`check-rules` report the same problems, under *Setup problems*, without
stopping.

| Page | Must be |
|---|---|
| `User:ParamBot` | an existing wikitext page that uses `{{bot}}` to name the operator, as bot policy requires |
| `User:ParamBot/Rules` | an existing wikitext page, not a redirect, **template-editor protected or higher** (or what `[rules] protection` in the [settings](#settings) asks), listing the rules pages and their approved revisions |
| `User:ParamBot/Run` | an existing wikitext page, not a redirect, saying `yes` (or `report`, for a report-only run) |
| `User:ParamBot/Report` | an existing wikitext page, not a redirect, that the bot account can edit |

The rules decide what the bot edits, so anyone able to change them could
make the bot edit thousands of articles. That's why `User:ParamBot/Rules`
must be protected. The rules pages it lists, such as
`User:ParamBot/Rules/Infobox settlement`, needn't be: the list gives the
revision of each that a template editor has approved, and the bot reads
exactly that revision. An edit to a rules page does nothing until a template
editor approves the new revision; until then the report notes that the page
has changed, with a link to the changes.

The Run page is left open so any editor can stop the bot. The bot adds a note
to the report if the Run page is protected, if the rules page's protection
is due to expire, or if `User:ParamBot/Rules/Instructions`,
`User:ParamBot/LinkRule` or `User:ParamBot/FAQ` is missing.

**Stopping and failures**

- **Emergency stop.** The bot checks `User:ParamBot/Run` before every edit.
  Changing it to anything but `yes` stops the bot straight away. `report`
  lets a report-only run update the report, but still stops any run that
  would edit articles. After that
  it makes no more wiki edits, not even the report, which is written to a
  local file instead.
- **Large runs are flagged.** There's no limit on edits per run, but a run of
  more than 500 edits (`large_run`) gets a note on the report, so a rule that
  catches more than it should is noticed. `max_edits`, or `--max-edits N`,
  sets a limit, for example for a BRFA trial.
- **Runs end within a day.** A run stops starting new work after 20 hours
  (`max_hours`), so a daily run is done before the next one starts. What's
  left is picked up the next day.
- **Gentle on the API.** Every read waits at least a second after the last
  one (`read_delay`), so the bot can't make more than 3,600 an hour, and edits
  are at least 10 seconds apart (Pywikibot's `put_throttle`). Nothing is asked once per
  article or per template: pages, their templates, redirects, categories and
  expansions go 50 to a request, and the cooldown comes from one look at the
  bot's own recent edits. A run needs about 25 reads, plus about one for each
  50 templates and each 50 articles, one for each category with pages in it,
  and, in a live run, one for each edit, to check the Run page.
- **Errors are reported.** An error on one page is logged, the page is listed
  as not edited, and the run carries on. Five failures in a row, or any
  failure outside the page loop, stop the run. The report is still saved, with
  an *Errors* section (or written locally if the wiki can't be reached), and
  the process exits with a failure code so Toolforge emails the operator.

## Writing rules

Rule writers should read
[`docs/rules-instructions.mediawiki`](docs/rules-instructions.mediawiki). It's written
for editors rather than programmers, and belongs on the wiki at
`User:ParamBot/Rules/Instructions`, shown at the top of the rules page. See
[`examples/rules.mediawiki`](examples/rules.mediawiki) for a full rules page,
and [`examples/rules/`](examples/rules/) for the pages it lists.

`User:ParamBot/Rules` lists one page per template, named after the template,
with the revision of it that has been approved, under one of two headings:

```wikitext
== Active ==
* {{User:ParamBot/LinkRule|Infobox settlement|1234567890}}
* {{User:ParamBot/LinkRule|Infobox officeholder|1234567999}}

== Inactive ==
* {{User:ParamBot/LinkRule|Infobox organization|1234568000}}
```

Active rules are used. Inactive rules are read and checked on every run, and
their problems reported like any others, but they are never used: that's
where new rules wait until the report is clean, and where a template's rules
can be paused. Anything elsewhere on the page, such as links to archives, is
ignored.

**Approving rules.** The bot reads exactly the revision each line gives,
never a newer one, so changing a template's rules takes two edits: anyone
edits its rules page, then a template editor checks the changes and puts the
new revision number on the list. A rules page listed with a plain link, or
without a number, isn't used; the report gives the line to paste, with the
page's current revision. Edit summaries link to the approved revision the
bot used (`Special:Permalink/…`), so anyone can see exactly which rules made
an edit, and to `User:ParamBot/FAQ`, a short explanation for anyone who finds
the edit on their watchlist.

[`User:ParamBot/LinkRule`](docs/link-rule.mediawiki) shows each line as a
link to the approved version, the current page, the changes since approval
and the template. The bot reads the list's wikitext, not what LinkRule
shows, so LinkRule doesn't need protecting.

Each template's rules are an ordinary wikitable, so its page reads on the
wiki as exactly what the bot will do:

```wikitext
{| class="wikitable"
|+ {{tl|Infobox officeholder}}
! Old parameter !! New parameter !! If both are set
|-
| {{para|imagesize}} || {{para|image_size}} ||
|-
| {{para|termstart#}} || {{para|term_start#}} ||
|-
| {{para|alma_mater}} || {{para|education}} || merge
|-
| {{para|nationality}} || remove ||
|}
```

- **Caption:** names the template. On a template's own rules page, every
  table is for that template, so the caption is optional there, and a table
  whose caption names another template is reported and ignored. The bot
  watches
  `Category:Pages using <template, first letter lowercase> with unknown parameters`,
  unless the caption links to a different category, as some templates need:
  `|+ {{tl|Infobox bone}} watches [[:Category:Anatomy infobox template using unknown parameters]]`.
  On every run the bot works out which category each template really uses,
  by expanding the template's `Check for unknown parameters` call as if for an
  article (for a wrapper, the wrapped template's call, with the wrapper's
  settings, such as `template_name`, filled in). If a table watches the wrong one, the report says which link to
  add.
- **Columns:** column 1 holds the old names, column 2 the new name or
  `remove`. An optional column headed *If both are set* can say `merge`;
  other extra columns are notes.
- **Numbers:** `#` stands for no number or any number, so `termstart#`
  covers `termstart`, `termstart2`, `termstart12`, and so on. An exact name
  beats a `#` name, so `termstart2` can have a rule of its own.
- **One rule per old name:** rows for the same old name must agree. If they
  give different new names, neither is used; if only some say `merge`, the
  bot doesn't merge. Both are reported.
- **Notes and spans:** text in a cell besides the `{{para}}` names is a note,
  and `rowspan`/`colspan` work. Existing deprecation tables can be pasted in
  with a caption added.
- **One-line format:** `{{AWB rename template parameter|Template|old|new}}`
  lines, in the format of
  [WP:AWB/RTP](https://en.wikipedia.org/wiki/Wikipedia:AutoWikiBrowser/Rename_template_parameters),
  also work.

The bot won't run unless `User:ParamBot/Rules` is template-editor protected
or higher (the `[rules] protection` setting), so only template editors can
approve rules. Even so, the
safeguards limit what a bad rule can do, because the old name has to be one
the template rejects and the new name one it accepts.

## Setup

Needs Python 3.11 or later.

```bash
python -m venv .venv
source .venv/bin/activate         # on Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Before pushing, run the same checks GitHub runs:

```bash
ruff check .     # lint
mypy             # type-check
pytest           # tests
```

[GitHub Actions](.github/workflows/tests.yml) runs all three on Python 3.11,
3.12, 3.13 and 3.14 for every push and every pull request.

- **No test touches a real wiki.** They use a fake one from
  [`tests/fakes.py`](tests/fakes.py), which has the same methods as
  `parambot.wiki.Wiki`.
- **`tests/test_docs.py`** checks every example in the rule-writer
  instructions, and that the example edit in the bot's documentation is
  exactly what the bot does, so keep both in step with the code.
  **`tests/test_examples.py`** does the same for `examples/`.
- **`tests/test_readme.py`** checks that this README's links and file names
  point at files that exist, and that the project layout below lists every
  module.

## Usage

With the virtual environment active:

```bash
parambot --rules-file examples/rules check-rules
parambot --rules-file examples/rules run
parambot run --page "Some article" --template "Infobox person"
parambot run --page "User:Someone/sandbox" --any-namespace
parambot scaffold "Infobox settlement"
```

| Command | What it does |
|---|---|
| `run` | Does what `mode` in the [settings](#settings) says. Without one, that's a dry run: it reads the wiki, then writes `out/edits-*.diff` and `out/report-*.mediawiki` instead of editing. |
| `run --live` | Edits for real. Needs a bot account and a `user-config.py` (see [Deploying](#deploying-on-toolforge)). |
| `check-rules` | Checks the bot's own pages, then every rule, active and inactive, against its template and category, without looking at any articles. Exits 1 if there are problems. |
| `scaffold TEMPLATE` | Prints a rules table built from the template's `{{#invoke:Check for deprecated parameters\|check\|...}}` block, and says which page to put it on. Lua patterns become `#` rows, and any that can't be converted are flagged. `--oldid` reads an older revision, from before the block was removed. |

Options that apply to every command go before the command name, for example
`parambot --rules-file x.wiki run`.

| Option | Default | Meaning |
|---|---|---|
| `--config FILE` | `parambot.toml` next to `user-config.py` | The [settings](#settings) file. |
| `--bot-user NAME` | the account in `user-config.py`, else `ParamBot` | Account name. Also sets the default names of the bot's pages, under `User:NAME/`. |
| `--rules-page TITLE` | `[pages] rules`, else `User:<bot-user>/Rules` | The page listing the rules pages. |
| `--rules-file PATH` | | Read the rules from a local file instead, as if each file were an active rules page. A directory means every `.mediawiki` file in it. Can be repeated. |
| `--lang`, `--family` | `en`, `wikipedia` | Wiki to work on. Not taken from `user-config.py`, where a missing `mylang` makes Pywikibot quietly pick test.wikipedia. |
| `-v` | | Verbose logging. |

Options for `run`:

| Option | Default | Meaning |
|---|---|---|
| `--dry-run` | | Read only, whatever `mode` says: write the report and the edits it would make to files. |
| `--live` | | Edit for real. |
| `--trial` | off | Allow a live run without the bot flag, for BRFA trial edits. |
| `--report-only` | | Save the report page and never edit anything else, even with `--live`. Works out every fix like a dry run, and writes the edits it would make to a file. Needs no bot flag: the bot policy lets a bot edit its own userspace without approval, so the report page must be a subpage of `User:<bot-user>`. It needs a full run, so it can't be combined with `--page`, `--template`, `--any-namespace` or `--rules-file`, and it carries on past setup problems, to put them on the report. |
| `--max-edits N` | `max_edits` | Stop after this many edits, for example for a BRFA trial. `0` means no limit. |
| `--max-hours H` | `max_hours` | Stop starting new work after this many hours. `0` means no limit. |
| `--cooldown-days N` | `cooldown_days` | Don't edit a page the bot edited this recently. `0` turns this off. |
| `--template NAME` | all | Only use this template's rules. Can be repeated. |
| `--page TITLE` | | Only check this page, skipping the categories. Can be repeated. |
| `--any-namespace` | off | With `--page`, allow non-articles such as sandboxes. Dry runs only. |
| `--report-page`, `--run-page` | `[pages] report`, `[pages] run` | Pages to use instead. |
| `--out-dir DIR` | `[output] dir` | Where dry runs, and live runs that can't save the report, write their files. |

Without `--dry-run`, `--report-only` or `--live`, a run does what `mode` in
the settings says. Given more than one, the safest wins: `--dry-run`, then
`--report-only`. Dry runs don't need an account or a `user-config.py`.

`run` exits with 0 when the run finishes, and 1 when an error stopped it (the
report is still written). It exits with 2 when it refused to start or was
switched off: for example the Run page doesn't say `yes`, the rules page is
missing, or the account is wrong. A run with no usable rules finishes
normally, with the reasons on the report.

## Settings

Everything that can be changed without changing the code is in
`parambot.toml`, next to Pywikibot's `user-config.py`: in `PYWIKIBOT_DIR`,
or the directory the bot runs in. `--config FILE` names another file. Copy
[`deploy/parambot.example.toml`](deploy/parambot.example.toml), which lists
every setting with its default and what it does. Every setting is optional,
and the options above override them for one run. A misspelt or unusable
setting stops the bot before it does anything, saying what's wrong.

The account isn't in it: it comes from `user-config.py`, along with
Pywikibot's own settings, such as `put_throttle` (seconds between edits). The
wiki is the English Wikipedia unless `--lang` or `--family` says otherwise.

| Setting | Default | Meaning |
|---|---|---|
| `mode` | `"dry-run"` | What a plain `parambot run` does: `"dry-run"`, `"report-only"` or `"live"`. |
| `[pages]` `rules`, `report`, `run`, `instructions`, `faq`, `header`, `link_rule` | `User:<bot>/Rules`, `/Report` and so on; `instructions` is the rules page's `/Instructions` | The bot's pages. The report page can't be one of the others. |
| `[limits]` `cooldown_days` | `30` | Don't edit a page the bot edited this recently. `0` turns it off. |
| `[limits]` `max_hours` | `20` | Stop starting new work after this many hours, so a daily run is done before the next starts. `0` means no limit. |
| `[limits]` `max_edits` | `0` | Stop after this many edits. `0` means no limit. |
| `[limits]` `large_run` | `500` | A run with more edits than this gets a note on the report. `0` means never. |
| `[limits]` `failures_in_a_row` | `5` | Stop the run when this many pages in a row fail. |
| `[limits]` `read_delay` | `1` | Seconds between API reads, at least. |
| `[rules]` `protection` | `"templateeditor"` | The protection the rules page needs before a live run will start: `"autoconfirmed"`, `"extendedconfirmed"`, `"templateeditor"` or `"sysop"`, or anything stronger. |
| `[output]` `dir` | `"out"` | Where dry runs, and runs that can't save the report, write their files. |
| `[output]` `contact` | the bot's user page | A URL or email address for the User-Agent, so Wikimedia can reach the operators. |

Some things stay in the code on purpose, because the bot's approval rests on
them: it only edits articles, and the words that let the Run page switch it
on (`yes`, `true`, `run`, `on`, and `report` for a report-only run).

## Deploying on Toolforge

[`deploy/jobs.yaml`](deploy/jobs.yaml) runs the bot once a day with the
[Toolforge jobs framework](https://wikitech.wikimedia.org/wiki/Help:Toolforge/Running_jobs).
It uses the `@daily` schedule, as the Toolforge documentation asks, so
Toolforge chooses the time of day. Once it's set up,
[`docs/operators.md`](docs/operators.md) covers looking after it: logs,
updates, stopping it, trials and common problems.

1. Check the repository out at `~/parambot`, and create a virtual environment
   at `~/parambot/venv` with the package installed. Build it with the same
   Python image the job uses (`python3.13`), for example in a one-off
   `toolforge jobs run … --image python3.13 --wait` job, so the Python
   versions match.
2. On the bot account, create a
   [bot password](https://en.wikipedia.org/wiki/Special:BotPasswords) with the
   *High-volume (bot) access* and *Edit existing pages* grants.
3. Copy [`deploy/user-config.example.py`](deploy/user-config.example.py) to
   `~/parambot/user-config.py`, and put the bot password in
   `~/parambot/user-password.py`. To change any [settings](#settings), copy
   [`deploy/parambot.example.toml`](deploy/parambot.example.toml) to
   `~/parambot/parambot.toml`. All three files are git-ignored.
4. Set up the bot's pages. *Edit existing pages* doesn't let the bot create
   pages, so they all have to exist first:
   - `User:ParamBot`, using `{{bot|YourUsername}}`
   - `User:ParamBot/Rules`, listing the rules pages and their approved
     revisions under `== Active ==` and `== Inactive ==` (like
     [`examples/rules.mediawiki`](examples/rules.mediawiki))
   - `User:ParamBot/Rules/<Template name>` for each template, with its rules
     (like the files in [`examples/rules/`](examples/rules/))
   - `User:ParamBot/LinkRule`, a copy of
     [`docs/link-rule.mediawiki`](docs/link-rule.mediawiki)
   - `User:ParamBot/Rules/Instructions`, a copy of
     [`docs/rules-instructions.mediawiki`](docs/rules-instructions.mediawiki)
   - `User:ParamBot/FAQ`, a copy of [`docs/faq.mediawiki`](docs/faq.mediawiki);
     every edit summary links to it
   - `User:ParamBot/Documentation`, a copy of
     [`docs/documentation.mediawiki`](docs/documentation.mediawiki), for
     anyone wondering what the bot does (optional)
   - `User talk:ParamBot`, a copy of
     [`docs/talk-page.mediawiki`](docs/talk-page.mediawiki); the FAQ sends
     people there to report bad edits
   - `User:ParamBot/Report`, a placeholder
   - `User:ParamBot/Header`, a copy of
     [`docs/header.mediawiki`](docs/header.mediawiki): the links across the
     top of the bot's pages, which the bot puts at the top of the report
   - `User:ParamBot/Run`, containing `yes`

   Ask for `User:ParamBot/Rules` to be template-editor protected at
   [Requests for page protection](https://en.wikipedia.org/wiki/Wikipedia:Requests_for_page_protection).
   The rules pages themselves don't need protecting.
5. Run `parambot check-rules` and fix anything it reports under `SETUP` or
   `PROBLEM`.
6. Run `toolforge jobs load deploy/jobs.yaml`.

Until the bot is approved, the job runs with `--report-only`, and
`User:ParamBot/Run` says `report`: it updates the report every day and edits
no articles. For a BRFA trial, run by hand first with
`parambot run --live --trial --max-edits 50`. Once approved, change the job's
`--report-only` to `--live`, and the Run page to `yes`. (Or take
`--report-only` out of the job and set `mode` in `parambot.toml` instead: the
job then does what the settings say.)

## Project layout

A run goes `cli` → `bot`, which checks the bot's pages (`botpages`), finds
and reads the rules pages (`rulespages`, `rules`), checks the rules against
the templates (`prepare`), then applies the active ones to each article
(`fixer`) and writes the report (`report`). Only `wiki` talks to the wiki.

| Path | Contents |
|---|---|
| `parambot/cli.py` | The command line: one function per command. |
| `parambot/options.py` | The settings for a run, with their defaults. |
| `parambot/settings.py` | Reading the settings file, `parambot.toml`. |
| `parambot/bot.py` | A run: pre-flight checks, finding pages in the categories, fixing them, the report. |
| `parambot/botpages.py` | Checking the bot's own pages (user page, rules, Run and report pages). |
| `parambot/rulespages.py` | Reading the list of rules pages, fetching each one's approved revision, and combining their rules. |
| `parambot/rules.py` | Reading one rules page into a `RuleSet` per template. |
| `parambot/wikitable.py` | Reading wikitables: captions, header rows, `rowspan` and `colspan`. |
| `parambot/prepare.py` | Checking each `RuleSet` against its template, giving the `TemplateRules` the fixer applies. |
| `parambot/fixer.py` | Applying `TemplateRules` to a page's wikitext. |
| `parambot/templatescan.py` | Reading a template's own parameter checks, and wrapper templates; `scaffold`. |
| `parambot/luapattern.py` | Lua patterns, as used in templates, translated to Python regexes. |
| `parambot/report.py` | The report page. |
| `parambot/messages.py` | Everything the bot says on the report, in edit summaries and when it stops. |
| `parambot/wiki.py` | Everything the bot asks of the wiki, through Pywikibot. |
| `parambot/wikitext.py` | Small wikitext helpers. |
| `docs/rules-instructions.mediawiki` | Instructions for rule writers, for the wiki. |
| `docs/link-rule.mediawiki` | The `User:ParamBot/LinkRule` template, for the wiki. |
| `docs/documentation.mediawiki` | Full documentation of the bot, for `User:ParamBot/Documentation`. |
| `docs/faq.mediawiki` | A short FAQ, for `User:ParamBot/FAQ`, which every edit summary links to. |
| `docs/talk-page.mediawiki` | The header of `User talk:ParamBot`, with archiving. |
| `docs/operators.md` | For the operators: how the bot runs on Toolforge, and commands for looking after it. |
| `docs/header.mediawiki` | The `User:ParamBot/Header` template: links across the top of the bot's pages and the report. |
| `examples/rules.mediawiki` | An example of the list of rules pages. |
| `examples/rules/` | Example rules pages, one per template. |
| `deploy/` | Toolforge job, and templates for Pywikibot's `user-config.py` and the settings file. |
| `tests/` | The test suite; `tests/fakes.py` is the fake wiki. |
| `.github/workflows/tests.yml` | The checks GitHub runs on every push and pull request. |

## Status

- **Approval.** The bot approval request,
  [Wikipedia:Bots/Requests for approval/ParamBot](https://en.wikipedia.org/wiki/Wikipedia:Bots/Requests_for_approval/ParamBot),
  was filed on 1 October 2026 and is open. The bot has no bot flag yet, and
  its user page says `status=unapproved`.
- **Running.** The bot runs once a day on Toolforge in report-only mode:
  `User:ParamBot/Run` says `report`, and the job runs with `--report-only`.
  It updates `User:ParamBot/Report` with the edits it would make, and edits
  nothing else.
- **On the wiki.** The bot's pages are set up: `User:ParamBot/Rules` is
  template-editor protected and lists the approved rules pages, and the
  documentation, FAQ, instructions and talk page are in place.

Decided:

- **Rules pages.** They stay in the bot's userspace, under
  `User:ParamBot/Rules`, with the list template-editor protected.
- **Timing.** The bot runs once a day, or more often if editors ask for it.
- **Scope.** Renames and `remove` rules are in.

Still open:

- **Cooldown.** How long the bot waits before editing an article again: 30
  days now. At the BRFA, 15 days and 7 days (with weekly runs) have been
  suggested, as has a shorter wait when a revert undid the bot's edit along
  with the edit before it. It's `cooldown_days` in the
  [settings](#settings).
- **Merging.** Whether `merge` rules are wanted. This will be discussed on
  the wiki.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
