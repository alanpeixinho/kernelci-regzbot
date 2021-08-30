#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'
#
# FIXME:
# - path to testdir is hardcoded

import email
import re
import regzbot

from email import policy

logger = regzbot.logger

regzbot_tag_re = re.compile(
    r'^#(regzb|regzbot) (.*?)\n\s*\n', re.MULTILINE | re.IGNORECASE | re.DOTALL)
regzbot_tag2_re = re.compile(
    r'^#(regzb|regzbot) (.*)$', re.MULTILINE | re.IGNORECASE)
link_re = re.compile(
    r'^(.)*?(\#regzb.*|Link:\s*)?((http://|https://)(.*))(\s)*', re.MULTILINE | re.IGNORECASE)


def process_tag(repsrc, tag, msg):
    def spilttag_first_word(tagload):
        tagload = tagload.split(maxsplit=1)
        firstpart = tagload[0]
        if len(tagload) > 1:
            secondpart = tagload[1]
        else:
            secondpart = None
        return firstpart, secondpart

    # split #regzbot (which gets ignored), tagcmd and it payload
    tag = tag.split(' ', 2)
    tagcmd = tag[1].lower()
    tagload = tag[2]

    # tagcmds work with and without colon at the end
    if tagcmd[-1] == ':':
        tagcmd = tagcmd[:-1]

    # get all the other data we need
    subject = email_get_subject(msg)
    gmtime = email.utils.mktime_tz(email.utils.parsedate_tz(msg['Date']))

    msgid = email_get_msgid(msg)
    if tagcmd == "^introduced":
        # the report is about the parent
        msgid_parent = email_get_msgid_parent(msg)
    else:
        True

    # get the regression id, in case there is one already
    regressionb = regzbot.RegressionBasic.get_by_msgreferences(
        msg['References'])
    if not regressionb:
        if tagcmd == "introduced":
            regressionb = regzbot.RegressionBasic.introduced_create(
                repsrc.repsrcid, msgid, subject, tagload)
        elif tagcmd == "^introduced":
            regressionb = regzbot.RegressionBasic.introduced_create(
                repsrc.repsrcid, msgid_parent, subject, tagload)
        else:
            urltoreport = repsrc.url(msgid)
            regzbot.UnhandledEvent.add(
                urltoreport, "regzbot tag in a thread not associated with a regression", gmtime=gmtime, subject=subject)
            return False
    else:
        if tagcmd == "dupof" or tagcmd == "dup-of":
            regressionb.dupof(tagload, gmtime, msgid, subject, repsrc.repsrcid)
        elif tagcmd == "fixed-by" or tagcmd == "fixedby:":
            commit_hexsha, commit_subject = spilttag_first_word(tagload)
            regressionb.fixedby(
                gmtime, commit_hexsha, commit_subject, repsrcid=repsrc.repsrcid, repentry=msgid)
        elif tagcmd == "invalid":
            regressionb.invalid(tagload, gmtime, msgid, repsrc.repsrcid)
        elif tagcmd == "introduced" or tagcmd == "^introduced":
            regressionb.introduced_update(tagload)
        elif tagcmd == "link":
            regressionb.linkadd(tagload, gmtime)
        elif tagcmd == "unlink":
            regressionb.linkremove(tagload)
        elif tagcmd == "monitor":
            regressionb.monitoradd(tagload, gmtime, repsrc, msg)
        elif tagcmd == "unmonitor":
            regressionb.monitorremove(tagload, gmtime, repsrc, msg)
        elif tagcmd == "subject" or tagcmd == "title":
            regressionb.title(tagload)
        else:
            reportsource = regzbot.ReportSource.get_by_id(repsrc.repsrcid)
            urltoreport = reportsource.url(msgid)
            regzbot.UnhandledEvent.add(
                urltoreport, "unkown regzbot command: %s" % tagcmd, gmtime=gmtime, subject=subject)
            return

    # create entry in the reghistory
    regzbot.RegHistory.event(
        regressionb.regid, gmtime, msgid, subject, repsrcid=repsrc.repsrcid, regzbotcmd=tagcmd + ": " + tagload)


def email_get_msgid(msg):
    # strip the < and > at the start and the end
    return msg['message-id'][1:-1]


def email_get_msgid_parent(msg):
    if 'In-Reply-To' in msg:
        return msg['In-Reply-To'][1:-1]
    else:
        logger.info(
            "The tag in the email %s refers uses a ^ to refer to its parent, but the mail's header does not specify a 'In-Reply-To'; skipping reference.",
            msg['message-id'])
        return msg['message-id'][1:-1]


def email_get_subject(msg, remove_retag=False):
    if (remove_retag
            and msg['subject'].startswith('Re: ')
            or msg['subject'].startswith('RE: ')):
        return msg['subject'][4:]
    else:
        return msg['subject']


