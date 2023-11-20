#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2023 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import datetime
import gitlab
import sys
import urllib.parse
from functools import cached_property

import _trackers._base
import regzbot._rbcmd
from regzbot import PatchKind

if __name__ != "__main__":
    import regzbot
    logger = regzbot.logger
else:
    import logging
    logger = logging
    #if False:
    if True:
        logger.basicConfig(level=logging.DEBUG)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

_CACHE_INSTANCES = {}
_CACHE_PROJECTS ={}

class GlActivity(_trackers._base._activity):
    def __init__(self, gl_issue, *, comment=None, comment_number=None, commit=None, event=None):
        self._gl_issue = gl_issue

        self.id = None
        self.patchkind = 0
        summary_prefix = '%s, issue %s' % (self._gl_issue.gl_project.longname, self._gl_issue.id)

        if not any((comment, commit, event)):
            self.created_at = self._gl_issue.created_at
            self.message = self._gl_issue.message
            self.realname = self._gl_issue.realname
            self.summary = '%s: creation' % summary_prefix
            self.username = self._gl_issue.username
            self.web_url = self._gl_issue.web_url
        elif comment:
            self.created_at = datetime.datetime.fromisoformat(comment.created_at)
            self.comment_id = comment.id
            self.message = comment.body
            self.realname = comment.author['name']
            if commit:
                self.patchkind = PatchKind.getby_commit_header(commit.message)
                self.summary = '%s: gitlab noticed a commit referencing this issue' % summary_prefix
            else:
                self.summary = '%s: new comment' % summary_prefix
                if comment_number:
                    self.summary = self.summary + '(#%s)' % comment_number
            self.username = comment.author['username']
            self.web_url = '%s#note_%s' % (self._gl_issue.web_url, self.comment_id)
        elif event:
            self.created_at = datetime.datetime.fromisoformat(event.created_at)
            self.message = ''
            self.realname = event.user['name']
            self.summary = "%s: state changed to: %s" % (summary_prefix, event.state)
            self.username = event.user['username']
            self.web_url = self._gl_issue.web_url
        else:
            logger.critical('[gitlab] GlActivity called with something unknown; aborting.')
            sys.exit(1)

        # do this at the end, as it will perfor
        super().__init__()


class GlInstance():
    def __init__(self, netloc, token):
        logger.debug('[gitlab] %s: connecting', netloc)
        self._glpy_instance = gitlab.Gitlab('https://%s' % netloc, token)
        self.web_url = netloc

    def project(self, project_name):
        global _CACHE_PROJECTS
        if project_name not in _CACHE_PROJECTS:
            logger.debug('[gitlab] %s: opening project %s', self.web_url, project_name)
            _CACHE_PROJECTS[project_name] = GlProject(self, self._glpy_instance.projects.get(project_name))
        return _CACHE_PROJECTS[project_name]


class GlIssue(_trackers._base._issue):
    def __init__(self, gl_project, glpy_issue):
        self.gl_project = gl_project
        self._glpy_issue = glpy_issue

        self.created_at = datetime.datetime.fromisoformat(glpy_issue.created_at)
        self.id = glpy_issue.iid
        self.message = glpy_issue.description
        self.realname = glpy_issue.author['name']
        self.state = glpy_issue.state
        self.summary = glpy_issue.title
        self.username = glpy_issue.author['username']
        self.web_url = glpy_issue.web_url

        # it can easily happen that we need them multiple times; cache them
        self.__acitivities = []

        super().__init__()

    def activities(self, *, since=None):
        def _get_commit(comment):
            # ohh boy, there must be a better way to do this, but I looked hard and did not find one :-/
            if type(comment.body) is set and comment.body[0] == 'mentioned in commit ':
                commit_def = comment.body[1]
            elif comment.body.startswith("mentioned in commit "):
                commit_def = comment.body[20:]
            else:
                return None

            if '@' in commit_def:
                projectname, hexsha = commit_def.split('@')
                if '/' not in projectname:
                    projectname = '%s/%s' % (self.gl_project.namespace_path, projectname)
                gl_instance = self.gl_project.gl_instance
                project = gl_instance.project(projectname)
            else:
                hexsha = commit_def
                project = self.gl_project
            return project.commit(hexsha)

        # walk comments (and thus commits) first, then events; that they will be raised out
        # of order is not a problem for now
        if not self.__acitivities:
            self.__acitivities.append(GlActivity(self))

            logger.debug('[gitlab] %s: retrieving comments', self.web_url[8:])
            comment_counter = 0
            for comment in self._glpy_issue.notes.list(sort='asc', iterator=True):
                commit = _get_commit(comment)
                # ignore all other system notes (e.g. notes about changes to the object, like
                # assignee changes or changes to the issue's description)
                if not commit and comment.system:
                    continue
                if not commit:
                    comment_counter += 1
                self.__acitivities.append(GlActivity(self, comment=comment, comment_number=comment_counter, commit=commit))

            logger.debug('[gitlab] %s: retrieving events', self.web_url[8:])
            for event in self._glpy_issue.resourcestateevents.list(sort='asc', iterator=True):
                self.__acitivities.append(GlActivity(self, event=event))

        for activity in self.__acitivities:
            if since and activity.created_at < since:
                continue
            yield activity


