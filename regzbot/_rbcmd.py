#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2022 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import regzbot


class RbCmdOrigin:
    def __init__(self, repsrc, entry, gmtime, authorname, authormail, subject):
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
        regression = regzbot.RegressionBasic.introduced_create(
            self.origin.repsrcid,
            self.origin.entry,
            self.origin.subject,
            self.origin.authorname,
            self.origin.authormail,
            self.parameters,
            self.origin.gmtime)
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
