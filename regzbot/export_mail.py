#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import datetime
import re
from email.message import EmailMessage
import email.utils
import tempfile
import os

import regzbot

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
        report = list()
        report.append(self.subject)
        report.append('-'*len(self.subject))
        report.append('')
        report.append(self.report_url)
        report.append("By %s, %s days ago; latest activity %s days ago;" % (self.author, regzbot.days_delta(self.gmtime), regzbot.days_delta(self._actievents[-1].gmtime)))
        report = self.add_introduced(report)
        report.append('https://linux-regtracking.leemhuis.info/regzbot/regression/%s/' % regzbot.urlencode(self.entry))
        report = self.add_links(report)
        report.append('')
        return report

    def add_introduced(self, report):
        presentable = ''
        if self._introduced_presentable:
             presentable = ' (%s)' % self._introduced_presentable
        report.append('Introduced in %s%s' % (self._introduced_short, presentable))
        return report

    def add_links(self, report):
        if not self._links:
            return report

        report.append('\nRelated:')
        for link in self._links:
            report.append(link.mailreport())
        return report

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
    def __create_mail(cls, content, treename):
        msg = EmailMessage()
        msg['From'] = 'Regzbot (for Thorsten Leemhuis) <regressions@leemhuis.info>'
        msg['To'] = 'Thorsten Leemhuis <regressions@leemhuis.info>'
        msg['Subject'] = 'Regression report for linux-%s [%s]' % (treename, datetime.date.today())
        msg['Date'] = email.utils.localtime()
        msg['Message-Id'] = email.utils.make_msgid(domain='leemhuis.info')
        msg.set_content(content, cte='quoted-printable')
        return msg

    @classmethod
    def pagecreate(cls, categories, treename):
        def repintro(report, number_issues, treename):
            intro = list()
            intro.append("Hi, this is regzbot, the Linux kernel regression tracking bot. FYI:")
            intro.append("Currently I'm aware of %s regressions in linux-%s. Below you'll" % (number_issues, treename))
            intro.append("find all I started to track since the last report as well as all")
            intro.append("introduced in the current development cycle (%s..). Older regressions" % regzbot.LATEST_VERSIONS['indevelopment'])
            intro.append("for previous cycles are included as well if there was a recent activity.\n")
            intro.append("Wanna know more about regzbot or how to use it to track regressions for")
            intro.append("your subsystem? Then check out the getting started guide:")
            intro.append("https://gitlab.com/knurd42/regzbot/-/blob/main/docs/getting_started.md\n")
            intro.append("So without further adue, here is my report:\n\n")
            report.insert(0, '\n'.join(intro))
            return report

        def repsectionheader(report, headline):
            report.append(headline)
            report.append('='*len(headline))
            report.append('')
            return report

        number_issues = 0
        report = list()
        for category in categories.keys():
            if not categories[category]['entries']:
                # nothing to do
                continue

            number_issues += len(categories[category]['entries'])

            if category == 'default':
                report = repsectionheader(report, 'Inactive regressions')
                report.append("The regzbot's website lists %s more regressions omitted here due to lack of recent activity:" % len(['entries']))
                report.append("https://linux-regtracking.leemhuis.info/regzbot/%s/" % treename)
                report.append('')
            else:
                report = repsectionheader(report, categories[category]['desc'])
                report.append('')
                for regexportreport in categories[category]['entries']:
                    report.append(regexportreport.reporttext)
                    report.append('')

        print(report)
        report = repintro(report, number_issues, treename)
        print(report)
        return ('\n'.join(report))


    @classmethod
    def categorize(cls, regressionlist):
        # some lines are commented out below to keep code similar to the one used in export_web,
        # as it shows a few regressions that don't make it into the reports

        categories = {
            'next': {
                'new': {
                    'desc': "newly tracked since the last report",
                    'entries': list(),
                },
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
                'new': {
                    'desc': "newly tracked since the last report",
                    'entries': list(),
                },
                'identified_indevelopment': {
                    'desc': "current cycle (%s.. aka %s-rc), culprit identified" % (regzbot.LATEST_VERSIONS['latest'], regzbot.LATEST_VERSIONS['indevelopment']),
                    'entries': list(),
                },
                'identified_latest': {
                    'desc': "previous cycle (%s..%s), culprit identified, with activity in the past three weeks" % (regzbot.LATEST_VERSIONS['previous'], regzbot.LATEST_VERSIONS['latest']),
                    'entries': list(),
                },
                'identified': {
                   'desc': "old cycles (..%s), culprit identified, with activity in the past three weeks" % regzbot.LATEST_VERSIONS['previous'],
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
                    'desc': 'old cycles (..%s), unkown culprit, with activity in the past three weeks' % regzbot.LATEST_VERSIONS['previous'],
                    'entries': list(),
                },
                'default': {
                    'desc': 'all others with activity in the past three months',
                    'entries': list(),
                },
            },
            'stable': {
                'new': {
                    'desc': "newly tracked since the last report",
                    'entries': list(),
                },
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
            filed_days = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromtimestamp(regression.gmtime_filed, datetime.timezone.utc)).days
            last_activity_days = regzbot.days_delta(regression.gmtime_activity)

            if regression.treename == 'next' or regression.treename == 'stable':
                if filed_days < 7:
                    categories['new'][regression.treename]['entries'].append(regression)
                elif regression.identified:
                    categories[regression.treename]['identified']['entries'].append(regression)
                else:
                    categories[regression.treename]['default']['entries'].append(regression)
            elif regression.treename == 'mainline':
                if filed_days < 7:
                    categories['new'][regression.treename]['entries'].append(regression)
                elif regression.versionline == 'indevelopment':
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

        reporttime = datetime.datetime.now(datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdirname:
            for counter, treename in enumerate(categories.keys()):
                if treename == 'next' or treename == 'stable' or treename == 'unassociated':
                    # ignore those for now
                    continue
                report = cls.pagecreate(categories[treename], treename)
                if not report:
                    logger.info('Nothing to report for %s' % treename)
                    continue


                filename = os.path.join(tmpdirname, "%s-regzbotreport-%s" % (counter, treename))
                msg = cls.__create_mail(report, treename)
                print('#'*120)
                print('\n%s\n' % filename)
                print('#'*120)
                print(msg)
                with open(filename, 'w') as out:
                    gen = email.generator.Generator(out)
                    gen.flatten(msg)

            print('#'*120)
            print("Review the reports in %s and sent them using \"git send-email --from='Regzbot (on behalf of Thorsten Leemhuis) <regressions@leemhuis.info>' --to '' --no-thread %s*\"" % (tmpdirname, tmpdirname))
            answer = input('Enter c to confirm you sent the report, anything else to abort: ')
            if answer.lower() != 'c':
               return
            regzbot.RegzbotState.set('lastreport', reporttime)
        logger.debug("[report] generated")
