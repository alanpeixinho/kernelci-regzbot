#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2022 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'


import base64
import bugzilla
import pprint
import datetime
import regzbot
import sys


from bugzilla import bug as pybugzilla_bug
from regzbot import ReportSourceRaw
from regzbot import PatchKind
from urllib.parse import urlparse


_BZCONNECTIONS = dict()
_BZUSERCACHE = dict()
logger = regzbot.logger


class BZActivity():
    def __init__(self, bzcon, bug_id, creator, creation_time, subject, *, comment_nr=None, patchkind=0, newstatus=None):
        self.bug_id = bug_id
        self.comment_nr = comment_nr
        self.creation_time = creation_time
        self.creator = creator
        self.newstatus = newstatus
        self.patchkind = patchkind
        self.subject = subject

        self.authorname, self.authormail = BZUser.author_details(bzcon, creator)
        self.gmtime = int(_bztime_to_datetime(creation_time).timestamp())


class BZAttachment():
    @staticmethod
    def get_attachment(bzcon, attachmentid, include_fields=None, exclude_fields=None):
        logger.debug('[bugzilla] getting attachment %s (include_fields=%s, exclude_fields=%s)',
                     attachmentid, include_fields, exclude_fields)
        return bzcon.get_attachments(None, attachmentid, include_fields, exclude_fields)


