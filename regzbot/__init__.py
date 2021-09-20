# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import datetime
import logging
import os
import pathlib
import re
import sqlite3
import sys

import git
import yattag


__VERSION__ = '0.0.1-dev'
__CITESTING__ = False
DBCON = None
REPOSDIR = None
LATEST_VERSIONS = None
WEBPAGEDIR = None

logger = logging.getLogger('regzbot')


class RecordProcessedMsgids():
    def __init__(self, msgid, gmtime):
        self.msgid = msgid
        self.gmtime = gmtime

    @staticmethod
    def db_create(dbcursor, version):
        logger.debug('Initializing new dbtable "msgidrecord"')
        dbcursor.execute('''
            INSERT INTO meta
            VALUES(?, ?)''', ('msgidrecord', version, ))
        dbcursor.execute('''
            CREATE TABLE msgidrecord (
                msgid       STRING   NOT NULL PRIMARY KEY,
                gmtime      INTEGER  NOT NULL
            )''')

    @staticmethod
    def add(msgid, gmtime, dbcursor=None):
        if dbcursor is None:
            dbcursor = DBCON.cursor()

        dbcursor.execute('''INSERT INTO msgidrecord
                            (msgid, gmtime)
                            VALUES (?, ?)''',
                         (msgid, gmtime))
        logger.debug(
            '[db msgidrecord] insert (msgid:%s, gmtime:%s)' % (msgid, gmtime))

    @staticmethod
    def check_presence(msgid, gmtime=None):
        dbcursor = DBCON.cursor()

        dbresult = dbcursor.execute(
            'SELECT * FROM msgidrecord WHERE msgid=(?)', (msgid, )).fetchone()
        if dbresult:
            return True
        elif gmtime:
            # in this case add the msgid
            RecordProcessedMsgids.add(msgid, gmtime, dbcursor)

        return False


class GitBranch():
    def __init__(self, gitbranchid, gittreeid, name, lastchked):
        self.gitbranchid = gitbranchid
        self.gittreeid = gittreeid
        self.name = name
        self.lookupname = 'origin/%s' % name
        self.lastchked = lastchked

    @staticmethod
    def db_create(dbcursor, version):
        logger.debug('Initializing new dbtable "gitbranches"')
        dbcursor.execute('''
            INSERT INTO meta
                VALUES(?, ?)''', ('gitbranches', version, ))
        dbcursor.execute('''
            CREATE TABLE gitbranches (
                gitbranchid INTEGER  NOT NULL PRIMARY KEY,
                gittreeid   INTEGER  NOT NULL,
                name        STRING   NOT NULL,
                lastchked   STRING
            )''')

    @staticmethod
    def add(gittree, branchname, lastchked):
        branchname = branchname.removeprefix('origin/')
        dbcursor = DBCON.cursor()
        dbcursor.execute('''INSERT INTO gitbranches
            (gittreeid, name, lastchked)
            VALUES (?, ?, ?)''',
                         (gittree.gittreeid, branchname, lastchked))
        logger.debug('[db gitbranches] insert (gitbranchid:%s, gittreeid:%s, branchname:%s, lastchked:%s)' % (
            dbcursor.lastrowid, gittree.gittreeid, branchname, lastchked))
        return dbcursor.lastrowid

    def commit_exists(self, identifier, repo=None):
        # this makes it possible to reuse the repo obj
        if repo is None:
            gittree = GitTree.get_by_id(self.gittreeid)
            repo = gittree.repo()

        try:
            # reminder: just relying on the exception is not enough here, as it will *not* fire
            # if the commit exists in the tree, but in another branch :-/
            result = repo.git.branch(
                self.lookupname, '--all', '--contains', identifier)
            if result:
                return True
        except git.exc.GitCommandError as err:
            output = err.args[2].decode("utf-8")
            ignored = {'error: malformed object name',
                       'error: no such commit'}
            if not any(x in output for x in ignored):
                logger.critical("GitCommandError: {0}".format(err))
                logger.critical(err.args)
        return False

    @staticmethod
    def get_by_id(gitbranchid):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM gitbranches WHERE gitbranchid=(?)', (gitbranchid, )).fetchone()
        if dbresult:
            return GitBranch(*dbresult)
        return None

    @staticmethod
    def get_by_treeid_branchname(gittreeid, name):
        # avoids programming pitfalls:
        if name.startswith('origin/'):
            name = name.removeprefix('origin/')

        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM gitbranches WHERE gittreeid=(?) AND name=(?)', (gittreeid, name)).fetchone()
        if dbresult:
            return GitBranch(*dbresult)

        return None

    @staticmethod
    def getall(order='gittreeid gitbranchid'):
        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM gitbranches ORDER BY ?', order):
            yield GitBranch(*dbresult)

    @staticmethod
    def getall_by_gittreeid(gittreeid):
        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM gitbranches WHERE gittreeid=(?)', (gittreeid,)):
            yield GitBranch(*dbresult)

    def merge_date(self, hexsha, repo=None):
        def get_date(repo, hexsha):
            return repo.commit(hexsha).committed_date

        if repo is None:
            gittree = GitTree.get_by_id(self.gittreeid)
            repo = gittree.repo()

        try:
            # idea from https://stackoverflow.com/a/20615706
            ancestry_path = repo.git.rev_list(
                '--ancestry-path', "%s..HEAD" % hexsha).splitlines()
            first_parent = repo.git.rev_list(
                '--first-parent', "%s..HEAD" % hexsha).splitlines()

            # committed directly
            if len(ancestry_path) == 0:
                return get_date(repo, hexsha)

            # find the last result in ancestry_path that's also in first_parent
            ancestry_path.reverse()
            for commit in ancestry_path:
                if commit in first_parent:
                    return get_date(repo, commit)
        except git.exc.GitCommandError as err:
            errmsg = err.args[2].decode("utf-8")
            logger.critical("GitCommandError: {0}".format(errmsg))
            logger.critical(err.args)
            return None

    def url(self, entry, gittree=None):
        if gittree is None:
            gittree = GitTree.get_by_id(self.gittreeid)
        return '%s?h=%s&id=%s' % (gittree.weburl, self.name, entry)

    @staticmethod
    def url_by_id(gitbranchid, entry):
        gitbranch = GitBranch.get_by_id(gitbranchid)
        return gitbranch.url(entry)

    def set_lastchked(self, lastchked):
        dbcursor = DBCON.cursor()
        dbcursor.execute('''UPDATE gitbranches SET lastchked = (?) WHERE gitbranchid=(?)''',
                         (lastchked, self.gitbranchid))


