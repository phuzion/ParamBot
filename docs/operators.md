# Operating ParamBot

Notes for ParamBot's operators: how the bot runs on Toolforge, and the
commands for looking after it. For what the bot does and how its rules work,
see the [README](../README.md) and
[User:ParamBot/Documentation](https://en.wikipedia.org/wiki/User:ParamBot/Documentation).

In the commands below, `<tool>` is the Toolforge tool ParamBot runs as, and
`<you>` is your Toolforge shell name.

## The bot's pages

| Page | What it's for |
|---|---|
| [User:ParamBot/Run](https://en.wikipedia.org/wiki/User:ParamBot/Run) | The off switch: `yes` to run, `report` to update only the report, anything else to stop. |
| [User:ParamBot/Report](https://en.wikipedia.org/wiki/User:ParamBot/Report) | What the last run found: pages needing review, pages it skipped, and problems with the rules. |
| [User:ParamBot/Rules](https://en.wikipedia.org/wiki/User:ParamBot/Rules) | The approved rules pages, with the revision of each to use. Template-editor protected. |
| [Special:Contributions/ParamBot](https://en.wikipedia.org/wiki/Special:Contributions/ParamBot) | Its edits. |
| [The BRFA](https://en.wikipedia.org/wiki/Wikipedia:Bots/Requests_for_approval/ParamBot) | The approval request. |

## How it runs

The bot runs as a scheduled job on
[Toolforge](https://wikitech.wikimedia.org/wiki/Help:Toolforge), with these
files in the tool's home directory:

| Path | What it is |
|---|---|
| `~/parambot` | A git checkout of [phuzion/ParamBot](https://github.com/phuzion/ParamBot). The job runs the code straight from here. |
| `~/parambot/venv` | The Python 3.13 virtual environment, with Pywikibot and mwparserfromhell. |
| `~/parambot/user-config.py`, `~/parambot/user-password.py` | Pywikibot's settings, and the bot password. |
| `~/parambot/parambot.toml` | The bot's settings (see [Settings](../README.md#settings)). Optional: without it, everything has its default. |
| `~/parambot/out/` | Files the runs write: the edits a run would have made (`edits-*.diff`), and any report it couldn't save (`report-*.mediawiki`). |
| `~/parambot.out`, `~/parambot.err` | The job's output. `.err` has the log, `.out` the one-line summary of each run. Each run adds to the end of them. |

`user-config.py`, `user-password.py` and `parambot.toml` are git-ignored, so
`git pull` never touches them. Don't edit the files git tracks here, such as
`deploy/jobs.yaml`: change them in the repository and pull, or the next pull
will fail with a conflict.

The job is called `parambot`, and is defined in
[`deploy/jobs.yaml`](../deploy/jobs.yaml):

- **When:** `@daily`. Toolforge picks the time of day; `toolforge jobs show
  parambot` shows when it last ran.
- **What:** `python -m parambot run --report-only`, until the BRFA is
  approved: it updates the report and edits no articles.
- **Image:** `python3.13`. It must match the Python the venv was built with.
- **Email:** Toolforge emails the tool's maintainers when a run fails.

Each run:

1. logs which commit of the bot it is, such as `INFO ParamBot 3457b05`, and
   where its settings came from;
2. checks User:ParamBot/Run, logs in, and checks the bot's pages;
3. reads the approved rules, checks them against the templates, and polls
   the templates' unknown-parameter categories;
4. fixes the pages it finds, or, reporting only, works out the fixes and
   writes them to `out/`;
5. saves User:ParamBot/Report, if what it found has changed. The report's
   last line names the commit, such as `<!-- ParamBot 3457b05 -->`.

A run stops starting new work after 20 hours (`max_hours`), so it can't
still be going when the next one starts.

How a run ends:

| Exit code | Meaning |
|---|---|
| 0 | The run finished. |
| 1 | An error stopped it. The report is still written. |
| 2 | It refused to start, or was switched off: for example, the Run page says no, or the settings file has a mistake. |

Anything but 0 gets a failure email. So while the Run page says `no`, expect
an email every day.

## Getting in

```bash
ssh <you>@login.toolforge.org
become <tool>
cd ~/parambot
```

The commands below assume you're in `~/parambot`.

## Everyday commands

### Did it run, and what happened?

```bash
toolforge jobs show parambot     # the schedule, when it last ran, and how it ended
tail -n 40 ~/parambot.err        # the log of the latest run
tail -n 3 ~/parambot.out         # one line per run: "Last run: ... (reporting only) 3 edits."
```

Or look at User:ParamBot/Report and its history.

### What would it have edited?

Each report-only run writes the edits it would have made to a diff:

```bash
ls -t out/ | head
less "$(ls -t out/edits-*.diff | head -n 1)"
```

There's one diff per run, so they pile up. To delete the ones over a month
old:

```bash
find out -name 'edits-*.diff' -mtime +30 -delete
```

### Run it now

```bash
toolforge jobs list                # check it isn't running already
toolforge jobs restart parambot    # start the scheduled job straight away
```

### Update the code

```bash
git pull
git log -1 --oneline
```

That's all: the next run uses the new code. If `pyproject.toml`'s
dependencies changed, also [rebuild the venv](#rebuild-the-venv). If the
command, image or schedule in `deploy/jobs.yaml` changed, reload it with
`toolforge jobs load deploy/jobs.yaml`.

### Check the bot's pages and the rules

This reads the wiki and saves nothing. Run it after changing
`parambot.toml`, `user-config.py` or the rules:

```bash
toolforge jobs run parambot-check --image python3.13 --wait \
  --command 'cd $HOME/parambot && PYWIKIBOT_DIR=$HOME/parambot ./venv/bin/python -m parambot check-rules'
cat ~/parambot-check.out ~/parambot-check.err
toolforge jobs delete parambot-check
```

In the output, `SETUP` lines would stop a live run, `PROBLEM` lines are about
the rules, and `NOTE` lines are for information. With any `SETUP` or
`PROBLEM` lines, the job ends with exit code 1.

### Preview one page

```bash
toolforge jobs run parambot-preview --image python3.13 --wait \
  --command 'cd $HOME/parambot && PYWIKIBOT_DIR=$HOME/parambot ./venv/bin/python -m parambot run --dry-run --page "Some article"'
less "$(ls -t out/edits-*.diff | head -n 1)"
toolforge jobs delete parambot-preview
```

Add `--template "Infobox person"` to use only that template's rules, or
`--any-namespace` to preview a sandbox. This is just as easy from your own
computer, since a dry run needs no account: see [Usage](../README.md#usage).

### Change a setting

```bash
nano parambot.toml
```

Then [check it](#check-the-bots-pages-and-the-rules). A mistake in the file
stops the next run straight away, with exit code 2, and the log names the
setting. Every setting is listed, with its default, in
[`deploy/parambot.example.toml`](../deploy/parambot.example.toml).

## Stopping the bot

- **From the wiki.** Anyone can do this. Change User:ParamBot/Run to `no`.
  The bot checks it at the start of every run and before every edit. Each
  daily run then ends with exit code 2, and a failure email, until the page
  is changed back.
- **On Toolforge.** `toolforge jobs delete parambot` removes the job,
  including a run in progress. Bring it back with
  `toolforge jobs load deploy/jobs.yaml`.

## A BRFA trial

When the Bot Approvals Group approves a trial:

1. Set User:ParamBot/Run to `yes`.
2. Check when the daily run is due (`toolforge jobs show parambot`), so the
   trial doesn't run at the same time.
3. Start the trial, with `--max-edits` set to the number of edits approved:

   ```bash
   toolforge jobs run parambot-trial --image python3.13 \
     --command 'cd $HOME/parambot && PYWIKIBOT_DIR=$HOME/parambot ./venv/bin/python -m parambot run --live --trial --max-edits 50'
   tail -f ~/parambot-trial.err     # Ctrl+C stops watching, not the trial
   ```

   `--trial` lets it edit without the bot flag. Edits are at least 10
   seconds apart.
4. When it's finished, set the Run page back to `report`, run
   `toolforge jobs delete parambot-trial`, and link the trial edits on the
   BRFA.

## After approval

1. Check that the account has the bot flag, at
   [Special:UserRights/ParamBot](https://en.wikipedia.org/wiki/Special:UserRights/ParamBot).
   Live runs refuse to start without it, and the bot password needs the
   *High-volume (bot) access* grant.
2. In the repository, change `--report-only` to `--live` in
   `deploy/jobs.yaml`, commit and push. Then on Toolforge:

   ```bash
   git pull
   toolforge jobs load deploy/jobs.yaml
   ```

   (Or take `--report-only` out of the job and set `mode = "live"` in
   `parambot.toml`: the job then does what the settings say.)
3. Set User:ParamBot/Run to `yes`, and update the approval and status on the
   user page.

## Maintenance

### Rebuild the venv

This is needed when the job's image changes to another Python version, or
`pyproject.toml`'s dependencies change. Build it with the same image the job
uses:

```bash
toolforge jobs run parambot-venv --image python3.13 --wait \
  --command 'cd $HOME/parambot && python3 -m venv --clear venv && ./venv/bin/pip install -e .'
cat ~/parambot-venv.err
toolforge jobs delete parambot-venv
```

### Upgrade Pywikibot

```bash
toolforge jobs run parambot-pip --image python3.13 --wait \
  --command 'cd $HOME/parambot && ./venv/bin/pip install --upgrade pywikibot'
toolforge jobs delete parambot-pip
```

Then [check the pages and rules](#check-the-bots-pages-and-the-rules). Since
Pywikibot 11.8, `user-config.py` shouldn't set `maxlag`: it was renamed, and
each version warns about the other's name.

### Change the bot password

1. Logged in as ParamBot, reset the password at
   [Special:BotPasswords](https://en.wikipedia.org/wiki/Special:BotPasswords).
2. Put the new one in `~/parambot/user-password.py`, and keep the file
   private: `chmod 600 user-password.py`.
3. If logging in fails after that, delete `pywikibot-ParamBot.lwp`, the saved
   login cookies, and the next run logs in afresh.

### Log files

`~/parambot.err` and `~/parambot.out` grow with every run. To empty them:

```bash
truncate -s 0 ~/parambot.err ~/parambot.out
```

Toolforge plans to stop writing job logs to files. After that, read them with
`toolforge jobs logs parambot`.

## When something goes wrong

| In the log | What it means | What to do |
|---|---|---|
| `User:ParamBot/Run does not say "yes" or "report"; not running` | The bot is switched off. | If it should run, change the Run page back. |
| `User:ParamBot/Run no longer says "yes"; stopped before editing …` | It was switched off during a run. | The same. |
| `Logged in as 'X', expected 'ParamBot'` | `user-config.py` or `user-password.py` is for another account. | Fix them. |
| `ParamBot does not have the bot right; use --trial for BRFA trial edits` | A live run without the bot flag, or without the bot password's *High-volume (bot) access* grant. | Use `--trial` for a trial; otherwise check the flag and the grant. |
| `parambot: error: …/parambot.toml: …` | A mistake in the settings file. | Fix the setting it names. |
| `Not running, because of problems with the bot's pages:` | A live run's checks failed, for example the rules page isn't protected enough. | Fix what it lists. [Check the pages](#check-the-bots-pages-and-the-rules) lists the same problems. |
| `5 pages in a row failed` | Something bigger is wrong, often with the wiki's API. | Look at the errors before it. The next run tries again. |
| HTTP 429 or 403 errors | Wikimedia is slowing or blocking the bot's requests. | Raise `read_delay` in `parambot.toml`. |
| The report hasn't changed | It's only saved when what the bot finds changes. | `tail ~/parambot.out` shows each run's summary. |