def email_process_tagmatches(matches):
    parsed = list()

    # slit tag commands in case somebody used multiple without seperating them with a blank line
    for match in matches:
        # remove newlines
        partly_parsed = ''
        for line in match.splitlines():
            newmatch = regzbot_tag2_re.match(line)
            if newmatch and partly_parsed:
                # line starts with our tag: send the previous tag on its way and clear tmp vairable
                parsed.append(partly_parsed)
                partly_parsed = line
            elif partly_parsed:
                # line didn't start with our tag, so add it to the previous line
                partly_parsed = partly_parsed + ' ' + line
            else:
                partly_parsed = line
        # we are through with this match, so finish the line
        parsed.append(partly_parsed)

    # move introduced tag to the front in case there is one
    for tagline in parsed:
        if tagline.startswith("introduced") or tagline.startswith("^introduced"):
            parsed.remove(tagline)
            parsed.insert(0, tagline)
            break

    return parsed


def process_link(link):
    mailinglist = linked_msgid = None

    processed_link = link.split('/')
    if len(processed_link) < 5 or processed_link[4] == '':
        # ignore
        pass
    elif processed_link[2] == 'lore.kernel.org':
        # ignore the lore redirector here
        if not processed_link[3] == "r":
            mailinglist = processed_link[3]
        linked_msgid = processed_link[4]
    elif processed_link[2] == 'lkml.kernel.org':
        # this subdomain always redirects to lkml
        mailinglist = 'lkml'
        linked_msgid = processed_link[4]

    return mailinglist, linked_msgid


def process_msg(repsrc, msg):
    msgid = email_get_msgid(msg)
    subject = email_get_subject(msg)
    gmtime = email.utils.mktime_tz(email.utils.parsedate_tz(msg['Date']))

    msg_simplest = msg.get_body(preferencelist=('plain'))
    if msg_simplest is None:
        logger.warning('Skipping msg %s, could not find any content', msgid)
        return

    # process messages with tags:
    try:
        msgcontent = msg_simplest.get_content()
    except LookupError as err:
        logger.warning('Skipping msg %s due to error: "%s"', msgid, err)
        return

    matches = list()
    for match in regzbot_tag_re.finditer(msgcontent):
        matches.append('#regzbot ' + match.group(2))
    if len(matches) > 0:
        if repsrc.acceptcommands:
            for match in email_process_tagmatches(matches):
                process_tag(repsrc, match, msg)
        else:
            regzbot.UnhandledEvent.add(
                repsrc.url(msgid), "regzbot cmd on a mailing list where they are not allowed to be used", gmtime=gmtime, subject=subject)

    # record this activety, if this thread is tracked
    def add_actimon(reference, msgid, gmtime, subject):
        for actimon in regzbot.RegActivityMonitor.getall_by_repsrcid_n_entry(repsrc.repsrcid, reference):
            regzbot.RegressionBasic.activity_event_monitored(
                repsrc.repsrcid, gmtime, msgid, subject, actimon)
    add_actimon(msgid, msgid, gmtime, subject)
    if msg['References'] is not None:
        for reference in msg['References'].split(" "):
            add_actimon(reference[1:-1], msgid, gmtime, subject)

    # check this mail for links that point to tracked regressions
    for match in link_re.finditer(msgcontent):
        regbottag = False
        linktag = False
        url = False
        for grp in match.groups():
            if grp is None:
                continue
            elif grp.startswith("#regzb"):
                regbottag = True
                break
            elif grp.startswith("Link:"):
                linktag = True
                continue
            elif grp.startswith("http"):
                url = grp
                break

        # avoid catching URLs already dealt with
        if regbottag:
            continue

        mailinglist, linked_msgid = process_link(url)
        if linked_msgid is None:
            continue

        regressionb = regzbot.RegressionBasic.get_by_entry(linked_msgid)
        if regressionb is None:
            continue

        # check if the thread is already monitored
        def thread_already_monitored():
            if msg['References'] is not None:
                for reference in msg['References'].split(" "):
                    actimonid = regzbot.RegActivityMonitor.get_by_msgid(
                        reference)
                    if actimonid is not None:
                        return actimonid
            return None
        actimonid = thread_already_monitored()

        if actimonid is None and linktag is True:
            # start monitoring this thread
            regressionb.monitoradd_direct(
                repsrc.repsrcid, gmtime, msgid, subject)
            regzbot.RegHistory.event(regressionb.regid, gmtime, msgid, subject, repsrcid=repsrc.repsrcid,
                                     regzbotcmd='monitor: automatically started monitoring "%s", as it referred to this this regression with a "Link:"'
                                     % subject)
        elif actimonid is not None:
            # already monitored, so make sure this get tracked
            regzbot.RegressionBasic.activity_event_monitored(
                repsrc.repsrcid, gmtime, msgid, subject, actimonid=actimonid)
        else:
            # just add the event to the regression
            regzbot.RegressionBasic.activity_event_linked(
                repsrc.repsrcid, gmtime, msgid, subject, regid=regressionb.regid)
            regzbot.RegHistory.event(regressionb.regid, gmtime, msgid, subject,
                                     repsrcid=repsrc.repsrcid, regzbotcmd='linked: "%s" mentioned this regression' % subject)


def processmsg_nntp(repsrc, article):
    msg = email.message_from_bytes(b'\n'.join(
        article.lines), policy=policy.default)
    logger.info("processing mail: subject:'%s'; from:%s'; article %s on %s",
                msg['Subject'], msg['From'],  article.number, repsrc.serverurl)
    process_msg(repsrc, msg)


def processmsg_file(repsrc, file):
    with open(file, "r") as f:
        msg = email.message_from_file(f, policy=policy.default)
        process_msg(repsrc, msg)
