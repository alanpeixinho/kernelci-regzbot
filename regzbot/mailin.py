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


def adjust_repsrc(repsrc, msg):
    def get_email_adresses(recipients):
        return re.findall(r'[\w\.-]+@[\w\.-]+', recipients)

    adresses = []
    if 'To' in msg:
        # try/except needed here to handle mails without To:
        # https://lore.kernel.org/all/20210925074531.10446-1-tomm.merciai@gmail.com/raw
        # https://bugs.python.org/issue39100
        try:
            adresses.extend(get_email_adresses(msg['To']))
        except AttributeError:
            pass

    if 'CC' in msg:
        adresses.extend(get_email_adresses(msg['CC']))

    for adress in adresses:
        tmprepsrc = regzbot.ReportSource.get_by_identifier(adress)
        if tmprepsrc is None:
            continue
        elif repsrc is None or tmprepsrc.priority < repsrc.priority:
            repsrc = tmprepsrc

    return repsrc


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
    gmtime = email_get_gmtime(msg)
    msgid = email_get_msgid(msg)
    regzbotcmd = tagcmd + ": " + tagload

    # get the regression id, in case there is one already
    regressionb = regzbot.RegressionBasic.get_by_msgreferences(
        msg['References'])

    if not regressionb:
        if tagcmd == "introduced":
            regressionb = regzbot.RegressionBasic.introduced_create(
                repsrc.repsrcid, msgid, subject, tagload, gmtime)
        elif tagcmd == "^introduced" or tagcmd == "^^introduced":
            parent_msgid = email_get_msgid_parent(msg)

            if regzbot.is_running_citesting('offline'):
                if tagcmd == "^^introduced":
                    if msg['References'] is None:
                        urltoreport = repsrc.url(msgid)
                        regzbot.UnhandledEvent.add(
                            urltoreport, "^^introduced in a thread that has to references tag", gmtime=gmtime, subject=subject)
                        return False
                    for reference in msg['References'].split(" "):
                        tmpmsgid = email_get_msgid(reference)
                        if tmpmsgid != parent_msgid:
                            parent_msgid = tmpmsgid
                            break
                parent_repsrc = repsrc
                parent_gmtime = gmtime
                parent_subject = subject
            else:
                if tagcmd == "^^introduced":
                    parent_repsrc, parent_msg = regzbot.download_msg(parent_msgid)
                    parent_msgid = email_get_msgid_parent(parent_msg)
                parent_repsrc, parent_msg = regzbot.download_msg(parent_msgid)
                parent_gmtime = email_get_gmtime(parent_msg)
                parent_subject = email_get_subject(parent_msg)

            regressionb = regzbot.RegressionBasic.introduced_create(
                parent_repsrc.repsrcid, parent_msgid, parent_subject, tagload, parent_gmtime)
            # we need to add the entries for the parent manually
            actimon = regzbot.RegActivityMonitor.get_by_regid_n_entry(regressionb.regid, parent_msgid)
            regzbot.RegressionBasic.activity_event_monitored(
                parent_repsrc.repsrcid, parent_gmtime, parent_msgid, parent_subject, actimon)
            regzbot.RegHistory.event(
                regressionb.regid, parent_gmtime, parent_msgid, parent_subject, repsrcid=parent_repsrc.repsrcid,
                regzbotcmd="report: automatically added due to later %s" % tagcmd)
        else:
            urltoreport = repsrc.url(msgid)
            regzbot.UnhandledEvent.add(
                urltoreport, "regzbot tag in a thread not associated with a regression", gmtime=gmtime, subject=subject)
            return False

        # create entry in the reghistory now that we know the regid
        regzbot.RegHistory.event(
            regressionb.regid, gmtime, msgid, subject, repsrcid=repsrc.repsrcid, regzbotcmd=regzbotcmd)

        # we might need to recheck the thread, as it can contain msgs we have seen earlier and ignored earlier
        if tagcmd == "^introduced" or tagcmd == "^^introduced":
             if not regzbot.is_running_citesting('offline'):
                 regzbot.process_thread(parent_msgid)
    else:
        # create entry in the reghistory before processing the tag, otherwise loops will happen
        # if a monitor commands points to a mail higher up in the same thread
        regzbot.RegHistory.event(
            regressionb.regid, gmtime, msgid, subject, repsrcid=repsrc.repsrcid, regzbotcmd=regzbotcmd)

        if tagcmd == "dupof" or tagcmd == "dup-of":
            regressionb.dupof(tagload, gmtime, msgid, subject, repsrc.repsrcid)
        elif tagcmd == "fixed-by" or tagcmd == "fixedby:":
            commit_hexsha, commit_subject = spilttag_first_word(tagload)
            regressionb.fixedby(
                gmtime, commit_hexsha, commit_subject, repsrcid=repsrc.repsrcid, repentry=msgid)
        elif tagcmd == "invalid":
            regressionb.invalid(tagload, gmtime, msgid, repsrc.repsrcid)
        elif tagcmd == "introduced" or tagcmd == "^introduced"  or tagcmd == "^^introduced":
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