class GitTree():
    def __init__(self, gittreeid, name, server, kind, weburl, branchregex):
        self.gittreeid = gittreeid
        self.name = name
        self.server = server
        self.kind = kind
        self.weburl = weburl
        self.branchregex = branchregex
        self.__repo = None  # only initialize it once needed

    @staticmethod
    def db_create(dbcursor, version):
        logger.debug('Initializing new dbtable "gittrees"')
        dbcursor.execute('''
            INSERT INTO meta
                VALUES(?, ?)''', ('gittrees', version, ))
        dbcursor.execute('''
            CREATE TABLE gittrees (
                gittreeid   INTEGER  NOT NULL PRIMARY KEY,
                name        STRING   NOT NULL,
                server      STRING   NOT NULL,
                kind        STRING   NOT NULL,
                weburl      STRING   NOT NULL,
                branchregex STRING   NOT NULL
            )''')

    @staticmethod
    def add(name, server, kind, weburl, branchregex):
        dbcursor = DBCON.cursor()
        dbcursor.execute('''INSERT INTO gittrees
            (name, server, kind, weburl, branchregex)
            VALUES (?, ?, ?, ?, ?)''',
                         (name, server, kind, weburl, branchregex))
        logger.debug('[db gittrees] insert (gittreeid:%s, name:%s, server:%s, kind:%s, weburl:%s, branchregex:%s)' % (
            dbcursor.lastrowid, name, server, kind, weburl, branchregex))
        return dbcursor.lastrowid

    def commit(self, hexsha):
        repo = self.repo()
        return repo.commit(hexsha)

    def commit_describe(self, identifier):
        repo = self.repo()
        try:
            # reminder: just relying on the exception is not enough here, as it will not fire
            # if the commit exists in the tree, but in another branch :-/
            result = repo.git.describe('--contains', identifier)
            if result:
                result = result.split('~')[0]
                return result, True
        except git.exc.GitCommandError as err:
            output = err.args[2].decode("utf-8")
            if 'fatal: cannot describe' in output:
                # commit present, but unabled to describe, as since then no commit was tagged
                return None, True
            ignored = ('error: malformed object name')
            if not any(x in output for x in ignored):
                logger.critical("GitCommandError: {0}".format(err))
                logger.critical(err.args)
        return None, None

    @staticmethod
    # commitdesc can be a tag or a hexsha
    def commit_find(commitdesc):
        for gittree in GitTree.getall():
            repo = gittree.repo()
            for gitbranch in GitBranch.getall_by_gittreeid(gittree.gittreeid):
                if gitbranch.commit_exists(commitdesc, repo):
                    return gittree, gitbranch
        return None, None

    @staticmethod
    def commit_summary(hexsha):
        for gittree in GitTree.getall():
            repo = gittree.repo()
            try:
                commit = repo.commit(hexsha)
                if commit:
                    return commit.summary
            except Exception:
                pass

    @staticmethod
    def check_latest_versions(repo=None):
        if repo is None:
            gittree = GitTree.get_by_name('mainline')
            if not gittree:
                logger.critical(
                    "Unable to determine current and next version, as it's determined from a gittree with the name 'mainline', which could not be found.")
                return False
            repo = gittree.repo()

        global LATEST_VERSIONS
        LATEST_VERSIONS = {
            'indevelopment': None,
            'latest': None,
            'previous': None,
        }

        re_expectedtags = re.compile(
            r'^(v[0-9]+\.[0-9]+)(-rc[0-9]+)*(-dontuse)*$')
        for line in repo.git.tag('--sort=-creatordate').splitlines():
            match = re_expectedtags.search(line)
            if match is None:
                logger.critical(
                    "aborting: encountered a tag that doesn't follow the expected pattern ('%s')" % line)
                sys.exit(1)

            if match.group(2):
                if LATEST_VERSIONS['indevelopment'] is None:
                    LATEST_VERSIONS['indevelopment'] = match.group(1)
                continue
            elif match.group(1) and match.group(2) is None:
                # we found our first proper (aka non-rc) tag
                if LATEST_VERSIONS['indevelopment'] is None:
                    # we haven't seen a rc tag yet, so we are in the middle of a merge window and don't known yet what the current version will be called
                    LATEST_VERSIONS['indevelopment'] = False
                    # fallthrough
                if LATEST_VERSIONS['latest'] is None:
                    LATEST_VERSIONS['latest'] = match.group(1)
                    continue
                else:
                    LATEST_VERSIONS['previous'] = match.group(1)
                    return

            logger.critical(
                "Unable to determine current and next version, could not find expected tags")
            logger.debug(
                "'next' is now '%s', 'latest' is now '%s', and 'previous' is niw '%s'",
                LATEST_VERSIONS['indevelopment'], LATEST_VERSIONS['latest'], LATEST_VERSIONS['previous'])
            return False

    @staticmethod
    def getall():
        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM gittrees'):
            yield GitTree(*dbresult)

    @staticmethod
    def get_by_id(gittreeid):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM gittrees WHERE gittreeid=(?)', (gittreeid, )).fetchone()
        if dbresult:
            return GitTree(*dbresult)
        return None

    @staticmethod
    def get_by_name(treename):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM gittrees WHERE name=(?)', (treename, )).fetchone()
        if dbresult:
            return GitTree(*dbresult)
        return None

    def repo(self):
        # hidden even within the class, to only initialize it when actually needed
        if self.__repo is None:
            self.__repo = git.Repo.init(os.path.join(REPOSDIR, self.name))
        return self.__repo

    def update(self):
        def process_link(url, foundspot):
            _, _, msgid = parse_link(url)
            if msgid:
                return RegressionFull.get_by_entry(msgid)
            else:
                logger.debug(
                    "Skipping link %s (found in %s): Unable to parse", url, foundspot)
            return None

        # update
        repo = self.repo()
        for remote in repo.remotes:
            remote.fetch()

        # check for new branches
        for repobranch in repo.remote().refs:
            # do we care about this branch?
            if re.search(self.branchregex, repobranch.name) is None:
                continue

            gitbranch = GitBranch.get_by_treeid_branchname(
                self.gittreeid, repobranch.name)

            # if we encounter this branch for the first time, start to track it
            # Note: we'll miss the first batch of commits if this is a new stable branch – but
            # that shouldn't be a problem, as all regressions up to this point are mainline regressions
            # anyway [famous last words?]
            if not gitbranch:
                GitBranch.add(self, repobranch.name, repobranch.commit.hexsha)
                continue

            # if nothing changed, there is nothing to do for us here
            if gitbranch.lastchked == repobranch.commit.hexsha:
                logger.debug("nothing new in %s/%s ",
                             self.name, gitbranch.name)
                continue

            # if this is mainline repo, update the latest versions variable
            # side note: mainline should only have one branch that is relevant for this [famous last words?])
            if self.name == 'mainline':
                self.check_latest_versions(repo)

            # check if a fix we are waiting for finally landed
            for regressionbasic in RegressionBasic.get_pending():
                if gitbranch.commit_exists(regressionbasic.solved_entry):
                    commit = self.commit(regressionbasic.solved_entry)
                    # leave checking if it's really the right tree/branch to the
                    # following function, it needs to do anyway:
                    mergedate = gitbranch.merge_date(commit.hexsha)
                    if regressionbasic.fixed(mergedate, commit.hexsha, commit.summary, gitbranch.gitbranchid):
                        RegHistory.event(regressionbasic.regid, regressionbasic.solved_gmtime, regressionbasic.solved_entry,
                                         regressionbasic.solved_subject, gitbranchid=gitbranch.gitbranchid,
                                         regzbotcmd="fixed (fixed-by landed): %s" % (regressionbasic.solved_reason))

            # now check new commits for links
            re_link = re.compile(
                r'(^\s*Link:\s*)(http(.*))\s*\n', re.MULTILINE)
            for commit in repo.iter_commits(('--reverse', gitbranch.lastchked + '..' + repobranch.commit.hexsha)):
                for match in re_link.finditer(commit.message):
                    regressionfull = process_link(match.group(2), "%s, %s, %s" % (
                        self.name, gitbranch.name, commit))
                    if not regressionfull:
                        logger.debug(
                            "Saw link to %s, but not aware of any regressions about it", match.group(2))
                        continue

                    if regressionfull.treename == self.name:
                        mergedate = gitbranch.merge_date(commit.hexsha)

                        regressionfull.fixed(
                            mergedate, commit.hexsha, commit.summary, gitbranch.gitbranchid)
                        RegHistory.event(regressionfull.regid, mergedate, commit.hexsha, commit.summary,
                                         gitbranchid=gitbranch.gitbranchid, regzbotcmd="fixed (link in commit): %s" % commit.hexsha[0:12])
                    else:
                        mergedate = gitbranch.merge_date(commit.hexsha)

                        regressionfull.fixedby(
                            mergedate, commit.hexsha, commit.summary, gitbranch.gitbranchid, lookup=False)
                        RegHistory.event(regressionfull.regid, mergedate, commit.hexsha, commit.summary,
                                         gitbranchid=gitbranch.gitbranchid, regzbotcmd="fixed-by: %s (noticed in %s)" % (self.name, commit.hexsha[0:12]))
                        RegActivityEvent.event(mergedate, commit.hexsha, "The commit '%s' in '%s' linked to this regression" % (
                            self.name, commit.hexsha[0:12]), gitbranchid=gitbranch.gitbranchid, regid=regressionfull.regid)

            # and we are done here
            gitbranch.set_lastchked(repobranch.commit.hexsha)

    @staticmethod
    def updateall():
        for gittree in GitTree.getall():
            gittree.update()


class RegActivityMonitor():
    def __init__(self, actimonid, regid, repsrcid, entry, ):
        self.actimonid = actimonid
        self.regid = regid
        self.repsrcid = repsrcid
        self.entry = entry

    @staticmethod
    def db_create(dbcursor, version):
        logger.debug('Initializing new dbtable "actmonitor"')
        dbcursor.execute('''
            INSERT INTO meta
            VALUES(?, ?)''', ('actmonitor', version, ))
        dbcursor.execute('''
            CREATE TABLE actmonitor (
                actimonid   INTEGER  NOT NULL PRIMARY KEY,
                regid       INTEGER  NOT NULL,
                repsrcid    INTEGER  NOT NULL,
                entry       INTEGER  NOT NULL
            )''')

    @staticmethod
    def add(regid, repsrcid, entry):
        dbcursor = DBCON.cursor()
        dbcursor.execute('''INSERT INTO actmonitor
                            (regid, repsrcid, entry)
                            VALUES (?, ?, ?)''',
                         (regid, repsrcid, entry))
        logger.debug('[db actmonitor] insert (actimonid:%s, regid:%s, repsrcid:%s, entry:%s)' % (
            dbcursor.lastrowid, regid, repsrcid, entry))
        return dbcursor.lastrowid

    @staticmethod
    def remove(regid, repsrcid, entry):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT actimonid FROM actmonitor WHERE regid=(?) AND repsrcid=(?) AND entry=(?)', (regid, repsrcid, entry)).fetchone()
        if dbresult is not None:
            dbcursor.execute('''DELETE FROM actmonitor
                             WHERE regid=(?) AND repsrcid=(?) AND entry=(?)''',
                             (regid, repsrcid, entry))
            logger.debug('[db actmonitor] deleted (actimonid:%s, regid:%s, repsrcid:%s, entry:%s; %s)' % (
                dbcursor.lastrowid, regid, repsrcid, entry, dbcursor.lastrowid))
            return True
        return False

    @staticmethod
    def get(actimonid):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM actmonitor WHERE actimonid=(?)', (actimonid, )).fetchone()
        if dbresult:
            return RegActivityMonitor(*dbresult)
        return None

    @staticmethod
    def getall_by_regid(regid):
        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM actmonitor WHERE regid=(?)', (regid, )):
            yield RegActivityMonitor(*dbresult)

    @staticmethod
    def getall_by_repsrcid_n_entry(repsrcid, entry):
        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM actmonitor WHERE repsrcid=(?) AND entry=(?)', (repsrcid, entry)):
            yield RegActivityMonitor(*dbresult)

    @staticmethod
    def get_by_regid_repsrcid_n_entry(regid, repsrcid, entry):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM actmonitor WHERE regid=(?) AND repsrcid=(?) AND entry=(?)', (regid, repsrcid, entry, )).fetchone()
        if dbresult is not None:
            return RegActivityMonitor(*dbresult)
        else:
            return False

    @staticmethod
    def ismonitored(entry, regid=None, repsrcid=None):
        dbcursor = DBCON.cursor()
        if regid and repsrcid:
            if dbcursor.execute('SELECT * FROM actmonitor WHERE regid=(?) AND repsrcid=(?) AND entry=(?)', (regid, repsrcid, entry)).fetchone() is not None:
                return True
        else:
            if dbcursor.execute('SELECT * FROM actmonitor WHERE entry=(?)', (entry, )).fetchone() is not None:
                return True

        return False


