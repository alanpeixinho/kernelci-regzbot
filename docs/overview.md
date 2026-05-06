# Regzbot: high-level overview

This document introduces **regzbot**: what it is, why it exists, how it fits
into the Linux kernel development process, and how the codebase is organized.
Regzbot is **now part of [KernelCI](https://kernelci.org/)**, where it contributes
to coordinated regression tracking across the kernel ecosystem.
For usage instructions see [getting\_started.md](getting_started.md) and
[reference.md](reference.md). For setup, see
[installation.md](installation.md).

***

## What is regzbot?

**Regzbot** is a Linux kernel **regression tracking bot**. It monitors mailing
lists, bug trackers, and Git repositories so reported regressions do not slip
between first report and a fix in the appropriate kernel tree.

It is designed around the kernel's **email-centric** workflow: reporters and
developers interact with it through special lines in emails (`#regzbot`
commands) or existing conventions (`Link:` / `Closes:` tags in commits). The
goal is **low overhead**: no new tooling, no mandatory accounts, and no mandatory
web interfaces.

The project **runs in production** for public Linux kernel regression tracking
(see [Public dashboards](#public-dashboards-and-artifacts)) and is authored by
**Thorsten Leemhuis**.

***

## Key concepts for newcomers

### What is a regression?

A **regression** is a change in the kernel that breaks something that previously
worked. It does not have to be a crash: it can be degraded performance, a
feature that stops working, or hardware that is no longer recognized. The
critical distinction is that **something used to work and now does not**, because of a
specific change in the code.

Regressions are treated with higher urgency than ordinary bugs because they
violate user trust: someone upgraded their kernel and something broke that was
fine before. Linus Torvalds has always made clear that fixing regressions takes
priority over adding new features.

> WE DO NOT BREAK USER SPACE!

### The kernel's email-based workflow

Unlike many projects that rely on web-based platforms (GitHub, GitLab, and the
like) for code review and bug tracking, Linux kernel development happens
primarily over **email**. Understanding a few pieces of this infrastructure
helps explain how regzbot operates:

* **Mailing lists.** Kernel developers communicate through dozens of mailing
  lists organized by subsystem. Bug reports, patches, code reviews, and
  discussions all happen as email threads. The list
  `regressions@lists.linux.dev` is specifically for regression reports.

* **lore.kernel.org.** The public archive of all kernel mailing lists. Every
  email sent to a kernel list is stored here with a permanent URL. When someone
  says "link to the report on lore," they mean a URL such as
  `https://lore.kernel.org/r/<message-id>/`.

* **Message-ID, In-Reply-To, References.** Standard email headers that define
  threading. Each email has a unique `Message-ID`; replies carry `In-Reply-To`
  and `References` headers pointing at earlier messages. Regzbot uses this to tie
  replies, patches, and fixes to the original report without a centralized
  database.

* **`Link:` and `Closes:` tags.** Conventions used in Git commit messages to
  reference related mailing list discussions. When a developer writes `Link:
  https://lore.kernel.org/r/...` in a fix commit, it yields a traceable link
  between the fix and the report. Regzbot watches these tags to detect when a
  regression has been fixed.

### Mainline, linux-next, and stable

Regzbot tracks three trees because fixes arrive at different times:

* **Mainline** (`torvalds/linux.git`) is where official releases appear.
  `#regzbot introduced:` ranges (such as `v6.8..v6.9-rc1`) use tags from here.

* **linux-next** (`linux-next.git`) merges subsystem work before mainline.
  A fixing commit may appear here first; until mainline has it, regzbot can show **fix incoming**.

* **Stable** (`stable/linux.git`) holds **`linux-X.Y.y`** branches for kernels already shipped to users.

Reporting targets mainline; linux-next and stable explain whether the fix has landed yet.

***

## Why regzbot exists

### The "no regressions" rule

Kernel development rests on the idea of avoiding regressions, and that
regressions take priority over new features. Official kernel documentation
lays out expectations:

| Audience | Document | Key points |
|----------|----------|------------|
| Reporters | [Reporting regressions](https://docs.kernel.org/admin-guide/reporting-regressions.html) | How to report; CC `regressions@lists.linux.dev`; `#regzbot introduced:` recommended |
| Developers | [Handling regressions](https://docs.kernel.org/process/handling-regressions.html) | Use `Link:`/`Closes:` in commits; timing expectations; `#regzbot ^introduced` for missed reports |

### The problem regzbot solves

Before automated tracking, regressions reported on lists could disappear in the
traffic. Regzbot automates the bookkeeping:

* **Visibility:** open regressions appear on a public web dashboard.

* **Accountability:** periodic mail summaries list outstanding regressions ahead
  of releases.

* **Automatic correlation:** `Link:` tags in fixes tie into tracked regressions
  without an extra manual step.

***

## Core concepts

### 1. Starting tracking: `#regzbot` commands

A regression enters tracking when an email contains a line like:

```text
#regzbot introduced: v5.13..v5.14-rc1
```

If they are kind enough, one might include naming a direct *culprit* commit
(`#regzbot introduced: 1f2e3d4c5d`).

### 2. Connecting fixes without extra bot commands

Patches and commits that carry `Link:` or `Closes:` tags targeting the report URL
let regzbot associate fixes automatically. Developers already follow **this same
convention**, so nothing new is required there.

### 3. Tree awareness: "where is it fixed?"

Regzbot distinguishes **mainline**, **linux-next**, and **stable** trees. A fix
present only in linux-next surfaces as **"fix incoming"** until it reaches the
tree that matters for that regression. That is enforced using local Git clones
configured during setup.

### 4. Report sources (pluggable backends)

Not every report originates on mailing lists. Regzbot supports several backends:

| Source | Implementation | Notes |
|--------|----------------|-------|
| **lore** (NNTP/HTTPS) | `_repsources/_lore.py` | Primary source; kernel mailing list archives |
| **bugzilla.kernel.org** | `_repsources/_bugzilla.py` | REST API with API key |
| **GitLab** | `_repsources/_gitlab.py` | Issue tracker integration |
| **GitHub** | `_repsources/_github.py` | Issue tracker integration |

Tracker polling logic lives in `_repsources/_trackers.py`.

### 5. Persistence

State is stored in **SQLite** (`~/.local/share/regzbot/database.db`): tracked
regressions, processed message IDs, repository metadata, and report history.

***

### Available CLI commands

| Command | Purpose |
|---------|---------|
| `setup` | Initialize database, register sources, first Git tree sync |
| `run` | Full update cycle (sources → git → web) |
| `pages` | Regenerate web output only |
| `report` | Build interactive mail reports (operator sends manually) |
| `recheck` | Reprocess specific message IDs |
| `test` | Run offline/online test suites |

## Codebase organization

| Area | Files | Role |
|------|-------|------|
| Core + DB | `__init__.py` | Regression model, `GitTree`/`GitBranch`, `ReportThread`, `run()`/`generate_web()`/`report()` |
| Bot commands | `_rbcmd.py` | Parse and execute `#regzbot` subcommands |
| CLI | `commandl.py` | argparse-based subcommands |
| Web export | `export_web.py` | Static HTML generation |
| Mail reports | `export_mail.py` | Weekly text/mail report layout |
| CSV export | `export_csv.py` | CSV-oriented export (tests) |
| Lore ingestion | `_repsources/_lore.py` | NNTP and HTTPS access to lore archives |
| Tracker sources | `_bugzilla.py`, `_gitlab.py`, `_github.py`, `_generic.py` | Tracker-specific API integrations |
| Tests | `testing_online.py`, `testing_offline.py`, `testing_trackers.py`, `testdata/*` | Offline/online/tracker tests/expected results |

### Dependencies

From `requirements.txt`: **GitPython**, **requests**, **yattag**,
**python-bugzilla**, **python-gitlab**, **PyGithub**. Standard library modules
used include `sqlite3`, `email`, and `nntplib`.

***

## Public dashboards and artifacts

| Resource | URL |
|----------|-----|
| Tracked regressions (mainline) | https://linux-regtracking.leemhuis.info/regzbot/mainline/ |
| All views (index) | https://linux-regtracking.leemhuis.info/regzbot/ |
| About the effort | https://linux-regtracking.leemhuis.info/about/ |
| Weekly reports (lore search) | [lore.kernel.org](https://lore.kernel.org/lkml/?q=%22Linux+regressions+report%22+f%3Aregzbot) |

***

## Further reading

* [Getting started with regzbot](getting_started.md) (reporter and developer quick-start).

* [Reference documentation](reference.md) (full command syntax and behavior).

* [Installation](installation.md) (local instance).

* [About Linux kernel regression tracking](https://linux-regtracking.leemhuis.info/about/) (broader context and aims).

* [Reporting regressions (kernel.org)](https://docs.kernel.org/admin-guide/reporting-regressions.html).

* [Handling regressions (kernel.org)](https://docs.kernel.org/process/handling-regressions.html).
