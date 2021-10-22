#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import datetime
import regzbot
import re
logger = regzbot.logger

class RegLinkMailReport(regzbot.RegLink):
    def __init__(self, *args):
        super().__init__(*args)

    def mailreport(self):
        monitored = ''
        if self.repsrcid \
                and self.entry \
                and regzbot.RegActivityMonitor.ismonitored(
                        self.entry, self.regid, self.repsrcid):
             monitored = ' [monitored]'

        return('* %s\n  %s\n  %s days ago, by %s%s' % (self.subject, self.link, regzbot.days_delta(self.gmtime), self.author, monitored))

class RegressionMailReport(regzbot.RegressionFull):
    Reglink = RegLinkMailReport

    def __init__(self, *args):
        super().__init__(*args)
       
    def compile(self):
        compiled = list()
        compiled.append(self.subject)
        compiled.append('-'*len(self.subject))
        compiled.append('')
        compiled.append(self.report_url)
        compiled.append("%s days ago, by %s" % (regzbot.days_delta(self.gmtime), self.author))
        compiled = self.add_introduced(compiled)
        compiled.append('')
        compiled.append('Oldest and latest activity: %s and %s days ago:'
                   % (regzbot.days_delta(self._actievents[0].gmtime), regzbot.days_delta(self._actievents[-1].gmtime)))
        compiled.append('https://linux-regtracking.leemhuis.info/regzbot/all.html#%s' % regzbot.urlencode(self.entry))
        compiled = self.add_links(compiled)
        compiled.append('')
        return compiled

    def add_introduced(self, compiled):
        presentable = ''
        if self._introduced_presentable:
             presentable = ' (%s)' % self._introduced_presentable
        compiled.append('Introduced in %s%s' % (self._introduced_short, presentable))
        return compiled

    def add_links(self, compiled):
        if not self._links:
            return compiled

        compiled.append('\nRelated:')
        for link in self._links:
            compiled.append(link.mailreport())
        return compiled

    def dump(self):
        return('\n'.join(self.compile()))



class RegExportMailReport():
    def __init__(self, entry, gmtime_report, gmtime_filed, gmtime_activity, treename, reporttext):
        self.entry = entry
        self.gmtime_report = gmtime_report
        self.gmtime_filed = gmtime_filed
        self.gmtime_activity = gmtime_activity
        self.treename = treename
        self.reporttext = reporttext

    @classmethod
    def get_all_categorized(cls, only_unsolved = True):
        categories = {
            'new': {
                'desc': 'tracked less than a week',
                'entries': list(),
            },
            'identified_indevelopment': {
                'desc': "current cycle, culprit identified",
                'entries': list(),
            },
            'unidentified_indevelopment': {
                'desc': "current cycle, unkown culprit",
                'entries': list(),
            },
            'identified_latest': {
                'desc': "previous cycle, culprit identified, activity in the past four weeks",
                'entries': list(),
            },
            'unidentified_latest': {
                'desc': "previous cycle, unkown culprit, activity in the past four weeks",
                'entries': list(),
            },
            'identified_previous': {
               'desc': "older cycles, culprit identified, with activity in the past two weeks",
               'entries': list(),
            },
            'unidentified_previous': {
               'desc': "older cycles, culprit identified, with activity in the past two weeks",
               'entries': list(),
            },
            'identified': {
               'desc': "older cycles, culprit identified, with activity in the past three months",
               'entries': list(),
            },
            'default': {
                'desc': 'tracked by less than a week, with activity in the past three months',
                'entries': list(),
            },
        }

        for regression in RegressionMailReport.get_all(only_unsolved=only_unsolved):
            last_activity_days = regzbot.days_delta(regression._actievents[-1].gmtime)
            filed_days = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromtimestamp(regression.gmtime_filed, datetime.timezone.utc)).days

            # ignore some
            if regression.treename != 'mainline':
                # for now only generate reports for mainline
                continue
            elif last_activity_days > 91:
                # ignore due to inactivity for ~three months
                continue

            # okay, we care about this one
            regexport = cls(regression.entry, regression.gmtime, regression.gmtime_filed, regression._actievents[-1].gmtime,
                                    regression.treename, regression.dump())
            if filed_days < 7:
                categories['new']['entries'].append(regexport)
            elif regression.versionline == 'indevelopment':
                if regression.identified:
                       categories['identified_indevelopment']['entries'].append(regexport)
                else:
                       categories['unidentified_indevelopment']['entries'].append(regexport)
            elif regression.versionline == 'latest' and last_activity_days < 21:
                if regression.identified:
                       categories['identified_latest']['entries'].append(regexport)
                else:
                       categories['unidentified_latest']['entries'].append(regexport)
            elif regression.versionline == 'previous' and last_activity_days < 21:
                if regression.identified:
                       categories['identified_previous']['entries'].append(regexport)
                else:
                       categories['unidentified_previous']['entries'].append(regexport)
            elif regression.identified:
                categories['identified']['entries'].append(regexport)
            else:
                categories['default']['entries'].append(regexport)

        return categories


def main():
    categories = RegExportMailReport.get_all_categorized(only_unsolved=True)
    for category in categories.keys():
        if not categories[category]['entries']:
            # nothing to do
            continue

        print(categories[category]['desc'])
        print('='*len(categories[category]['desc']))
        print('\n')

        categories[category]['entries'].sort(key=lambda x: x.gmtime_report, reverse=True)
        for regexportreport in categories[category]['entries']:
            print(regexportreport.reporttext)
            print('')
