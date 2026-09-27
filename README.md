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

**Status:** not deployed. The `ParamBot` account exists, but there is no bot
approval request (BRFA) yet. See [Status](#status).

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

1. **Pre-flight checks** (live runs only). It logs in as the bot account,
   checks the account has the `bot` right (unless `--trial` is given), checks
   that `User:ParamBot/Run` says `yes`, and checks that all of its pages are
   set up properly (see [Safeguards](#safeguards)).
2. **Reads the rules** from `User:ParamBot/Rules`.
3. **Checks every template the rules name.** It loads each template's
   redirects and its `{{#invoke:Check for unknown parameters|check|...}}`
   list of accepted parameters, and reports rules that can't work.
4. **Checks the size of each template's unknown-parameters category,** 50 at
   a time, and skips the empty ones.
5. **Fixes each article** in the categories that have pages, then saves it,
   or writes a diff in a dry run.
6. **Writes the report** to `User:ParamBot/Report`, listing articles that
   need human review, articles it skipped and why, and problems in the rules.
   The report is only saved when its contents change.

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
| `User:ParamBot/Rules` | an existing wikitext page, not a redirect, **template-editor protected or higher**, with at least one rule |
| `User:ParamBot/Run` | an existing wikitext page, not a redirect, saying `yes` |
| `User:ParamBot/Report` | an existing wikitext page, not a redirect, that the bot account can edit |

The rules page decides what the bot edits, so anyone able to change it could
make the bot edit thousands of articles. That's why it must be protected. The
Run page is left open so any editor can stop the bot. The bot adds a note to
the report if the Run page is protected, if the rules page's protection is
due to expire, or if `User:ParamBot/Rules/Instructions` is missing.

**Stopping and failures**

- **Emergency stop.** The bot checks `User:ParamBot/Run` before every edit.
  Changing it to anything but `yes` stops the bot straight away. After that
  it makes no more wiki edits, not even the report, which is written to a
  local file instead.
- **Edit cap.** At most 100 edits per run (`--max-edits`).
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
[`examples/rules.mediawiki`](examples/rules.mediawiki) for a full rules page.

Each template's rules are an ordinary wikitable, so the rules page reads on the
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

- **Caption:** names the template. The bot watches
  `Category:Pages using <template, first letter lowercase> with unknown parameters`,
  unless the caption links to a different category, as some templates need:
  `|+ {{tl|Infobox bone}} watches [[:Category:Anatomy infobox template using unknown parameters]]`.
  On every run the bot works out which category each template really uses,
  by expanding the template's `Check for unknown parameters` call as if for an
  article. If a table watches the wrong one, the report says which link to
  add.
- **Columns:** column 1 holds the old names, column 2 the new name or
  `remove`. An optional column headed *If both are set* can say `merge`;
  other extra columns are notes.
- **Numbers:** `#` stands for no number or any number, so `termstart#`
  covers `termstart`, `termstart2`, `termstart12`, and so on.
- **Notes and spans:** text in a cell besides the `{{para}}` names is a note,
  and `rowspan`/`colspan` work. Existing deprecation tables can be pasted in
  with a caption added.
- **One-line format:** `{{AWB rename template parameter|Template|old|new}}`
  lines, in the format of
  [WP:AWB/RTP](https://en.wikipedia.org/wiki/Wikipedia:AutoWikiBrowser/Rename_template_parameters),
  also work.

The bot won't run unless the rules page is template-editor protected or
higher. Even so, the safeguards limit what a bad rule can do, because the old
name has to be one the template rejects and the new name one it accepts.

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
  instructions, so keep the instructions in step with the code.
- **`tests/test_readme.py`** checks that this README's links and file names
  point at files that exist, and that the project layout below lists every
  module.

## Usage

With the virtual environment active:

```bash
parambot --rules-file examples/rules.mediawiki check-rules
parambot --rules-file examples/rules.mediawiki run
parambot run --page "Some article" --template "Infobox person"
parambot run --page "User:Someone/sandbox" --any-namespace
parambot scaffold "Infobox settlement"
```

| Command | What it does |
|---|---|
| `run` | A dry run by default: it reads the wiki, then writes `out/edits-*.diff` and `out/report-*.mediawiki` instead of editing. |
| `run --live` | Edits for real. Needs a bot account and a `user-config.py` (see [Deploying](#deploying-on-toolforge)). |
| `check-rules` | Checks the bot's own pages, then every rule against its template and category, without looking at any articles. Exits 1 if there are problems. |
| `scaffold TEMPLATE` | Prints a rules table built from the template's `{{#invoke:Check for deprecated parameters\|check\|...}}` block. Lua patterns become `#` rows, and any that can't be converted are flagged. `--oldid` reads an older revision, from before the block was removed. |

Options that apply to every command go before the command name, for example
`parambot --rules-file x.wiki run`.

| Option | Default | Meaning |
|---|---|---|
| `--bot-user NAME` | `ParamBot` | Account name. Also sets the default rules, report and run pages under `User:NAME/`. |
| `--rules-page TITLE` | `User:<bot-user>/Rules` | Rules page to read. |
| `--rules-file PATH` | | Read the rules from a local file instead. |
| `--lang`, `--family` | `en`, `wikipedia` | Wiki to work on. |
| `-v` | | Verbose logging. |

Options for `run`:

| Option | Default | Meaning |
|---|---|---|
| `--live` | off | Edit for real. |
| `--trial` | off | Allow `--live` without the bot flag, for BRFA trial edits. |
| `--max-edits N` | 100 | Stop after this many edits. |
| `--cooldown-days N` | 30 | Don't edit a page the bot edited this recently. `0` turns this off. |
| `--template NAME` | all | Only use this template's rules. Can be repeated. |
| `--page TITLE` | | Only check this page, skipping the categories. Can be repeated. |
| `--any-namespace` | off | With `--page`, allow non-articles such as sandboxes. Dry runs only. |
| `--report-page`, `--run-page` | `User:<bot-user>/Report`, `/Run` | Pages to use instead. |
| `--out-dir DIR` | `out` | Where dry runs, and live runs that can't save the report, write their files. |

Dry runs don't need an account or a `user-config.py`. Set `PARAMBOT_CONTACT`
to put a contact URL or email address in the User-Agent; the default is the
bot's user page.

`run` exits with 0 when the run finishes, and 1 when an error stopped it (the
report is still written). It exits with 2 when it refused to start or was
switched off: for example the Run page doesn't say `yes`, the rules page is
missing, or the account is wrong.

## Deploying on Toolforge

[`deploy/jobs.yaml`](deploy/jobs.yaml) runs the bot daily at 04:17 UTC with the
[Toolforge jobs framework](https://wikitech.wikimedia.org/wiki/Help:Toolforge/Jobs_framework).

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
   `~/parambot/user-password.py`. Both files are git-ignored.
4. Set up the bot's pages. *Edit existing pages* doesn't let the bot create
   pages, so they all have to exist first:
   - `User:ParamBot`, using `{{bot|YourUsername}}`
   - `User:ParamBot/Rules`, with the rules, and template-editor protected
     (ask at
     [Requests for page protection](https://en.wikipedia.org/wiki/Wikipedia:Requests_for_page_protection))
   - `User:ParamBot/Rules/Instructions`, a copy of
     [`docs/rules-instructions.mediawiki`](docs/rules-instructions.mediawiki)
   - `User:ParamBot/Report`, a placeholder
   - `User:ParamBot/Run`, containing `yes`
5. Run `parambot check-rules` and fix anything it reports under `SETUP` or
   `PROBLEM`.
6. Run `toolforge jobs load deploy/jobs.yaml`.

For a BRFA trial, run by hand first with
`parambot run --live --trial --max-edits 50`.

## Project layout

| Path | Contents |
|---|---|
A run goes `cli` → `bot`, which checks the bot's pages (`botpages`), reads the
rules (`rules`), checks them against the templates (`prepare`), then applies
them to each article (`fixer`) and writes the report (`report`). Only `wiki`
talks to the wiki.

| Path | Contents |
|---|---|
| `parambot/cli.py` | The command line: one function per command. |
| `parambot/options.py` | The settings for a run. |
| `parambot/bot.py` | A run: pre-flight checks, finding pages in the categories, fixing them, the report. |
| `parambot/botpages.py` | Checking the bot's own pages (user page, rules, Run and report pages). |
| `parambot/rules.py` | Reading the rules page into a `RuleSet` per template. |
| `parambot/wikitable.py` | Reading wikitables: captions, header rows, `rowspan` and `colspan`. |
| `parambot/prepare.py` | Checking each `RuleSet` against its template, giving the `TemplateRules` the fixer applies. |
| `parambot/fixer.py` | Applying `TemplateRules` to a page's wikitext. |
| `parambot/templatescan.py` | Reading a template's own parameter checks; `scaffold`. |
| `parambot/luapattern.py` | Lua patterns, as used in templates, translated to Python regexes. |
| `parambot/report.py` | The report page. |
| `parambot/messages.py` | Everything the bot says on the report, in edit summaries and when it stops. |
| `parambot/wiki.py` | Everything the bot asks of the wiki, through Pywikibot. |
| `parambot/wikitext.py` | Small wikitext helpers. |
| `docs/rules-instructions.mediawiki` | Instructions for rule writers, for the wiki. |
| `examples/rules.mediawiki` | An example rules page. |
| `deploy/` | Toolforge job and Pywikibot config template. |
| `tests/` | The test suite; `tests/fakes.py` is the fake wiki. |
| `.github/workflows/tests.yml` | The checks GitHub runs on every push and pull request. |

## Status

The code is complete and tested against the live wiki in dry runs, but the bot
hasn't edited Wikipedia. The `ParamBot` account and its pages exist as
placeholders; `parambot check-rules` lists what they still need. Still to
decide before filing a BRFA:

- **Rules page.** Whether it stays in the bot's userspace or moves to a
  Wikipedia-space page. Either way it must be template-editor protected.
- **Timing.** The cooldown length, and whether the bot should run daily.
- **Scope.** Whether `remove` and `merge` rules are wanted, or only renames.
  Zackmann08 described the bot as changing "only those params it can directly
  replace".

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
