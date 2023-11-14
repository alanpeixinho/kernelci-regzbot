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

                    repsrc, entry = regzbot.ReportSourceRaw.get_by_url(argument)
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
        self.rbcmd_stack = rbcmd_stack
        self.report_issue = rbcmd_stack.report_issue
        self.report_rzbcmd = rbcmd_stack.report_rzbcmd
        self.cmd = cmd
        self.parameters = parameters

    def _add_history_event(self, regression):
        regzbotcmd = '%s' % self.cmd
        if self.parameters:
            regzbotcmd = '%s: %s' % (regzbotcmd, self.parameters)
        regzbot.RegHistory.event(
                regression.regid,
                self.report_rzbcmd.gmtime,
                self.report_rzbcmd.entryid,
                self.report_rzbcmd.summary,
                self.report_rzbcmd.realname,
                repsrcid=self.report_rzbcmd.repsrc.repsrcid,
                regzbotcmd=regzbotcmd)

    def _backburn(self, regression):
        regression.backburner_add(
                self.report_rzbcmd.repsrc.repsrcid,
                self.report_rzbcmd.entryid,
                self.report_rzbcmd.gmtime,
                self.report_rzbcmd.realname,
                self.parameters)

    def _duplicate(self, regression):
        regression.duplicate(
                self.parameters,
                self.report_rzbcmd.gmtime,
                self.report_rzbcmd.entryid,
                self.report_issue.summary,
                self.report_rzbcmd.realname,
                self.report_rzbcmd.repsrc.repsrcid)

    def _duplicateof(self, regression):
        regression.dupof(
                self.parameters,
                self.report_rzbcmd.gmtime,
                self.report_rzbcmd.entryid,
                self.report_issue.summary,
                self.report_rzbcmd.realname,
                self.report_rzbcmd.repsrc.repsrcid)

    def _fix(self, regression):
        # FIXME: this should not be here
        def _remove_quoting_chars(pattern):
            for character in (('(', ')'), "'", '"'):
                if pattern.startswith(character[0]) and pattern.endswith(character[-1]):
                    pattern = pattern[1:-1]
            return pattern

       # FIXME: this should not be here
        def _spilttag_first_word(pattern):
            pattern = pattern.split(maxsplit=1)
            firstpart = pattern[0]
            if len(pattern) > 1:
                secondpart = pattern[1]
            else:
                secondpart = None
            return firstpart, secondpart

        # FIXME: this should not be here
        commit_specifier, commit_subject = _spilttag_first_word(self.parameters)
        if re.search('^[0-9a-fA-F]{8,40}', commit_specifier) is None:
            # looks like this is no hexsha, so assume it's a commit summary
            commit_specifier = None
            commit_subject = _remove_quoting_chars(self.parameters)
        else:
            # ignore subject
            commit_subject = None

        regression.fixedby(
                self.report_rzbcmd.gmtime,
                commit_specifier,
                commit_subject,
                repsrcid=self.report_rzbcmd.repsrc.repsrcid,
                repentry=self.report_rzbcmd.entryid,
                )

    def _from(self, regression):
        regression.update_author(
                self.report_rzbcmd.entryid,
                self.parameters,
                )

    def _inconclusive(self, regression):
        regression.inconclusive(
                self.parameters,
                self.report_rzbcmd.gmtime,
                self.report_rzbcmd.entryid,
                self.report_issue.repsrc.repsrcid,
                )

    def _ignore_activity(self, regression):
        # nothing to do here, handled elsewhere
        pass

    def _introduced(self, regression):
        def _introduced_create():
            # add regression
            regression = regzbot.RegressionBasic.introduced_create(
                    self.report_issue.repsrc.repsrcid,
                    self.report_issue.entryid,
                    self.report_issue.summary,
                    self.report_issue.realname,
                    self.report_issue.username,
                    self.parameters,
                    self.report_issue.gmtime,
                    )
            # add all existing activities for the newly created regression
            for activity in self.report_issue.get_activities:
                regzbot.RegActivityEvent.event(
                    activity.gmtime,
                    activity.issue_id,
                    activity.summary,
                    activity.realname,
                    activity.repsrc.repsrcid,
                    actimonid=regression.actimonid,
                    patchkind=activity.patchkind,
                    subentry=activity.comment_id,
                    )
            # return newly created regression
            return regression

        def _introduced_update(regression):
            regression.introduced_update(self.parameters)

        if not regression:
            return _introduced_create()
        return _introduced_update(regression)

    def _link(self, regression):
        regression.linkadd(
                self.parameters,
                self.report_rzbcmd.gmtime,
                self.report_rzbcmd.realname,
                )

    def _monitor(self, regression):
        regression.monitoradd(
                self.parameters,
                self.report_issue.gmtime,
                self.report_issue.repsrc,
                None,
                )

    def _poke(self, regression):
        # nothing to do here, handled elsewhere
        pass

    def _summary(self, regression):
        regression.title(self.parameters)

    def _unbackburn(self, regression):
        regression.backburner_remove()

    def _unlink(self, regression):
        regression.linkremove(self.parameters)

    def _unmonitor(self, regression):
        regression.monitorremove(
                self.parameters,
                self.report_issue.gmtime,
                self.report_issue.repsrc,
                None,
                )

    def process(self, regression):
        regression_created = False
        if self.cmd == 'introduced':
            regression_created = self._introduced(regression)
            if regression_created:
                regression = regression_created
        elif self.cmd in (
                'backburn',
                'duplicate',
                'duplicateof',
                'fix',
                'from',
                'link',
                'ignore-activity',
                'inconclusive',
                'monitor',
                'poke',
                'resolve',
                'summary',
                'unbackburn',
                'unlink',
                'unmonitor',
                ):
            getattr(self, '_%s' % self.cmd)(regression)
        else:
            regzbot.UnhandledEvent.add(
                self.report_rzbcmd.web_url, "unknown regzbot command: %s" % self.cmd, gmtime=self.report_rzbcmd.gmtime, subject=self.report_rzbcmd.summary)

        # finish up with adding the history event
        self._add_history_event(regression)

        # return the regression, which might have been created if a introduced command was used
        if regression_created:
            return regression
        return None


