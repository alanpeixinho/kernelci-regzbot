#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'
#
# FIXME:
# - path to testdir is hardcoded

import argparse
import email
import re
import regzbot
import regzbot._rbcmd as rbcmd

from email import policy
from urllib.parse import urlparse

logger = regzbot.logger

regzbot_tag_re = re.compile(
    r'^#(regzb|regzbot) (.*?)\n\s*\n', re.MULTILINE | re.IGNORECASE | re.DOTALL)
regzbot_tag2_re = re.compile(
    r'^#(regzb|regzbot) (.*)$', re.MULTILINE | re.IGNORECASE)
link_re = re.compile(
    r'^(\#regzb |\#regzbot |Link: |.*)?(\n)?((http://|https://)\S*)', re.MULTILINE | re.IGNORECASE)


class MailinRbCmdOrgHelper:
    def __init__(self, msg):
        self.msg = msg

    @staticmethod
    def _modify_msgid_orgin(origin, msgid):
        return regzbot.RbCmdOrigin(
            origin.repsrc,
            msgid,
            origin.gmtime,
            origin.authorname,
            origin.authormail,
            origin.subject,
            origin.helper)

    def thread_parent(self, origin):
        parent_msgid = email_get_msgid_parent(self.msg)
        if regzbot.is_running_citesting('offline'):
            return self._modify_msgid_orgin(origin, parent_msgid)
        return msg_metadata(parent_msgid)

    def thread_root(self, origin):
        if regzbot.is_running_citesting('offline'):
            references = email_get_references(self.msg)
            return self._modify_msgid_orgin(origin, references[0])
        raise NotImplementedError

    def process_thread(self, report):
         if not regzbot.is_running_citesting('offline'):
             regzbot.process_thread(report.entry, report.repsrcid)

def msg_metadata(msgid):
    repsrc, msg = regzbot.download_msg(regzbot.urlencode(msgid))
    gmtime = email_get_gmtime(msg)
    subject = email_get_cleansubject(msg)
    authorname, authormail = email_get_from(msg)
    helper = MailinRbCmdOrgHelper(msg)
    cmd_origin = regzbot.RbCmdOrigin(repsrc, msgid, gmtime, authorname, authormail, subject, helper)
    return cmd_origin

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


def find_regressions(msg):
        msgids_tocheck = [email_get_msgid(msg)]
        if 'References' in msg:
            for reference in msg['References'].split():
                msgids_tocheck.append(email_get_msgid(reference))
        if 'In-Reply-To' in msg and 'References' in msg and not msg['In-Reply-To'] in msg['References']:
            msgids_tocheck.append(email_get_msgid(msg['In-Reply-To']))

        for msgid_tocheck in msgids_tocheck:
            for regression in regzbot.RegressionBasic.getall_by_entry(msgid_tocheck):
                yield regression


def find_actimon(msg):
        msgids_tocheck = [email_get_msgid(msg)]
        if 'References' in msg:
            for reference in msg['References'].split():
                msgids_tocheck.append(email_get_msgid(reference))
        if 'In-Reply-To' in msg and 'References' in msg and not msg['In-Reply-To'] in msg['References']:
            msgids_tocheck.append(email_get_msgid(msg['In-Reply-To']))

        for msgid_tocheck in msgids_tocheck:
             actimon = regzbot.RegActivityMonitor.get_by_regactivity(msgid_tocheck)
             if actimon:
                 return actimon

        return None