class RegActivityEvent():
    def __init__(self, gmtime, entry, subject, repsrcid, gitbranchid, actimonid, regid):
        self.gmtime = gmtime
        self.entry = entry
        self.subject = subject
        self.repsrcid = repsrcid
        self.gitbranchid = gitbranchid
        self._actimonid = actimonid
        self._regid = regid

    @staticmethod
    def db_create(dbcursor, version):
        logger.debug('Initializing new dbtable "regactivity"')
        dbcursor.execute('''
            INSERT INTO meta
            VALUES(?, ?)''', ('regactivity', version, ))
        dbcursor.execute('''
            CREATE TABLE regactivity (
                gmtime       INTEGER  NOT NULL,
                entry        STRING   NOT NULL,
                subject      STRING   NOT NULL,
                repsrcid     INTEGER,
                gitbranchid  INTEGER,
                actimonid    INTEGER,
                regid        INTEGER
            )''')

    @staticmethod
    def event(gmtime, entry, subject, repsrcid=None, gitbranchid=None, actimonid=None, regid=None):
        # a few lines from the department of "this should not happen, but better ensure it doesn't":
        if repsrcid is None and gitbranchid is None:
            logger.critical(
                'this should not happen: RegActivityEvent.event(%s, %s, %s, %s, %s, %s, %s) was called without specifying either repsrcid or gitbranchid; '
                % (gmtime, entry, subject, repsrcid, gitbranchid, actimonid, regid))
        if repsrcid and gitbranchid:
            logger.critical(
                'this should not happen: RegActivityEvent.event(%s, %s, %s, %s, %s, %s, %s) was called with specifying both repsrcid or gitbranchid'
                % (gmtime, entry, subject, repsrcid, gitbranchid, actimonid, regid))

        # a few lines from the department of "this should not happen, but better ensure it doesn't":
        if actimonid is None and regid is None:
            logger.critical(
                'this should not happen: RegActivityEvent.event(%s, %s, %s, %s, %s, %s, %s) was called without specifying either actimonid or regid; '
                % (gmtime, entry, subject, repsrcid, gitbranchid, actimonid, regid))
        if actimonid and regid:
            logger.critical(
                'this should not happen: RegActivityEvent.event(%s, %s, %s, %s, %s, %s, %s) was called with specifying both actimonid or regid'
                % (gmtime, entry, subject, repsrcid, gitbranchid, actimonid, regid))

        dbcursor = DBCON.cursor()
        dbcursor.execute('''INSERT INTO regactivity
                        (gmtime, entry, subject, repsrcid, gitbranchid, actimonid, regid)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                         (gmtime, entry, subject, repsrcid, gitbranchid, actimonid, regid))
        logger.debug('[db regactivity] insert (gmtime:%s, entry:"%s", subject:"%s", repsrcid:%s, gitbranchid:%s, actimonid:%s, regid:%s)' % (
            gmtime, entry, subject, repsrcid, gitbranchid, actimonid, regid))

    @staticmethod
    def getall_by_regid(regid):
        def _getall_actimonids(regid):
            actimonids = list()
            for actimon in RegActivityMonitor.getall_by_regid(regid):
                actimonids.append("%s" % actimon.actimonid)
            return actimonids

        # prepare query with an unkown number of items in the "WHERE IN" clause
        replacements = _getall_actimonids(regid)
        placeholders = ', '.join('?' for unused in replacements)
        replacements.append(regid)

        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM regactivity WHERE actimonid IN (%s) OR regid=(?) ORDER BY gmtime' % placeholders, replacements):
            yield RegActivityEvent(*dbresult)

    def url(self):
        if self.repsrcid is None:
            return GitBranch.url_by_id(self.gitbranchid, self.entry)
        return ReportSource.url_by_id(self.repsrcid, self.entry)

    def csv(self):
        return "%s, %s, %s" % (self.subject, self.url(), self.gmtime)

    def html(self, yattagdoc):
        with yattagdoc.tag('a', href=self.url()):
            yattagdoc.text("%s" % self.subject)


class RegHistory():
    def __init__(self, regid, gmtime, entry, subject, regzbotcmd, gitbranchid, repsrcid):
        self.regid = regid
        self.gmtime = gmtime
        self.entry = entry
        self.subject = subject
        self.regzbotcmd = regzbotcmd
        self.gitbranchid = gitbranchid
        self.repsrcid = repsrcid

    @staticmethod
    def db_create(dbcursor, version):
        logger.debug('Initializing new dbtable "reghistory"')
        dbcursor.execute('''
            INSERT INTO meta
            VALUES(?, ?)''', ('reghistory', version, ))
        dbcursor.execute('''
            CREATE TABLE reghistory (
                regid       INTEGER  NOT NULL,
                gmtime      INTEGER  NOT NULL,
                entry       STRING   NOT NULL,
                subject     STRING   NOT NULL,
                regzbotcmd  STRING,
                gitbranchid INTEGER,
                repsrcid    INTEGER
            )''')

    @staticmethod
    def _event(regid, gmtime, entry, subject, gitbranchid=None, repsrcid=None, regzbotcmd=None):
        dbcursor = DBCON.cursor()
        dbcursor.execute('''INSERT INTO reghistory
                        (regid, gmtime, entry, subject, regzbotcmd, gitbranchid, repsrcid)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                         (regid, gmtime, entry, subject, regzbotcmd, gitbranchid, repsrcid))
        logger.debug('[db reghistory] insert (regid:%s, gmtime:%s, entry:%s, subject:"%s", regzbotcmd:"%s", gitbranchid:%s, repsrcid:%s)' % (
            dbcursor.lastrowid, gmtime, entry, subject, regzbotcmd, gitbranchid, repsrcid))
        return dbcursor.lastrowid

    @staticmethod
    def event(regid, gmtime, entry, subject, repsrcid=None, gitbranchid=None, regzbotcmd=None):
        # a few lines from the department of "this should not happen, but better ensure it doesn't":
        if repsrcid is None and gitbranchid is None:
            logger.critical(
                'this should not happen: RegActivityEvent.event(%s, %s, %s, %s, %s, %s, %s) was called without specifying either repsrcid or gitbranchid; '
                % (gmtime, entry, subject, repsrcid, gitbranchid, regzbotcmd, regid))
        if repsrcid and gitbranchid:
            logger.critical(
                'this should not happen: RegActivityEvent.event(%s, %s, %s, %s, %s, %s, %s) was called with specifying both repsrcid or gitbranchid'
                % (gmtime, entry, subject, repsrcid, gitbranchid, regzbotcmd, regid))

        RegHistory._event(
            regid, gmtime, entry, subject, repsrcid=repsrcid, gitbranchid=gitbranchid, regzbotcmd=regzbotcmd)

    def already_processed(regid, entry, regzbotcmd, repsrcid=None):
        dbcursor = DBCON.cursor()
        if repsrcid:
            dbresult = dbcursor.execute(
                'SELECT * FROM reghistory WHERE regid=(?) AND entry=(?) AND regzbotcmd=(?) AND repsrcid=(?)', (regid, entry, regzbotcmd, repsrcid)).fetchone()
        else:
            dbresult = dbcursor.execute(
                'SELECT * FROM reghistory WHERE regid=(?) AND entry=(?) AND regzbotcmd=(?)', (regid, entry, regzbotcmd)).fetchone()

        if dbresult is None:
            return False
        else:
            return True

    @staticmethod
    def get_all(regid, order="gmtime"):
        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM reghistory WHERE regid=(?) ORDER BY (?)', (regid, order)):
            yield RegHistory(*dbresult)

    @staticmethod
    def get_latest(regid):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM reghistory WHERE regid=(?) ORDER BY gmtime DESC', (regid, )).fetchone()
        if dbresult is not None:
            return RegHistory(*dbresult)
        else:
            return False

    def url(self):
        if self.gitbranchid is not None:
            return GitBranch.url_by_id(self.gitbranchid, self.entry)
        elif self.repsrcid is not None:
            return ReportSource.url_by_id(self.repsrcid, self.entry)
        return None

    def csv(self):
        if self.regzbotcmd:
            return "%s, %s, %s, %s" % (self.subject, self.url(), self.gmtime, self.regzbotcmd)
        return "%s, %s, %s" % (self.subject, self.url(), self.gmtime)

    def html(self, yattagdoc):
        if self.regzbotcmd:
            with yattagdoc.tag('a', href=self.url()):
                yattagdoc.text("%s" % self.regzbotcmd)
        else:
            with yattagdoc.tag('a', href=self.url()):
                yattagdoc.text("%s" % self.subject)


class RegLink():
    def __init__(self, regid, gmtime, repsrcid, entry, link, subject):
        self.regid = regid
        self.gmlime = gmtime
        self.repsrcid = repsrcid
        self.entry = entry
        self.subject = subject

        if link is not None:
            self.link = link
        else:
            self.link = ReportSource.url_by_id(self.repsrcid, self.entry)

    @staticmethod
    def db_create(dbcursor, version):
        logger.debug('Initializing new dbtable "reglinks"')
        dbcursor.execute('''
            INSERT INTO meta
            VALUES(?, ?)''', ('reglinks', version, ))
        dbcursor.execute('''
            CREATE TABLE reglinks (
                regid       INTEGER  NOT NULL,
                gmtime      INTEGER,
                repsrcid    INTEGER,
                entry       STRING,
                link        STRING,
                subject     STRING
            )''')

    @staticmethod
    def add_entry(regid, gmtime, description, repsrcid, entry):
        dbcursor = DBCON.cursor()
        dbcursor.execute('''INSERT INTO reglinks
                            (regid, gmtime, repsrcid, entry, subject)
                            VALUES (?, ?, ?, ?, ?)''',
                         (regid, gmtime, repsrcid, entry, description))
        logger.debug('[db reglinks] insert (regid:%s, gmtime:%s, repsrcid:%s, entry:%s, subject:"%s", )' % (
            regid, gmtime, repsrcid, entry, description, ))

    @staticmethod
    def add_link(regid, gmtime, description, link):
        def add(dbcursor, regid, link, description, gmtime):
            dbcursor.execute('''INSERT INTO reglinks
                            (regid, gmtime, link, subject)
                            VALUES (?, ?, ?, ?)''',
                             (regid, gmtime, link, description))
            logger.debug('[db reglinks] insert (regid:%s, gmtime:%s, link:%s, subject:"%s")' % (
                regid, gmtime, link, description))

        def update(dbcursor, regid, link, description):
            dbcursor.execute('''UPDATE reglinks
                            SET link = (?), subject = (?)
                            WHERE regid=(?)''',
                             (link, description, regid))
            logger.debug(
                '[db reglinks] update (regid:%s, link:%s)' % (regid, link))

        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT link FROM reglinks WHERE regid=(?)', (regid,)).fetchone()
        if dbresult is None:
            add(dbcursor, regid, link, description, gmtime)
            return False
        else:
            update(dbcursor, regid, link, description)
            return True
        return None

    @staticmethod
    def del_link(regid, link):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT link FROM reglinks WHERE regid=(?)', (regid,)).fetchone()
        if dbresult is not None:
            dbcursor.execute('''DELETE FROM reglinks
                             WHERE regid=(?) AND link=(?)''',
                             (regid, link))
            logger.debug(
                '[db reglinks] delete (regid:%s, link:%s)' % (regid, link))
            return True
        return False

    @staticmethod
    def get_all(regid):
        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM reglinks WHERE regid=(?)', (regid,)):
            yield RegLink(*dbresult)

    def csv(self):
        if self.repsrcid and self.entry:
            monitored = RegActivityMonitor.ismonitored(
                self.entry, self.regid, self.repsrcid)
        else:
            monitored = False
        return "%s, %s [monitored:%s]" % (self.subject, self.link, monitored)

    def html(self, yattagdoc):
        with yattagdoc.tag('a', href=self.link):
            yattagdoc.text(self.subject)
        if self.repsrcid and self.entry and RegActivityMonitor.ismonitored(self.entry, self.regid, self.repsrcid):
            yattagdoc.text(" [monitored]")