class GlProject(_trackers._base._project):
    def __init__(self, gl_instance, glpy_project):
        self.gl_instance = gl_instance
        self._glpy_project = glpy_project

    @cached_property
    def web_url(self):
        return self._glpy_project.web_url

    @property
    def namespace_path(self):
        return self._glpy_project.namespace['path']

    @property
    def longname(self):
        return self._glpy_project.path_with_namespace

    def issue(self, *, id=None, url=None):
        assert any((id, url))
        if url:
            id = url.removeprefix('%s/-/issues/' % self.web_url)
        logger.debug('[gitlab] %s: retrieving issue %s', self.web_url[8:], id)
        issue = self._glpy_project.issues.get(id)
        return GlIssue(self, issue)

    def commit(self, hexsha):
        logger.debug('[gitlab] %s: retrieving commit %s', self.web_url[8:], hexsha)
        return self._glpy_project.commits.get(hexsha)

    def threads_updated(self, since):
        logger.debug('[gitlab] %s: retrieving issues updated since %s', self.web_url[8:], since)
        for issue in self._glpy_project.issues.list(iterator=True, order_by='updated_at', updated_after=since):
            yield GlIssue(self, issue)

    def search(self, pattern, since):
        additional_msg = ''
        if since:
            additional_msg = ' submitted after %s' % since
        logger.debug("[gitlab] %s: searching for '%s' in issues%s", self.web_url[8:], pattern, additional_msg)
        for searchresult in self._glpy_project.search(gitlab.const.SearchScope.ISSUES, pattern, order_by='updated_at', sort='asc', iterator=True):
            if datetime.datetime.fromisoformat(searchresult['created_at']) < since:
                continue
            yield GlPossibleSearchHit(self, searchresult['iid'], pattern, since, is_hit_in_submission=True)
        logger.debug("[gitlab] %s: searching for '%s' in comments%s", self.web_url[8:], pattern, additional_msg)
        for searchresult in self._glpy_project.search(gitlab.const.SearchScope.PROJECT_NOTES, pattern, order_by='updated_at', sort='asc', iterator=True):
            if datetime.datetime.fromisoformat(searchresult['created_at']) < since:
                continue
            yield GlPossibleSearchHit(self, searchresult['noteable_iid'], pattern, since)


class GlPossibleSearchHit(_trackers._base._possible_search_result):
    def __init__(self, gl_project, issue_id, pattern, since, *, is_hit_in_submission=False):
        self._gl_project = gl_project
        self._issue = None
        self._hit_in_submission = is_hit_in_submission
        super().__init__(issue_id, pattern, since)

    @property
    def issue(self):
        if not self._issue:
            self._issue = self._gl_project.issue(self.issue_id)
        return self._issue

    def is_hit_in_submission(self):
        return self._hit_in_submission


class GlRepAct(regzbot.ReportActivity):
    def __init__(self, reptrd, gl_acivitiy):
        self.reptrd = reptrd
        self._gl_acivitiy = gl_acivitiy

        self.created_at = gl_acivitiy.created_at
        self.id = gl_acivitiy.id
        self.gmtime = int(gl_acivitiy.created_at.timestamp())
        self.message = gl_acivitiy.message
        self.patchkind = gl_acivitiy.patchkind
        self.realname = gl_acivitiy.realname
        self.summary = gl_acivitiy.summary
        self.username = gl_acivitiy.username

        super().__init__()


