#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2023 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'


import re

import regzbot._rbcmd as rbcmd


class _activity():
    def __str__(self):
        return _describe(self, ('created_at', 'message', 'realname', 'summary', 'username', 'web_url'))


class _issue():
    def __str__(self):
        return _describe(self, ('created_at', 'message', 'realname', 'state', 'title', 'username', 'web_url'))

    def scan(self, since):
        def _scan_commands(body):
            for foo in re.finditer('^(#regzbot ).*$', body, re.MULTILINE):
                print(body, foo)
        
        _scan_command(self.message)
        for activity in self.get_activities():
            _contains_command(activity.message)
            


class _project():
    def scan(self, since):
        # 
        # FIXME: check for updates
        #
        
        for searchresult in self.search('#regzbot', since):
            # 
            # FIXME: ignore if issue is tracked already
            #

            issue = searchresult.issue
            issue.scan(since)

class _possible_search_result():
    def __init__(self, issue_id, pattern, since):
        self.issue_id = issue_id
        self._pattern = pattern
        self._since = since

    def __str__(self):
        return _describe(self, ('issue', 'issue_id'))

    def _check_pattern(self, body):
        return bool(re.search(self._pattern, body))

    def is_hit_in_submission(self):
        return False

    def get_matching_activities(self):
        for activity in self.issue.get_activities(since=self._since):
            if self._check_pattern(activity.message):
                yield activity

    # meant only for testing infra
    def _get_hits(self):
        if self.is_hit_in_submission():
            yield self.issue
        for hit in self.get_matching_activities():
            yield hit


def _describe(obj, variable_names):
    content = []
    for variable_name in variable_names:
        # handle normal variables and  properties:
        if variable_name in obj.__dict__:
            value = obj.__dict__[variable_name]
        else:
            value_getter = getattr(obj.__class__, variable_name)
            value = value_getter.__get__(obj, obj.__class__)

        if type(value) is str:
            value = value.replace('\r', ' ')
            value = value.replace('\n', ' ')
            if len(value) > 79:
                value = '%s…' % value[0:79]
        content.append("'%s': '%s'" % (variable_name, value))
    return str(obj.__class__) + ' => {' + ', '.join(content) + '}'
