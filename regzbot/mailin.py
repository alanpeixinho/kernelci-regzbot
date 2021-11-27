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
    r'^(\#regzb |\#regzbot |Link: |.*)?(\n)?((http://|https://)\S*)', re.MULTILINE | re.IGNORECASE)

def adjust_repsrc(repsrc, msg):
    def get_email_adresses(recipients):
        return re.findall(r'[\w\.-]+@[\w\.-]+', recipients)

    adresses = []
    if 'To' in msg:
        try:
            adresses.extend(get_email_adresses(msg['To']))
        except AttributeError as err:
            # handle mails without To:, for example
            #      https://lore.kernel.org/all/20211005053239.3E8DEC4338F@smtp.codeaurora.org/raw
            #     https://lore.kernel.org/all/20210925074531.10446-1-tomm.merciai@gmail.com/raw
            # related: https://bugs.python.org/issue39100
            logger.warning('Ignoring "To" in %s due to and exception: "AttributeError: %s"', email_get_msgid(msg), err)
        except ValueError as err:
            # Workaround for https://lore.kernel.org/all/1634261360.fed2opbgxw.astroid@bobo.none/raw
            #     -> "ValueError: invalid arguments; address parts cannot contain CR or LF"
            logger.warning('Ignoring "To" in %s due to and exception: "ValueError: %s"',  email_get_msgid(msg), err)

    if 'CC' in msg:
        # sane workarund as above, triggered by
        try:
            adresses.extend(get_email_adresses(msg['CC']))
        except AttributeError as err:
            # see above
            logger.warning('Ignoring "CC" in %s due to and exception: "AttributeError: %s"', email_get_msgid(msg), err)
        except ValueError as err:
            # see above
            logger.warning('Ignoring "CC" in %s due to and exception: "ValueError: %s"',  email_get_msgid(msg), err)

    for adress in adresses:
        tmprepsrc = regzbot.ReportSource.get_by_identifier(adress)
        if tmprepsrc is None:
            continue
        elif repsrc is None or tmprepsrc.priority < repsrc.priority:
            repsrc = tmprepsrc

    return repsrc