class BZBug(pybugzilla_bug.Bug):
    def __init__(self, bug):
        # cast bug object into this class by copying everything from the object.
        # side note: not sure if this is the most elegant way; would overriding __new__
        # or something else have been better solution in this case?
        for key, value in bug.__dict__.items():
            self.__dict__[key] = value

        # avoid unnessary queries and only set these when needed
        self.authorname = None
        self.authormail = None

        self.gmtime = int(_bztime_to_datetime(self.creation_time).timestamp())
        self.subject = self.summary

        parsedurl = urlparse(bug.bugzilla.url)
        self.netloc = parsedurl.netloc

    def _set_author_details(self):
        self.authorname, self.authormail = BZUser.author_details(self.bugzilla, self.creator)

    def get_authorname(self):
        if not self.authorname:
            self._set_author_details()
        return self.authorname

    def get_authormail(self):
        if not self.authormail:
            self._set_author_details()
        return self.authormail

    def _retrieve_comments(self, gmtime_from, gmtime_to):
        def _check_attachment(comment):
            if not comment['attachment_id']:
                return 0

            attachment_id_str = str(comment['attachment_id'])
            attachment_info = BZAttachment.get_attachment(
                self.bugzilla, comment['attachment_id'], exclude_fields='data')
            attachment_details = attachment_info['attachments'][attachment_id_str]
            if attachment_details['size'] > 25000 or \
                    attachment_details['content_type'] != 'text/plain':
                return 0

            attachment_data_raw = BZAttachment.get_attachment(
                self.bugzilla, comment['attachment_id'], include_fields='data')
            attachment_data_dec = base64.b64decode(
                attachment_data_raw['attachments'][attachment_id_str]['data']).decode('utf-8')

            return int(PatchKind.getby_content(attachment_data_dec))

        # reminder: comments will be processed in reverse order, which as of now doesn't matter anywhere in this file
        logger.debug('[bugzilla] retrieving comments for bug %s', self.bug_id)
        for comment in reversed(self.getcomments()):
            if gmtime_to or gmtime_from:
                comment_gmtime = int(_bztime_to_datetime(comment['creation_time']).timestamp())
                if gmtime_to and comment_gmtime > gmtime_to:
                    continue
                elif gmtime_from and comment_gmtime < gmtime_from:
                    break

            # check attachments added in parallel
            patchkind = _check_attachment(comment)

            if not comment['count']:
                yield BZActivity(self.bugzilla, comment['bug_id'], comment['creator'], comment['creation_time'],
                                 self.summary, newstatus='creation', patchkind=patchkind)
            else:
                yield BZActivity(self.bugzilla, comment['bug_id'], comment['creator'], comment['creation_time'],
                                 self.summary, comment_nr=comment['count'], patchkind=patchkind)

    def _retrieve_status_changes(self, gmtime_from, gmtime_to):
        status_changes = {}
        logger.debug('[bugzilla] retrieving history for bug %s', self.bug_id)
        history = self.get_history_raw()
        for historyevent in history['bugs'][0]['history']:
            for change in historyevent['changes']:
                if change['field_name'] == 'status':
                    change_gmtime = int(_bztime_to_datetime(historyevent['when']).timestamp())
                    if gmtime_to and change_gmtime > gmtime_to:
                        continue
                    elif gmtime_from and change_gmtime < gmtime_from:
                        break
                    status_changes[historyevent['when']] = BZActivity(
                        self.bugzilla, self.bug_id, historyevent['who'], historyevent['when'],
                        self.summary, newstatus=change['added'])
        return status_changes

    def get_activities(self, *, gmtime_from=None, gmtime_to=None):
        status_changes = self._retrieve_status_changes(
            gmtime_from, gmtime_to)
        for comment in self._retrieve_comments(gmtime_from, gmtime_to):
            # merge status changes done in parallel
            if comment.creation_time in status_changes and \
                    comment.creator == status_changes[comment.creation_time].creator:
                comment.newstatus = status_changes[comment.creation_time].newstatus
                del(status_changes[comment.creation_time])
            yield comment

        # process status changes performed without creating a comment in parallel
        for key in status_changes.keys():
            yield status_changes[key]

    def process_activities(self, actimon, repsrc, entry, *, gmtime_from=None):
        for activity in self.get_activities(gmtime_from=gmtime_from):
            subj_details = []
            if activity.comment_nr:
                subj_details.append('new comment(#%s)' % activity.comment_nr)
            if activity.newstatus:
                if activity.newstatus == 'creation':
                    subj_details.append("submission")
                else:
                    subj_details.append("status now '%s'" % activity.newstatus)
            subject = '%s bug %s: %s' % (self.netloc, activity.bug_id, '; '.join(subj_details))

            if activity.comment_nr:
                subentry = activity.comment_nr
            else:
                subentry = activity.gmtime

            if regzbot.RegActivityEvent.present_alt(repsrc.repsrcid, entry, subentry):
                logger.warning('Activity already present, not adding again: Bug %s, %s', self.bug_id, subject)
                continue

            regzbot.RegActivityEvent.event(
                activity.gmtime,
                entry,
                subject,
                activity.authorname,
                repsrc.repsrcid,
                actimonid=actimon.actimonid,
                patchkind=activity.patchkind,
                subentry=subentry)

    @classmethod
    def get(cls, bzcon, *, gmtime_from=None, bugstocheck=None):
        query = bzcon.build_query()
        query["include_fields"] = ["id", "summary", "creator", 'creation_time', 'status', 'resolution']
        if bugstocheck:
            try:
                _ = iter(bugstocheck)
            except TypeError:
                bugstocheck = (bugstocheck, )
            query['bug_id'] = bugstocheck
        if gmtime_from:
            datetimestr_from = datetime.datetime.fromtimestamp(
                gmtime_from, datetime.timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")
            query["chfieldfrom"] = datetimestr_from
            query["chfieldto"] = 'Now'

        logger.debug('[bugzilla] queryng for bugs (gmtime_from=%s, bugstocheck=%s)', gmtime_from, bugstocheck)
        for bzbug in bzcon.query(query):
            if bugstocheck and bzbug.id not in bugstocheck:
                continue
            yield cls(bzbug)


class BZUser():
    @staticmethod
    def getuser(bzcon, username):
        global _BZUSERCACHE
        if bzcon.url not in _BZUSERCACHE.keys():
            _BZUSERCACHE[bzcon.url] = {}
        if username not in _BZUSERCACHE[bzcon.url]:
            logger.debug('[bugzilla] retrieving details for user %s', username)
            _BZUSERCACHE[bzcon.url][username] = bzcon.getuser(username)
        return _BZUSERCACHE[bzcon.url][username]

    @classmethod
    def author_details(cls, bzcon, username):
        bzuser = cls.getuser(bzcon, username)
        if bzuser.real_name:
            real_name = bzuser.real_name
        else:
            real_name = bzuser.email.split('@', 1)[0]
        return real_name, bzuser.email


class BZServer():
    # will be set at runtime after all subclasses initialized:
    _subclasses = []

    # to be set by subclasses
    domainname = None

    @classmethod
    def connect(cls, api_key):
        global _BZCONNECTIONS
        if cls.domainname not in _BZCONNECTIONS.keys():
            logger.debug('bugzilla: connecting to %s', cls.domainname)
            _BZCONNECTIONS[cls.domainname] = bugzilla.Bugzilla(cls.domainname, force_rest=True, api_key=api_key)
        return _BZCONNECTIONS[cls.domainname]

    @classmethod
    def _check_bug(cls, bzcon, testvals):
        print("Checking bug")
        # checking just one bug
        entered = None
        for bzbug in BZBug.get(bzcon, bugstocheck=testvals['bug']['id']):
            entered = True
            if not cls._validate_bug:
                print("Bugcheck [%s] failed: Summary does not match" % bzbug.bug_id)
                pprint.pprint(vars(bzbug))
                return False

        if not entered:
            print("Bugcheck [%s] failed: Didn't get any bug")
            return False

        return True

    @classmethod
    def _check_activities(cls, bzcon, testvals):
        print("Checking activities")
        # checking for bugs with changes
        testbugs = [testvals['bug']['id'] - 1,
                    testvals['bug']['id'],
                    testvals['bug']['id'] + 1]
        gmtime_from = testvals['bug']['gmtime_from']
        gmtime_to = testvals['bug']['gmtime_to']

        activities = []
        for bzbug in BZBug.get(bzcon, gmtime_from=gmtime_from, bugstocheck=testbugs):
            for activity in BZBug.get_activities(bzbug, gmtime_from=gmtime_from, gmtime_to=gmtime_to):
                activities.append(activity)
        return cls._validate_activities(activities)

    @classmethod
    def _check_user(cls, bzcon, testvals):
        print("Checking user")
        user = BZUser.getuser(bzcon, testvals['user']['id'])
        # do it again to check the cached version
        user = BZUser.getuser(bzcon, testvals['user']['id'])
        if not cls._validate_user(user):
            print("Usercheck failed; values for the user found:")
            pprint.pprint(user)
            return False
        return True

    @staticmethod
    def _check_command(bzcon, command, testvals):
        if command == 'attachment':
            pprint.pprint(BZAttachment.get_attachment(bzcon, testvals['attachment']['id']))
        elif command == 'bugzilla':
            pprint.pprint(vars(bzcon))
        elif command == 'user':
            pprint.pprint(vars(BZUser.getuser(bzcon, testvals['user']['id'])))
        elif command in ('bug', 'activities', 'history', 'shortcut'):
            for bzbug in BZBug.get(bzcon, bugstocheck=testvals['bug']['id']):
                pass
            if command == 'bug':
                pprint.pprint(vars(bzbug))
            elif command == 'activities':
                pprint.pprint(bzbug.getcomments())
            elif command == 'history':
                pprint.pprint(bzbug.get_history_raw())
            elif command == 'shortcut':
                # nothing currently
                pass
        else:
            print('Unkown command: %s', command)
            sys.exit(1)

    @classmethod
    def get_bug(cls, url):
        subclass, bzid = cls.get_bug_id(url)
        if not subclass:
            return None

        logger.debug('[bugzilla] getting bug %s from %s', bzid, subclass.domainname)
        return subclass._get_bug(bzid)

    @classmethod
    def get_bug_id(cls, url):
        if not cls._subclasses:
            cls._set_subclasses()
        for subclass in cls._subclasses:
            bzid = subclass._get_ticketid(url)
            if bzid:
                return subclass, bzid
        return None, None

    @classmethod
    def _check_updates(cls, gmtime):
        raise NotImplementedError

    @classmethod
    def updateall(cls):
        if not cls._subclasses:
            cls._set_subclasses()

        for subclass in cls._subclasses:
            gmtime_now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
            gmtime_from = regzbot.RegzbotState.get('%s_lastchktime' % subclass.domainname)
            if gmtime_from:
                subclass._check_updates(gmtime_from)
            regzbot.RegzbotState.set('%s_lastchktime' % subclass.domainname, gmtime_now)

    @classmethod
    def _set_subclasses(cls):
        for subclass in cls.__subclasses__():
            cls._subclasses.append(subclass)

    @classmethod
    def _testbugzilla(cls, apikey, command):
        bzcon = cls.connect(apikey)
        if command:
            cls._check_command(bzcon, command, cls.testvals)
        else:
            if not cls._check_user(bzcon, cls.testvals) or not \
                    cls._check_bug(bzcon, cls.testvals) or not \
                    cls._check_activities(bzcon, cls.testvals):
                print('Aborting.')
                sys.exit(1)
            print('All tests succeeded')


class BZServer_bko(BZServer):
    domainname = "bugzilla.kernel.org"
    testvals = {
        'attachment': {
            'id': 300404,
        },
        'bug': {
            'id': 214667,
            'gmtime_from': 1643740374,
            'gmtime_to': 1645121177,
        },
        'user': {
            'id': 'regressions@leemhuis.info',
        }
    }

    @classmethod
    def _check_updates(cls, gmtime_from):
        repsrc = ReportSourceRaw.get_by_serverurl('https://%s' % cls.domainname)
        if not repsrc:
            logger.warning('No repsrc entry found for %s, not checking for updates', cls.domainname)
            return

        bzcon = cls.connect(regzbot.CONFIGURATION[cls.domainname]['apikey'])

        for bug in BZBug.get(bzcon, gmtime_from=gmtime_from):
            actimon = regzbot.RegActivityMonitor.get_by_repsrc_n_entry(repsrc, bug.bug_id)
            if not actimon:
                continue
            bug.process_activities(actimon, repsrc, bug.bug_id, gmtime_from=gmtime_from)

    @classmethod
    def _get_ticketid(cls, url):
        parsed = urlparse(url)
        if not parsed.netloc == 'bugzilla.kernel.org':
            return False
        if not parsed.path == '/show_bug.cgi':
            return False
        if not parsed.query.startswith('id='):
            return False
        else:
            return int(parsed.query.replace('id=', ''))
        return None

    @classmethod
    def _get_bug(cls, bzid):
        if not bzid:
            return None

        if cls.domainname not in regzbot.CONFIGURATION.sections():
            logger.warn('No configuration found for %s' % cls.domainname)
            sys.exit(1)
        if 'apikey' not in regzbot.CONFIGURATION[cls.domainname].keys():
            logger.debug('Aborting, no apikey found for %s' % cls.domainname)
            sys.exit(1)

        bzcon = cls.connect(regzbot.CONFIGURATION[cls.domainname]['apikey'])
        return BZBug.get(bzcon, bugstocheck=bzid)

    @classmethod
    def _validate_activities(cls, activities):
        if len(activities) != 8:
            print("Activitycheck failed: expected 8 results, but got %s" % len(activities))
            for counter, activity in enumerate(activities):
                print('%s:' % counter)
                pprint.pprint(vars(activity))
            return False
        elif activities[4].patchkind != 7 or activities[4].comment_nr != 35 or activities[4].authorname != 'Hans de Goede':
            print("Activitycheck failed: comment 0 doesn't look liked expected:")
            pprint.pprint(vars(activities[4]))
            return False
        elif activities[7].newstatus != 'CLOSED' or activities[7].comment_nr:
            print("Activitycheck failed: comment 7 doesn't look liked expected:")
            pprint.pprint(vars(activities[7]))
            return False
        return True

    @classmethod
    def _validate_bug(cls, bzbug):
        if (bzbug.bug_id == cls.testvals['bug']['id'] and bzbug.summary ==
                'Touchpad is not working anymore after suspend to RAM since kernel 5.14 - AMD Ryzen 5 4600H)'):
            return True

    @classmethod
    def _validate_user(cls, user):
        if (user.real_name == "The Linux kernel's regression tracker (Thorsten Leemhuis)" and
                user.email == 'regressions@leemhuis.info'):
            return True


class BzOrigin(regzbot.RbCmdOrigin):
    def __init__(self, repsrc, entry, bug):
        self._bug = bug
        super().__init__(
            repsrc,
            entry,
            self._bug.gmtime,
            self._bug.get_authorname(),
            self._bug.get_authormail(),
            self._bug.subject,
            None)

    @classmethod
    def get(cls, *, url=None):
        repsrc, entry = ReportSourceRaw.get_by_url(url)

        bug = None
        for bug in BZServer.get_bug(url):
            break
        return cls(repsrc, entry, bug)

    def process_comments(self):
        actimon = regzbot.RegActivityMonitor.get_by_repsrc_n_entry(self.repsrc, self.entry)
        self._bug.process_activities(actimon, self.repsrc, self.entry)


def _bztime_to_datetime(bztime):
    return datetime.datetime.fromisoformat(bztime[:-1] + '+00:00')


def get_bug_id(url):
    _, bug_id = BZServer.get_bug_id(url)
    return bug_id


def _test():
    # no need for argparse here, it's just for development anyway
    command = None
    if len(sys.argv) == 4:
        command = sys.argv[3]
    elif len(sys.argv) < 3:
        print("call '$0 bzid apikey <command>'")
        sys.exit(1)

    if len(sys.argv[2]) != 40:
        print('Apikey looks malformed')
        sys.exit(1)
    apikey = sys.argv[2]

    # go
    if sys.argv[1] == 'bko':
        BZServer_bko._testbugzilla(apikey, command)
    else:
        print('Unsupported')
        sys.exit(1)


if __name__ == "__main__":
    _test()