def toberemoved_parse_introduced_args(args):
    def is_uri(uri):
        try:
            result = urlparse(uri)
            return all([result.scheme, result.netloc])
        except ValueError:
            pass
        return False

    def parse(args):

        for arg in args:
            if not sha1sum and re.search('^[0-9a-fA-F]{8,40}$', arg):
                sha1sum = arg
            elif not reporturl and (arg == '^' or arg == '~' or is_uri(arg)):
                reporturl = arg

            if sha1sum and reporturl:
                break

        return sha1sum, reporturl

    parser = argparse.ArgumentParser()
    parser.add_argument('parms', nargs='+', type=str)
    args = parser.parse_args(args.split())

    reporturl = False
    if len(args.parms) > 1 and (args.parms[1] == '^' or args.parms[1] == '~' or is_uri(args.parms[1])):
        reporturl = args.parms[1]

    return args.parms[0], reporturl


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
    authorname, authormail = email_get_from(msg)
    gmtime = email_get_gmtime(msg)
    msgid = email_get_msgid(msg)
    if tagload:
        regzbotcmd = tagcmd + ": " + tagload
    else:
        regzbotcmd = tagcmd

    primary_regression = None
    for count, regressionb in enumerate(find_regressions(msg)):
        if count == 0:
            primary_regression = regressionb
        elif count == 1:
            # some commands should not affect duplicates
            dupes_disallowed = ['link', 'monitor', 'dupof', 'dup-of', 'dup', 'duplicate']
            if tagcmd in dupes_disallowed:
                continue
        else:
            # we only care about the primary regression (returned first) and
            # the topmost regression (returned second)
            break

        # create entry in the reghistory before processing the tag, otherwise loops will happen
        # if a monitor commands points to a mail higher up in the same thread
        regzbot.RegHistory.event(
            regressionb.regid, gmtime, msgid, subject, authorname, repsrcid=repsrc.repsrcid, regzbotcmd=regzbotcmd)

        if tagcmd == "backburner" or tagcmd == "back-burner":
            regressionb.backburner_add(repsrc.repsrcid, msgid, gmtime, authorname, tagload)
        elif tagcmd == "unbackburn" or tagcmd == "unbackburner":
            regressionb.backburner_remove()
        elif tagcmd == "dup" or tagcmd == "duplicate":
            regressionb.duplicate(tagload, gmtime, msgid, subject, authorname, repsrc.repsrcid)
        elif tagcmd == "dupof" or tagcmd == "dup-of":
            regressionb.dupof(tagload, gmtime, msgid, subject, authorname, repsrc.repsrcid)
        elif tagcmd == "fix" or tagcmd == "fixed-by" or tagcmd == "fixedby:":
            commit_hexsha, commit_subject = spilttag_first_word(tagload)
            regressionb.fixedby(
                gmtime, commit_hexsha, commit_subject, repsrcid=repsrc.repsrcid, repentry=msgid)
        elif tagcmd == "from":
            regressionb.update_author(msgid, tagload)
        elif tagcmd == "invalid":
            regressionb.invalid(tagload, gmtime, msgid, repsrc.repsrcid)
        elif tagcmd == "introduced" or tagcmd == "^introduced"  or tagcmd == "^^introduced":
            regressionb.introduced_update(tagload)
        elif tagcmd == "link":
            regressionb.linkadd(tagload, gmtime, authorname)
        elif tagcmd == "unlink":
            regressionb.linkremove(tagload)
        elif tagcmd == "monitor":
            regressionb.monitoradd(tagload, gmtime, repsrc, msg)
        elif tagcmd == "unmonitor":
            regressionb.monitorremove(tagload, gmtime, repsrc, msg)
        elif tagcmd == "poke":
            # nothing to do here, the entry in the history is enough
            pass
        elif tagcmd == "subject" or tagcmd == "title":
            regressionb.title(tagload)
        else:
            reportsource = regzbot.ReportSource.get_by_id(repsrc.repsrcid)
            urltoreport = reportsource.url(msgid)
            regzbot.UnhandledEvent.add(
                urltoreport, "unkown regzbot command: %s" % tagcmd, gmtime=gmtime, subject=subject)
            return

    if not primary_regression:
        if tagcmd == "^introduced":
            tagcmd = 'introduced'
            tagload = tagload + ' ^'

        if tagcmd == "introduced":
            origin_helper = MailinRbCmdOrgHelper(msg)
            cmd_origin = regzbot.RbCmdOrigin(repsrc, msgid, gmtime, authorname, authormail, email_get_cleansubject(msg), origin_helper)
            cmd_stack = rbcmd.RbCmdStack(cmd_origin, None)
            cmd_stack.add('introduced', tagload)
            regressionb = cmd_stack.process()
        else:
            urltoreport = repsrc.url(msgid)
            regzbot.UnhandledEvent.add(
                urltoreport, "regzbot tag in a thread not associated with a regression", gmtime=gmtime, subject=subject)
            return False


def email_get_from(msg):
    from email.utils import parseaddr
    name, email = parseaddr(msg['From'])

    if len(name) == 0:
        name = email

    return name, email

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

def email_get_references(msg):
    if 'References' not in msg:
        return ""
    return msg['References'].translate({ ord(c): None for c in "<>" }).split()

