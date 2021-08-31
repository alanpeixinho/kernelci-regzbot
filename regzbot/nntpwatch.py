#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import email
import nntplib

import regzbot

logger = regzbot.logger

# without this, we occationally [as on 20210831] run into
# "nntplib.NNTPDataError: line too long" errors
# might be a bug in the public-inbox code behind lore
nntplib._MAXLINE = 65536

def run():
    nntp_connection = None

    # retrieve the number of msg for all groups first to avoid races
    for repsrc in regzbot.ReportSource.getall_bykind('lore'):
        _, _, nntp_server, nntp_group = repsrc.serverurl.split('/', maxsplit=3)

        # open connection or reuse it
        if (nntp_connection is None
                or nntp_server != nntp_connection.host):
            logger.debug('connecting to "%s"' % nntp_server)
            nntp_connection = nntplib.NNTP(nntp_server)

        _, _, group_firstid, group_lastid, _ = nntp_connection.group(nntp_group)

        # is there something new to check?
        if not repsrc.lastchked:
            repsrc.set_lastchked(group_firstid)
            startwith = group_lastid
            logger.info(
                'seeing %s for the first time, starting to monitor it from now on', repsrc.serverurl)
            repsrc.set_lastchked(group_lastid)
            continue
        elif repsrc.lastchked == group_lastid:
            logger.debug('nothing new in %s', repsrc.serverurl)
            continue
        else:
            startwith = repsrc.lastchked + 1

        logger.debug('processing "%s"', repsrc.serverurl)

        _, overviews = nntp_connection.over((startwith, group_lastid))

        for art_num, over in overviews:
            msgid = over['message-id'][1:-1]
            gmtime = email.utils.mktime_tz(email.utils.parsedate_tz(over['date']))

            if regzbot.RecordProcessedMsgids.check_presence(msgid, gmtime):
                logger.debug('skipping "%s", we already encountered it it', msgid)
            else:
                _, article = nntp_connection.article(art_num)
                regzbot.mailin.processmsg_nntp(repsrc, article)

        # update database
        repsrc.set_lastchked(group_lastid)
