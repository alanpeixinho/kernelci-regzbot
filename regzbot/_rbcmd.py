#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2022 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import argparse
import regzbot
import regzbot._bugzilla as bz

from urllib.parse import urlparse


logger = regzbot.logger


class RbCmdSingle:
    def __init__(self, cmdsource, cmd, parameters):
        self.cmdsource = cmdsource
        self.origin = cmdsource.origin
        self.regression = cmdsource.regression
        self.cmd = cmd
        self.parameters = parameters

    def _introduced(self):
        def _parse():
            def is_uri(uri):
                try:
                    result = urlparse(uri)
                    return all([result.scheme, result.netloc])
                except ValueError:
                    pass
                return False

            parser = argparse.ArgumentParser()
            parser.add_argument('parms', nargs='*', type=str)
            args = parser.parse_args(self.parameters.split())

            if len(args.parms) == 0:
                raise NotImplementedError

            parameters = []
            for parm in args.parms:
                if len(parameters) == 0:
                    parameters.append(parm)
                elif parm in ('^', '~', '/') or is_uri(parm):
                    parameters.append(parm)
                else:
                    logger.info("Ignoring '%s' parameter '%s'", self.cmd, parm)

            return parameters

        def _helper_supports(method):
            if not self.origin.helper:
                return False
            if not getattr(self.origin.helper, method, None):
                return False
            if callable(getattr(self.origin.helper, method, None)):
                return True
            return False

        def _reports(arguments):
            if len(arguments) == 0:
                yield None, self.origin
                return

            for argument in arguments:
                if argument in ('^', '~') and _helper_supports('thread_parent'):
                    report = self.origin.helper.thread_parent(self.origin)
                elif argument == '/' and _helper_supports('thread_root'):
                    report = self.origin.helper.thread_root(self.origin)
                elif bz.get_bug_id(argument):
                    report = bz.BzOrigin.get(url=argument)
                else:
                    if argument in ('^', '~', '/'):
                        logger.info("Ignoring '%s' parameter, not supported in this case", argument)
                        continue

                    repsrc, entry = regzbot.ReportSource.get_by_url(argument)
                    report = regzbot.RbCmdOrigin(
                        repsrc,
                        entry,
                        self.origin.gmtime,
                        None,
                        None,
                        self.origin.subject,
                        None)
                yield argument, report

        def _create_histentry(regression):
            regzbot.RegHistory.event(regression.regid,
                                     self.origin.gmtime,
                                     self.origin.entry,
                                     self.origin.subject,
                                     self.origin.authorname,
                                     repsrcid=self.origin.repsrcid,
                                     regzbotcmd='%s: %s' % (self.cmd,
                                                            self.parameters))

        arguments = _parse()
        area_introduced = arguments.pop(0)

        regressions = []
        primary_regression_origin = None
        for argument, report in _reports(arguments):
            if len(regressions) == 0:
                first_report = report

            regressions.append(regzbot.RegressionBasic.introduced_create(
                report.repsrcid,
                report.entry,
                report.subject,
                report.authorname,
                report.authormail,
                area_introduced,
                report.gmtime))
            # create entry in the reghistory now that we know the regid
            _create_histentry(regressions[-1])

            if not primary_regression_origin:
                primary_regression_origin = report

            if argument in ('^', '~', '/'):
                # we need to add create the activity event for the parent manually and
                # recheck the thread, as it may contain msgs we saw and ignored earlier
                actimon = regzbot.RegActivityMonitor.get_by_regid_n_repsrcid_n_entry(
                    regressions[-1].regid, report.repsrcid, report.entry)
                regzbot.RegressionBasic.activity_event_monitored(
                    report.repsrcid, report.gmtime, report.entry, report.subject, report.authorname, actimon)
                # recheck the thread or the report, as it can contain msgs we have seen but ignored earlier
                if _helper_supports('process_thread'):
                    self.origin.helper.process_thread(report)
            elif bz.get_bug_id(argument):
                report.process_comments()

            # mark regressions as dupe
            if regressions[0] != regressions[-1]:
                regressions[-1]._dupof_direct(
                    regressions[0],
                    self.origin.gmtime,
                    self.origin.entry,
                    self.origin.subject,
                    self.origin.authorname,
                    self.origin.repsrcid)

        if arguments and arguments[0] not in ('^', '~', '/'):
            # create an entry for the report with the introduced command as well
            # take author from the first report
            regressions.append(regzbot.RegressionBasic.introduced_create(
                self.origin.repsrcid,
                self.origin.entry,
                self.origin.subject,
                primary_regression_origin.authorname,
                primary_regression_origin.authormail,
                area_introduced,
                self.origin.gmtime))

            _create_histentry(regressions[-1])

            regressions[-1]._dupof_direct(
                regressions[0],
                self.origin.gmtime,
                self.origin.entry,
                self.origin.subject,
                first_report.authorname,
                self.origin.repsrcid)

        return regressions[0]

    def process(self):
        if self.cmd == 'introduced':
            return self._introduced()


class RbCmdStack:
    def __init__(self, origin, regression):
        self.origin = origin
        self.regression = regression
        self.commands = []

    def add(self, cmd, parameters):
        cmdobj = RbCmdSingle(self, cmd, parameters)
        # 'introduced' needs to be processed first
        if cmd == 'introduced':
            self.commands.insert(0, cmdobj)
            return
        # 'poke' needs to be last
        if self.commands[-1].cmd == 'poke':
            self.commands.insert(-1, cmdobj)
            return
        # simply append all otherss
        self.commands.append(RbCmdSingle(cmdobj))

    def process(self):
        for cmd in self.commands:
            if cmd.cmd == 'introduced':
                self.regression = cmd.process()
                for c in self.commands:
                    c.regression = self.regression
                continue

            if not cmd.regression:
                raise RuntimeError
            cmd.process()

        return self.regression
