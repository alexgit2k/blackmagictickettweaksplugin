#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2008 Stephen Hansen <shansen@advpubtech.com>
# Copyright (C) 2009 Rowan Wookey <support@obsidianproject.co.uk>
# Copyright (C) 2008-2009 www.obsidianproject.co.uk
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

from setuptools import find_packages, setup

setup(
    name='BlackMagicTicketTweaks',
    version='0.12r1',
    author='Stephen Hansen',
    maintainer='Rowan Wookey',
    maintainer_email='support@obsidianproject.co.uk',
    author_email='shansen@advpubtech.com',
    description="Various hacks to alter the behavior of the ticket form.",
    license="BSD 3-Clause",
    url="http://trac-hacks.org/wiki/BlackMagicTicketTweaksPlugin",
    packages=find_packages(exclude=['*.tests*']),
    package_data={
        'blackmagic': [
            'htdocs/js/*.js', 'htdocs/css/*.css'
        ]
    },
    entry_points={
        'trac.plugins': [
            'blackmagic = blackmagic',
        ]
    }
)
