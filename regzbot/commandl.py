#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'


import argparse
import glob
import logging
import os
import tempfile
import sys

import regzbot
import regzbot.testing

logger = regzbot.logger


def get_testdatadir():
    # check if we are running from git
    basedir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    testingdir = os.path.join(basedir, 'testdata')
    if os.path.exists(testingdir):
        return testingdir
    return None


def cmd_setup(cmdargs):
    regzbot.basicressources_setup()


def cmd_run(cmdargs):
    regzbot.basicressources_init()
    regzbot.run()


def cmd_test(cmdargs):
    def tests_run(tmpdir, onlinetests):
        regzbot.basicressources_setup(tmpdir)
        regzbot.basicressources_init(tmpdir)

        _, gittreesdir, _ = regzbot.basicressources_get_dirs(tmpdir)
        regzbot.testing.run(get_testdatadir(), tmpdir, gittreesdir, onlinetests)

        regzbot.db_close()

    onlinetests = True
    if cmdargs.offline:
        onlinetests = False

    if cmdargs.tmpdir:
        if len(glob.glob(os.path.join(cmdargs.tmpdir, '*'))) > 0:
            logger.critical("aborting, the directory %s is not empty", cmdargs.tmpdir)
            sys.exit(1)
        tests_run(cmdargs.tmpdir, onlinetests)
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            tests_run(tmpdir, onlinetests)


def cmd():
    parser = argparse.ArgumentParser(
        prog='regzbot',
        description='A bot for tracking Linux kernel regressions',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # basics
    parser.add_argument('--version', action='version',
                        version=regzbot.__VERSION__)
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Enable debugging info in output')
    parser.add_argument('--quiet', action='store_true', default=False,
                        help='Only print critical information')

    # subcommands
    subparsers = parser.add_subparsers(help='sub-command help', dest='subcmd')

    # setup
    sparser_setup = subparsers.add_parser('setup', help='Initialize regzbot')
    sparser_setup.set_defaults(func=cmd_setup)

    # run
    sparser_run = subparsers.add_parser('run', help='Run regzbot')
    sparser_run.set_defaults(func=cmd_run)

    # test
    if get_testdatadir():
        sparser_test = subparsers.add_parser('test', help='run tests')
        sparser_test.add_argument(
            '--tmpdir', dest='tmpdir', default=None, help='Create repos and mails for testing here')
        sparser_test.add_argument(
            '--offline', action='store_true', default=False, help='Run only test that work without internet connection')
        sparser_test.set_defaults(func=cmd_test)

    # parse
    cmdargs = parser.parse_args()

    # handle basics
    logger.setLevel(logging.DEBUG)
    loghandler = logging.StreamHandler()
    loghandler.setFormatter(logging.Formatter('%(message)s'))
    if cmdargs.quiet:
        loghandler.setLevel(logging.CRITICAL)
    elif cmdargs.debug:
        loghandler.setLevel(logging.DEBUG)
    else:
        loghandler.setLevel(logging.INFO)
    logger.addHandler(loghandler)

    # go
    if 'func' not in cmdargs:
        parser.print_help()
        sys.exit(1)

    cmdargs.func(cmdargs)


if __name__ == '__main__':
    cmd()