class GlRepSrc(regzbot.ReportSource):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @cached_property
    def _gl_project(self):
        parsed_url = urllib.parse.urlparse(self.serverurl)
        instance_name = parsed_url.netloc
        project_name = parsed_url.path.strip("/")

        instance = connect(instance_name)
        project = instance.project(project_name)
        assert self.serverurl == project.web_url
        return project

    def supports_url(self, url):
        if url.startswith(self.serverurl):
            return True

    def thread(self, *, id=None, url=None):
        gl_issue = self._gl_project.issue(id=id, url=url)
        return GlRepTrd(self, gl_issue)


class GlRepTrd(regzbot.ReportThread):
    def __init__(self, repsrc, gl_issue):
        self.repsrc = repsrc
        self._gl_issue = gl_issue

        self.created_at = gl_issue.created_at
        self.id = gl_issue.id
        self.gmtime = int(gl_issue.created_at.timestamp())
        self.message = gl_issue.message
        self.realname = gl_issue.realname
        self.summary = gl_issue.summary
        self.username = gl_issue.username
        super().__init__()

    def activities(self):
        for activity in self._gl_issue.activities():
            yield GlRepAct(self, activity)


def connect(instance_name):
    global _CACHE_INSTANCES
    if instance_name not in _CACHE_INSTANCES:
        _CACHE_INSTANCES[instance_name] = GlInstance(instance_name, regzbot.CONFIGURATION[instance_name]['token'])
    return _CACHE_INSTANCES[instance_name]


