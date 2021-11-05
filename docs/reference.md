# Reference documentation for regzbot, the Linux kernel regression tracking bot

[[_TOC_]]

*Note: this document explains regzbot concept and all options; if you want something that's easier to consume, head over to '[getting started with regzbot](https://gitlab.com/knurd42/regzbot/-/blob/main/docs/getting_started.md)'*

## Basic concept

Regzbot is a bot watching mailing lists and Git trees to track Linux kernel regression from report to elimination, to ensure none fall though the cracks unnoticed. It tries to impose as little overhead as possible on reporters and developers, needs two things to do its work:

 * someone needs to tell regzbot when a mail contains a regression report
 * related discussions like the fix need to link to the mail with the report

The first task creates an small burden on people, which simply can't be avoided; the second task on the other hand normally shouldn't cause extra work for anyone, as patches fixing a regression ought to do that already years before regzbot came to light.

But even the first task is easy to fulfill when reporting the regression as outlined in the [Linux kernel's "reporting issues" document](https://www.kernel.org/doc/html/latest/admin-guide/reporting-issues.html): simply add the following line to the mail with the report, separated from the earlier and later parts of the mail by a blank line:

#regzbot introduced: v5.13..v5.14

Regzbot then considers this mail as a report for a regression that was introduced between Linux 5.13 and 5.14. Instead of a version range it's possible to specify a commit-id here, too, if the change causing the regression is known.

After telling regzbot about the regression it will try to keep track of the fixing progress. To do so, it will record all direct and indirect replies to this mail. In addition, regzbot will look for mails and commits that link to the report using the mail's 'Message-ID'. Say someone reported a regression in a mail with the ID '4970a940-211b-25d6-edab-21a815313954@example.com', then regzbot will look out for mails and commits with a string like this:

Link: https://lore.kernel.org/r/4970a940-211b-25d6-edab-21a815313954@example.com/

That way regzbot can automatically record if a patch to fix the regression gets posted to one of the main Linux kernel development mailing lists for review. That allows regzbot to associate that thread with the regression report and consider any activity there as progress.

Regzbot will also notice when such a patch gets applied to a git tree to fix the regression. It then marks the regression as 'to be fixed' or 'fixed', depending on the tree where the patch is applied. Say regzbot was told about a regression with a command like `#regzbot introduced: v5.13..v5.14`. From those two version tags it can conclude the regression needs to be fixed in linux-mainline. Hence, if a fix for that regression gets applied in a tree upstream to mainline (say linux-next), it will mark the regression only as 'to be fixed' and store a pointer to the commit. Only when this change gets merged to linux-mainline it will consider the regression 'fixed'.

## What regzbot does with the gathered data

From the collected data Regzbot compiles a website holding information about all tracked regressions, like the regressions title or the age of the first and the last activity; additionally, it will link to the thread with the report, the latest activities, as well as mailing list threads and webpages related to the regression.

Regzbot is also able to compile occasional reports with unresolved regression with a similar scope, which can be used to send a weekly report to the Linux kernel mailing list and the tree maintainers.

## Interacting with regzbot

Above outlines the core concept of regzbot. Obviously that's not enough, as users will sometimes forgot to get regzbot involved when reporting a regression; and they might want to update the version range initially specified, for example after they found the change that causes the regression with a bisection. Other times the report might turn out to be a duplicate of another report or not a regression at all. And developers might forget linking to the report in the fixes commit message, hence there needs to be another way to tell regzbot a tracked regression got resolved.

To cover these and other use-cases it's possible to interact with regzbot using 'regzbot commands'. These need to be used in mails sent as direct or indirect reply to the mail that got the regression tracked (e.g., the mail that used `#regzbot introduced: ...`), as that allows regzbot to automatically associate the command with the tracked regression.

## regzbot commands

The following regzbot commands are available; only the `introduced` commands can be used in threads not already tracked by regzbot.

### commands to make regzbot track a regression

 * `#regzbot introduced: <commit-id|range>`

   Makes regzbot consider this mail as a report for a regression introduced in <commit-id> or <range> the mail's author wants to see tracked by regzbot.

   `<commit-id>` must be a commit-id at least 8 characters long. Regzbot will try to look the commit-id up in linux-mainline, linux-next, and linux-stable (in this order) to associate the regression to one of those trees.

   `<range>` must be in the format used by git using either tags or commit-ids that ideally should both be present in one of linux-next, linux-mainline, or linux-stable. A `<range>` thus can look like this: `v5.13..v5.14`, `v5.14-rc1..v5.14-rc2`, `v5.13..1f2e3d4c5d`, `next-20211006..next-20211008`, or `v5.13.8..v5.13.10`. Ranges that use tags from different trees (like `v5.13.8..v5.14-rc1`) won't make regzbot fail, but it might associate the regression to the wrong tree or consider it unassociated.

 * `#regzbot ^introduced: <commit-id|range>`

   Like `#regzbot introduced`, but will consider the parent mail as the report of the regression (the one the mail's header specifies as 'In-Reply-To'). Useful to make regzbot track a regressions some reported without getting regzbot involved.


### commands to update properties of a tracked regression

 * `#regzbot introduced: <commit-id|range>`

    When used in a thread of an already tracked regression this will update the introduced field for the tracked regression.

 * `#regzbot title: <title>`

   Update the title regzbot assigned to the regression, which it normally automatically derives from the subject of the report.

   `<title>` must be a string.

### commands to point to related webpages and discussions

 * `#regzbot link: <link> [title]`

   Tell regzbot about something on the web that is of interest to anyone looking into the regression. Regzbot will show the link prominently in the web-interface and its reports. The title is optional, but recommended to tell users what the link leads to.

   This can be useful to highlight important parts of a discussion.

   `<link>` must point to a mail in the lore message archiver service and thus needs to look like this: `https://lore.kernel.org/lkml/30th.anniversary.repost@klaava.Helsinki.FI/`

   `[title]` is optional and must be a string

 * `#regzbot unlink: <link>`

   Remove a link added earlier by a `#rezbot link:`

 * `#regzbot monitor: <link> [title]`

   Tell regzbot about a discussion related to the regression. Regzbot will show the link prominently in the web-interface and its reports; additionally, it will also monitor the thread and consider any activity there as an activity for the regression. This can be used to monitor related threads, for example a review of an patch for the particular regression; ideally thus the mail with the patch would have linked to the report with the regression using a 'Link: ' tag, as that would have had the same effect on regzbot.

   `<link>` must point to a mail in the lore message archiver service and thus needs to look like this: `https://lore.kernel.org/lkml/30th.anniversary.repost@klaava.Helsinki.FI/`

 * `#rezbot unmonitor: <link>`

   Remove a monitored thread from the regression that was added earlier by a `regzbot monitor:` command.

### commands to resolve a regzbot entry

 * `#regzbot dup-of: <link>`

   Mark the entry for this regression as a duplicate of the entry for the linked regression.

   `<link>` must point to a report of a tracked regression in the lore message archiver service and might look like this: `https://lore.kernel.org/lkml/30th.anniversary.repost@klaava.Helsinki.FI/`

 * `#regzbot fixed-by: <commit-id>`

   Tells regzbot the regression is fixed or is going to be fixed by commit <commit-id>. If the commit is found in the tree wunlinkkhere the regression occurred, regzbot will mark the regression immediately as 'fixed'; for all other cases it will consider the regression as 'to be fixed', until the commit shows up in the appropriate tree.

 * `#regzbot invalid: [reason]`

   Makes regzbot close the entry for the regression.

   `[reason]` is optional and specifies the reason why this entry should be considered is closed as 'invalid'.

### commands users and developers normally shouldn't use

 * `#regzbot activity-ignore`

   Regzbot will not consider the mails with this command as an activity for the regression; It thus will neither update the value for 'days since last activity' nor link to the mail in the 'latest activity' section of its web-interface. The command is useful for mails that are totally irrelevant for the bug processing process and thus would only noise to people looking into the regression; it's thus of use for mails only meant for regzbot, for example ones that just update Regzbot properties like the title.

 * `#regzbot poke`

   Regzbot will consider the mail with this command as a 'poke' asking for a progress update from someone involved. It's meant to be used in inquires when a regression seems to become state, after there was no mail from a user or developer for a while. Regzbot in its reports and the web UI will show if someone sent a poke to get things rolling again. But a mail with this command otherwise will be handled like `#regzbot activity-ignore` and thus not be counted as an activity; that way it will continue to look state until someone replies.
