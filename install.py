# installer for the weewx-columbia-ms driver
# Copyright 2020 William Burton
# Distributed under the terms of the GNU Public License (GPLv3)

from weecfg.extension import ExtensionInstaller

def loader():
    return ColumbiaMicroServerInstaller()

class ColumbiaMicroServerInstaller(ExtensionInstaller):
    def __init__(self):
        super(ColumbiaMicroServerInstaller, self).__init__(
            version="0.2.0",
            name='columbia_ms',
            description='Capture weather data from a Columbia Weather Systems MicroServer',
            author="William Burton",
            author_email="bburton@mail.com",
            files=[('bin/user', ['bin/user/columbia_ms.py'])]
            )
