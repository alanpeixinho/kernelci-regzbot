# Regression tracking bot designed for the Linux kernel

Regzbot is a bot tailored for low-overhead regression tracking in the email
driven Linux kernel development process. It's actually used in the field, but
still in a alpha stage: more adjustments are needed to make it better suite the
its intended purpose.

Anyone can make regzbot track a regression by adding a command such as
`#regzbot introduced: <commit-id>` to an email sent to the Linux kernel mailing
list (LKML) or `regressions@lists.linux.dev`. Regzbot later notices fixes
automatically when a change points to the report using existing conventions such
as `Link:` or `Closes:` tags, which avoids extra work for developers. If those
links were forgotten, or if more details need to be recorded, the documentation
below lists other `#regzbot` commands.

Kernel development treats regressions with high urgency — fixing them takes
priority over new features. Before automated tracking, regression reports on
mailing lists could disappear in the traffic. Regzbot automates the
bookkeeping: open regressions appear on a public dashboard, and periodic mail
summaries list outstanding issues ahead of releases. See the kernel
documentation for
[reporting regressions](https://docs.kernel.org/admin-guide/reporting-regressions.html) and
[handling regressions](https://docs.kernel.org/process/handling-regressions.html).

## Scope

Regzbot focuses on Linux kernel regressions in mainline, the latest mainline
release, and the stable series derived from it. Tracking is best-effort:
regzbot helps reports stay visible and helps connect fixes to reports, but it
does not guarantee every regression is tracked or fixed.

It is not intended to track ordinary bugs, monitor every bug tracker used by
kernel subsystems, or produce complete regression statistics.

The public dashboards below show regression tracking in practice: start with
the mainline regression list to see currently tracked issues, while this README
gives background on the Linux kernel regression tracking effort. The
documentation links cover reporting, fixing, installation, and development.

### Public dashboards

| Resource | URL |
|----------|-----|
| Tracked regressions (mainline) | https://linux-regtracking.leemhuis.info/regzbot/mainline/ |
| All views (index) | https://linux-regtracking.leemhuis.info/regzbot/ |
| About the effort | [README](README.md) |
| Weekly reports (lore search) | [lore.kernel.org](https://lore.kernel.org/lkml/?q=%22Linux+regressions+report%22+f%3Aregzbot) |

### Documentation

* [Getting started](docs/getting_started.md) — report, fix, or update a tracked regression
* [Reference](docs/reference.md) — full `#regzbot` command syntax
* [Installation](docs/installation.md) — run your own instance
* [Contributing](CONTRIBUTING.md) — codebase layout and development

## History

Linux had no formal regression tracking for most of its history. Rafael J.
Wysocki tracked regressions for several years in the 2000s, but that effort
ended in 2012.

Thorsten Leemhuis restarted the work manually in 2017. That showed the value of
regression tracking, but also that manual tracking did not scale.

Development of regzbot started in 2021, and Thorsten began tracking
regressions with it later that year.

## Licensing and funding

Regzbot is available under the LGPL 2.1; see the file COPYING for details.

Regzbot was started by Thorsten Leemhuis as part of a project that received
funding from the European Union's Horizon 2020 research and innovation
programme under grant agreement No 871528.

Starting in May 2022, regzbot development and the Linux kernel regression
tracking efforts performed by Thorsten were supported with funds from Meta for
about two years. Regzbot is now part of [KernelCI](https://kernelci.org/),
where it contributes to coordinated regression tracking across the kernel
ecosystem and receives funding for current development.
