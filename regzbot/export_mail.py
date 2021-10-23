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
        compiled.append('https://linux-regtracking.leemhuis.info/regzbot/regression/%s/' % regzbot.urlencode(self.entry))
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

    def mailreport(self):
        return('\n'.join(self.compile()))



class RegExportMailReport():
    def __init__(self, entry, gmtime_report, gmtime_filed, gmtime_activity, treename, versionline, identified, reporttext):
        self.entry = entry
        self.gmtime_report = gmtime_report
        self.gmtime_filed = gmtime_filed
        self.gmtime_activity = gmtime_activity
        self.treename = treename
        self.versionline = versionline
        self.identified = identified
        self.reporttext = reporttext


    @classmethod
    def pagecreate(cls, categories):
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


    @classmethod
    def categorize(cls, regressionlist):
        categories = {
            'new': {
                'next': {
                   'desc': "next",
                   'entries': list(),
                },
                'mainline': {
                   'desc': "mainline",
                   'entries': list(),
                },
                'stable': {
                    'desc': 'stable/longterm',
                    'entries': list(),
                },
            },
            'next': {
                'identified': {
                   'desc': "culprit identified",
                   'entries': list(),
                },
                'default': {
                    'desc': 'culprit unkown',
                    'entries': list(),
                },
            },
            'mainline': {
                'identified_indevelopment': {
                    'desc': "current cycle (%s.. aka %s-rc), culprit identified" % (regzbot.LATEST_VERSIONS['latest'], regzbot.LATEST_VERSIONS['indevelopment']),
                    'entries': list(),
                },
                'identified_latest': {
                    'desc': "previous cycle (%s..%s), culprit identified, with activity in the past three weeks" % (regzbot.LATEST_VERSIONS['previous'], regzbot.LATEST_VERSIONS['latest']),
                    'entries': list(),
                },
                'identified': {
                   'desc': "older cycles, culprit identified, with activity in the past three weeks",
                   'entries': list(),
                },
                'unidentified_indevelopment': {
                    'desc': "current cycle (%s.. aka %s-rc), unkown culprit" % (regzbot.LATEST_VERSIONS['latest'], regzbot.LATEST_VERSIONS['indevelopment']),
                    'entries': list(),
                },
                'unidentified_latest': {
                    'desc': "previous cycle (%s..%s), unkown culprit, with activity in the past three weeks" % (regzbot.LATEST_VERSIONS['previous'], regzbot.LATEST_VERSIONS['latest']),
                    'entries': list(),
                },
                'unidentified': {
                    'desc': 'older cycles, unkown culprit, with activity in the past three weeks',
                    'entries': list(),
                },
                'default': {
                    'desc': 'all others with activity in the past three months',
                    'entries': list(),
                },
            },
            'stable': {
                'identified': {
                   'desc': "culprit identified",
                   'entries': list(),
                },
                'default': {
                    'desc': 'culprit unkown',
                    'entries': list(),
                },
            },
            'unassociated': {
                'default': {
                    'desc': '',
                    'entries': list(),
                },
            },
        }

        for regression in regressionlist:
            last_activity_days = regzbot.days_delta(regression.gmtime_activity)
            if regression.treename == 'next' or regression.treename == 'stable':
                if regression.identified:
                    categories[regression.treename]['identified']['entries'].append(regression)
                else:
                    categories[regression.treename]['default']['entries'].append(regression)
            elif regression.treename == 'mainline':
                if regression.versionline == 'indevelopment':
                    if regression.identified:
                           categories[regression.treename]['identified_indevelopment']['entries'].append(regression)
                    else:
                           categories[regression.treename]['unidentified_indevelopment']['entries'].append(regression)
                elif regression.versionline == 'latest' and last_activity_days < 21:
                    if regression.identified:
                           categories[regression.treename]['identified_latest']['entries'].append(regression)
                    else:
                           categories[regression.treename]['unidentified_latest']['entries'].append(regression)
                elif last_activity_days < 21:
                    if regression.identified:
                           categories[regression.treename]['identified']['entries'].append(regression)
                    else:
                           categories[regression.treename]['unidentified']['entries'].append(regression)
                else:
                    categories[regression.treename]['default']['entries'].append(regression)
            else:
                categories['unassociated']['default']['entries'].append(regression)

            # put copies on the new page
            filed_days = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromtimestamp(regression.gmtime_filed, datetime.timezone.utc)).days
            if filed_days < 7:
                categories['new'][regression.treename]['entries'].append(regression)

        return categories


    @classmethod
    def compile(cls):
        logger.debug("[reportmail] generating")

        # gather everything we need
        regressionslist = list()

        for regression in RegressionMailReport.get_all(only_unsolved=True):
            # ignore some
            last_activity_days = regzbot.days_delta(regression._actievents[-1].gmtime)
            if regression.treename != 'mainline':
                # for now only generate reports for mainline
                continue
            elif last_activity_days > 91:
                # ignore due to inactivity for ~three months
                continue
            regressionslist.append(cls(regression.entry, regression.gmtime, regression.gmtime_filed,
                                                    regression._actievents[-1].gmtime, regression.treename,
                                                    regression.versionline, regression.identified, regression.mailreport()))

        regressionslist.sort(key=lambda x: x.gmtime_activity, reverse=True)
        categories = cls.categorize(regressionslist)

        for treename in categories.keys():
          cls.pagecreate(categories[treename])

        logger.debug("[webpages] generated")
