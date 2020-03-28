#!/usr/bin/env python
# Copyright 2020 by William Burton
# Distributed under the terms of the GNU Public License (GPLv3)

"""Driver for collecting data from the Columbia Weather Systems MicroServer.

This is directly modeled after the weewx-ip100 plugin
(https://github.com/weewx/weewx/wiki/ip100) by Matthew Wall.

This file contains a weewx driver.

Installation

Put this file in the bin/user directory.

Driver Configuration

Add the following to weewx.conf:

[ColumbiaMicroServer]
    driver = user.columbia_ms
    port = 80
    host = 192.168.0.50
    poll_interval = 10 # how often to query the MicroServer, in seconds
    max_tries = 3
    retry_wait = 5  
    
TODO

1. Verify units in XML input file with assumptions in the code.

The XML file downloaded from the MicroServer is the enhanced version which
includes the units of each item as an attribute so it's possible to determine 
if the station temperatures are configured in celcius or farenheight, rain 
is in mm, cm or inches, wind speed in kph, mph or knots, etc. However, at 
present, the code assumes all US/imperial units have been configured and 
does not check these units. At the very least, checking needs to be 
implemented to avoid corrupt data or better if the driver can automatically
convert data if appropriate.

2. Implement a way to load historical data.

The MicroServer by default logs one record per minute to a CSV file on a
microSD card with a new CSV file started for each day. These CSV files are
automatically pruned after one year so there's never more than about 365 
files or days of data on the MicroServer.

Probably the best way to import historical data is to implement a new import
configuration class based on the Weather Underground wuimport.py implementation 
used with the weeimport utility. This requires the following functionality:

a. Option to download all or a date range of files from the MicroServer. 
   This will require logging in as the admin user and screen-scraping the 
   Data Logs page (/admin/logfiles.php) to retrieve the URL of each available 
   file. Then, each file within the range would be downloaded. It would be 
   preferable to point this to a known folder and avoid downloading any
   file that was already downloaded. Note that the file for "today" is always
   a partial file so it may be best not to download it.

b. Import daily CSV files from a folder, optionally based on a date-range.
   The import function needs to be separate from the download so it will be
   possible to upload older archived files into WeeWX that are no longer 
   on the MicroServer but were previously downloaded by other means.
 
Non-goals

The MicroServer does not have any API's to support the following functions:
* Query of hardware status
* Setting hardware configuration
* Update historical data automatically within this driver.

The best that's available is a web-based administration console which would 
have to be reverse-engineered to enable this driver to perform these functions. 
Since there already exists a full-featured web-based administration console, 
spending much effort to duplicate the console functionality is probably not 
worth the effort.

"""

from __future__ import with_statement
from __future__ import absolute_import
from __future__ import print_function
import time
import socket
from xml.etree import ElementTree

DRIVER_NAME = 'ColumbiaMicroServer'
DRIVER_VERSION = '0.1'
DRIVER_SHORT_NAME = 'columbia_ms'

try:
    # Python 3
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:
    # Python 2
    from urllib2 import Request, urlopen, HTTPError, URLError

import weewx
import weewx.drivers

try:
    # Test for new-style weewx logging by trying to import weeutil.logger
    import weeutil.logger
    import logging
    log = logging.getLogger(__name__)

    def logdbg(msg):
        log.debug(msg)

    def loginf(msg):
        log.info(msg)

    def logerr(msg):
        log.error(msg)

except ImportError:
    # Old-style weewx logging
    import syslog

    def logmsg(level, msg):
        # output in a way to avoid a TypeError
        try:
            syslog.syslog(level, '%s: %s' % (DRIVER_SHORT_NAME, msg))
        except TypeError as e:
            syslog.syslog(level, '%s: TypeError %s - %s: ' % (DRIVER_SHORT_NAME, e, type(msg)))

    def logdbg(msg):
        logmsg(syslog.LOG_DEBUG, msg)

    def loginf(msg):
        logmsg(syslog.LOG_INFO, msg)

    def logerr(msg):
        logmsg(syslog.LOG_ERR, msg)

def loader(config_dict, engine):
    return ColumbiaMicroServerDriver(**config_dict[DRIVER_NAME])

def configurator_loader(config_dict):
    return ColumbiaMicroServerConfigurator()

def confeditor_loader():
    return ColumbiaMicroServerConfEditor()


class ColumbiaMicroServerConfEditor(weewx.drivers.AbstractConfEditor):
    @property
    def default_stanza(self):
        return """
[ColumbiaMicroServer]
    # This section is for the Columbia Weather Systems MicroServer.

    # The driver to use
    driver = user.columbia_ms

    # How often to poll the MicroServer, in seconds
    poll_interval = 10

    max_tries = 3
    retry_wait = 5  

"""