def __test():
    # main issue used for testing (chosen without much thought): https://gitlab.freedesktop.org/drm/intel/-/issues/8357
    TESTDATA = {
        'project': 'https://gitlab.freedesktop.org/drm/intel',
        'issue': {
            'total': 17,
            'issue_id': 8357,
            'expected': '''<class '__main__.GlIssue'> => {'created_at': '2023-04-11 16:17:04.368000+00:00', 'message': 'I'm working on a "hatch/jinlon" Chromebook which is a Cometlake-U device, and h…', 'realname': 'Ross Zwisler', 'state': 'closed', 'summary': 'CML-U: external 5120x2160 monitor can't play video', 'username': 'zwisler', 'web_url': 'https://gitlab.freedesktop.org/drm/intel/-/issues/8357'}'''
        },
        'comments_recent': {
            'since': datetime.datetime.fromisoformat('2023-04-18T16:37:00.000Z'),
            'expected': '''<class '__main__.GlActivity'> => {'created_at': '2023-04-18 16:37:48.523000+00:00', 'message': '[0001-drm-i915-Check-pipe-source-size-when-using-skl-scale.patch](/uploads/d3b7…', 'realname': 'Ville Syrjälä', 'summary': 'New comment', 'username': 'vsyrjala', 'web_url': 'https://gitlab.freedesktop.org/drm/intel/-/issues/8357#note_1873234'}'''
        },
        'commits_recent': {
            'since': datetime.datetime.fromisoformat('2023-05-06T00:00:00.000Z'),
            'expected': '''<class '__main__.GlActivity'> => {'created_at': '2023-05-17 19:20:40.224000+00:00', 'message': 'mentioned in commit superm1/linux@74a03d3c8d895a7d137bb4be8e40cae886f5d973', 'realname': 'Ville Syrjälä', 'summary': 'Commit referenced this issue', 'username': 'vsyrjala', 'web_url': 'https://gitlab.freedesktop.org/drm/intel/-/issues/8357#note_1912677'}'''
        },
        'search_since': {
            'pattern': '805f04d42a6b5f4187935b43c9c39ae03ccfa761',
            'date': datetime.datetime.fromisoformat('2022-08-27T00:00:01.00Z'),
            'total': 2,
        },
        'search_comment': {
            'pattern': '805f04d42a6b5f4187935b43c9c39ae03ccfa761',
            'total': 1,
            'since': datetime.datetime.fromisoformat('2022-08-27 00:00:01+00:00'),
            'expected': '''<class '__main__.GlActivity'> => {'created_at': '2022-08-27 13:26:12+00:00', 'message': 'After taking the twelve ehm 15 step program :D  $ git bisect log - bad: [f2906a…', 'realname': 'JackCasual', 'summary': 'New comment', 'username': 'JackCasual', 'web_url': 'https://gitlab.freedesktop.org/drm/intel/-/issues/6652#note_1526397'}'''
        },
        'search_issue': {
            'pattern': '805f04d42a6b5f4187935b43c9c39ae03ccfa761',
            'since': datetime.datetime.fromisoformat('2022-08-26 00:00:01+00:00'),
            'total': 2,
            'expected': '''<class '__main__.GlIssue'> => {'created_at': '2022-08-26 04:24:15.380000+00:00', 'message': 'I have a new Framework Laptop with an i7-1280P and Xe graphics, running Debian …', 'realname': 'Brian Tarricone', 'state': 'closed', 'summary': '[regression] [bisected] Mouse cursor stuttering/jerkiness on Alder Lake with 5.…', 'username': 'kelnos', 'web_url': 'https://gitlab.freedesktop.org/drm/intel/-/issues/6679'}'''
        },
        'search_days_updated': 1
    }

    def _testing_check_result(kind, value, expected):
        if value == expected:
            print(' %s' % kind, flush=True, end='')
            return
        elif not expected:
            print(" %s (unknown, apparently '%s')" % (kind, value))
            return
        else:
            print('\n%s: mismatch; expected vs retrieved view:\n%s\n%s' % (kind, expected, value))
            if len(sys.argv) < 3 or sys.argv[2] != '--warn':
                print(" Aborting.")
                sys.exit(1)

    # = setup =

    # no need for argparse here, it's just for development anyway
    if len(sys.argv) < 2:
        print("call '$0 <gitlab apikey>'")
        sys.exit(1)
    elif len(sys.argv[1]) != 26:
        print('apikey looks malformed')
        sys.exit(1)

    parsed_url = urllib.parse.urlparse(TESTDATA['project'])
    name_instance = parsed_url.netloc
    name_project = parsed_url.path.strip("/")
    instance = GlInstance(name_instance, sys.argv[1])
    project = instance.project(name_project)

    # = go =
    print("Checking basic issue:", flush=True, end='')
    issue = project.issue(TESTDATA['issue']['issue_id'])
    _testing_check_result('data', str(issue), TESTDATA['issue']['expected'])
    _testing_check_result('total', len(list(issue.activities())),
                          TESTDATA['issue']['total'])
    print("; succeeded.")

    print("Checking a comment:", flush=True, end='')
    for comment in issue.activities(since=TESTDATA['comments_recent']['since']):
        _testing_check_result('firsthit', str(comment), TESTDATA['comments_recent']['expected'])
        break
    print("; succeeded.")

    print("Checking a commit:", flush=True, end='')
    for commit in issue.activities(since=TESTDATA['commits_recent']['since']):
        _testing_check_result('firsthit', str(commit), TESTDATA['commits_recent']['expected'])
        break
    print("; succeeded.")

    if 'search_since' in TESTDATA:
        print("Checking search:", flush=True, end='')
        results_search_broad = []
        for result in project.search(TESTDATA['search_since']['pattern'], datetime.datetime.fromisoformat('2020-01-01T00:00:00.00Z')):
            for hit in result._get_hits():
                results_search_broad.append(hit)
        results_search_narrow = []
        for result in project.search(TESTDATA['search_since']['pattern'], TESTDATA['search_since']['date']):
            for hit in result._get_hits():
                results_search_narrow.append(hit)
        _testing_check_result('total', len(results_search_broad), TESTDATA['search_since']['total'])
        _testing_check_result('difference', len(results_search_broad) - len(results_search_narrow), 1)
        print("; succeeded.")

    if 'search_comment' in TESTDATA:
        print("Checking search (pattern in comment):", flush=True, end='')
        results_search_comments = []
        for result in project.search(TESTDATA['search_comment']['pattern'], since=TESTDATA['search_comment']['since']):
            for hit in result._get_hits():
                results_search_comments.append(hit)
        _testing_check_result('firsthit', str(results_search_comments[0]), TESTDATA['search_comment']['expected'])
        _testing_check_result('total', len(results_search_comments), TESTDATA['search_comment']['total'])
        print("; succeeded.")

    if 'search_issue' in TESTDATA:
        print("Checking search (pattern in issue):", flush=True, end='')
        results_search_issue = []
        for result in project.search(TESTDATA['search_issue']['pattern'], since=TESTDATA['search_issue']['since']):
            for hit in result._get_hits():
                results_search_issue.append(hit)
        _testing_check_result('firsthit', str(results_search_issue[0]), TESTDATA['search_issue']['expected'])
        _testing_check_result('total', len(results_search_issue), TESTDATA['search_issue']['total'])
        print("; succeeded.")

    print('All issues updated in the past %s days:' % TESTDATA['search_days_updated'])
    since = datetime.datetime.now() - datetime.timedelta(days=TESTDATA['search_days_updated'])
    for issue in project.threads_updated(since):
        print('', issue.web_url, issue.summary[0:80])


if __name__ == "__main__":
    __test()
