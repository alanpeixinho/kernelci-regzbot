#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

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
       
    def compile(self, compiled):
        compiled.append('=======================================================================')
        self.add_body(compiled)
        self.add_links(compiled)
        compiled.append('')
        return compiled

    def add_body(self, compiled):
        compiled.append(self.subject)
        compiled.append(self.report_url)
        compiled.append("by %s, %s days ago" % (self.author, regzbot.days_delta(self.gmtime)))
        compiled.append('')
        compiled.append('Oldest and latest activity: %s and %s days ago:'
                   % (regzbot.days_delta(self._actievents[0].gmtime), regzbot.days_delta(self._actievents[-1].gmtime)))
        compiled.append('https://linux-regtracking.leemhuis.info/%s' % regzbot.urlencode(self.entry))
        return compiled

    def add_links(self, compiled):
        if not self._links:
            return compiled

        compiled.append('\nRelated:')
        for link in self._links:
            compiled.append(link.mailreport())
        return compiled

    def dump(self):
        print('\n'.join(self.compile(list())))


def main():
    for regression in RegressionMailReport.get_all(unsolved=False):
        regression.dump()
