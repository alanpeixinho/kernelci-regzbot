# Get started with regzbot

[[_TOC_]]


## Why and how to make regzbot track a Linux kernel regression

When reporting a Linux kernel regression it is in your interest to make regzbot aware of the issue, as that ensures the report won't accidentally fall though the cracks; it also makes sure leading developers see the issue via the tracked regression website [or the weekly reports, which are not sent yet, but soon will be].

To get these benefits there is just one thing you need to do when reporting the regression by mail: include a line starting with `#regzbot introduced foo`, where foo specifies when the regression started to happen. One way to do that is to specify a version range which is stating the last version that worked and the first broken:

`#regzbot introduced: v5.13..v5.14-rc1`

See below for a few other examples how to specify ranges.

You know which commit causes the regression? Even better, as that will help to get the regression fixed quickly, so be sure to point it out:

`#regzbot introduced: 1f2e3d4c5d`

In both cases ensure a blank line separates this bot-command from the rest of the mail and CC regressions@lists.linux.dev, as sending a copy to the regression mailing-list get the report on the radar of regzbot and people fighting regressions. That's all that you have to do in addition to what is outlined in the kernel's [Reporting Issues](https://www.kernel.org/doc/html/latest/admin-guide/reporting-issues.html) document.

See below how to add modifying the version range or make it aware of further data sources.

## How to tell regzbot that you are fixing a tracked Linux kernel regression

Regzbot is designed to normally not create any additional chores for Linux kernel developers like you. But for that to work it's important you do something the [Linux kernel documentation specifies for a while already aready](https://www.kernel.org/doc/html/latest/process/submitting-patches.html): when fixing a regression, include a `Link:` tag with the URL to the report in the [mailing list archives on lore.kernel.org](https://lore.kernel.org/). This aspect is important for regzbot, as it allows the bot to connect the fix with the regression's report. That's needed so regzbot can do all the things automatically that otherwise would be manual work for somebody — like marking the regression as resolved once the fix hits mainline.

But sometimes you might want to do more with regzbot, like telling it about the causing commit or marking the report as invalid. These and other things are explained below; the instructions there also will tell you how to use regzbot to track regressions for your own code or the subsystem you maintain, to make sure none falls through the cracks unnoticed.


## More regzbot features relevant for both reporters and developers


### Important basics: How to interact with regzbot

There are four important things you need to know about regzbot before this document covers more details on its use:

1. To modify properties of a tracked regression, use regzbot commands in a mail you send as reply to the mail that regzbot considers the report. The easiest and safest way to achieve that: reply to the mail that made regzbot track the regression using `#regzbot introduced`. You don't need to reply directly to the report, you can use regzbot commands anywhere below in the hierarchy. For example, if the report is in message A, and B is a reply to A, then it's fine to use a regzbot command in a reply to B, as regzbot will know it's about the regression reported in A. For all that to work you need to use your mailers 'Reply' or 'Reply-to-all' functions, as it only then will set the _In-Reply-To_ and _References_ fields in the mail's header appropriately.

2. Regzbot is monitoring a few popular lists, but to make sure it sees mails with instruction always add regressions@lists.linux.dev to the recipients, as everything concerning regressions should CC that list anyway. It's up to you if you send the mail just there or use your mailers 'Reply-to-all' function to also sent it to other people and lists as well; most of the time it will be wise to keep them in the loop.

3. You can use multiple regzbot commands in one mail, but you must separate them from the rest of the mail with a blank line; also make sure the '#' before the "regzbot" is the line's first character.

4. If you have additional information relevant to the regression, just sent a reply to the report or a descendant mail. Regzbot will see it and list the five most recent activities on its web-interface, as those most of the time allow to quickly get the current status.


### Make regzbot track and existing report

You want to make regzbot track a regression you or someone else reported already without getting regzbot involved? Then simply reply directly to the mail with the report (if it's yours, you'll find it in your mailer's 'Sent' folder) with a line like this in the body:

`#regzbot ^introduced: v5.13..v5.14-rc1`

The caret (^) before the 'introduced' makes regzbot treat the parent mail (the one you reply to) as the report, hence you from now on can use regzbot commands is any replies that are decedents of the report.


### Update properties of a tracked regression


#### change the range or commit that introduced the regression

Simply write a reply to the report that uses the 'introduced' command again. Just like initially, you can use ranges, commits, or a mix of both. Here are a few examples:

`#regzbot introduced: v5.14-rc1..v5.14-rc2`

`#regzbot introduced: 1f2e3d4c5d`

`#regzbot introduced: v5.13..1f2e3d4c5d`

`#regzbot introduced: v5.13.8..v5.14-rc1`

`#regzbot introduced: v5.13.8.. v5.13.10`

`#regzbot introduced: next-20211006..next-20211008`

Note: to associate the regression to a tree, rezbot will look version tags and commits up in the Git trees for the Linux mainline, stable and next; if it can't find one, it might miss-file the regression, thus stick to the format used in the examples.

Reminder: Linux distributors often modify or enhance their Linux based kernels. These changes might be causing the problem you face. That's why the Linux kernel developers [mainly care about regressions in unmodified kernels, often called 'upstream kernel', 'official kernel', or 'vanilla'](https://www.kernel.org/doc/html/latest/admin-guide/reporting-issues.html#make-sure-you-re-using-the-upstream-linux-kernel). Regzbot thus focuses on these, too. It thus is only understand version tags used by the upstream Linux kernel developers and doesn't handle version numbers like `5.13.12-200.fc34.x86_64` (Fedora) or `5.4.0-12.15-generic` (Ubuntu). It's often a bad idea anyway to as reporting a regression where you used such a kernel.

Also remember to read the [Reporting Issues](https://www.kernel.org/doc/html/latest/admin-guide/reporting-issues.html) document carefully, as some ranges are possible to encounter, but might be too vague and thus not be handled appropriately by the developers. One such range would be `v5.13.8..v5.14.4`, as such a regression might be caused by a change in mainline between v5.13 and v5.14, or due to a modification performed between 5.14.3 and 5.14.4. Ideally you thus should rule out which of the two it is.


#### Update the report's title

Use this command, just replace `foo` with the new title:

`#regzbot title: foo`


### Point regzbot to other places with further details about a regression

#### Link and monitor a related discussion

Sometimes someone else will report a regression a second time without getting regzbot involved; or a discussion closely related to a tracked regression will happen in a different mailing list thread. In such cases it's a good idea to make regzbot monitor such threads, as regzbot then will show this activity in its web-interface – which helps others that look into the regression to determine its current status, as all relevant information then are at hand.

There are two ways to realize this. One is sending a reply to the report of the regression where you use a command like this:

`#regzbot monitor: https://lore.kernel.org/all/30th.anniversary.repost@klaava.Helsinki.FI/`

Alternatively, you can do it the other way around: by sending a mail in the second discussion that links to the report of the regression. Instead of a regzbot command you just need to add a link tag. Let's assume a regression tracked by regzbot was reported in https://lore.kernel.org/all/30th.anniversary.repost@klaava.Helsinki.FI/, then all you have to include in your mail to the second discussion is this:

`Link: https://lore.kernel.org/all/30th.anniversary.repost@klaava.Helsinki.FI/`

Consider putting something like *'# tell regzbot about this, as it's related to this tracked regression'* in the preceding line to let everyone known why you put that link tag there:

If you wonder why regzbot relies on using `Link:` here, there is a simple reason: it will ensure regzbot automatically monitors all mailing list threads with postings of patches that are supposed to fix the linked regression. Developers thus don't have to about regzbot when posting fixes for regressions, as long as they link to the report, which they are supposed to do anyway.


#### Point to a place with further details, like a bug-tracker

Most of Linux kernel development is done via mailing lists, but sometimes additional information is stored somewhere on the web, for example an issue tracker. In such cases consider telling regzbot about it, as it will then mention it prominently on its webpage:

`#regzbot link: https://bugzilla.kernel.org/show_bug.cgi?id=123456789`

Just like the monitor command this will help people that look into the regression to quickly gather all important facts.

### Resolve a regression

#### Mark a regression as fixed

As stated earlier, the preferred way to fix a regression tracked by regzbot is by linking to the regression's report using `Link:` in the commit message with the fix. Sometimes someone will forget to do that; other times a developer might have committed the fix already when someone reports a regression. In such cases tell regzbot about it like this, if its tracking the regression:

`#regzbot fixed-by: 1f2e3d4c5d`

You can use this as soon as the commit-id is stable, even if the fix hasn't reached the next or mainline tree's yet: regzbot will consider the regression as "to be fixed" then and marks it as fixed once the commits hits there tree where the regression occurred.


#### Mark a regression as a duplicate

Sometimes multiple people will report the same regressions without knowing about each other. When you notice that, check which of the two seems to be the one which is closer to the root of the problem or even a solution. Let's assume we have two reports tracked by regzbot we call A and B; A is older, but B is more informative, as crucial developers replied there and discussed a solution. Then it's a good idea to mark A a duplicate of B. To do that, send this rezbot command to the thread with the report A, where you replace `foo` with a link to the B in the [mailing list archives on lore.kernel.org](https://lore.kernel.org/all/):

`#regzbot dup-of: foo`

It thus might look like this:

`#regzbot dup-of: https://lore.kernel.org/all/30th.anniversary.repost@klaava.Helsinki.FI/`

Regzbot nevertheless will continue to track the report A.

#### Mark a regression as invalid

Your regression is not actually a regression? Don't worry, this can happen for various reasons. In that case just tell the world about it in a reply where you also let regzbot know like this:

`#regzbot invalid: nothing is broken, by hardware was faulty`

The explanation is optional.
