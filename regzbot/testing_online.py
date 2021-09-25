#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import os
import sys

import regzbot
import regzbot.lore
logger = regzbot.logger


def init(tmpdir):
    regzbot.set_citesting('online')
    regzbot.basicressources_setup(
        tmpdir=tmpdir, gittreesdir=True, databasedir=os.path.join(tmpdir, 'db-onlinetsts'))
    regzbot.basicressources_init(
        tmpdir=tmpdir, gittreesdir=True, databasedir=os.path.join(tmpdir, 'db-onlinetsts'))


def run(resultfilename, tmpdir):
    init(tmpdir)

    resultfile = open(resultfilename, 'a')
    testfuncprefix = 'onlntest'
    this = sys.modules[__name__]

    outercount = 0
    while '%s_%s_0' % (testfuncprefix, outercount) in dir(this):
        regzbot.db_rollback()

        innercount = 0
        while '%s_%s_%s' % (testfuncprefix, outercount, innercount) in dir(this):
            # run test
            callfunction = getattr(this, '%s_%s_%s' %
                                   (testfuncprefix, outercount, innercount))
            chk_mail, chk_git, wait = callfunction(
                'test_%s_%s' % (outercount, innercount))

            # write results
            resultfile.write('[%s_%s_%s]\n' %
                             (testfuncprefix, outercount, innercount))
            for entry in regzbot.RegressionFull.dumpall_csv():
                for line in entry:
                    resultfile.write('%s\n' % line)
            for line in regzbot.UnhandledEvent.dumpall_csv():
                resultfile.write('UNHANDLED: %s\n' % line)
            resultfile.write('\n')

            regzbot.RegressionWeb.create_htmlpages()

            if wait:
                # regzbot.db_commit()
                os.system('read -p "Press any key to continue"')

            # finish this up
            innercount += 1
        outercount += 1
    resultfile.close()
    regzbot.db_commit()
    regzbot.db_close()


def onlntest_0_0(funcname):
#    regzbot.process_msg('a11ba91f-a520-e6ab-5566-dfc9fd934440@leemhuis.info')
#    regzbot.process_msg('8d83985a-68a6-13f9-42b6-a6980c9f853c@leemhuis.info')
    regzbot.process_thread('a11ba91f-a520-e6ab-5566-dfc9fd934440@leemhuis.info')
    return False, False, False