def email_get_gmtime(msg):
    return email.utils.mktime_tz(email.utils.parsedate_tz(msg['Date']))


def email_get_msgid(msg_or_msgid):
    if isinstance(msg_or_msgid, email.message.EmailMessage):
        msgid = msg_or_msgid['message-id']
    else:
        msgid = msg_or_msgid

    # this gets rid of everything after > (some email clients insert something there...)
    msgid = msgid.split(">", 1)
    return msgid[0].strip(' <>')


def email_get_msgid_parent(msg):
    if 'In-Reply-To' in msg:
        return email_get_msgid(msg['In-Reply-To'])
    else:
        logger.warning(
            "The tag in the email %s refers uses a ^ or a ^^ to refer to a (grant)parent, but the mail's header does not specify a 'In-Reply-To'; skipping reference.",
            msg['message-id'])
        return email_get_msgid(msg)


def email_get_subject(msg):
    subject = re.sub(' *\[ *(regression|patch) *\] *', '', msg['subject'], flags=re.IGNORECASE)
    return subject


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
        if tagline.startswith("introduced") or tagline.startswith("^introduced") or tagline.startswith("^^introduced"):
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

    logger.info("processing mail(%s): subject:'%s'; from:%s'; :",
                msgid, msg['Subject'], msg['From'])

    msg_simplest = msg.get_body(preferencelist=('plain'))
    if msg_simplest is None:
        logger.warning('Skipping msg %s, could not find any content', msgid)
        return

    # adjust the repsrc to the one with the lowest priority
    repsrc = adjust_repsrc(repsrc, msg)

    # process messages with tags:
    try:
        msgcontent = msg_simplest.get_content()
    except LookupError as err:
        logger.warning('Skipping msg %s due to error: "%s"', msgid, err)
        return

    # check for commands
    if regzbot.RegHistory.present(msgid):
        logger.debug("Ignoring tags and links in %s, as it was already processed", msgid)
    else:
        matches = list()
        # add two newlines here to make the regex catch msgs where they are missing
        for match in regzbot_tag_re.finditer(msgcontent + '\n\n'):
            matches.append('#regzbot ' + match.group(2))
        if len(matches) > 0:
            for match in email_process_tagmatches(matches):
                process_tag(repsrc, match, msg)

    # record this activity, if this thread is tracked
    def add_actimon(reference, msgid, gmtime, subject):
        for actimonid in regzbot.RegActivityEvent.get_actimonid_by_entry(reference):
            if actimonid and not regzbot.RegActivityEvent.present(actimonid, msgid):
                regzbot.RegressionBasic.activity_event_monitored(
                    repsrc.repsrcid, gmtime, msgid, subject, regzbot.RegActivityMonitor.get(actimonid))
    add_actimon(msgid, msgid, gmtime, subject)
    if msg['References'] is not None:
        for reference in msg['References'].split(" "):
            add_actimon(email_get_msgid(reference), msgid, gmtime, subject)

    if regzbot.RegHistory.present(msgid):
       # we are done here
       return

    # check this mail for links that point to tracked regressions
    for match in link_re.finditer(msgcontent):
        skip = False
        linktag = False
        url = False

        for grp in match.groups():
            if grp is None:
                continue
            elif grp.startswith("#regzb"):
                # avoid catching URLs we already dealt with
                skip = True
                break
            elif grp.startswith("Link:"):
                linktag = True
                continue
            elif grp.startswith("http"):
                url = grp
                break
        if skip:
            continue

        mailinglist, linked_msgid = process_link(url)
        if linked_msgid is None:
            continue

        regressionb = regzbot.RegressionBasic.get_by_entry(linked_msgid)
        if regressionb is None:
            continue

        # so this is related to a tracked regression; check if the thread is monitored or start monitoring it
        def thread_already_monitored():
            if msg['References'] is not None:
                for reference in msg['References'].split(" "):
                    actimongen = regzbot.RegActivityMonitor.getall_by_entry(
                        reference)
                    if actimongen is not None:
                        return actimongen
            return None
        actimongen = thread_already_monitored()

        if actimongen is None and linktag is True:
            # start monitoring this thread
            regressionb.monitoradd_direct(
                repsrc.repsrcid, gmtime, msgid, subject)
            regzbot.RegHistory.event(regressionb.regid, gmtime, msgid, subject, repsrcid=repsrc.repsrcid,
                                     regzbotcmd='monitor: automatically started monitoring "%s", as it referred to this this regression with a "Link:"'
                                     % subject)
        elif actimongen:
            # already monitored, nothing to do
            return
        else:
            # just add the event to the regression
            regzbot.RegressionBasic.activity_event_linked(
                repsrc.repsrcid, gmtime, msgid, subject, regid=regressionb.regid)
            regzbot.RegHistory.event(regressionb.regid, gmtime, msgid, subject,
                                     repsrcid=repsrc.repsrcid, regzbotcmd='linked: "%s" mentioned this regression' % subject)


def processmsg_file(repsrc, file):
    with open(file, "r") as f:
        msg = email.message_from_file(f, policy=policy.default)
        process_msg(repsrc, msg)
