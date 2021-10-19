#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import datetime
import os

import yattag

import regzbot
from regzbot import days_delta

logger = regzbot.logger


class RegLinkWeb(regzbot.RegLink):
    def __init__(self, *args):
        super().__init__(*args)

    def html(self, yattagdoc):
        with yattagdoc.tag('a', href=self.link):
            yattagdoc.text(self.subject)

        yattagdoc.text('; %s days ago, by %s' % (days_delta(self.gmtime), self.author))
        if self.repsrcid and self.entry and regzbot.RegActivityMonitor.ismonitored(self.entry, self.regid, self.repsrcid):
            yattagdoc.text(" (monitored)")

        return yattagdoc


class RegHistoryWeb(regzbot.RegHistory):
    def __init__(self, *args):
        super().__init__(*args)

    def html(self, yattagdoc):
        if self.regzbotcmd:
            with yattagdoc.tag('a', href=self.url()):
                yattagdoc.text("%s" % self.regzbotcmd)
        else:
            with yattagdoc.tag('a', href=self.url()):
                yattagdoc.text("%s" % self.subject)


class RegActivityEventWeb(regzbot.RegActivityEvent):
    def __init__(self, *args):
        super().__init__(*args)

    def html(self, yattagdoc):
        with yattagdoc.tag('a', href=self.url()):
                 yattagdoc.text("%s" % self.subject)
        with yattagdoc.tag('div', style="padding-left: 1em;"):
             yattagdoc.text("%s days ago, by %s" % (days_delta(self.gmtime), self.author))

        return yattagdoc



class RegressionFullWeb(regzbot.RegressionFull):
    Reglink = RegLinkWeb
    Reghistory = RegHistoryWeb
    Regactivityevent = RegActivityEventWeb

    def __init__(self, *args):
        super().__init__(*args)

    def compile(self):
        oldwebpage(self)

    @classmethod
    def oldwebgen_getall_html(cls):
        from export_web import RegressionWebOld as RegressionWebOld
        regressionlist = list()
        for regressionf in cls.get_all():
            if regressionf.category == 'resolved':
                regressionlist.append(RegressionWebOld(regressionf.entry, regressionf.gmtime,
                                                    regressionf._actievents[-1].gmtime, 'resolved', regressionf.treename, 'default', regressionf.oldwebgen_html()))
            elif days_delta(regressionf._actievents[-1].gmtime) > 21 and not regzbot.is_running_citesting():
                regressionlist.append(RegressionWebOld(regressionf.entry, regressionf.gmtime,
                                                    regressionf._actievents[-1].gmtime, 'dormant', regressionf.treename, 'default', regressionf.oldwebgen_html()))
            else:
                regressionlist.append(RegressionWebOld(regressionf.entry, regressionf.gmtime, regressionf._actievents[-1].gmtime,
                                                    regressionf.treename, regressionf.treename, regressionf.category, regressionf.oldwebgen_html()))
        return regressionlist


    def oldwebgen_html(self):
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
                        with yattagdoc.tag('a', href=self.report_url):
                            yattagdoc.text(self.subject)
                    yattagdoc.text(' by %s' % self.author)

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
                            yattagdoc.text('Oldest and latest activity: ')
                            with yattagdoc.tag('a', href=self._actievents[0].url()):
                                yattagdoc.text('%s' % days_delta(
                                    self._actievents[0].gmtime))
                            if self._actievents[0] is not self._actievents[-1]:
                                yattagdoc.text(' and ')
                                with yattagdoc.tag('a', href=self._actievents[-1].url()):
                                    yattagdoc.text('%s' % days_delta(
                                        self._actievents[-1].gmtime))
                            yattagdoc.text(' days ago.')

                        entered_loop = False
                        for counter, regressionlink in enumerate(RegLinkWeb.get_all(self.regid), start=1):
                            if counter == 1:
                                entered_loop = True
                                yattagdoc.text(' Related issues: ')
                            else:
                                yattagdoc.text(', ')
                            with yattagdoc.tag('a', href=regressionlink.link):
                                yattagdoc.text("[%s]" % counter)
                        if entered_loop:
                            yattagdoc.text('.')

                for counter, regressionlink in enumerate(RegLinkWeb.get_all(self.regid), start=1):
                    with yattagdoc.tag('div'):
                        yattagdoc.text('[%s]: ' % counter)
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
                    with yattagdoc_line.tag('ul', style='padding-left: 5px; margin-top: -1em;'):
                        for actievent in reversed(self._actievents[-5:]):
                            with yattagdoc.tag('li', style="list-style-position: inside;"):
                                actievent.html(yattagdoc)

                with yattagdoc_line.tag('p'):
                    yattagdoc.text("Regression history")
                    with yattagdoc_line.tag('ul', style='padding-left: 5px; margin-top: -1em;'):
                        for histevent in reversed(self._histevents):
                            with yattagdoc.tag('li', style="list-style-position: inside;"):
                                with yattagdoc.tag('i'):
                                    histevent.html(yattagdoc)
                                yattagdoc.text(" (%s days ago)" % days_delta(
                                               histevent.gmtime))

                if self.solved_reason:
                    return

                with yattagdoc.tag('p'):
                    yattagdoc.text(
                         "When fixing, include one of these in the commit message to automatically resolve this entry in the regression tracking database:")
                    for actimonitor in regzbot.RegActivityMonitor.getall_by_regid(self.regid):
                        with yattagdoc_line.tag('ul', style='padding-left: 1em; margin-top: -1em; font-style: italic; list-style-type: none;'):
                            yattagdoc.text("Link: ")
                            link = "https://lore.kernel.org/r/%s" % actimonitor.entry
                            with yattagdoc.tag('a', href=link):
                                yattagdoc.text(link)

                # use self._introduced_url here, as that will avoid ranges and commits we could not find
                if self._introduced_url:
                    commitsummary = regzbot.GitTree.commit_summary(self.introduced)
                    with yattagdoc.tag('p'):
                        yattagdoc.text( "You likely also want to add this to the commit message:")
                        with yattagdoc.tag('div', style='padding-left: 1em; margin-top: -1em; font-style: italic;'):
                            yattagdoc.text('Fixes: %s ("%s")' % (
                                self.introduced[0:12], commitsummary))

        yattagdoc_line = yattag.Doc()
        with yattagdoc_line.tag('td', style="width: 200px;"):
            cell1(yattagdoc_line)
        with yattagdoc_line.tag('td'):
            cell2(yattagdoc_line)
        return yattagdoc_line



