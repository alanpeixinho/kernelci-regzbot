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
    def __init__(self, repsrc, entry, gmtime, authorname, authormail, subject):
        self.repsrc = repsrc
        self.repsrcid = repsrc.repsrcid
        self.entry = entry
        self.gmtime = gmtime
        self.authorname = authorname
        self.authormail = authormail
        self.subject = subject

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
                elif parm == '^' or parm == '~':
                    parameters.append('^')
                elif is_uri(parm):
                    parameters.append(parm)
                else:
                    logger.info("Ignoring '%s' parameter '%s'", self.cmd, parm)

            return parameters

        arguments = _parse()
        area_introduced = arguments.pop(0)

        if len(arguments) == 0:
            report = self.origin
        else:
            report = RbCmdOrigin(
                self.origin.repsrc,
                self.origin.entry,
                self.origin.gmtime,
                None,
                None,
                self.origin.subject)

        regression = regzbot.RegressionBasic.introduced_create(
            report.repsrcid,
            report.entry,
            report.subject,
            report.authorname,
            report.authormail,
            area_introduced,
            report.gmtime)

        if len(arguments) > 0:
            regression.dupof(
                arguments[0],
                report.gmtime,
                report.entry,
                report.subject,
                None,
                report.repsrcid)

        return regression

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