class ColumbiaMicroServerConfigurator(weewx.drivers.AbstractConfigurator):
    def add_options(self, parser):
        super(ColumbiaMicroServerConfigurator, self).add_options(parser)
        parser.add_option("--info", dest="info", action="store_true",
                          help="display weather station configuration")
        parser.add_option("--current", dest="current", action="store_true",
                          help="get the current weather conditions")

    def do_options(self, options, parser, config_dict, prompt):
        station = ColumbiaMicroServerDriver(**config_dict[DRIVER_NAME])
        if options.current:
            self.show_current(station)
        else:
            self.show_info(station)

    @staticmethod
    def show_info(station):
        """Query the station then display the settings."""
        # FIXME: implement show_info

    @staticmethod
    def show_current(station):
        """Display latest readings from the station."""
        for packet in station.genLoopPackets():
            print(packet)
            break


class ColumbiaMicroServerDriver(weewx.drivers.AbstractDevice):
    # Default map for the Columbia MicroServer to WeeWX.
    DEFAULT_SENSOR_MAP = {
        #'dateTimeHW': 'mtSampTime',
        'outTemp': 'mtTemp1',
        'outHumidity': 'mtRelHumidity',
        'barometer': 'mtAdjBaromPress',
        'windSpeed': 'mtWindSpeed',
        'windDir': 'mtAdjWindDir',
        'windGust': 'mt2MinWindGustSpeed',
        'windGustDir': 'mt2MinWindGustDir',
        'outHumidity': 'mtRelHumidity',
        'rainRate': 'mtRainRate',
        'dewpoint': 'mtDewPoint',
        'windchill': 'mtWindChill',
        'heatindex': 'mtHeatIndex',
        'radiation': 'mtSolarRadiaton',
        'extraTemp1': 'mtTemp_2',
        'extraTemp2': 'mtTemp_3',
        'extraTemp3': 'mtTemp_4'
    }
    # Map is used when parsing the MicroServer XML to determine if an input 
    # element should be passed back or not.
    XML_INPUT_ELEMENTS = {
        #'mtSampTime': 1,
        'mtTemp1': 1,
        'mtRelHumidity': 1,
        'mtAdjBaromPress': 1,
        'mtWindSpeed': 1,
        'mtAdjWindDir': 1,
        'mt2MinWindGustSpeed': 1,
        'mt2MinWindGustDir': 1,
        'mtRelHumidity': 1,
        'mtRainRate': 1,
        'mtDewPoint': 1,
        'mtWindChill': 1,
        'mtHeatIndex': 1,
        'mtSolarRadiaton': 1,
        'mtTemp_2': 1,
        'mtTemp_3': 1,
        'mtTemp_4': 1
    }

    def __init__(self, **stn_dict):
        loginf('driver version is %s' % DRIVER_VERSION)
        if 'station_url' in stn_dict:
            self.station_url = stn_dict['station_url']
        else:
            host = stn_dict.get('host', '192.168.0.50')
            port = int(stn_dict.get('port', 80))
            self.station_url = "http://%s:%s/tmp/latestsampledata_u.xml" % (host, port)
        loginf("station url is %s" % self.station_url)
        self.poll_interval = int(stn_dict.get('poll_interval', 10))
        loginf("poll interval is %s" % self.poll_interval)
        self.sensor_map = dict(ColumbiaMicroServerDriver.DEFAULT_SENSOR_MAP)
        if 'sensor_map' in stn_dict:
            self.sensor_map.update(stn_dict['sensor_map'])
        loginf("sensor map: %s" % self.sensor_map)
        self.max_tries = int(stn_dict.get('max_tries', 3))
        self.retry_wait = int(stn_dict.get('retry_wait', 5))

    @property
    def hardware_name(self):
        return "Columbia Weather Systems MicroServer"

    def genLoopPackets(self):
        ntries = 0
        while ntries < self.max_tries:
            ntries += 1
            try:
                data = ColumbiaMicroServerStation.get_data(self.station_url)
                logdbg("genLoopPackets: raw data: %s" % data)
                pkt = ColumbiaMicroServerStation.parse_data(data)
                logdbg("genLoopPackets: parsed packet: %s" % pkt)
                ntries = 0
                packet = {'dateTime': int(time.time() + 0.5)}
                if pkt['base_units'] == 'English':
                    packet['usUnits'] = weewx.US
                else:
                    packet['usUnits'] = weewx.METRICWX
                for k in self.sensor_map:
                    if self.sensor_map[k] in pkt:
                        packet[k] = pkt[self.sensor_map[k]]
                yield packet
                if self.poll_interval:
                    time.sleep(self.poll_interval)
            except weewx.WeeWxIOError as e:
                loginf("failed attempt %s of %s: %s" %
                       (ntries, self.max_tries, e))
                time.sleep(self.retry_wait)
        else:
            raise weewx.WeeWxIOError("max tries %s exceeded" % self.max_tries)


