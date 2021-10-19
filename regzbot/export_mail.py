#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import regzbot
logger = regzbot.logger


class RegressionMailReport(regzbot.RegressionFull):
    def __init__(self, *args):
        super().__init__(*args)
        self.compiled = self.body()
       
    def body(self):
        text = list()
        text.append('=======================================================================')
        text.append(self.subject)
        text.append(self.report_url)
        text.append("by %s, %s days ago" % (self.author, regzbot.days_delta(self.gmtime)))
        text.append('')
        text.append('Oldest and latest activity: %s and %s days ago:' 
                   % (regzbot.days_delta(self._actievents[0].gmtime), regzbot.days_delta(self._actievents[-1].gmtime)))
        text.append('https://linux-regtracking.leemhuis.info/%s' % regzbot.urlencode(self.entry))
        text.append('')
        
        return text

    def dump(self):
        print('\n'.join(self.compiled))


def main():
    for regression in RegressionMailReport.get_all(unsolved=False):
        regression.dump()