class RegressionBasic():
    def __init__(self, regid, repsrcid, entry, subject, introduced, gitbranchid, solved_reason=None, solved_gmtime=None,
                 solved_entry=None, solved_subject=None, solved_gitbranchid=None, solved_repsrcid=None, solved_repentry=None):
        self.regid = regid

        # FIXMELATER: get those from RegAcitivityMonitor? OTOH it might be a bad idea :-/
        self.repsrcid = repsrcid
        self.entry = entry

        self.subject = subject
        self.introduced = str(introduced)
        self.gitbranchid = gitbranchid
        self.solved_reason = solved_reason
        self.solved_gmtime = solved_gmtime
        self.solved_entry = solved_entry
        self.solved_subject = solved_subject
        self.solved_gitbranchid = solved_gitbranchid
        self.solved_repsrcid = solved_repsrcid
        self.solved_repentry = solved_repentry

    @staticmethod
    def db_create(dbcursor, version):
        logger.debug('Initializing new dbtable "regressions"')
        dbcursor.execute('''
            INSERT INTO meta
                VALUES(?, ?)''', ('regressions', version, ))
        dbcursor.execute('''
            CREATE TABLE regressions (
                regid              INTEGER  NOT NULL PRIMARY KEY,
                repsrcid           INTEGER  NOT NULL,
                entry              STRING   NOT NULL,
                subject            STRING   NOT NULL,
                introduced         STRING   NOT NULL,
                gitbranchid        INTEGER,
                solved_reason      STRING,
                solved_gmtime      INTEGER,
                solved_entry       STRING,
                solved_subject     STRING,
                solved_gitbranchid INTEGER,
                solved_repsrcid    INTEGER,
                solved_repentry    STRING
            )''')

    def _db_update_solved(self):
        dbcursor = DBCON.cursor()
        dbcursor.execute('''UPDATE regressions
                            SET solved_reason = (?), solved_gmtime = (?), solved_entry = (?), solved_subject = (?),
                                solved_gitbranchid = (?), solved_repsrcid = (?) , solved_repentry = (?)
                            WHERE regid=(?)''',
                         (self.solved_reason, self.solved_gmtime, self.solved_entry, self.solved_subject,
                             self.solved_gitbranchid, self.solved_repsrcid, self.solved_repentry, self.regid))
        logger.debug(
            '[db regressions] update solved fieds: (regid:%s; solved_reason:%s; solved_gmtime:%s; solved_entry:%s; solved_subject:"%s"; solved_gitbranchid:%s; solved_repsrcid:%s; solved_repentry:%s;  )',
            self.regid, self.solved_reason, self.solved_gmtime, self.solved_entry,
            self.solved_subject, self.solved_gitbranchid, self.solved_repsrcid, self.solved_repentry)

    @staticmethod
    def getall(order="regid"):
        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM regressions ORDER BY (?)', (order, )):
            yield dbresult

    @staticmethod
    def get_by_regid(regid):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM regressions WHERE regid=?', (regid,)).fetchone()
        if dbresult:
            return RegressionBasic(*dbresult)
        return None

    @staticmethod
    def get_by_entry(entry):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM regressions WHERE entry=?', (entry,)).fetchone()
        if dbresult:
            return RegressionBasic(*dbresult)
        return None

    @staticmethod
    def get_by_link(link):
        tmpstring = link
        if tmpstring.startswith("https://"):
            tmpstring = tmpstring.removeprefix("https://")
        elif tmpstring.startswith("http://"):
            tmpstring = tmpstring.removeprefix("http://")

        if tmpstring.startswith("lore.kernel.org/"):
            _, _, tmpstring = tmpstring.split('/', maxsplit=3)
            msgid, _, _ = tmpstring.partition('/')
            return RegressionBasic.get_by_entry(msgid)
        else:
            logger.warning(
                "RegressionBasic.get_by_link(%s): unsupported domain ", link)
        return None

    @staticmethod
    def get_by_msgreferences(references):
        # handle mails without references
        if not references:
            return False

        dbcursor = DBCON.cursor()
        for ref in references.split():
            dbresult = dbcursor.execute(
                'SELECT * FROM regressions WHERE entry=?', (ref[1:-1],)).fetchone()
            if dbresult is not None:
                return RegressionBasic(*dbresult)
        return False

    @staticmethod
    def get_pending():
        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM regressions WHERE solved_reason=?', ('to_be_fixed',)):
            yield RegressionBasic(*dbresult)

    @staticmethod
    def activity_event_monitored(repsrcid, gmtime, entry, subject, actimon):
        regression = RegressionBasic.get_by_regid(actimon.regid)
        RegActivityEvent.event(
            gmtime, entry, subject, repsrcid=repsrcid, actimonid=actimon.actimonid)
        logger.info('regression[%s, "%s"]: activity detected in %s")' % (
            regression.regid, regression.subject, entry))

    @staticmethod
    def activity_event_linked(repsrcid, gmtime, entry, subject, regid):
        regression = RegressionBasic.get_by_regid(regid)
        RegActivityEvent.event(
            gmtime, entry, subject, repsrcid=repsrcid, regid=regid)
        logger.info('regression[%s, "%s"]: link to this regression found in "%s" (%s)' % (
            regid, regression.subject, subject, ReportSource.url_by_id(repsrcid, entry)))

    @staticmethod
    def introduced_create(repsrcid, entry, subject, introduced):
        # remove everything after the first space, in case someone wrote something like this:
        # regzbot introduced cf68fffb66d6 ("add support for Clang CFI")
        introduced = introduced.split()[0]

        # try to find what tree/branch this belongs
        _, gitbranch, _ = RegressionBasic._gettree_n_branch(introduced)
        if gitbranch:
            gitbranchid = gitbranch.gitbranchid
        else:
            gitbranchid = None

        dbcursor = DBCON.cursor()

        # create regression
        dbcursor.execute('''INSERT INTO regressions
                            (repsrcid, entry, subject, introduced, gitbranchid)
                            VALUES (?, ?, ?, ?, ?)''',
                         (repsrcid, entry, subject, introduced, gitbranchid))
        # create entry for monitoring
        RegActivityMonitor.add(dbcursor.lastrowid, repsrcid, entry)

        logger.debug('[db regressions] inserted (regid:%s; subject:"%s" repsrcid:%s; entry:%s; introduced:%s; gitbranchid:%s)',
                     dbcursor.lastrowid, subject, repsrcid, entry, introduced, gitbranchid)

        logger.info('regression[%s, "%s"]: created ("%s"; "%s")',
                    dbcursor.lastrowid, subject, entry, introduced)
        return RegressionBasic(dbcursor.lastrowid, repsrcid, entry, subject, introduced, gitbranchid)

    def introduced_update(self, tagload):
        self.introduced = tagload
        logger.debug('regression %s (%s): introduced now %s',
                     self.regid, self.subject, self.introduced)
        dbcursor = DBCON.cursor()
        dbcursor.execute('''UPDATE regressions
                            SET introduced = (?)
                            WHERE regid=(?)''',
                         (self.introduced, self.regid))
        logger.debug('[db regressions] introduced is now %s (regid:%s; subject:"%s" )',
                     self.introduced, self.regid, self.subject)
        logger.info('regression[%s, "%s"]: setting introduced to "%s"',
                    self.regid, self.subject, self.introduced)

    def dupof(self, tagload, gmtime, msgid, msgsubject, repsrcid):
        def parse(tagload):
            tagload = tagload.split(maxsplit=1)
            url = tagload[0]
            if len(tagload) > 1:
                subject = tagload[1]
            else:
                subject = None
            return url, subject

        self.solved_entry, self.solved_subject = parse(tagload)

        regression_other = self.get_by_link(self.solved_entry)
        if self.solved_subject is None and regression_other:
            self.solved_subject = regression_other.subject
        else:
            # better a URL as subject than nothing at all:
            self.solved_subject = self.solved_entry

        self.solved_reason = 'duplicateof'
        self.solved_gmtime = gmtime
        self.solved_repsrcid = repsrcid
        self.solved_repentry = msgid

        self._db_update_solved()

        if regression_other:
            logger.info('regression[%s, "%s"]: marked as duplicate of regression Regression[%s, "%s"])',
                        self.regid, self.subject, regression_other.regid, regression_other.subject)
            # make sure this is mentioned in the other regression, too
            RegHistory.event(regression_other.regid, gmtime, msgid, self.solved_subject, repsrcid=repsrcid,
                             regzbotcmd='dup: the regression "%s" was marked as duplicate of this' % (self.subject))
            RegActivityEvent.event(
                gmtime, msgid, msgsubject, repsrcid=repsrcid, regid=regression_other.regid)
        else:
            logger.warning('regression[%s, "%s"]: marked as duplicate of "%s", but could not find a regression entry for it',
                           self.regid, self.subject, self.solved_subject)

    def fixed(self, gmtime, commit_hexsha, commit_subject, gitbranchid):
        if self.solved_reason == 'fixed':
            logger.info('regression[%s, "%s"]: was marked as fixed by %s earlier, changing it to %s instead.',
                        self.regid, self.subject, self.solved_entry, commit_hexsha)

        self.solved_reason = 'fixed'
        self.solved_gmtime = gmtime
        self.solved_gitbranchid = gitbranchid
        self.solved_entry = commit_hexsha
        self.solved_subject = commit_subject

        # remove these, as they are unneeded as of now
        self.solved_repsrcid = None
        self.solved_repentry = None

        self._db_update_solved()
        logger.info('regression[%s, "%s"]: marked as %s by %s ("%s")',  self.regid,
                    self.subject, self.solved_reason, self.solved_entry, self.solved_subject)
        return True

    def fixedby(self, gmtime, commit_hexsha, commit_subject, gitbranchid=None, repsrcid=None, repentry=None, lookup=True):
        # in case the fix already showed up, let the responsible function take over
        if lookup:
            gittree, gitbranch = GitTree.commit_find(commit_hexsha)
            if gitbranch:
                commit = gittree.commit(commit_hexsha)
                mergedate = gitbranch.merge_date(commit.hexsha)

                return self.fixed(mergedate, commit.hexsha, commit.summary, gitbranch.gitbranchid)

        self.solved_reason = 'to_be_fixed'
        self.solved_gmtime = gmtime
        self.solved_entry = commit_hexsha
        self.solved_subject = commit_subject
        self.solved_entry = commit_hexsha
        self.solved_gitbranchid = gitbranchid
        self.solved_repsrcid = repsrcid
        self.solved_repentry = repentry

        self._db_update_solved()
        logger.info('regression[%s, "%s"]: marked as %s by %s ("%s")',  self.regid,
                    self.subject, self.solved_reason, self.solved_entry, self.solved_subject)
        return True

    def invalid(self, tagload, gmtime, msgid, repsrcid):
        self.solved_reason = 'invalid'
        self.solved_gmtime = gmtime
        self.solved_subject = tagload
        self.solved_repsrcid = repsrcid
        self.solved_repentry = msgid
        self._db_update_solved()

    @staticmethod
    def linkparse(tagload):
        tagload = tagload.split(maxsplit=1)
        link = tagload[0]
        if len(tagload) > 1:
            description = tagload[1]
        else:
            description = link.removeprefix("http://")
        return link, description

    def linkadd(self, tagload, gmtime):
        link, description = self.linkparse(tagload)
        updated = RegLink.add_link(
            self.regid, gmtime, description, link)
        if updated is False:
            logger.info('regression[%s, "%s"]: added link to %s")' % (
                self.regid, self.subject, link))
        if updated is True:
            logger.info('regression[%s, "%s"]: subject of link %s is now "%s"' % (
                self.regid, self.subject, link, description))

    def linkremove(self, tagload):
        link, _ = self.linkparse(tagload)
        RegLink.del_link(self.regid, link)
        logger.info('regression[%s, "%s"]: removed link to %s' % (
            self.regid, self.subject, link))

    def monitoradd_direct(self, repsrcid, gmtime, msgid, description):
        actimonid = RegActivityMonitor.add(self.regid, repsrcid, msgid)
        RegActivityEvent.event(
            gmtime, msgid, description, repsrcid=repsrcid, actimonid=actimonid)
        RegLink.add_entry(
            self.regid, gmtime, description, repsrcid, msgid)
        logger.info('regression[%s, "%s"]: started to monitor %s' % (
            self.regid, self.subject, msgid))

    @staticmethod
    def monitorcommon_unhandled(errormsg, report_repsrc, report_msg, gmtime):
        urltoreport = report_repsrc.url(report_msg['message-id'][1:-1])
        UnhandledEvent.add(
            urltoreport, errormsg, gmtime=gmtime, subject=report_msg['subject'])
        return False

    def monitoradd(self, tagload, gmtime, report_repsrc, report_msg):
        def get_msg(target_msgid):
            if not is_running_citesting_offline():
                return download_msg(target_msgid)
            return None, None

        link, description = self.linkparse(tagload)

        domain, mailinglist, target_msgid = parse_link(link)
        if not domain or not mailinglist or not target_msgid:
            errormsg = "unable to monitor thread %s as URL could not be parsed" % link
            logger.critical('regression[%s, "%s"]: %s' % (
                self.regid, self.subject, errormsg))
            return self.monitorcommon_unhandled(errormsg, report_repsrc, report_msg, gmtime)

        target_repsrc, target_msg = get_msg(target_msgid)
        if target_repsrc and target_msg:
            target_gmtime = mailin.email_get_gmtime(target_msg)
            target_subject = mailin.email_get_subject(target_msg)
            self.monitoradd_direct(target_repsrc.repsrcid, target_gmtime, target_msgid, target_subject)
        else:
            repsrc = ReportSource.get_byweburl('%%%s/%s%%' % (domain, mailinglist))
            if repsrc is None:
                errormsg = "unable to monitor thread %s, mailinglist unkown" % link
                logger.critical('regression[%s, "%s"]: %s' % (
                    self.regid, self.subject, errormsg))
                return self.monitorcommon_unhandled(errormsg, report_repsrc, report_msg, gmtime)
            self.monitoradd_direct(repsrc.repsrcid, gmtime, target_msgid, description)

        if not is_running_citesting_offline():
            lore.process_replies(target_msgid)

    def monitorremove(self, tagload, gmtime, report_repsrc, report_msg):
        link, _ = self.linkparse(tagload)

        domain, mailinglist, msgid = parse_link(link)
        if not mailinglist or not msgid:
            errormsg = 'unable to unmonitor thread %s as URL could not be parsed' % link
            logger.critical('regression[%s, "%s"]: %s',
                            self.regid, self.subject, errormsg)
            return self.monitorcommon_unhandled(errormsg, report_repsrc, report_msg, gmtime)

        repsrc = ReportSource.get_byweburl('%%%s/%s%%' % (domain, mailinglist))
        if repsrc is None:
            errormsg = "unable to unmonitor thread %s, mailinglist unkown" % link
            logger.critical('regression[%s, "%s"]: %s',
                            self.regid, self.subject, errormsg)
            return self.monitorcommon_unhandled(errormsg, report_repsrc, report_msg, gmtime)

        if RegActivityMonitor.remove(self.regid, repsrc.repsrcid, msgid):
            logger.info('regression[%s, "%s"]: stopped monitoring %s' % (
                self.regid, self.subject, ReportSource.url_by_id(repsrc.repsrcid, msgid)))
            return True
        else:
            errormsg = "thread %s is not monitored, thus unable to unmonitor it" % link
            logger.critical('regression[%s, "%s"]: %s',
                            self.regid, self.subject, errormsg)
            return self.monitorcommon_unhandled(errormsg, report_repsrc, report_msg, gmtime)

    def title(self, tagload):
        dbcursor = DBCON.cursor()
        dbcursor.execute('''UPDATE regressions
                            SET subject = (?)
                            WHERE regid=(?)''',
                         (tagload, self.regid))
        logger.debug('[db regressions] subject is now %s (regid:%s; subject:"%s" )',
                     tagload, self.regid, self.subject)
        logger.info('regression[%s, "%s"]: subject now "%s"',
                    self.regid, self.subject, tagload)
        self.subject = tagload

    @staticmethod
    def _gettree_n_branch(introduced):
        if '..' in introduced:
            range_start, range_end = introduced.split("..", 1)
            gittree_end, gitbranch_end = GitTree.commit_find(range_end)
            return gittree_end, gitbranch_end, True
        else:
            gittree, gitbranch = GitTree.commit_find(introduced)
            if gitbranch:
                return gittree, gitbranch, False
        return None, None, None


