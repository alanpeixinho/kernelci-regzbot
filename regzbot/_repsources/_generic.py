#! /usr/bin/python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0
# Copyright (C) 2023 by Thorsten Leemhuis
__author__ = 'Thorsten Leemhuis <linux@leemhuis.info>'

from regzbot import ReportSource
from regzbot import ReportThread

class GenRepSrc(ReportSource):
    def thread(self, *, url=None, id=None):
        # for a generic report they are identical
        if not url:
            url = id
        return GenRepTrd(self, url)


class GenRepTrd(ReportThread):
    def __init__(self, repsrc, url):
        self.repsrc = repsrc
        self.id = url
        self.summary = None
        self.gmtime = None
        self.realname = None
        self.username = None
        super().__init__()

    def update(self, *args, **kwargs):
        return