def find_regression(msg):
        msgids_tocheck = [email_get_msgid(msg)]
        if 'References' in msg:
            for reference in msg['References'].split():
                msgids_tocheck.append(email_get_msgid(reference))
        if 'In-Reply-To' in msg and not msg['In-Reply-To'] in msg['References']:
            msgids_tocheck.append(email_get_msgid(msg['In-Reply-To']))

        for msgid_tocheck in msgids_tocheck:
             regressionb = regzbot.RegressionBasic.get_by_regactivity(msgid_tocheck)
             if regressionb:
                 return regressionb

        return None


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
    if len(tag) > 2:
       tagload = tag[2]
    else:
       tagload = ''

    # tagcmds work with and without colon at the end
    if tagcmd[-1] == ':':
        tagcmd = tagcmd[:-1]

    # get all the other data we need
    subject = email_get_subject(msg)
    author = email_get_from(msg)
    gmtime = email_get_gmtime(msg)
    msgid = email_get_msgid(msg)
    if tagload:
        regzbotcmd = tagcmd + ": " + tagload
    else:
        regzbotcmd = tagcmd

    # get the regression id, in case there is one already
    regressionb = find_regression(msg)

    if not regressionb:
        if tagcmd == "introduced":
            regressionb = regzbot.RegressionBasic.introduced_create(
                repsrc.repsrcid, msgid, email_get_cleansubject(msg), author, tagload, gmtime)
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
                parent_author = author
                parent_cleansubject = subject
            else:
                if tagcmd == "^^introduced":
                    parent_repsrc, parent_msg = regzbot.download_msg(parent_msgid)
                    parent_msgid = email_get_msgid_parent(parent_msg)
                parent_repsrc, parent_msg = regzbot.download_msg(parent_msgid)
                parent_gmtime = email_get_gmtime(parent_msg)
                parent_subject = email_get_subject(parent_msg)
                parent_author = email_get_from(parent_msg)
                parent_cleansubject = email_get_cleansubject(parent_msg)

            regressionb = regzbot.RegressionBasic.introduced_create(
                parent_repsrc.repsrcid, parent_msgid, parent_cleansubject, parent_author, tagload, parent_gmtime)
            # we need to add the entries for the parent manually
            actimon = regzbot.RegActivityMonitor.get_by_regid_n_entry(regressionb.regid, parent_msgid)
            regzbot.RegressionBasic.activity_event_monitored(
                parent_repsrc.repsrcid, parent_gmtime, parent_msgid, parent_subject, parent_author, actimon)
            regzbot.RegHistory.event(
                regressionb.regid, parent_gmtime, parent_msgid, parent_subject, parent_author, repsrcid=parent_repsrc.repsrcid,
                regzbotcmd="note: report, added by regzbot due to later %s" % tagcmd)
        else:
            urltoreport = repsrc.url(msgid)
            regzbot.UnhandledEvent.add(
                urltoreport, "regzbot tag in a thread not associated with a regression", gmtime=gmtime, subject=subject)
            return False

        # create entry in the reghistory now that we know the regid
        regzbot.RegHistory.event(
            regressionb.regid, gmtime, msgid, subject, author, repsrcid=repsrc.repsrcid, regzbotcmd=regzbotcmd)

        # we might need to recheck the thread, as it can contain msgs we have seen earlier and ignored earlier
        if tagcmd == "^introduced" or tagcmd == "^^introduced":
             if not regzbot.is_running_citesting('offline'):
                 regzbot.process_thread(parent_msgid, repsrc.repsrcid)
    else:
        # create entry in the reghistory before processing the tag, otherwise loops will happen
        # if a monitor commands points to a mail higher up in the same thread
        regzbot.RegHistory.event(
            regressionb.regid, gmtime, msgid, subject, author, repsrcid=repsrc.repsrcid, regzbotcmd=regzbotcmd)

        if tagcmd == "dupof" or tagcmd == "dup-of":
            regressionb.dupof(tagload, gmtime, msgid, subject, author, repsrc.repsrcid)
        elif tagcmd == "fixed-by" or tagcmd == "fixedby:":
            commit_hexsha, commit_subject = spilttag_first_word(tagload)
            regressionb.fixedby(
                gmtime, commit_hexsha, commit_subject, repsrcid=repsrc.repsrcid, repentry=msgid)
        elif tagcmd == "invalid":
            regressionb.invalid(tagload, gmtime, msgid, repsrc.repsrcid)
        elif tagcmd == "introduced" or tagcmd == "^introduced"  or tagcmd == "^^introduced":
            regressionb.introduced_update(tagload)
        elif tagcmd == "link":
            regressionb.linkadd(tagload, gmtime, author)
        elif tagcmd == "unlink":
            regressionb.linkremove(tagload)
        elif tagcmd == "monitor":
            regressionb.monitoradd(tagload, gmtime, repsrc, msg)
        elif tagcmd == "unmonitor":
            regressionb.monitorremove(tagload, gmtime, repsrc, msg)
        elif tagcmd == "poke":
            # nothing to do, the entry in the history is enough
            pass
        elif tagcmd == "subject" or tagcmd == "title":
            regressionb.title(tagload)
        else:
            reportsource = regzbot.ReportSource.get_by_id(repsrc.repsrcid)
            urltoreport = reportsource.url(msgid)
            regzbot.UnhandledEvent.add(
                urltoreport, "unkown regzbot command: %s" % tagcmd, gmtime=gmtime, subject=subject)
            return

def email_get_from(msg):
    stripped = re.sub(" <.*>", "", msg['From'])
    stripped = stripped.lstrip('\'"').rstrip('\'"')
    return stripped

def email_get_gmtime(msg):
    return email.utils.mktime_tz(email.utils.parsedate_tz(msg['Date']))


def email_get_msgid(msg_or_msgid):
    if isinstance(msg_or_msgid, email.message.EmailMessage) or isinstance(msg_or_msgid, email.message.EmailMessage):
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
    return msg['subject']