class RegressionFull(RegressionBasic):
    def __init__(self, *args):
        super().__init__(*args)

        self._histevents = self._init_histdata(self.regid)
        self._actievents = self._init_actidata(self.regid)

        self.gmtime = self._actievents[0].gmtime

        self._report_url = ReportSource.get_by_id(
            self.repsrcid).url(self.entry)
        self._introduced_short, _ = self._get_presentable(self.introduced)

        # provide a default for these, as this can't be None:
        self.treename = 'unassociated'
        self.category = 'default'

        self._branchname = None
        self._introduced_url = None
        self._introduced_presentable = None
        self._solved_entry_presentable = None

        if self.gitbranchid:
            gitbranch = GitBranch.get_by_id(self.gitbranchid)
            gittree = GitTree.get_by_id(gitbranch.gittreeid)

            # catch commits that were introduced and reported in next but moved to master
            if gittree.name == 'next':
                tmpgittree, tmpgitbranch, _ = RegressionBasic._gettree_n_branch(
                    self.introduced)
                if tmpgittree.name == 'master':
                    gitbranch = tmpgitbranch
                    gittree = tmpgittree

            self.treename = gittree.name
            self._branchname = gitbranch.name
            self._introduced_presentable, self.category = self._get_presentable(
                self.introduced, gittree=gittree, getcategory=True)
            if self._introduced_short == self._introduced_presentable:
                self._introduced_presentable = None

            if '..' not in self.introduced:
                self._introduced_url = gitbranch.url(
                    self.introduced, gittree)

        if self.solved_gitbranchid:
            self._solved_entry_presentable, _ = self._get_presentable(
                self.solved_entry, gittree=gittree)
            self.solved_url = GitBranch.url_by_id(
                self.solved_gitbranchid, self.solved_entry)
        elif self.solved_repsrcid:
            self.solved_url = ReportSource.url_by_id(
                self.solved_repsrcid, self.solved_repentry)
        else:
            self.solved_url = None

    @staticmethod
    def _init_histdata(regid):
        histevents = list()
        for event in RegHistory.get_all(regid):
            histevents.append(event)
        return histevents

    @staticmethod
    def _init_actidata(regid):
        actievents = list()
        for actievent in RegActivityEvent.getall_by_regid(regid):
            actievents.append(actievent)
        return actievents

    def _get_presentable(self, gitref, gittree=None, getcategory=None):
        def iscommitid(commitid):
            if commitid is None or commitid is False or commitid is True:
                return False
            elif re.search('^[0-9a-fA-F]{8,40}', commitid) is not None:
                return True
            else:
                return False

        def lookup_commit(commitid):
            if iscommitid(commitid):
                description, present = gittree.commit_describe(commitid)
                if description is None:
                    # fallback for situations where a commit is present, but can't be described since it happened after the last tag
                    description = commitid
                return description, present
            return commitid, None

        def shorten(commitid):
            if iscommitid(commitid) and len(commitid) > 11:
                return commitid[0:12]
            else:
                return commitid

        def combine(point1, point2):
            point1 = shorten(point1)
            point2 = shorten(point2)
            if point1 is not None:
                return "%s..%s" % (point1, point2)
            else:
                return "%s" % (point2)

        gitref = str(gitref)
        if gitref is None:
            return None, None
        elif '..' in gitref:
            point1, point2 = gitref.split("..", 1)
        else:
            point1 = None
            point2 = gitref

        point1pres = None
        point2pres = None
        if gittree is not None:
            if point1 is not None:
                point1, point1pres = lookup_commit(point1)
            point2, point2pres = lookup_commit(point2)

        # we might be done here
        if not getcategory:
            return combine(point1, point2), None

        def isdevcycle(series, version):
            if LATEST_VERSIONS[series] and version.startswith(LATEST_VERSIONS[series]):
                return True
            return False

        def retcategory(category='default'):
            return combine(point1, point2), category

        # handle all solved ones
        if self.solved_reason == 'fixed' or self.solved_reason == 'duplicateof' or self.solved_reason == 'invalid':
            return retcategory('resolved')

        # only mainline has more that three categories
        if not self.treename == 'mainline':
            if point1 is None and point2pres:
                if iscommitid(point2) or point2pres is True:
                    return retcategory('identified')
            return retcategory()

        # handle all regressions specifying a commit
        if point2 and not point1:
            if isdevcycle('indevelopment', point2):
                # from the current cycle
                return retcategory('curridentified')
            elif iscommitid(point2) and point2pres:
                # commit is present, but 'git describe --tags' failed, which means: commit happenend since the last tag
                return retcategory('curridentified')
            elif point2pres:
                # it's from an earlier cycle
                return retcategory('identified')
            else:
                # this commit could not be found, so just put it in the default section
                return retcategory()

        # now handle ranges
        if days_delta(self.gmtime) < 8:
            return retcategory('new')

        if isdevcycle('indevelopment', point2):
            # this checks:
            # 1) if range starts with the same version number
            # 2) if range starts with the number from the previous cycle (catches mainline and stable releases)
            if isdevcycle('indevelopment', point1) or \
               point1.startswith(LATEST_VERSIONS['latest']):
                return retcategory('currrange')
        if isdevcycle('latest', point2):
            if isdevcycle('latest', point1) or \
               point1.startswith(LATEST_VERSIONS['previous']):
                return retcategory('prevrange')

        # default: either its and older range or something doesn't match up, which can happen if user specifies odd ranges
        return retcategory('default')

    @staticmethod
    def get_by_entry(entry):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM regressions WHERE entry=?', (entry,)).fetchone()
        if dbresult:
            return RegressionFull(*dbresult)
        return None

    @staticmethod
    def get_all(order="regid"):
        for dbresult in RegressionBasic.getall(order):
            yield RegressionFull(*dbresult)

    @staticmethod
    def dumpall_csv():
        regressionlist = list()
        for regression in RegressionFull.get_all():
            regressionlist.append(regression.csv())
        return regressionlist

    # this should be moved to RegressionWeb class
    @staticmethod
    def getall_html():
        regressionlist = list()
        for regressionf in RegressionFull.get_all():
            if regressionf.category == 'resolved':
                regressionlist.append(RegressionWeb(regressionf.entry, regressionf.gmtime,
                                                    regressionf._actievents[-1].gmtime, 'resolved', regressionf.treename, 'default', regressionf.html()))
            elif days_delta(regressionf._actievents[-1].gmtime) > 21 and not __CITESTING__:
                regressionlist.append(RegressionWeb(regressionf.entry, regressionf.gmtime,
                                                    regressionf._actievents[-1].gmtime, 'dormant', regressionf.treename, 'default', regressionf.html()))
            else:
                regressionlist.append(RegressionWeb(regressionf.entry, regressionf.gmtime, regressionf._actievents[-1].gmtime,
                                                    regressionf.treename, regressionf.treename, regressionf.category, regressionf.html()))
        return regressionlist

    def csv(self):
        rtntext = list()
        rtntext.append("REGRESSION: %s, %s, %s (%s), %s, %s, %s, %s, %s" %
                       (self.subject, self._report_url, self._introduced_short, self._introduced_presentable,
                           self._introduced_url, self.gmtime, self.treename, self._branchname, self.category))

        for link in RegLink.get_all(self.regid):
            rtntext.append("LINK: " + link.csv())

        if self.solved_reason:
            rtntext.append("SOLVED: %s, %s, %s, %s, %s" %
                           (self.solved_reason, self.solved_gmtime, self._solved_entry_presentable, self.solved_url, self.solved_subject))

        for actievent in self._actievents:
            rtntext.append("ACTIVITY: " + actievent.csv())

        for histevent in self._histevents:
            rtntext.append("HISTORY: " + histevent.csv())

        rtntext.append("LATEST: " + self._actievents[-1].csv())

        return rtntext

    # this should be moved to RegressionWeb class
    def html(self):
        def cell1(yattagdoc):
            with yattagdoc.tag('div', style="padding-left: 1em;"):
                with yattagdoc.tag('li'):
                    if self._introduced_url:
                        with yattagdoc.tag('a', href=self._introduced_url):
                            yattagdoc.text(self._introduced_short)
                        if self._introduced_presentable:
                            with yattagdoc.tag('div'):
                                yattagdoc.text("(%s)" %
                                               self._introduced_presentable)
                    else:
                        yattagdoc.text(self._introduced_short)

        def cell2(yattagdoc):
            def add_introduced(yattagdoc):
                yattagdoc.text(self._introduced_short)

            with yattagdoc_line.tag('details', style="padding-left: 1em;"):
                with yattagdoc_line.tag('summary', style="list-style-position: outside;"):
                    yattagdoc.text('Report: ')
                    with yattagdoc.tag('i'):
                        with yattagdoc.tag('a', href=self._report_url):
                            yattagdoc.text(self.subject)
                    yattagdoc.text(' (%s days old)' % days_delta(self.gmtime))

                    if self.solved_reason:
                        yattagdoc.text(' ')
                        with yattagdoc.tag('mark', style='background-color: #D0D0D0;'):
                            yattagdoc.text('[ ')
                            if self.solved_reason == 'fixed':
                                yattagdoc.text('Fixed')
                            elif self.solved_reason == 'to_be_fixed':
                                yattagdoc.text('To be fixed')
                            elif self.solved_reason == 'duplicateof':
                                yattagdoc.text('Duplicate')
                            elif self.solved_reason == 'invalid':
                                yattagdoc.text('Invalid')
                            elif self.solved_reason is not None:
                                yattagdoc.text('%s' % self.solved_reason)
                            yattagdoc.text(' ]')
                        yattagdoc.text(' ')

                    with yattagdoc.tag('div'):
                        if len(self._actievents) < 2:
                            yattagdoc.text('No further activity yet')
                        else:
                            yattagdoc.text('Latest activity: ')
                            with yattagdoc.tag('a', href=self._actievents[-1].url()):
                                yattagdoc.text('%s days ago' % days_delta(
                                    self._actievents[-1].gmtime))
                            yattagdoc.text('.')

                        entered_loop = False
                        for counter, regressionlink in enumerate(RegLink.get_all(self.regid)):
                            if counter == 0:
                                entered_loop = True
                                yattagdoc.text(' Related issues: ')
                            else:
                                yattagdoc.text(', ')
                            with yattagdoc.tag('a', href=regressionlink.link):
                                yattagdoc.text("[%s]" % counter)
                        if entered_loop:
                            yattagdoc.text('.')

                for counter, regressionlink in enumerate(RegLink.get_all(self.regid)):
                    with yattagdoc.tag('div'):
                        yattagdoc.text('Related[%s]: ' % counter)
                        with yattagdoc.tag('i'):
                            regressionlink.html(yattagdoc)

                if self.solved_reason:
                    with yattagdoc.tag('div'):
                        yattagdoc.text(' ')
                        with yattagdoc.tag('strong'):
                            if self.solved_reason == 'fixed':
                                yattagdoc.text('Fixed: ')
                            elif self.solved_reason == 'to_be_fixed':
                                yattagdoc.text('To be fixed by: ')
                            elif self.solved_reason == 'duplicateof':
                                yattagdoc.text('Duplicate of: ')
                            elif self.solved_reason == 'invalid':
                                yattagdoc.text('Invalid: ')
                            elif self.solved_reason is not None:
                                yattagdoc.text('%s ' % self.solved_reason)

                        if self.solved_entry and self._solved_entry_presentable and not self._solved_entry_presentable == self.solved_entry[:12]:
                            yattagdoc.text('In %s by ' %
                                           self._solved_entry_presentable)

                        def solved_explanation(yattagdoc):
                            with yattagdoc.tag('i'):
                                if self.solved_reason == 'fixed' or self.solved_reason == 'to_be_fixed':
                                    yattagdoc.text('%s' %
                                                   self.solved_entry[:12])
                                    if self.solved_subject:
                                        yattagdoc.text(' ("%s")' %
                                                       self.solved_subject)
                                elif self.solved_subject:
                                    yattagdoc.text(self.solved_subject)
                        if self.solved_url is None:
                            solved_explanation(yattagdoc)
                        else:
                            with yattagdoc.tag('a', href=self.solved_url):
                                solved_explanation(yattagdoc)

                        yattagdoc.text(' (%s days ago)' % days_delta(
                            self.solved_gmtime))

                with yattagdoc_line.tag('p'):
                    yattagdoc.text("Latest known activities")
                    with yattagdoc_line.tag('ul'):
                        for actievent in reversed(self._actievents[-5:]):
                            with yattagdoc.tag('li', style="list-style-position: inside;"):
                                actievent.html(yattagdoc)
                                yattagdoc.text(" (%s days ago)" % days_delta(
                                    actievent.gmtime))

                with yattagdoc_line.tag('p'):
                    yattagdoc.text("Regression history")
                    with yattagdoc_line.tag('ul'):
                        for histevent in reversed(self._histevents):
                            with yattagdoc.tag('li', style="list-style-position: inside;"):
                                with yattagdoc.tag('i'):
                                    histevent.html(yattagdoc)
                                yattagdoc.text(" (%s days ago)" % days_delta(
                                               histevent.gmtime))

                with yattagdoc.tag('p'):
                    with yattagdoc.tag('div'):
                        yattagdoc.text(
                            "When fixing this, include this in the commit message to automatically resolve this entry in the regression tracking database:")
                    with yattagdoc.tag('div', style="padding-left: 1em;"):
                        with yattagdoc.tag('div', style='font-style: italic;'):
                            yattagdoc.text(
                                "Link: https://lore.kernel.org/regressions/%s" % self.entry)
                        if 'identified' in self.category:
                            commitsummary = GitTree.commit_summary(
                                self.introduced)
                            with yattagdoc.tag('div', style='font-style: italic;'):
                                yattagdoc.text('Fixes: %s ("%s")' % (
                                    self.introduced[0:12], commitsummary))

        yattagdoc_line = yattag.Doc()
        with yattagdoc_line.tag('td', style="width: 200px;"):
            cell1(yattagdoc_line)
        with yattagdoc_line.tag('td'):
            cell2(yattagdoc_line)
        return yattagdoc_line


