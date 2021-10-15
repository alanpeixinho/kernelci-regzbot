# Regression tracking bot designed for the Linux kernel

Regzbot is a bot tailored for low-overhead regression tracking in the email
driven Linux kernel development process. It's currently WIP; the regzbot
developer started to use it now in a kind of alpha testing, but it's not ready
for general consumption, as major details might still change. That's why the
documentation for now is intentionally quite sparse.

For some background and how regzbot is supposed to work see here:
https://linux-regtracking.leemhuis.info/post/regzbot-approach/ 

The current version that is now test-driven is not too far away from the
initial plan of operation, but some details changed during early development.
For the list of understood commands hence stick to those described below. Make
sure to use the `#regbot` tag on a blank line with the "#" as first character
of that line. You are free to use multiple regzbot commands in one mail.

### How to make regzbot track a reported regression

To add an issue to the list of tracked regressions, sent or CC a mail to
regressions@lists.linux.dev, which is a public mailing list dedicated to
regressions in the Linux kernel. In that mail, use one of these two regzbot
commands:

* `#regzb introduced <commitid>|<range>`

 Adds the mail that uses this rebzot command as a regression report to the list
 of tracked regressions. When doing so, you need to either specify the commit
 that causes the regression or the version range where it was introduced.

 When specifying the culprit with the commit-id, use at least the first eight
 characters of its hexsha.

 When specifying a range, use tags or commit-ids; for example, if 5.8 worked
 fine, but Linux 5.9-rc1 does not, use `v5.8..v5.9-rc1`.

 Regzbot from then on will automatically monitor that thread and record any
 activity.

 The subject of the mail will be used as title for the report.

* `#regzb ^introduced <commitid>|<range>`

 Similar to `introduced`, but instead adds the parent mail (the one your mailer
 specifies in the mail's header with `In-Reply-To`) as the report for the
 regression that regzbot from now on will track.

### Modify aspects of an report

There are a few more commands to modify aspects of tracked regression. To use
them, send a mail in the thread with the regression report and use one or
multiple regzbot commands. You for example can use the `introduced` command
again to change the commit or the range that is causing the regression or
modify other properties with the following commands:

* `#regzb link http://example.com/some/place/ (<title>)`

 Adds a link to the regression report that has relevant information for people
 that look into the report, for example an additional report about the issue in
 a bug tracker.

* `#regzb unlink http://example.com/some/place/`

 Remove the specified link for the database, for example if it turned out to be
 an unrelated issue.

* `#regzb monitor https://lore.kernel.org/lkml/some_msgid@example/ (<title>)`

 Similar to the link command, but only works for mailing lists on
 lore.kernel.org and makes regzbot monitor that discussion. That for example is
 useful to monitor a thread with a different report about the same issue; it's
 also of interest to watch threads with a proposed fix still under discussion.

* `#regzb unmonitor https://lore.kernel.org/lkml/some_msgid@example/`

 Stop monitoring the discussion and remove all its activity from the database,
 for example if it turned out to be an unrelated issue.

* `#regzb title More meaningful description`

 Provide a better title for the tracked regression.

### Resolve a report

Ideally developers that fix a tracked regression tracked will link to the
regression report in the commit message of the fix like this:

`Link: https://lore.kernel.org/lkml/regression_report_msgid@example/`

This is done for many years now and will make regzbot mark the regression as
resolved once that commit hits the git tree where the regression occurred.
Regzbot will also notice messages with such a link on various monitored mailing
lists; if one points to a tracked regression, it will automatically start that
thread for activity. Additionally, regzbot will watch linux-next and record
when a fix for a regression in downstream tree shows up there.

There are a few other commands to use in cases where the above doesn't work
out:

 * `#regzb dupof https://lore.kernel.org/lkml/regression_report_msgid@example/`

 Marks the regression reported in the current thread as a duplicate of the
 linked regression report.

 * `#regzb fixedby 1234567890ab`

 Marks the regression as fixed by the commit with the hexsha 1234567890ab. You
 can use that approach even if that commit hasn't yet hit the tree where the
 regression occurs: in this case regzbot will leave the report unresolved until
 it lands there, but will make it obvious in the webinterface that a fix is
 incoming.

 * `#regzb invalid Some reason why`

 Marks the regression as invalid with the provided reason

## Licensing

Rezbot is available under the APGL 3.0; see the file COPYING for details. If
you think a more liberal license should be used, let Thorsten know what you'd
prefer, as for now it's still quite easy to change the license.

Regzbot was started by Thorsten Leemhuis as part of a project that has received
funding from the European Union’s Horizon 2020 research and innovation
programme under grant agreement No 871528.
