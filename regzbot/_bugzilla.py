#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2022 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'


import base64
import bugzilla
import pprint
import datetime
import sys


from bugzilla import bug as pybugzilla_bug
from regzbot import PatchKind


_BZUSERCACHE = dict()


class BZActivity():
    def __init__(self, bzcon, bug_id, creator, creation_time, subject, *, comment_nr=None, patchkind=0, newstatus=None):
        self.bug_id = bug_id
        self.comment_nr = comment_nr
        self.creation_time = creation_time
        self.creator = creator
        self.newstatus = newstatus
        self.patchkind = patchkind
        self.subject = subject

        self.autorname, self.authormail = BZUser.author_details(bzcon, creator)


class BZAttachment():
    @staticmethod
    def get_attachment(bzcon, attachmentid):
        return bzcon.get_attachments(None, attachmentid)


class BZBug(pybugzilla_bug.Bug):
    def __init__(self, bug):
        # cast bug object into this class by copying everything from the object.
        # side note: not sure if this is the most elegant way; would overriding __new__
        # or something else have been better solution in this case?
        for key, value in bug.__dict__.items():
            self.__dict__[key] = value

        bzuser = BZUser.getuser(self.bugzilla, bug.creator)
        self.autorname = bzuser.real_name
        self.authormail = bzuser.email

    def _retrieve_comments(self, gmtime_from, gmtime_to):
        # reminder: comments will be processed in reverse order, which as of now doesn't matter anywhere in this file
        for comment in reversed(self.getcomments()):
            if gmtime_to or gmtime_from:
                comment_gmtime = int(bztime_to_datetime(comment['creation_time']).timestamp())
                if gmtime_to and comment_gmtime > gmtime_to:
                    continue
                elif gmtime_from and comment_gmtime < gmtime_from:
                    break

            # check if attachments was added in parallel
            patchkind = None
            if comment['attachment_id']:
                attachment_raw = BZAttachment.get_attachment(self.bugzilla, comment['attachment_id'])
                attachment_data = base64.b64decode(attachment_raw['attachments'][str(
                    comment['attachment_id'])]['data']).decode('utf-8')
                patchkind = int(PatchKind.getby_content(attachment_data))

            yield BZActivity(self.bugzilla, comment['bug_id'], comment['creator'], comment['creation_time'],
                             self.summary, comment_nr=comment['count'], patchkind=patchkind)

    def _retrieve_status_changes(self, gmtime_from, gmtime_to):
        status_changes = {}
        history = self.get_history_raw()
        for historyevent in history['bugs'][0]['history']:
            for change in historyevent['changes']:
                if change['field_name'] == 'status':
                    change_gmtime = int(bztime_to_datetime(historyevent['when']).timestamp())
                    if gmtime_to and change_gmtime > gmtime_to:
                        continue
                    elif gmtime_from and change_gmtime < gmtime_from:
                        break
                    status_changes[historyevent['when']] = BZActivity(
                        self.bugzilla, self.bug_id, historyevent['who'], historyevent['when'], self.summary, newstatus=change['added'])
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

    @classmethod
    def get(cls, bzcon, *, gmtime_from=None, bugstocheck=None):
        query = bzcon.build_query()
        query["include_fields"] = ["id", "summary", "creator", 'status', 'resolution']
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

        for bzbug in bzcon.query(query):
            if bzbug.id in bugstocheck:
                yield cls(bzbug)


class BZUser():
    @staticmethod
    def getuser(bzcon, username):
        global _BZUSERCACHE
        if bzcon.url not in _BZUSERCACHE.keys():
            _BZUSERCACHE[bzcon.url] = {}
        if username not in _BZUSERCACHE[bzcon.url]:
            _BZUSERCACHE[bzcon.url][username] = bzcon.getuser(username)
        return _BZUSERCACHE[bzcon.url][username]

    @classmethod
    def author_details(cls, bzcon, username):
        bzuser = cls.getuser(bzcon, username)
        return bzuser.real_name, bzuser.email


class _BZServer():
    domainname = None

    @classmethod
    def connect(cls, api_key):
        return bugzilla.Bugzilla(
            cls.domainname, force_rest=True, api_key=api_key)

    @classmethod
    def _check_bug(cls, bzcon, testvals):
        # checking just one bug
        for bzbug in BZBug.get(bzcon, bugstocheck=testvals['bug']['id']):
            if not cls._validate_bug:
                print("Bugcheck [%s] failed: Summary does not match" % bzbug.bug_id)
                pprint.pprint(vars(bzbug))
                return False

    def _check_activities(cls, bzcon, testvals):
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
            for attachment in BZAttachment.get_attachment(testvals['attachment']['id']):
                pprint.pprint(attachment)
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
    def _testbugzilla(cls, apikey, command):
        bzcon = cls.connect(apikey)
        if command:
            cls._check_command(bzcon, command, cls.testvals)
        else:
            if not cls._check_user(bzcon, cls.testvals) or not \
                    cls._check_bug(bzcon, cls.testvals) or not \
                    cls._check_activities(bzcon, cls.testvals):
                sys.exit(1)
            print('All tests succeeded')


class BZServer_bko(_BZServer):
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
    def _validate_activities(cls, activities):
        if len(activities) != 8:
            print("Activitycheck failed: expected 8 results, but got %s" % len(activities))
            for counter, activity in enumerate(activities):
                print('%s:' % counter)
                pprint.pprint(vars(activity))
            return False
        elif activities[4].patchkind != 7 or activities[4].comment_nr != 35 or activities[4].autorname != 'Hans de Goede':
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
        if (bzbug.bug_id == cls.testvals['bug']['id'] and
                bzbug.summary == 'Touchpad is not working anymore after suspend to RAM since kernel 5.14 - AMD Ryzen 5 4600H)'):
            return True

    @classmethod
    def _validate_user(cls, user):
        if (user.real_name == "The Linux kernel's regression tracker (Thorsten Leemhuis)" and
                user.email == 'regressions@leemhuis.info'):
            return True


def bztime_to_datetime(bztime):
    return datetime.datetime.fromisoformat(bztime[:-1] + '+00:00')


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