class RbCmdStackNew:
    def __init__(self, report_issue, report_rzbcmd):
        self._commands = []
        self.regression = None
        self.report_issue = report_issue
        self.report_rzbcmd = report_rzbcmd

    def _add_command(self, cmd, parameters):
        cmd = cmd.lower()

        # catch a few frequent typos and handle renamed commands
        if cmd in ('backburner', 'back-burner'):
            cmd = 'backburn'
        elif cmd in ('dup', ):
            cmd = 'duplicate'
        elif cmd in ('dupof', 'duplicate-of'):
            cmd = 'duplicateof'
        elif cmd in ('resolved', 'invalid'):
            cmd = 'resolve'
        elif cmd in ('fixedby', 'fixed-by'):
            cmd = 'fix'
        elif cmd in ('subject', 'title'):
            cmd = 'summary'
        elif cmd in ('unback-burner', 'back-burner'):
            cmd = 'unbackburn'

        cmdobj = RbCmdSingleNew(self, cmd, parameters)
        self._commands.append(cmdobj)

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

        self.regression = regzbot.RegressionBasic.get_by_repsrc_n_entry(self.report_issue.repsrc, self.report_issue.entryid)
        for single_command in _walk_commands():
            if single_command.cmd == 'introduced':
                self.regression = single_command.process(self.regression)
            elif not self.regression:
                raise RuntimeError
            else:
                single_command.process(self.regression)
        return self.regression

    @staticmethod
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


    @classmethod
    def process_input(cls, report_issue, report_rzbcmd, body):
        cmd_stack = None
        # the following loop locates sections with regzbot commands; it adds a newline at the start and two at the end
        # of the processed string, as the regzbot command might be right at the start or the end of the processed input
        for cmd_section in re.finditer(r'^\n#regzbot.*\n\s*\n$', '\n' + body + '\n\n', re.MULTILINE | re.IGNORECASE | re.DOTALL):
            for command, parameter in cls._parse(cmd_section[0]):
                if not cmd_stack:
                    cmd_stack = cls(report_issue, report_rzbcmd)
                cmd_stack._add_command(command, parameter)
            if cmd_stack:
                cmd_stack.process_commands()


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