class UnhandledEventWeb(regzbot.UnhandledEvent):
    def __init__(self, *args):
        super().__init__(*args)

    def getall_yattag(yattagdoc):
        count = 0
        for unhandled in UnhandledEventWeb.get_all():
            unhandled.html(yattagdoc)
            count += 1
        return count, yattagdoc

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


class RegressionWebOld():
    def __init__(self, entry, gmtime_report, gmtime_activity, page, tree, category, htmlsnippet):
        self.entry = entry
        self.gmtime_report = gmtime_report
        self.gmtime_activity = gmtime_activity
        self.page = page
        self.tree = tree
        self.category = category
        self.htmlsnippet = htmlsnippet

    @staticmethod
    def create_htmlpages():
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
            yattagdoc.asis('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/></head>')
            with yattagdoc.tag('body'):
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
                if regzbot.is_running_citesting():
                    # make this easier to read
                    outputfile.write(yattag.indent(yattagdoc.getvalue()))
                else:
                    outputfile.write(yattagdoc.getvalue())

        def create_page_unhandled(directory, htmlpages):
            yattagdoc = yattag.Doc()
            yattagdoc.asis('<!DOCTYPE html>')
            with yattagdoc.tag('html'):
                outpage_header(yattagdoc, htmlpages, None)

                rowcount, yattagrows = UnhandledEventWeb.getall_yattag(
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
        unhandled_count = create_page_unhandled(regzbot.WEBPAGEDIR, htmlpages)
        regressionslist = RegressionFullWeb.oldwebgen_getall_html()

        # all
        regressionslist.sort(key=lambda x: x.gmtime_report, reverse=True)
        categories = {
            'default': {
                'desc': 'sorted by date of report',
                'entries': list(),
            }
        }
        create_page_regressions(
            regzbot.WEBPAGEDIR, 'all', categories, htmlpages, regressionslist, unhandled_count)

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
            regzbot.WEBPAGEDIR, 'next', categories, htmlpages, regressionslist, unhandled_count)

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
            regzbot.WEBPAGEDIR, 'mainline', categories, htmlpages, regressionslist, unhandled_count)

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
            regzbot.WEBPAGEDIR, 'stable', categories, htmlpages, regressionslist, unhandled_count)

        categories = {
            'default': {
                'desc': None,
                'entries': list(),
            }
        }
        create_page_regressions(
            regzbot.WEBPAGEDIR, 'unassociated', categories, htmlpages, regressionslist, unhandled_count)

        categories = {
            'default': {
                'desc': 'no activity in the past three weeks',
                'entries': list(),
            },
        }
        create_page_regressions(
            regzbot.WEBPAGEDIR, 'dormant', categories, htmlpages, regressionslist, unhandled_count)

        categories = {
            'default': {
                'desc': None,
                'entries': list(),
            },
        }
        create_page_regressions(
            regzbot.WEBPAGEDIR, 'resolved', categories, htmlpages, regressionslist, unhandled_count)

        logger.debug("webpages regenerated")
