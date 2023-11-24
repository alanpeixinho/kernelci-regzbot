#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2022 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import argparse
import re
from urllib.parse import urlparse

if __name__ != "__main__":
    import regzbot
    import regzbot._bugzilla as bz
    logger = regzbot.logger
else:
    import logging
    logger = logging
    #if False:
    if True:
        logger.basicConfig(level=logging.DEBUG)


class RegressionCreatedException(Exception):
    pass

class RbCmdSingle:
    def __init__(self, cmdsource, cmd, parameters):
        self.cmdsource = cmdsource
        self.origin = cmdsource.origin
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
                    try:
                        report = self.origin.helper.thread_parent(self.origin)
                    except regzbot.lore.LoreDownloadError:
                        # parent not found; using current mail as report
                        report = self.origin
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


class RbCmdSingleNew:
    def __init__(self, rbcmd_stack, cmd, parameters):
        self._rbcmd_stack = rbcmd_stack
        self.cmd = cmd.lower()
        self.repact = rbcmd_stack.repact
        self.reptrd = rbcmd_stack.reptrd
        self.parameters = parameters

        # handle frequent typos, alternatives, and renamed commands
        if self.cmd in ('backburner', 'back-burner'):
            self.cmd = 'backburn'
        elif self.cmd in ('dup', 'dupof', 'duplicate-of' ):
            self.cmd = 'duplicate'
        elif self.cmd in ('resolved', 'invalid'):
            self.cmd = 'resolve'
        elif self.cmd in ('fixedby', 'fixed-by'):
            self.cmd = 'fix'
        elif self.cmd in ('subject', 'title'):
            self.cmd = 'summary'
        elif self.cmd in ('unback-burner', 'back-burner'):
            self.cmd = 'unbackburn'

    def _parse_link_and_description(self, pattern):
        splitted = pattern.split(maxsplit=1)
        url = splitted[0]
        if len(splitted) > 1:
            description = splitted[1]
        else:
            description = url.removeprefix("http://")
        return url, description

    def _cmd_backburn(self, regression):
        reason = self.parameters
        regression.cmd_backburn(self, reason)

    def _cmd_duplicate(self, regression):
        for url in self.parameters:
            regression_created = regression.cmd_duplicate(self, url)
            self._rbcmd_stack.add_related_activities(regression_created)

    def _cmd_fix(self, regression):
        def _remove_quoting_chars(pattern):
            for character in (('(', ')'), "'", '"'):
                if pattern.startswith(character[0]) and pattern.endswith(character[-1]):
                    pattern = pattern[1:-1]
            return pattern

        match = re.search(r'^[0-9a-fA-F]{8,40}', self.parameters)
        if match:
            hexsha = match[0]
            summary = None
        else:
            hexsha = None
            summary = _remove_quoting_chars(self.parameters)
        regression.cmd_fix(self, hexsha, summary)

    def _cmd_from(self, regression):
        if '<' in self.parameters and '>' in self.parameters:
            from email.utils import parseaddr
            realname, username = parseaddr(self.parameters)
        else:
            realname = self.parameters
            username = None
        regression.cmd_from(self, realname, username)

    def _cmd_inconclusive(self, regression):
        regression.cmd_resolve(self, self.parameters)

    def _cmd_introduced(self, regression):
        hexsha = self.parameters
        if regression:
            regression.cmd_introduced_update(self, hexsha)
            return None
        return regzbot.RegressionBasic.cmd_introduced_new(self, hexsha)

    def _cmd_link(self, regression):
        url, description = self._parse_link_and_description(self.parameters)
        regression.cmd_link(self, url, description)

    def _cmd_monitor(self, regression):
        raise NotImplementedError
        url, description = self._parse_link_and_description(self.parameters)

    def _cmd_resolve(self, regression):
        regression.cmd_resolve(self, self.parameters)

    def _cmd_summary(self, regression):
        regression.title(self.parameters)

    def _cmd_unbackburn(self, regression):
        regression.cmd_unbackburn(self)
        self.deprecated_historyevent = False

    def _cmd_unlink(self, regression):
        url, _ = self._parse_link_and_description(self.parameters)
        regression.cmd_unlink(self, url)

    def _cmd_unmonitor(self, regression):
        raise NotImplementedError
        url, _ = self._parse_link_and_description(self.parameters)

    def process(self, regression):
        regression_created = None
        if self.cmd == 'introduced':
            regression_created = self._cmd_introduced(regression)
            if regression_created:
                regression = regression_created
        elif self.cmd in (
                'poke',
                'ignore-activity',
                ):
            # these are flags releavent and handled when processing activities, so nothing to do here
            pass
        elif self.cmd in (
                'backburn',
                'duplicate',
                'fix',
                'from',
                'link',
                'inconclusive',
                'monitor',
                'resolve',
                'summary',
                'unbackburn',
                'unlink',
                'unmonitor',
                ):
            getattr(self, '_cmd_%s' % self.cmd)(regression)
        else:
            regzbot.UnhandledEvent.add(
                self.repact.web_url, "unknown regzbot command: %s" % self.cmd, gmtime=self.report_rzbcmd.gmtime, subject=self.report_rzbcmd.summary)

        # create the history event
        if self.cmd is not 'ignore-activity':
            regression.add_history_event(self)

        # let caller know if we created a regression
        return regression_created


