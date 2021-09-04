#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2021 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

import email
from email import policy
import nntplib
import gzip
import mailbox
import urllib.request
import tempfile
import shutil

import regzbot

logger = regzbot.logger

# without this, we occationally [as on 20210831] run into
# "nntplib.NNTPDataError: line too long" errors
# might be a bug in the public-inbox code behind lore
nntplib._MAXLINE = 65536


def _group(nntp_connection, nntpurl):
    _, _, nntp_server, nntp_group = nntpurl.split('/', maxsplit=3)

    # open connection or reuse it
    if (nntp_connection is None
            or nntp_server != nntp_connection.host):
        logger.debug('connecting to "%s"' % nntp_server)
        nntp_connection = nntplib.NNTP(nntp_server)

    _, _, group_firstid, group_lastid, _ = nntp_connection.group(nntp_group)
    return nntp_connection, group_firstid, group_lastid


def run():
    nntp_connection = None

    # retrieve the number of msg for all groups first to avoid races
    for repsrc in regzbot.ReportSource.getall_bykind('lore'):
        nntp_connection, group_firstid, group_lastid = _group(nntp_connection, repsrc.serverurl)

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
                msg = email.message_from_bytes(b'\n'.join(article.lines), policy=policy.default)
                regzbot.mailin.process_msg(repsrc, msg)

        # update database
        repsrc.set_lastchked(group_lastid)

def retrieve_thread(msgid):
   with tempfile.NamedTemporaryFile() as tmpfile:
       try:
           url = 'https://lore.kernel.org/all/%s/t.mbox.gz' % msgid
           with urllib.request.urlopen(url) as response:
               with gzip.open(response) as uncompressed:
                   shutil.copyfileobj(uncompressed, tmpfile)
           pass
           for message in mailbox.mbox(tmpfile.name):
               yield email.message_from_bytes(message.as_bytes(), policy=policy.default)
       except urllib.error.HTTPError as err:
           print('Failed to download thread %s: %s"', msgid, err)


def _article_vianntp(msgid):
    nntp_connection = None

    # at least currently on lore, it seems stat() returns a result with article number as "1",
    # even if the message was not sent to the list/group in question; we reply on this for now

    # simply take group and server from first repsource seen
    for repsrc in regzbot.ReportSource.getall_bykind('lore'):
        nntp_connection, _, _ = _group(nntp_connection, repsrc.serverurl)
        break

    try:
        resp, number, message_id = nntp_connection.stat('<%s>' % msgid)
    except nntplib.NNTPTemporaryError:
        # looks like the article does not exist
        return False

    repsrc = None
    try:
        _, overviews = nntp_connection.over('<%s>' % msgid)
        _, over = overviews[0]

        xrefs = over['xref'].split()
        servername = xrefs[0]
        for xref in xrefs[1:]:
            groupname, acticlenr = xref.split(':')
            serverurl = 'nntp://%s/%s' % (servername, groupname)

            tmprepsrc = regzbot.ReportSource.get_by_serverurl(serverurl)
            if tmprepsrc is None:
                logger.debug('failed to find a RepSource() where servername is nntp://%s/%s' % (servername, groupname))
                continue
            if repsrc is None or repsrc.priority > tmprepsrc.priority:
                repsrc = tmprepsrc

        if repsrc is None:
            return None
    except nntplib.NNTPTemporaryError:
        # looks like the article does not exist on that list
        return False

    nntp_connection, _, _ = _group(nntp_connection, repsrc.serverurl)
    _, article = nntp_connection.article('<%s>' % msgid)
    msg = email.message_from_bytes(b'\n'.join(article.lines), policy=policy.default)

    return(repsrc, msg)


def article(msgid):
    for msg in retrieve_thread(msgid):
        if msg is None:
           # something went from when retrieving that thread
           return None
        elif msgid == regzbot.mailin.email_get_msgid(msg):
           repsrc = regzbot.mailin.adjust_repsrc(None, msg)
           if repsrc:
               return (repsrc, msg)
           else:
               logger.warning('Found msg %s in the webarchives, but seems none of the sources for reports match; trying via NNTP instead', msgid)
               return _article_vianntp(msgid)
