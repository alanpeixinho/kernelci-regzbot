#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2022 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import regzbot
import argparse

from urllib.parse import urlparse

logger = regzbot.logger


class RbCmdOrigin:
    def __init__(self, repsrc, entry, gmtime, authorname, authormail, subject, helper):
        self.repsrc = repsrc
        self.repsrcid = repsrc.repsrcid
        self.entry = entry
        self.gmtime = gmtime
        self.authorname = authorname
        self.authormail = authormail
        self.subject = subject
        self.helper = helper

        self.ignore_activity = False

    def ignore_activity(self):
        self.ignore_activity = True


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
                else:
                    if argument in ('^', '~', '/'):
                        logger.info("Ignoring '%s' parameter, not supported in this case", argument)
                    report = RbCmdOrigin(
                        self.origin.repsrc,
                        self.origin.entry,
                        self.origin.gmtime,
                        None,
                        None,
                        self.origin.subject,
                        self.origin.helper)
                yield argument, report

        arguments = _parse()
        area_introduced = arguments.pop(0)

        regressions = []
        for argument, report in _reports(arguments):
            regressions.append(regzbot.RegressionBasic.introduced_create(
                report.repsrcid,
                report.entry,
                report.subject,
                report.authorname,
                report.authormail,
                area_introduced,
                report.gmtime))
            # create entry in the reghistory now that we know the regid
            regzbot.RegHistory.event(regressions[-1].regid,
                                     self.origin.gmtime,
                                     self.origin.entry,
                                     self.origin.subject,
                                     self.origin.authorname,
                                     repsrcid=self.origin.repsrcid,
                                     regzbotcmd='%s: %s' % (self.cmd,
                                                            self.parameters))
            if argument in ('^', '~', '/'):
                # we need to add these entries for the parent manually
                actimon = regzbot.RegActivityMonitor.get_by_regid_n_repsrcid_n_entry(
                    regressions[-1].regid, report.repsrcid, report.entry)
                regzbot.RegressionBasic.activity_event_monitored(
                    report.repsrcid, report.gmtime, report.entry, report.subject, report.authorname, actimon)

                # recheck the thread or the report, as it can contain msgs we have seen but ignored earlier
                if _helper_supports('process_thread'):
                    self.origin.helper.process_thread(report)

        regression = regressions[0]
        if len(arguments) > 0 and arguments[0] not in ('^', '~', '/'):
            regression.dupof(
                arguments[0],
                report.gmtime,
                report.entry,
                report.subject,
                None,
                report.repsrcid)

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
