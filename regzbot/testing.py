#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'
#
# FIXMELATER:
# * import commits and emails from files
# * maybe: use more of pathlib and less of os and glob (or nothing at all)
# * directly retrieve some mails from lore to see if everything works, once there are some on the list

import difflib
import glob
import os
import sys
import shutil

import regzbot
import regzbot.testing_offline as offlinetst
import regzbot.testing_online as onlinetst

logger = regzbot.logger


def get_resultfiles(path_testdata, path_tmpdir):
    if not os.path.isdir(path_testdata):
        logger.critical("Directory for expexted results and template %s doesn't exist. Aborting.",
                        path_testdata)
        sys.exit(1)

    results_expected = {
        'offline': os.path.join(path_testdata, 'expected/results-offline.csv'),
        'online': os.path.join(path_testdata, 'expected/results-online.csv'),
    }
    results_generated = {
        'offline': os.path.join(os.path.join(path_tmpdir, 'testresults-offline.csv')),
        'online': os.path.join(os.path.join(path_tmpdir, 'testresults-online.csv')),
    }
    return results_expected, results_generated


def check_results(results_expected, results_generated):
    def ask_user(results_expected, results_generated):
        answer = input(
            "Enter 'm' to call meld; enter 'a' or 'y' to accept differences; simply hit enter to move on.")
        if answer.lower() == 'm':
            os.system("meld %s %s" % (results_expected, results_generated))
            return False
        if answer.lower() == 'a' or answer.lower() == 'y':
            shutil.copyfile(results_generated, results_expected)
        return True

    with open(results_expected, 'r') as file_expected:
        with open(results_generated, 'r') as file_generated:
            if not regzbot.db_diff(file_expected, file_generated, "%s" % results_expected, "%s" % results_generated):
                sys.stdout.write('#######\n')
                while not ask_user(results_expected, results_generated):
                    pass


def init(tmpdir):
    if len(glob.glob(os.path.join(tmpdir, '*'))) > 0:
        logger.critical(
            "aborting, the directory %s is not empty", tmpdir)
        sys.exit(1)


def run(testmodes, testdatapath, tmpdir):
    results_expected, results_generated = get_resultfiles(
        testdatapath, tmpdir)

    if testmodes['offline']:
        offlinetst.run(results_generated['offline'], tmpdir, testdatapath)

    if testmodes['online']:
        onlinetst.run(results_generated['online'], tmpdir)

    if testmodes['offline']:
        check_results(results_expected['offline'],
                      results_generated['offline'])
    if testmodes['online']:
        check_results(results_expected['online'], results_generated['online'])
