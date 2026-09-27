# ParamBot

A Wikipedia bot for the request
[Bot to regularly check for restored deprecated parameters](https://en.wikipedia.org/wiki/Wikipedia:Bot_requests#Bot_to_regularly_check_for_restored_deprecated_parameters).

After a deprecation run has renamed an infobox's old parameters and support for
the old names has been removed, a revert (often of LLM-generated content) can
bring the old names back. The template then silently ignores them and the page
lands in *Pages using <template> with unknown parameters*. ParamBot polls those
categories on a schedule and re-applies **only** the parameter renames. It
never reverts the edit that brought them back.

## How it works

1. It reads the rules page (`User:ParamBot/Rules` by default).
2. It checks the size of every template's unknown-parameters category in one
   batched query. Empty categories cost nothing more.
3. For each populated category it reads the template's own
   `{{#invoke:Check for unknown parameters|check|...}}` whitelist and its
   redirects, then checks each member page (main namespace only).
4. On each page it renames old parameters in calls to that template (or its
   redirects) and saves, or, in a dry run, writes a diff.
5. It rewrites the report page (`User:ParamBot/Report`) with anything a human
   needs to look at. The report is only saved when its findings change.

### Safety rules

- **A rule stays inactive while the template still accepts the old name.**
  Rules can be added before support is removed; they switch on by themselves
  once the old name leaves the template's whitelist. Until then the
  deprecation runs and the deprecated-parameters category handle it.
- **Never renames to a name the template doesn't accept.** A typo in a rule
  shows up on the report instead of breaking infoboxes.
- **No whitelist, no rules.** If the bot can't read a template's
  `Check for unknown parameters` list, it switches that template's rules off
  and says so on the report. Without the list, a backwards rule
  (`image_size = imagesize`) would break every page it touched.
- **No cosmetic-only edits.** If the only changes are to empty parameters
  (which don't trigger the category with `ignoreblank=y`), the page is left
  alone.
- **Conflicts go to humans.** If the old and new parameters are both set to
  different values (the `alma_mater` + `education` case), the page is listed
  on the report and that parameter is left alone. A row can opt in with
  `merge` in an *If both are set* column, which appends the old value to the
  new one.
- **No edit wars.** If the bot has edited the page in the last 30 days
  (`--cooldown-days`), it doesn't repeat the fix and lists the page instead.
  Someone may have put the old parameter back on purpose.
- Honours `{{bots}}`/`{{nobots}}`. Only touches the main namespace. Ignores
  templates inside comments, `<nowiki>`, `<pre>` and `<syntaxhighlight>`.
- Keeps the page's formatting, including lined-up `=` signs.
- Live runs only happen when `User:ParamBot/Run` says `yes`. The bot checks
  it at the start and again before every edit, so changing it to anything
  else stops the bot straight away. After that the bot makes no more wiki
  edits, not even the report; the report goes to a local file instead.
- **Failures don't lose the report.** An error on one page is logged, the page
  is listed as not edited, and the run carries on. Five failures in a row, or
  any failure outside the page loop, stop the run. The report is still
  saved, with an *Errors* section (or written locally if the wiki can't be
  reached), and the process exits non-zero so Toolforge emails the operator.

| Old parameter | New parameter | What the bot does |
|---|---|---|
| set | absent | renames old → new |
| set | present but empty | moves the value into new, removes old |
| set | same value | removes old |
| set | different value | lists the page for review (or merges, if the row says `merge`) |
| empty | anything | nothing, unless the page is being edited anyway |

## The rules page

**Rule writers should read
[`docs/rules-instructions.wiki`](docs/rules-instructions.wiki).** It's
written for editors rather than programmers, and it belongs on the wiki at
`User:ParamBot/Rules/Instructions`, transcluded at the top of the rules page
(see [`examples/rules.wiki`](examples/rules.wiki)). `tests/test_docs.py`
checks that every example in it is valid, so keep it in step with the code.

In short, each template's rules are an ordinary wikitable, so the protected
rules page reads as what it is. The caption names the template, column 1
holds the old names and column 2 the new name or `remove`:

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

- `#` stands for no number or any number (`termstart`, `termstart2`, ...).
  It replaces the Lua patterns templates use.
- An optional column headed *If both are set* can say `merge`. Any other extra
  columns are notes.
- A category link in the caption changes the category the bot watches.
- `rowspan`/`colspan` work, and text in a cell besides the `{{para}}` names is
  a note. Existing deprecation tables can be pasted in with a caption added.
- The one-line `{{AWB rename template parameter|...}}` format from
  [WP:AWB/RTP](https://en.wikipedia.org/wiki/Wikipedia:AutoWikiBrowser/Rename_template_parameters)
  also works, since that template exists.

`parambot scaffold "Infobox settlement"` turns a template's
`{{#invoke:Check for deprecated parameters|check|...}}` block into a table,
converting its Lua patterns to `#` rows and flagging any that can't be
converted. Add `--oldid` to read the block from a revision from before it was
removed.

Every run checks every table against its template, so the report's
*Rules page problems* section catches mistakes whether or not any article
needs the rule yet. `parambot check-rules` runs the same checks from the
command line.

The rules page decides what the bot edits, so it should be protected
(template-editor protection is the natural level). The safety rules above
limit what a bad rule can do: the old name has to be one the template
rejects, and the new name has to be one it accepts.

## Running it

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # .venv/bin/python on Linux
.venv/Scripts/python -m pytest
```

Dry runs only read from the wiki and need no account or `user-config.py`:

```bash
python -m parambot --rules-file examples/rules.wiki check-rules   # check rules against templates
python -m parambot --rules-file examples/rules.wiki run           # writes out/edits-*.diff and out/report-*.wiki
python -m parambot run --page "Some article" --template "Infobox person"
python -m parambot run --page "User:Someone/sandbox" --any-namespace   # preview a sandbox
```

The bot only edits articles. `--any-namespace` lets `--page` name a sandbox
or other non-article page, to see what the bot would do to a sample infobox.
It's refused together with `--live`.

Live runs need a bot account and a Pywikibot `user-config.py` (see
[`deploy/`](deploy/)):

```bash
python -m parambot run --live --trial --max-edits 50   # BRFA trial: no bot flag yet
python -m parambot run --live                          # approved and flagged
```

`--bot-user` sets the account name, which also sets the default rules, report
and run pages. Set `PARAMBOT_CONTACT` to put a contact URL or address in the
User-Agent.

## Deployment (Toolforge)

`deploy/jobs.yaml` runs the bot daily with the
[Toolforge jobs framework](https://wikitech.wikimedia.org/wiki/Help:Toolforge/Jobs_framework).
`deploy/user-config.example.py` shows the Pywikibot settings, which log in with
a [BotPassword](https://en.wikipedia.org/wiki/Special:BotPasswords) that has
only the *Edit existing pages* grant.

## Before filing a BRFA

Still open:

- Account name. `ParamBot` is unregistered as of 2026-09-26, and every page
  name follows from `--bot-user`.
- Where the rules page lives and who can edit it (bot userspace plus
  template-editor protection, or a Wikipedia-space page).
- Cooldown length and run frequency (daily is the default).
- Whether `remove` rows (deleting restored parameters that had no replacement)
  and `merge` are wanted, or only renames. Zackmann08 described the bot as
  changing "only those params it can directly replace".

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
