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
            msgid = regzbot.mailin.email_get_msgid(over['message-id'])
            gmtime = email.utils.mktime_tz(email.utils.parsedate_tz(over['date']))

            _, article = nntp_connection.article(art_num)
            msg = email.message_from_bytes(b'\n'.join(article.lines), policy=policy.default)
            regzbot.mailin.process_msg(repsrc, msg)

        # update database
        repsrc.set_lastchked(group_lastid)


def download_thread_old(msgid, repsrcid = None):
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


def download_thread(msgid, repsrcid = None):
    def download_extract(url, file):
            try:
                logger.debug("Downloading %s", url)
                with urllib.request.urlopen(url) as response:
                    with gzip.open(response) as uncompressed:
                        shutil.copyfileobj(uncompressed, tmpfile)
                return True
            except urllib.error.HTTPError as err:
                logger.critical('Failed to download thread from %s: %s', url, err)
                return False

    with tempfile.NamedTemporaryFile() as tmpfile:
        downloaded = download_extract('https://lore.kernel.org/all/%s/t.mbox.gz' % msgid, tmpfile)
        if not downloaded and repsrcid:
            # work around https://twitter.com/kernellogger/status/1443863850722410496
            repsrc = regzbot.ReportSource.get_by_id(repsrcid)
            download_extract('%s/%s/t.mbox.gz' % (repsrc.weburl.rstrip('/'), msgid), tmpfile)

        for message in mailbox.mbox(tmpfile.name):
            yield email.message_from_bytes(message.as_bytes(), policy=policy.default)


def download_msg(msgid, repsrcid):
    def download_this(url):
        try:
            logger.debug("Downloading %s", url)
            with urllib.request.urlopen(url) as response:
                # ignore decoding errors due to messages like https://lore.kernel.org/all/20211101140613.GC1456700@rowland.harvard.edu/raw
                msg = email.message_from_string(response.read().decode('utf-8', errors='ignore'), policy=policy.default)
                return msg
        except urllib.error.HTTPError as err:
            logger.critical('Failed to download msg %s: %s"', msgid, err)
            return None

    repsrc = None
    msg = download_this('https://lore.kernel.org/all/%s/raw' % msgid)
    if not msg and repsrcid:
        # work around https://twitter.com/kernellogger/status/1443863850722410496
        repsrc = regzbot.ReportSource.get_by_id(repsrcid)
        msg = download_this('%s/%s/raw' % (repsrc.weburl.rstrip('/'), msgid))

    repsrc = regzbot.mailin.adjust_repsrc(repsrc, msg)
    return repsrc, msg


def process_replies(msgid):
    def find_repsrc(msg, repsrc=None):
        repsrc = regzbot.mailin.adjust_repsrc(repsrc, msg)
        if repsrc is None:
            repsrc, msg = download_msg(msgid)
            if repsrc is None:
                logger.critical("Found msg %s in the webarchives, but was unable to assign it to any of the sources we know about", msgid)
                return False

    for msg in download_thread(msgid):
        if msg is None:
            logger.critical("Downloading the thread %s failed", msgid)
            return None

        if msg['References'] is not None:
            for reference in msg['References'].split(" "):
                if regzbot.mailin.email_get_msgid(reference) == msgid:
                    repsrc = find_repsrc(msg)
                    regzbot.mailin.process_msg(repsrc, msg)