def email_get_subject(msg):
    # mails without a subject send greetings
    # https://lore.kernel.org/linux-usb/trinity-09ddec50-a8ca-4663-ba91-4331ab43c9e4-1639982794116@3c-app-gmx-bs07/raw
    subject = msg['subject']
    if subject:
        return subject
    return ''


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
    if subject.startswith(regzbot.REPORT_SUBJECT_PREFIX):
          logger.debug("[mailin] skipping mail %s, as it's a report we send", msgid)
          return

    authorname, authormail = email_get_from(msg)
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
                elif 'poke' in match or \
                       'backburner' in match or \
                       'back-burner' in match:
                     ignoreactivity = True
                elif '#forregzbot' in subject or \
                       '#justforregzbot' in subject:
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
                repsrc.repsrcid, gmtime, msgid, subject, authorname, regzbot.RegActivityMonitor.get(actimonid), contains_patch=contains_patch)
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
            url = match.group(0).split()
            if len(url) == 1:
                # malformated, like https://lore.kernel.org/lkml/20211221071634.25980-1-yu.tu@amlogic.com/
                continue
            url = url[1]
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
        if not url:
            continue

        # FIXME: this is ugly and needs to be cleaned up
        regressionb = None
        if 'lore.kernel.org' in url or 'lkml.kernel.org' in url:
            mailinglist, linked_msgid = process_link(url)
            if linked_msgid is None:
                continue

            for regressionb in regzbot.RegressionBasic.get_by_entry(linked_msgid):
                break
        elif 'bugzilla.kernel.org' in url:
            if url.startswith("https://"):
                tmpstring = url.removeprefix("https://")
            elif url.startswith("http://"):
                tmpstring = url.removeprefix("http://")

            bugid = tmpstring.removeprefix('bugzilla.kernel.org/show_bug.cgi?id=')
            if bugid.isnumeric():
                repsrc = regzbot.ReportSource.get_by_name('bugzilla.kernel.org')
                regressionb = regzbot.RegressionBasic.get_by_repsrc_n_entry(repsrc, bugid)
            else:
                logger.debug(
                    "Tried to get bugid from %s, but failed", url)

        if regressionb is None:
            continue

        actimon = find_actimon(msg)

        if actimon and actimon.regid == regressionb.regid:
            # already monitored, nothing to do
            return
        elif backmonitor is True :
                # start monitoring this thread
                if regzbot.is_running_citesting('offline'):
                    parent_msgid = email_get_msgid_parent(msg)
                    parent_repsrc = repsrc
                    parent_gmtime = gmtime
                    parent_subject = 'Parent of %s' % subject
                    parent_authorname = authorname
                    parent_authormail = authormail
                    parent_contains_patch = contains_patch
                else:
                    parent_msgid = email_get_msgid_parent(msg)
                    parent_repsrc, parent_msg = regzbot.download_msg(regzbot.urlencode(parent_msgid))
                    parent_gmtime = email_get_gmtime(parent_msg)
                    parent_subject = email_get_subject(parent_msg)
                    parent_authorname, parent_authormail = email_get_from(parent_msg)
                    parent_contains_patch = regzbot.PatchKind.getby_content(msg.get_body(preferencelist=('plain')).get_content(), subject=parent_subject)

                regressionb.monitoradd_direct(
                    parent_repsrc.repsrcid, parent_gmtime, parent_msgid, parent_subject, parent_authorname, parent_contains_patch)
                regzbot.RegHistory.event(regressionb.regid, gmtime, msgid, authorname, subject, repsrcid=repsrc.repsrcid,
                                         regzbotcmd="monitor: started monitoring parent mail '%s' due to '#regzbot ^backmonitor'"
                                         % parent_subject)

                # no activityentry for this, backmonitor works like activity-ignore
                # recheck the thread, to record the parent msg and all others we might have seen but ignored earlier
                if regzbot.is_running_citesting('offline'):
                    actimon = regzbot.RegActivityMonitor.get_by_regid_n_entry(regressionb.regid, parent_msgid)
                    regzbot.RegressionBasic.activity_event_monitored(
                        parent_repsrc.repsrcid, parent_gmtime, parent_msgid, parent_subject, parent_authorname, actimon, contains_patch=contains_patch)
                else:
                    process_thread(parent_msgid, parent_repsrc.repsrcid)
        elif linktag is True :
                regressionb.monitoradd_direct(
                    repsrc.repsrcid, gmtime, msgid, subject, authorname, contains_patch)
                regzbot.RegHistory.event(regressionb.regid, gmtime, msgid, subject, authorname, repsrcid=repsrc.repsrcid,
                                         regzbotcmd="monitor: 'Link:' to this regression in `%s`"
                                         % subject)
                # check thread, maybe it got added later via a recheck of an msgid
                if not regzbot.is_running_citesting('offline'):
                    process_thread(msgid, repsrcid=repsrc.repsrcid)
        elif url:
            # just add the event to the regression
            regzbot.RegressionBasic.activity_event_linked(
                repsrc.repsrcid, gmtime, msgid, subject, authorname, regid=regressionb.regid)
            regzbot.RegHistory.event(regressionb.regid, gmtime, msgid, subject, authorname,
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
            regzbot.RegHistory.event(regid, gmtime, msgid, subject, authorname,
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
        if not msg['message-id']:
            logger.warning("[mailin.process_thread] skipping mail %s, no message-id found", msg['subject'])
            continue

        msgid_current = email_get_msgid(msg['message-id'])

        if not actimonid:
            # ignore all messages until we hit the one we care about
            
            if not msgid_current == msgid_interested:
                logger.debug("[mailin.process_thread] skipping mail %s, waiting for the one we care about", msgid_current)
                continue
            actimonid = False

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
