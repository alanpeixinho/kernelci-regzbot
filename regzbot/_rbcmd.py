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
        self.activity_regression_report = rbcmd_stack.activity_regression_report
        self.activity_containing_rzbcmd = rbcmd_stack.activity_containing_rzbcmd
        self.parameters = parameters

        # handle frequent typos, alternatives, and renamed commands
        self.cmd = cmd.lower()
        if self.cmd in ('backburner', 'back-burner'):
            self.cmd = 'backburn'
        elif self.cmd in ('dup', ):
            self.cmd = 'duplicate'
        elif self.cmd in ('dupof', 'duplicate-of'):
            self.cmd = 'duplicateof'
        elif self.cmd in ('resolved', 'invalid'):
            self.cmd = 'resolve'
        elif self.cmd in ('fixedby', 'fixed-by'):
            self.cmd = 'fix'
        elif self.cmd in ('subject', 'title'):
            self.cmd = 'summary'
        elif self.cmd in ('unback-burner', 'back-burner'):
            self.cmd = 'unbackburn'

    def _add_history_event(self, regression):
        regzbotcmd = '%s' % self.cmd
        if self.parameters:
            regzbotcmd = '%s: %s' % (regzbotcmd, self.parameters)
        regzbot.RegHistory.event(
                regression.regid,
                self.activity_containing_rzbcmd.gmtime,
                self.activity_containing_rzbcmd.entryid,
                self.activity_containing_rzbcmd.summary,
                self.activity_containing_rzbcmd.realname,
                repsrcid=self.activity_containing_rzbcmd.repsrc.repsrcid,
                regzbotcmd=regzbotcmd)

    def _backburn(self, regression):
        regression.backburner_add(
                self.activity_containing_rzbcmd.repsrc.repsrcid,
                self.activity_containing_rzbcmd.entryid,
                self.activity_containing_rzbcmd.gmtime,
                self.activity_containing_rzbcmd.realname,
                self.parameters)

    def _duplicate(self, regression):
        regression.duplicate(
                self.parameters,
                self.activity_containing_rzbcmd.gmtime,
                self.activity_containing_rzbcmd.entryid,
                self.activity_regression_report.summary,
                self.activity_containing_rzbcmd.realname,
                self.activity_containing_rzbcmd.repsrc.repsrcid)

    def _duplicateof(self, regression):
        regression.dupof(
                self.parameters,
                self.activity_containing_rzbcmd.gmtime,
                self.activity_containing_rzbcmd.entryid,
                self.activity_regression_report.summary,
                self.activity_containing_rzbcmd.realname,
                self.activity_containing_rzbcmd.repsrc.repsrcid)

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
                self.activity_containing_rzbcmd.gmtime,
                commit_specifier,
                commit_subject,
                repsrcid=self.activity_containing_rzbcmd.repsrc.repsrcid,
                repentry=self.activity_containing_rzbcmd.entryid,
                )

    def _from(self, regression):
        regression.update_author(
                self.activity_containing_rzbcmd.entryid,
                self.parameters,
                )

    def _inconclusive(self, regression):
        regression.inconclusive(
                self.parameters,
                self.activity_containing_rzbcmd.gmtime,
                self.activity_containing_rzbcmd.entryid,
                self.activity_regression_report.repsrc.repsrcid,
                )

    def _introduced(self, regression):
        def __add_related_activities(regression):
            # when creating a regression, add existing activities to the database; but only
            # handle regzbot commands in activities that happened after the regression was
            # added; this way we also won't process the commands in the activity
            # we currently process, which might be in this list
            actimon = regression.get_actimon()
            for activity in self.activity_regression_report.all_related_activities():
                if _ignore_activity(activity.message):
                    pass
                elif activity.created_at <= self.activity_containing_rzbcmd.created_at:
                    actimon.add_activity(activity)
                else:
                    process_activity(activity)

        def _introduced_create():
            # add regression
            regression = regzbot.RegressionBasic.introduced_create(
                    self.activity_regression_report.repsrc.repsrcid,
                    self.activity_regression_report.entryid,
                    self.activity_regression_report.summary,
                    self.activity_regression_report.realname,
                    self.activity_regression_report.username,
                    self.parameters,
                    self.activity_regression_report.gmtime,
                    )

            return regression

        if not regression:
            regression = _introduced_create()
            __add_related_activities(regression)
            return regression

        regression.introduced_update(self.parameters)
        return None

    def _link(self, regression):
        regression.linkadd(
                self.parameters,
                self.activity_containing_rzbcmd.gmtime,
                self.activity_containing_rzbcmd.realname,
                )

    def _monitor(self, regression):
        regression.monitoradd(
                self.parameters,
                self.activity_regression_report.gmtime,
                self.activity_regression_report.repsrc,
                None,
                )

    def _summary(self, regression):
        regression.title(self.parameters)

    def _unbackburn(self, regression):
        regression.backburner_remove()

    def _unlink(self, regression):
        regression.linkremove(self.parameters)

    def _unmonitor(self, regression):
        regression.monitorremove(
                self.parameters,
                self.activity_regression_report.gmtime,
                self.activity_regression_report.repsrc,
                None,
                )

    def process(self, regression):
        regression_created = None
        if self.cmd == 'introduced':
            regression_created = self._introduced(regression)
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
                'duplicateof',
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
            getattr(self, '_%s' % self.cmd)(regression)
        else:
            regzbot.UnhandledEvent.add(
                self.activity_containing_rzbcmd.web_url, "unknown regzbot command: %s" % self.cmd, gmtime=self.report_rzbcmd.gmtime, subject=self.report_rzbcmd.summary)

        # create the history event
        if self.cmd is not 'ignore-activity':
            self._add_history_event(regression)

        # let caller know if we created a regression
        return regression_created


class RbCmdStackNew:
    def __init__(self, activity):
        self._commands = []
        self.activity_containing_rzbcmd = activity
        self.activity_regression_report = activity
        self.regression = self._locate_regression()

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

    def _locate_regression(self):
        return regzbot.RegressionBasic.get_by_activity(self.activity_regression_report)

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
        assert (self.activity_regression_report)
        for single_command in _walk_commands():
            if single_command.cmd == 'introduced':
                regression_created = single_command.process(self.regression)
                if regression_created:
                    self.regression = self._locate_regression()
                    assert (self.regression)
            else:
                assert (self.regression)
                single_command.process(self.regression)
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

def process_activity(activity):
    # add activity when something is montitoring this
    for actimon in regzbot.RegActivityMonitor.get_by_activity(activity):
        # check for flags before adding a activity; note that the RE used below is derivated from one in
        # RbCmdStackNew._parse and explained in more detail there
        if not _ignore_activity(activity.message):
            actimon.add_activity(activity)

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