class ColumbiaMicroServerStation(object):
    @staticmethod
    def get_data(url):
        try:
            request = Request(url)
            request.add_header('User-Agent', 'WeeWX/%s' % weewx.__version__)
            response = urlopen(request, timeout=4)
        except URLError as e:
            logerr("get_data(): Unable to open weather station %s or %s" % (url, e))
            raise weewx.WeeWxIOError("get_data(): Socket error or timeout for weather station %s or %s" % (url, e))
        except (socket.error, socket.timeout) as e:
            logerr("get_data(): Socket error or timeout for weather station %s or %s" % (url, e))
            raise weewx.WeeWxIOError("get_data(): Socket error or timeout for weather station %s or %s" % (url, e))
        if response.getcode() != 200:
            raise weewx.WeeWxIOError("get_data(): Bad response code returned: %d." % response.code)
        content_length = int(response.info().get('Content-Length'))
        return response.read(content_length).decode('utf-8')

    @staticmethod
    def parse_data(data):
        import re
        record = dict()
        # If closing tag is truncated or has excess junk, fix before parsing
        if data.startswith('<oriondata') and not data.endswith('</oriondata>'):
            data = re.sub('</ori(ondata)?.*$','</oriondata>', data)
            logerr("parse_data(): attempted to correct truncated data: %s" % data[-19:-1])
        try:
            root = ElementTree.fromstring(data)
            if root.tag == 'oriondata' and root[0].tag == 'meas':
                record.update(ColumbiaMicroServerStation.parse_weather(root))
            else:
                raise ElementTree.ParseError("invalid XML file. Mising <oriondat> and <meas/>")
        except ElementTree.ParseError as e:
            logerr("ElementTree ParseError: %s for data: %s" % (e, data))
            raise weewx.WeeWxIOError(e)
        return record

    @staticmethod
    def parse_weather(elements):
        record = dict()
        record['base_units'] = 'English'
        if not len(elements):
            return record
        for child in elements:
            name = child.attrib['name']
            if child.tag == 'meas' and name in ColumbiaMicroServerDriver.XML_INPUT_ELEMENTS:
                if name.endswith('Time'):
                    record[name] = child.text
                else:
                    record[name] = float(child.text)
        return record


if __name__ == '__main__':
    import optparse

    usage = """%prog [options] [--debug] [--help]"""

    def main():
        import sys
        import syslog
        import json
        syslog.openlog('wee_' + DRIVER_SHORT_NAME, syslog.LOG_PID | syslog.LOG_CONS)
        parser = optparse.OptionParser(usage=usage)
        parser.add_option('--version', dest='version', action='store_true',
                          help='display driver version')
        parser.add_option('--debug', dest='debug', action='store_true',
                          help='display diagnostic information while running')
        parser.add_option('--config', dest='cfgfn', type=str, metavar="FILE",
                          help="Use configuration file FILE. Default is /etc/weewx/weewx.conf or /home/weewx/weewx.conf")
        parser.add_option('--host', dest='host', metavar="HOST",
                          help='hostname or ip address of the MicroServer')
        parser.add_option('--port', dest='port', type=int, metavar="PORT",
                          default=80,
                          help='port on which the MicroServer is listening')
        parser.add_option('--test-parse', dest='filename', metavar='FILENAME',
                          help='test the xml parsing')
        (options, _) = parser.parse_args()

        if options.version:
            print("%s driver version %s" % (DRIVER_SHORT_NAME, DRIVER_VERSION))
            exit(1)

        weeutil.logger.setup(DRIVER_SHORT_NAME, {})

        if options.debug is not None:
            syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_DEBUG))
            weewx.debug = 1
        else:
            syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_INFO))
            weewx.debug = 0

        if options.filename:
            data = ''
            with open(options.filename, "r") as f:
                data = f.read()
            record = ColumbiaMicroServerStation.parse_data(data)
            #print("record: ", record)
            json.dump(record, sys.stdout)
            exit(0)

        url = "http://%s:%s" % (options.host, options.port)
        print("get data from %s" % url)
        data = ColumbiaMicroServerStation.get_data(url)
        if options.debug:
            print("data: ", data)
        record = ColumbiaMicroServerStation.parse_data(data)
        #print("record: ", record)
        json.dump(record, sys.stdout)

    main()