class RegressionWeb():
    def __init__(self, entry, gmtime_report, gmtime_activity, page, tree, category, htmlsnippet):
        self.entry = entry
        self.gmtime_report = gmtime_report
        self.gmtime_activity = gmtime_activity
        self.page = page
        self.tree = tree
        self.category = category
        self.htmlsnippet = htmlsnippet

    @staticmethod
    def create_htmlpages(directory):
        def outpage_header(yattagdoc, htmlpages, pagename):
            with yattagdoc.tag('h1'):
                yattagdoc.text('Linux kernel regression status')
            with yattagdoc.tag('h2'):
                description = None
                for htmlpage in htmlpages:
                    # make it obvious that stable is about longterm, too
                    if htmlpage == "stable":
                        description = "stable/longterm"
                    else:
                        description = htmlpage

                    # print
                    if htmlpage == pagename:
                        yattagdoc.text("[%s]" % description)
                    else:
                        with yattagdoc.tag('a', href='%s.html' % htmlpage):
                            yattagdoc.text("[%s]" % description)

                    # seperate entries by space, unless we are at the end
                    if not htmlpage == htmlpage[-1]:
                        yattagdoc.asis("&nbsp;")

        def outpage_table_span(yattagdoc, description, tablecolumns, horizontal_rule=False, strong=False, heading=False):
            with yattagdoc.tag('tr'):
                if heading:
                    htmltag = "tr"
                else:
                    htmltag = "td"
                with yattagdoc.tag(htmltag, colspan=tablecolumns, style="text-align: left;  padding-bottom: 1em;"):
                    #            with yattagdoc.tag(htmltag, style="text-align: left;  padding-bottom: 1em;"):
                    if horizontal_rule:
                        yattagdoc.asis('<hr>')
                    if description is None:
                        return
                    if strong:
                        yattagdoc.line('strong', description)
                    else:
                        yattagdoc.text(description)

        def outpage_table_header_unhandled(yattagdoc):
            with yattagdoc.tag('tr', style="vertical-align:top;"):
                with yattagdoc.tag('th', align='left', style="width: 10px;"):
                    yattagdoc.text("id")
                with yattagdoc.tag('th', align='left'):
                    yattagdoc.text("place")

        def outpage_footer(yattagdoc, count):
            with yattagdoc.tag('p'):
                yattagdoc.text("[compiled by ")
                with yattagdoc.tag('a', href='https://linux-regtracking.leemhuis.info'):
                    yattagdoc.text("regzbot")
                currenttime = datetime.datetime.now(datetime.timezone.utc)
                yattagdoc.text(" on %s (UTC)" %
                               currenttime.strftime("%Y-%m-%d %H:%M:%S"))
                if count == 0:
                    # nothing to do
                    yattagdoc.text("]")
                    return

                yattagdoc.text("; recently ")
                with yattagdoc.tag('a', href='unhandled.html'):
                    if count == 1:
                        yattagdoc.text(
                            "%s event occurred that regzbot was unable to handle" % count)
                    else:
                        yattagdoc.text(
                            "%s events occurred that regzbot was unable to handle" % count)
                yattagdoc.text(".]")

        def create_page_regressions(directory, pagename, categories, htmlpages, regressionslist, unhandled_count):
            for regressionweb in regressionslist:
                if (pagename == 'all'):
                    categories['default']['entries'].append(regressionweb)
                elif regressionweb.page == pagename:
                    categories[regressionweb.category]['entries'].append(
                        regressionweb)

            tablecolumns = 3
            yattagdoc = yattag.Doc()
            yattagdoc.asis('<!DOCTYPE html>')
            with yattagdoc.tag('html'):
                outpage_header(yattagdoc, htmlpages, pagename)
                with yattagdoc.tag('h3'):
                    yattagdoc.text()
                with yattagdoc.tag('table', style="width:100%;"):
                    for category in categories.keys():
                        # print section header
                        outpage_table_span(
                            yattagdoc, categories[category]['desc'], tablecolumns, horizontal_rule=True, strong=True, )
                        # check if the list for this section is empty
                        if not categories[category]['entries']:
                            outpage_table_span(yattagdoc, "none", tablecolumns)
                        # add html
                        for regressionweb in categories[category]['entries']:
                            with yattagdoc.tag('tr', style="vertical-align:top;"):
                                yattagdoc.asis(
                                    regressionweb.htmlsnippet.getvalue())
                                if (pagename == 'all'
                                        or pagename == 'resolved'
                                        or pagename == 'dormant'):
                                    with yattagdoc.tag('td', style="width: 100px;"):
                                        yattagdoc.text(regressionweb.tree)
                outpage_footer(yattagdoc, unhandled_count)

            with open(os.path.join(directory, '%s.html' % pagename), 'w') as outputfile:
                outputfile.write(yattagdoc.getvalue())

        def create_page_unhandled(directory, htmlpages):
            yattagdoc = yattag.Doc()
            yattagdoc.asis('<!DOCTYPE html>')
            with yattagdoc.tag('html'):
                outpage_header(yattagdoc, htmlpages, None)

                rowcount, yattagrows = UnhandledEvent.getall_yattag(
                    yattag.Doc())
                if rowcount == 0:
                    yattagdoc.text("No unhandled events known as of now.")
                else:
                    with yattagdoc.tag('table', style="width:100%;"):
                        outpage_table_header_unhandled(yattagdoc)
                        yattagdoc.asis(yattagrows.getvalue())

                outpage_footer(yattagdoc, 0)

            # write out
            with open(os.path.join(directory, 'unhandled.html'), 'w') as outputfile:
                outputfile.write(yattagdoc.getvalue())

            return rowcount

        htmlpages = ('next', 'mainline', 'stable',
                     'unassociated', 'dormant', 'resolved', 'all')
        unhandled_count = create_page_unhandled(directory, htmlpages)
        regressionslist = RegressionFull.getall_html()

        # all
        regressionslist.sort(key=lambda x: x.gmtime_report, reverse=True)
        categories = {
            'default': {
                'desc': 'sorted by date of report',
                'entries': list(),
            }
        }
        create_page_regressions(
            directory, 'all', categories, htmlpages, regressionslist, unhandled_count)

        # all the other pages are sorted by activity
        regressionslist.sort(key=lambda x: x.gmtime_activity, reverse=True)

        # next
        categories = {
            'identified': {
                'desc': 'culprit identified',
                'entries': list(),
            },
            'default': {
                'desc': 'others',
                'entries': list(),
            },
        }
        create_page_regressions(
            directory, 'next', categories, htmlpages, regressionslist, unhandled_count)

        # mainline
        categories = {
            'curridentified': {
                'desc': "current development cycle, culprit identified",
                'entries': list(),
            },
            'identified': {
                'desc': "older development cycles, culprit identified",
                'entries': list(),
            },
            'new': {
                'desc': "reported in the past week, unkown culprit",
                'entries': list(),
            },
            'currrange': {
                'desc': "current development cycle, unkown culprit",
                'entries': list(),
            },
            'prevrange': {
                'desc': "previous development cycle, unkown culprit",
                'entries': list(),
            },
            'default': {
                'desc': "older development cycles, unkown culprit",
                'entries': list(),
            },
        }
        create_page_regressions(
            directory, 'mainline', categories, htmlpages, regressionslist, unhandled_count)

        # next
        categories = {
            'identified': {
                'desc': 'culprit identified',
                'entries': list(),
            },
            'default': {
                'desc': 'others',
                'entries': list(),
            },
        }
        create_page_regressions(
            directory, 'stable', categories, htmlpages, regressionslist, unhandled_count)

        categories = {
            'default': {
                'desc': None,
                'entries': list(),
            }
        }
        create_page_regressions(
            directory, 'unassociated', categories, htmlpages, regressionslist, unhandled_count)

        categories = {
            'default': {
                'desc': 'no activity in the past three weeks',
                'entries': list(),
            },
        }
        create_page_regressions(
            directory, 'dormant', categories, htmlpages, regressionslist, unhandled_count)

        categories = {
            'default': {
                'desc': None,
                'entries': list(),
            },
        }
        create_page_regressions(
            directory, 'resolved', categories, htmlpages, regressionslist, unhandled_count)

        logger.debug("webpages regenerated")