class RbCmdStackNew:
    def __init__(self, repact):
        self._commands = []
        self.repact = repact
        self.reptrd = repact.reptrd
        self.regression = self._locate_regression()

    def _add_command(self, cmd, parameters):
        cmdobj = RbCmdSingleNew(self, cmd, parameters)
        self._commands.append(cmdobj)

    def _locate_regression(self):
        return regzbot.RegressionBasic.get_by_reptrd(self.reptrd)

    # maybe the following is somewhat oddly placed here, but putting it in Regression class felt misplaced, too, as this
    # only should be executed in the contect of commands like duplicate and introduced; and in the latter case only
    # after all commands have been executed
    def add_related_activities(self, regression, *, reptrd=None):
        if not reptrd:
            reptrd = ReportThread.from_actimon(regression.actimon)
        reptrd.update(None, None, rgzbcmds_since=self.repact.created_at, actimon=regression.actimon)

    def process_commands(self):
        def _walk_commands():
            # raise introduced commands first, poke commands last
            for single_command in self._commands:
                if single_command.cmd == 'introduced':
                    yield single_command
            for single_command in self._commands:
                if single_command.cmd == 'introduced' or single_command.cmd == 'poke':
                    continue
                yield single_command
            for single_command in self._commands:
                if single_command.cmd == 'poke':
                    yield single_command

        regression_created = False
        assert (self.reptrd)
        for single_command in _walk_commands():
            if single_command.cmd == 'introduced':
                regression_created = single_command.process(self.regression)
                if regression_created:
                    self.regression = self._locate_regression()
                    assert (self.regression)
            else:
                assert (self.regression)
                single_command.process(self.regression)

        # if a regressions was created and all commands processed, it's time to add all activities for it, which
        # might include even more commands
        if regression_created:
            self.add_related_activities(regression_created, reptrd=self.reptrd)
        return regression_created


def _ignore_activity(body):
    # this RE is derivated from the one in _parse() and there explained in more detail
    if re.search(r'((^|\n|;\s+)#regzbot\s+)(ignore-activity|poke)(?=(;?\n\s*$|;?\s+#regzbot))', '\n' + body + '\n\n', re.MULTILINE | re.IGNORECASE | re.DOTALL):
        return True
    return False


def _parse(cmd_section):
    # the following re has to deal with:
    # - mails where a long regzbot commands will have a line break in them
    # - mails or tickets, where multiple regzbot commands are separated by a semicolon
    # hence:
    # - "((^|\n|;\s+)#regzbot\s+)": find a '#regzbot' at the
    #   * the beginning of the line
    #   * after a newline
    #   * after something like an '; '
    # - (.*?): will contain the command we are looking for
    # - (?=(;?\n\s*$|(;?\n|;\s)+#regzbot)): lookahead assertion to stop on
    #   * the end of the section, as indicated by two newlines; optionally with a ; before the first and
    #     space characters before the second)
    #   * either a newline or a combination of semicolon and space characters that are followed '#regzbot'
    for cmd_line_raw in re.finditer(r'((^|\n|;\s+)#regzbot\s+)(.*?)(?=(;?\n\s*$|;?\s+#regzbot))', cmd_section, re.MULTILINE | re.IGNORECASE | re.DOTALL):
        # guess there is a better way to handle "#regzbot activity-\nignore" better, but whatever
        cmd_line = re.sub(r'\-\n', '-', cmd_line_raw[3])
        # remove linebreaks
        cmd_line = re.sub(r'\s?\n', ' ', cmd_line)
        # following split could be handled by above RE as well, but for the sake of readability is likely
        # better kept separate:
        # - ([\w-]+): will match the command
        # - (:?\n?\s+): commands can end in a colon and are separated from parameters using at least one space;
        #             optional, as not every command has parameters (optional)
        # - (.*)?: the parameters (optional)
        splitted = re.split(r'^([\w-]+)(:?\n?\s+)?(.*)?$', cmd_line)
        yield(splitted[1], splitted[3])

def process_activity(activity, *, rgzbcmds_since=None, actimon=None):
    if regzbot._TESTING_UNTIL and activity.created_at >= regzbot._TESTING_UNTIL:
        return

    if actimon:
        # check for flags before adding a activity; note that the RE used below is derivated from one in
        # RbCmdStackNew._parse and explained in more detail there
        if not _ignore_activity(activity.message):
            actimon.add_activity(activity)

    # when a regression is added and all activities walked, we in some cases only want to handle regzbot commands
    # in acitivies that happened after the report was added
    if rgzbcmds_since and activity.created_at <= rgzbcmds_since:
        return

    # the following loop locates sections with regzbot commands seperated by newlines;
    # note, it adds a newline at the start and two at the end of the processed input, as the
    # regzbot command might be right at its start or end
    regression_created = None
    for cmd_section in re.finditer(r'^\n#regzbot.*\n\s*\n$', '\n' + activity.message + '\n\n', re.MULTILINE | re.IGNORECASE | re.DOTALL):
        cmd_stack = RbCmdStackNew(activity)
        for command, parameter in _parse(cmd_section[0]):
            cmd_stack._add_command(command, parameter)
        regression_created = cmd_stack.process_commands()

    # let the caller know when a regression was introduced, as it likely mus stop processing related acitivies now, a
    # they were processed already when the regression was added to pick up all related (incuding earlier) activities
    if regression_created:
        raise RegressionCreatedException


if __name__ == "__main__":
    __TESTDATA=[]
    #__TESTDATA.append("#regzbot introduced foo")
    #__TESTDATA.append("#regzbot introduced foo\n#regzbot title bar")
    __TESTDATA.append("#regzbot  introduced\nfoo bar \nand more for and bar; and foobar, too;\n#regzbot ignore; #regzbot title foo;\n#regzbot title: baz;")
    for i in __TESTDATA:
        print('#########')
        print('"""\n%s """' % i)
        print()
        RbCmdStackNew.process(i)
        print('\n')