def email_get_cleansubject(msg):
    return re.sub(' *\[ *(regression|patch) *\] *', '', email_get_subject(msg), flags=re.IGNORECASE)



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

    # do not process messages a second time
    if regzbot.RegHistory.present(msgid):
          logger.debug('[mailin] skipping mail %s, as we already processed it', msgid)
          return

    subject = email_get_subject(msg)
    author = email_get_from(msg)
    gmtime = email.utils.mktime_tz(email.utils.parsedate_tz(msg['Date']))
    ignoreactivity = False

    logger.info("[mailin] processing mail %s: subject:'%s'; from:%s'; :",
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
                if 'backmonitor' in match:
                     # this is deal with later
                     continue
                elif 'ignore-activity' in match or \
                       'activity-ignore' in match or \
                       'ignoreact' in match:
                     ignoreactivity = True
                     continue
                elif 'poke' in match:
                     ignoreactivity = True
                process_tag(repsrc, match, msg)

    # record this activity, if this thread is tracked
    contains_patch = regzbot.PatchKind.getby_content(msgcontent, subject=subject)

    def add_actimon(reference, msgid, gmtime, subject):
        if ignoreactivity:
            return
        actimonid = regzbot.RegActivityEvent.get_actimonid_by_entry(reference)
        if actimonid and not regzbot.RegActivityEvent.present(msgid, actimonid=actimonid):
            regzbot.RegressionBasic.activity_event_monitored(
                repsrc.repsrcid, gmtime, msgid, subject, author, regzbot.RegActivityMonitor.get(actimonid), contains_patch=contains_patch)
    add_actimon(msgid, msgid, gmtime, subject)
    if msg['In-Reply-To'] is not None:
        add_actimon(email_get_msgid(msg['In-Reply-To']), msgid, gmtime, subject)
    if msg['References'] is not None:
        for reference in msg['References'].split(" "):
            add_actimon(email_get_msgid(reference), msgid, gmtime, subject)

    if regzbot.RegHistory.present(msgid):
       # we are done here
       return

    # check this mail for links that point to tracked regressions
    for match in link_re.finditer(re.sub(r'^>.*\n?', '', msgcontent, flags=re.MULTILINE)):
        linktag = False
        backmonitor = False
        url = False

        if match.group(0).startswith('Link'):
            if re.search(r'\#regzb.*\^backmonitor', msgcontent):
                # backmonitor implies ignore-activity, so skip this
                continue
            linktag = True
            url = match.group(0).split()[1]
        elif match.group(0).startswith('#regz'):
            if '^backmonitor' in match.group(0):
                backmonitor = True
                url = match.group(0).split()[2]
            else:
                # avoid catching URLs we already dealt with
               continue
        else:
            if 'Link:' in match.group(0):
                # Link should be at the beginning of the line; it's not, so it's
                # likely quoted or somethng and can be ignored
                continue
            for section in match.groups():
                if section and section.startswith('http'):
                    url = section
                    break

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
                    actimon = regzbot.RegActivityMonitor.get_by_entry(
                        reference)
                    if actimon is not None:
                        return actimon
            return None
        actimon = thread_already_monitored()

        if actimon:
            # already monitored, nothing to do
            return
        elif backmonitor is True :
                # start monitoring this thread
                if regzbot.is_running_citesting('offline'):
                    parent_msgid = email_get_msgid_parent(msg)
                    parent_repsrc = repsrc
                    parent_gmtime = gmtime
                    parent_subject = 'Parent of %s' % subject
                    parent_author = author
                    parent_contains_patch = contains_patch
                else:
                    parent_msgid = email_get_msgid_parent(msg)
                    parent_repsrc, parent_msg = regzbot.download_msg(parent_msgid)
                    parent_gmtime = email_get_gmtime(parent_msg)
                    parent_subject = email_get_subject(parent_msg)
                    parent_author = email_get_from(parent_msg)
                    parent_contains_patch = regzbot.PatchKind.getby_content(msg.get_body(preferencelist=('plain')).get_content(), subject=parent_subject)

                regressionb.monitoradd_direct(
                    parent_repsrc.repsrcid, parent_gmtime, parent_msgid, parent_subject, parent_author, parent_contains_patch)
                regzbot.RegHistory.event(regressionb.regid, gmtime, msgid, author, subject, repsrcid=repsrc.repsrcid,
                                         regzbotcmd="monitor: started monitoring parent mail '%s' due to '#regzbot ^backmonitor'"
                                         % parent_subject)

                # no activityentry for this, backmonitor works like activity-ignore
                # recheck the thread, to record the parent msg and all others we might have seen but ignored earlier
                if regzbot.is_running_citesting('offline'):
                    actimon = regzbot.RegActivityMonitor.get_by_regid_n_entry(regressionb.regid, parent_msgid)
                    regzbot.RegressionBasic.activity_event_monitored(
                        parent_repsrc.repsrcid, parent_gmtime, parent_msgid, parent_subject, parent_author, actimon, contains_patch=contains_patch)
                else:
                    process_thread(parent_msgid, parent_repsrc.repsrcid)
        elif linktag is True :
                regressionb.monitoradd_direct(
                    repsrc.repsrcid, gmtime, msgid, subject, author, contains_patch)
                regzbot.RegHistory.event(regressionb.regid, gmtime, msgid, subject, author, repsrcid=repsrc.repsrcid,
                                         regzbotcmd="monitor: 'Link:' to this regression in `%s`"
                                         % subject)
                # check thread, maybe it got added later via a recheck of an msgid
                process_thread(msgid, repsrcid=repsrc.repsrcid)
        elif url:
            # just add the event to the regression
            regzbot.RegressionBasic.activity_event_linked(
                repsrc.repsrcid, gmtime, msgid, subject, author, regid=regressionb.regid)
            regzbot.RegHistory.event(regressionb.regid, gmtime, msgid, subject, author,
                                     repsrcid=repsrc.repsrcid, regzbotcmd='linked: "%s" mentioned this regression' % subject)


    # now check if this mail contains a Fixed: tag that mentioned a commit that is known to cause a regression
    open_regressions = {}
    for match in re.finditer('^(Fixes: )([0-9,a-e]{12})', msgcontent, re.MULTILINE):
        # only fill this now, as we only need it if we found a Fixes: tag
        if len(open_regressions) == 0:
            for regression in regzbot.RegressionBasic.get_all(only_unsolved=True):
                if not '..' in regression.introduced:
                    open_regressions[regression.regid] = regression.introduced[0:12]

        if not match.group(2) in open_regressions.values():
            continue
        for regid in open_regressions.keys():
            if not open_regressions[regid] == match.group(2):
                continue
            if regzbot.RegHistory.present(msgid, regid=regid):
                # no need to add a second entry for mails that already were noticed as related,
                # for example if this msg that already has a Link: to this regression
                continue

            # no activity, only a history entry, as it might be about different bug in the same commit
            regzbot.RegHistory.event(regid, gmtime, msgid, subject, author,
                                     repsrcid=repsrc.repsrcid, regzbotcmd='note: "%s" contains a \'Fixes:\' tag for the culprit of this regression' % subject)


# processes messages from a thread that already got checked:
# finds the msgid in question, processes it and its replies,
# while ignoring the other messages; some of this complexity
# is needed to recheck nested threads like
# https://lore.kernel.org/regressions/ea5fe78c-9a36-726f-afe2-1bdc25c5eba7@leemhuis.info/
# https://lore.kernel.org/regressions/be354029-6062-b8e5-50a4-70df088f93d2@leemhuis.info/
def process_thread(msgid_interested, repsrcid):
    import regzbot.lore as lore

    def get_actimonid(references):
        for reference in references:
            reference_msgid = email_get_msgid(reference)
            actimonid_ref = regzbot.RegActivityEvent.get_actimonid_by_entry(reference_msgid)
            if actimonid_ref:
                return actimonid_ref

    actimonid = None

    for msg in lore.download_thread(msgid_interested, repsrcid):
        msgid_current = email_get_msgid(msg['message-id'])

        if not actimonid:
            # ignore all messages until we hit the one we care about
            if not msgid_current == msgid_interested:
                continue
            actimonid = False
        elif msg['References'] and get_actimonid(msg['References'].split(" ")) != actimonid:
                continue

        repsrc = adjust_repsrc(None, msg)
        process_msg(repsrc, msg)

        # we just found msgid_interested and now need to set this:
        if actimonid == False:
           actimonid = regzbot.RegActivityEvent.get_actimonid_by_entry(
                        msgid_interested)

def processmsg_file(repsrc, file):
    with open(file, "r") as f:
        msg = email.message_from_file(f, policy=policy.default)
        process_msg(repsrc, msg)