class UnhandledEvent():
    def __init__(self, unhanid, link, note, gmtime, regid, subject, solved_gmtime, solved_link, solved_subject):
        self.unhanid = unhanid
        self.link = link
        self.note = note
        self.gmtime = gmtime
        self.regid = regid
        self.subject = subject
        self.solved_gmtime = solved_gmtime
        self.solved_link = solved_link
        self.solved_subject = solved_subject

    @staticmethod
    def db_create(dbcursor, version):
        logger.debug('Initializing new dbtable "unhandled"')
        dbcursor.execute('''
            INSERT INTO meta
                VALUES(?, ?)''', ('unhandled', version, ))
        dbcursor.execute('''
            CREATE TABLE unhandled (
                unhanid         INTEGER  NOT NULL PRIMARY KEY,
                link            STRING   NOT NULL,
                note            STRING   NOT NULL,
                gmtime          INTEGER,
                regid           INTEGER,
                subject         STRING,
                solved_gmtime   INTEGER,
                solved_link     STRING,
                solved_subject  STRING
            )''')

    @staticmethod
    def add(link, note, gmtime=None, regid=None, subject=None):
        dbcursor = DBCON.cursor()
        dbcursor.execute('''INSERT INTO unhandled
            (link, note, gmtime, regid, subject)
            VALUES (?, ?, ?, ?, ?)''',
                         (link, note, gmtime, regid, subject))
        logger.debug('[db unhandled] insert (unhanid:%s, link:%s,  note:%s, gmtime:%s,regid:%s, subject:"%s")' % (
            dbcursor.lastrowid, link, note, gmtime, regid, subject))

    @staticmethod
    def dumpall_csv():
        for unhandled in UnhandledEvent.getall():
            yield unhandled.csv()

    def getall_yattag(yattagdoc):
        count = 0
        for unhandled in UnhandledEvent.getall():
            unhandled.html(yattagdoc)
            count += 1
        return count, yattagdoc

    def csv(self):
        return "%s, %s, %s, %s, %s, %s, %s, %s, %s" % (self.unhanid, self.link, self.note, self.gmtime, self.regid,
                                                       self.subject, self.solved_gmtime, self.solved_link, self.solved_subject)

    def html(self, yattagdoc):
        def cell1(yattagdoc):
            yattagdoc.text('%s' % self.unhanid)

        def cell2(yattagdoc):
            if self.subject is not None:
                subj = self.subject
            else:
                subj = self.link
            with yattagdoc.tag('div'):
                with yattagdoc.tag('a', href=self.link):
                    yattagdoc.text(subj)
                    # delta_filed = days_delta( self.gmtime)

            with yattagdoc.tag('div'):
                yattagdoc.text(self.note)

        # put everything together
        with yattagdoc.tag('tr', style="vertical-align:top;"):
            with yattagdoc.tag('td'):
                cell1(yattagdoc)
            with yattagdoc.tag('td'):
                cell2(yattagdoc)

    @staticmethod
    def getall():
        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM unhandled ORDER BY unhanid'):
            yield UnhandledEvent(*dbresult)


class ReportSource():
    def __init__(self, repsrcid, priority, name, serverurl, kind, weburl, identifiers, lastchked):
        self.repsrcid = repsrcid
        self.name = name
        self.serverurl = serverurl
        self.kind = kind
        self.weburl = weburl
        self.identifiers = identifiers
        self.lastchked = lastchked
        self.priority = priority

    def db_create(dbcursor, version):
        logger.debug('Initializing new dbtable "reportsources"')
        dbcursor.execute('''
            INSERT INTO meta
                VALUES(?, ?)''', ('reportsources', version, ))
        dbcursor.execute('''
            CREATE TABLE reportsources (
                repsrcid    INTEGER  NOT NULL PRIMARY KEY,
                priority    INTEGER  NOT NULL,
                name        STRING   NOT NULL,
                serverurl   STRING   NOT NULL,
                kind        STRING   NOT NULL,
                weburl      STRING   NOT NULL,
                identifiers STRING,
                lastchked   STRING
            )''')

    @staticmethod
    def add(name, priority, serverurl, kind, weburl, identifiers=None, lastchked=None):
        dbcursor = DBCON.cursor()
        dbcursor.execute('''INSERT INTO reportsources
            (name, serverurl, kind, priority, weburl, identifiers,  lastchked)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
                         (name, serverurl, kind, priority, weburl, identifiers, lastchked))
        logger.debug('[db reportsources] insert (repsrcid:%s, name:%s, serverurl:%s, kind:%s, priority:%s, weburl:%s, identifiers:%s, lastchked:%s)' % (
            dbcursor.lastrowid, name, serverurl, kind, priority, weburl, identifiers, lastchked))
        return dbcursor.lastrowid

    def delete(self):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute('''DELETE FROM reportsources
                                    WHERE repsrcid=(?)''',
                                    (self.repsrcid, ))
        logger.debug('[db reportsources] deleted entry (%s)', dbresult)
        return True

    @staticmethod
    def get_by_id(repsrcid):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM reportsources WHERE repsrcid=(?)', (repsrcid, )).fetchone()
        if dbresult:
            return ReportSource(*dbresult)
        return None

    @staticmethod
    def get_byweburl(url):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM reportsources WHERE weburl LIKE (?)', (url, )).fetchone()
        if dbresult:
            return ReportSource(*dbresult)
        return None

    @staticmethod
    def getall_bykind(kind):
        dbcursor = DBCON.cursor()
        for dbresult in dbcursor.execute('SELECT * FROM reportsources WHERE kind=(?) ORDER BY priority ASC', (kind, )):
            yield ReportSource(*dbresult)

    @staticmethod
    def getid_byname(name):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT repsrcid FROM reportsources WHERE name=(?)', (name, )).fetchone()
        return dbresult[0]

    @staticmethod
    def get_by_identifier(identifier):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM reportsources WHERE identifiers LIKE (?)', ('%%%s%%' % identifier, )).fetchone()
        if dbresult:
            return ReportSource(*dbresult)
        return None

    @staticmethod
    def get_by_serverurl(serverurl):
        dbcursor = DBCON.cursor()
        dbresult = dbcursor.execute(
            'SELECT * FROM reportsources WHERE serverurl LIKE (?)', (serverurl, )).fetchone()
        if dbresult:
            return ReportSource(*dbresult)
        return None

    @staticmethod
    def url_by_id(repsrcid, entry):
        repsrc = ReportSource.get_by_id(repsrcid)
        return repsrc.url(entry)

    def url(self, entry):
        if self.kind == 'lore':
            return '%s%s' % (self.weburl, entry)
        logger.critical(
            "ReportSource doesn't yet known how to return a URL for %s", self.kind)
        return None

    def set_lastchked(self, lastchked):
        self.lastchked = lastchked
        dbcursor = DBCON.cursor()
        dbcursor.execute('''UPDATE reportsources SET lastchked = (?) WHERE repsrcid=(?)''',
                         (self.lastchked, self.repsrcid))


def db_create(directory):
    def db_create_meta(dbcursor):
        logger.debug('Initializing new dbtable "meta"')
        dbcursor.execute('''
                CREATE TABLE meta (
                    name TEXT UNIQUE,
                    version INTEGER
            )''')

    def db_create_all(dbcursor):
        db_create_meta(dbcursor)
        RegActivityMonitor.db_create(dbcursor, 1)
        GitTree.db_create(dbcursor, 1)
        GitBranch.db_create(dbcursor, 1)
        RecordProcessedMsgids.db_create(dbcursor, 1)
        RegressionBasic.db_create(dbcursor, 1)
        RegActivityEvent.db_create(dbcursor, 1)
        RegHistory.db_create(dbcursor, 1)
        RegLink.db_create(dbcursor, 1)
        ReportSource.db_create(dbcursor, 1)
        UnhandledEvent.db_create(dbcursor, 1)

    dbcon = db_init(directory, create=True)
    if not dbcon:
        return dbcon

    dbcursor = DBCON.cursor()
    db_create_all(dbcursor)
    db_commit()
    return True


def db_commit():
    DBCON.commit()


def db_init(directory, create=False):
    dbfile = os.path.join(directory, 'database.db')
    if create:
        if os.path.isfile(dbfile):
            logger.warning(
                "Database file '%s' already exists, skipping creation" % dbfile)
            return False
    elif not os.path.isfile(dbfile):
        logger.warning("aborting, database file '%s' doesn't exist" % dbfile)
        return False

    global DBCON
    if DBCON is None:
        DBCON = sqlite3.connect(dbfile, sqlite3.PARSE_DECLTYPES)

    return DBCON


def db_close():
    global DBCON
    DBCON.close()
    DBCON = None


def db_rollback():
    DBCON.rollback()


def init_reposdir(directory):
    global REPOSDIR
    if REPOSDIR is None:
        REPOSDIR = os.path.join(directory)
    GitTree.check_latest_versions()
    return REPOSDIR


def days_delta(past):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromtimestamp(past, datetime.timezone.utc)).days


def parse_link(url):
    tmpstring = url

    if tmpstring.startswith("https://"):
        tmpstring = tmpstring.removeprefix("https://")
    elif tmpstring.startswith("http://"):
        tmpstring = tmpstring.removeprefix("http://")

    kind = mlist = msgid = None
    if (tmpstring.startswith("lore.kernel.org")
            or tmpstring.startswith("lkml.kernel.org")):
        split = tmpstring.split('/')
        if len(split) < 3:
            logger.warning(
                "Unable to parse '%s', non-standard format", url)
            return kind, mlist, msgid
        kind = split[0]
        mlist = split[1]
        msgid = split[2]

        if mlist == 'r':
            if tmpstring.startswith("lkml.kernel.org"):
                mlist = 'lkml'
            else:
                # FIXMELATER: this is the lore redirector; for now just assume it redirecting to LKML, which likely needs fixing later
                mlist = 'lkml'
    else:
        logger.debug(
            "Tried to get msgid from %s, but don't known how to handle that domain", url)
    return kind, mlist, msgid


def basicressources_get_dirs(directory):
    if directory:
        databasedir = os.path.join(directory, 'database')
        gittreesdir = os.path.join(directory, 'gittrees')
        websitesdir = os.path.join(directory, 'websites')
    else:
        homedir = pathlib.Path.home()
        databasedir = os.path.join(homedir, '.local/share/regzbot/')

        cachedir = os.path.join(homedir, '.cache/regzbot/')
        gittreesdir = os.path.join(cachedir, 'gittrees')
        websitesdir = os.path.join(cachedir, 'websites')
    return databasedir, gittreesdir, websitesdir


def basicressource_checkdir_exists(directory, create=False):
    try:
        if os.path.exists(directory):
            return True
        elif create is True:
            os.mkdir(directory)
            return True
        else:
            return False
    except Exception:
        return None


def basicressources_setup(directory=None):
    databasedir, gittreesdir, websitesdir = basicressources_get_dirs(directory)
    if not basicressource_checkdir_exists(databasedir, create=True):
        logger.error("Aborting, directory '%s' exist already." % databasedir)
        sys.exit(1)

    if db_create(databasedir):
        logger.info("Database created in %s" % databasedir)
    else:
        sys.exit(1)

    if directory:
        # until below hardcoding is solved, return here if a directory is specified, as that is only possible
        # when testing – and the testing code will handle all this properly
        return

    # FIXMELATER: we should clone these ourselves, but for now leave that task to the user
    for gittreedir in (os.path.join(gittreesdir, 'mainline'),
                       os.path.join(gittreesdir, 'next'),
                       os.path.join(gittreesdir, 'stable'),
                       ):
        if not basicressource_checkdir_exists(gittreedir, create=False):
            logger.error(
                "Aborting, as the directory '%s' does not exist yet; please create it and check clone the appropriate Linux tree into it." % gittreedir)
            sys.exit(1)

        gitdir = os.path.join(gittreedir, '.git')
        if not basicressource_checkdir_exists(gitdir, create=False):
            logger.error(
                "Aborting, as the directory '%s' appears to not contain a git tree." % gittreedir)
            sys.exit(1)

    # hardcoded for now
    ReportSource.add('lkml', 1,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-kernel',
                     'lore', 'https://lore.kernel.org/lkml/',
                     lastchked=4097114)
    ReportSource.add('regressions', 2,
                     'nntp://nntp.lore.kernel.org/dev.linux.lists.regressions',
                     'lore', 'https://lore.kernel.org/regressions/',
                     lastchked=190)
    ReportSource.add('netdev', 3,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.netdev',
                     'lore', 'https://lore.kernel.org/netdev/',
                     lastchked=799255)
    ReportSource.add('wireless', 4,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-wireless',
                     'lore', 'https://lore.kernel.org/linux-wireless/',
                     lastchked=214156)
    ReportSource.add('arm', 3,
                     'nntp://nntp.lore.kernel.org/org.infradead.lists.linux-arm-kernel',
                     'lore', 'https://lore.kernel.org/linux-arm-kernel/',
                     lastchked=844111)
    ReportSource.add('dri', 3,
                     'nntp://nntp.lore.kernel.org/org.freedesktop.lists.dri-devel',
                     'lore', 'https://lore.kernel.org/dri-devel/',
                     lastchked=329247)
    ReportSource.add('fsdevel', 3,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-fsdevel',
                     'lore', 'https://lore.kernel.org/linux-fsdevel/',
                     lastchked=213946)
    ReportSource.add('scsi', 3,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-scsi',
                     'lore', 'https://lore.kernel.org/linux-scsi/',
                     lastchked=172549)
    ReportSource.add('pm', 5,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-pm',
                     'lore', 'https://lore.kernel.org/linux-pm/',
                     lastchked=152570)
    ReportSource.add('pci', 5,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-pci',
                     'lore', 'https://lore.kernel.org/linux-pci/',
                     lastchked=100908)
    ReportSource.add('mips', 3,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-mips',
                     'lore', 'https://lore.kernel.org/linux-mips/',
                     lastchked=110188)
    ReportSource.add('ppc-dev', 3,
                     'nntp://nntp.lore.kernel.org/org.ozlabs.lists.linuxppc-dev',
                     'lore', 'https://lore.kernel.org/linuxppc-dev/',
                     lastchked=263995)
    ReportSource.add('alsa', 5,
                     'nntp://nntp.lore.kernel.org/org.alsa-project.alsa-devel',
                     'lore', 'https://lore.kernel.org/alsa-devel/',
                     lastchked=232899)
    ReportSource.add('usb', 5,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-usb',
                     'lore', 'https://lore.kernel.org/linux-usb/',
                     lastchked=51156)
    ReportSource.add('media', 5,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-media',
                     'lore', 'https://lore.kernel.org/linux-media/',
                     lastchked=209904)
    ReportSource.add('i2c', 5,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-i2c',
                     'lore', 'https://lore.kernel.org/linux-i2c/',
                     lastchked=53681)
    ReportSource.add('platform-driver-x86', 5,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.platform-driver-x86',
                     'lore', 'https://lore.kernel.org/platform-driver-x86/',
                     lastchked=27184)
    ReportSource.add('hwmon', 6,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-hwmon',
                     'lore', 'https://lore.kernel.org/linux-hwmon/',
                     lastchked=12573)
    ReportSource.add('input', 6,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-input',
                     'lore', 'https://lore.kernel.org/linux-input/',
                     lastchked=77074)
    ReportSource.add('edac', 6,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-edac',
                     'lore', 'https://lore.kernel.org/linux-edac/',
                     lastchked=6764)
    ReportSource.add('crypto', 6,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-crypto',
                     'lore', 'https://lore.kernel.org/linux-crypto/',
                     lastchked=58684)
    ReportSource.add('iio', 6,
                     'nntp://nntp.lore.kernel.org/org.kernel.vger.linux-iio',
                     'lore', 'https://lore.kernel.org/linux-iio/',
                     lastchked=63102)

    # hardcoded for now, too
    GitTree.add('mainline', 'https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/',
                'cgit', 'https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/',  'master')
    GitTree.add('next', 'https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/',
                        'cgit', 'https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/commit/', 'master')
    GitTree.add('stable', 'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git', 'cgit',
                'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/', r'linux-[0-9][0-9]*.[0-9][0-9]*\.y')
    GitTree.add('stable', 'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git', 'cgit',
                'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/', r'linux-[0-9][0-9]*.[0-9][0-9]*\.y')

    gittree = GitTree.get_by_name('mainline')
    GitBranch.add(gittree, 'master',
                  '73f3af7b4611d77bdaea303fb639333eb28e37d7')

    gittree = GitTree.get_by_name('next')
    GitBranch.add(gittree, 'master',
                  '7636510f976d75b860848884169ba985c8f844d8')

    gittree = GitTree.get_by_name('stable')
    GitBranch.add(gittree, 'linux-4.4.y',
                  'c13f051b7fc041d3163a96b10441b421ddecd123')
    GitBranch.add(gittree, 'linux-4.9.y',
                  '89a3a5a52bc58d04109f03011e8164ce24e94b01')
    GitBranch.add(gittree, 'linux-4.14.y',
                  '162b95d01320370b80cb2d5724cea4ae538ac740')
    GitBranch.add(gittree, 'linux-4.19.y',
                  '59456c9cc40c8f75b5a7efa0fe1f211d9c6fcaf1')
    GitBranch.add(gittree, 'linux-5.4.y',
                  'c15b830f7c1cafd34035a46485716933f66ab753')
    GitBranch.add(gittree, 'linux-5.10.y',
                  '2c5bd949b1df3f9fb109107b3d766e2ebabd7238')
    GitBranch.add(gittree, 'linux-5.13.y',
                  'f428e49b8cb1fbd9b4b4b29ea31b6991d2ff7de1')

    # run this once, to make sure all gitbraches db entries get created
    basicressources_init()
    GitTree.updateall()

    db_commit()


def basicressources_init(directory=None):
    databasedir, gittreesdir, websitesdir = basicressources_get_dirs(directory)

    dbconnection = db_init(databasedir)
    if not dbconnection:
        logger.debug('aborting: dbconnection could not be initialized')
        sys.exit(1)

    reposdir = init_reposdir(gittreesdir)
    if not reposdir:
        logger.debug('aborting: reposdir could not be initialized')
        sys.exit(1)

    basicressource_checkdir_exists(websitesdir, create=True)

    global WEBPAGEDIR
    WEBPAGEDIR = websitesdir


def set_citesting(kind):
    # needed for:
    # * webui testing, otherwise everything lands on the dormant page...
    # * monitor commands, as they otherwise try to download things from the web

    global __CITESTING__
    __CITESTING__ = kind


def is_running_citesting_offline():
    if __CITESTING__ == "offline":
        return True
    return False


def run():
    # check for new mails
    import lore
    lore.run()
    db_commit()

    GitTree.updateall()
    db_commit()

    RegressionWeb.create_htmlpages(WEBPAGEDIR)

    db_close()
    logger.info("The End")


def download_msg(msgid):
    return lore.download_msg(msgid)


def process_msg(msgid):
    repsrc, msg = download_msg(msgid)
    return mailin.process_msg(repsrc, msg)


def checksource(identifier):
    return lore.checksource(identifier)


def inspectobj(obj):
    for att in dir(obj):
        try:
            ref = getattr(obj, att)
            print("%s: %s  (%s)" % (att, getattr(obj, att), type(ref)))
        except Exception:
            print("ERROR: inspection of %s.%s failed" % (type(obj), att))
