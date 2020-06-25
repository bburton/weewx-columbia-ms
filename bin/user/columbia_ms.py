#!/usr/bin/env python
# Copyright 2020 by William Burton
# Distributed under the terms of the GNU Public License (GPLv3)

"""Driver for collecting data from the Columbia Weather Systems MicroServer.

This driver is loosely based on the weewx-ip100 driver
(https://github.com/weewx/weewx/wiki/ip100) by Matthew Wall.

This driver has been tested against WeeWX 3.9.2 under Python 2.7 and 
WeeWX 4 under Python 3.6.

To obtain weather data from the MicroServer, this driver polls the MicroServer 
via HTTP downloading the Enhanced XML version of the current data from 
/tmp/latestsampledata_u.xml. For more information on the format, see the 
Columbia Weather Systems MicroServer User Manual, Appendix B, Enhanced Web
Server available at http://columbiaweather.com/resources/manuals-and-brochures
in PDF format.

As the enhanced XML file downloaded includes the units of each item as an 
attribute, the driver uses that to determine if the station temperatures are 
configured in celcius or farenheight, rain is in mm, cm or inches, wind 
speed in kph, mph or knots, etc. The driver then groups the data by similar  
units and returns each group as a separate loop packet with the appropriate  
units specified.

In addition, wind data for speed and direction can be returned more frequently
to support near real-time updates but other data is returned only once a minute 
a few seconds before the top of the minute so the data can be processed right
before each archive interval.
 
Installation

Put this file in the bin/user directory.

Driver Configuration

Add the following to weewx.conf:

[ColumbiaMicroServer]
    driver = user.columbia_ms
    port = 80
    host = 192.168.0.50
    polls_per_minute = 4  # How many times per minute to poll the MicroServer
    poll_lead_seconds = 5  # Number of seconds to shift polling earlier
    quick_retries = 3
   
TODO

1. Implement a way to load historical data.

The MicroServer by default logs one record per minute to a CSV file on a
microSD card with a new CSV file started for each day. These CSV files are
automatically pruned after one year so there's never more than about 365 
files or days of data on the MicroServer.

Probably the best way to import historical data is to implement a new import
configuration class based on the Weather Underground wuimport.py implementation 
used with the wee_import utility. This requires the following functionality:

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

Since there already exists a full-featured web-based administration console, 
spending much effort to duplicate the console functionality is probably not 
worth the effort as screen-scraping and reverse-engineering would have to be
done.

"""

from __future__ import with_statement
from __future__ import absolute_import
from __future__ import print_function
import time
import socket
from xml.etree import ElementTree

DRIVER_NAME = 'ColumbiaMicroServer'
DRIVER_VERSION = '1.0.0'
DRIVER_SHORT_NAME = 'columbia_ms'

try:
    # Python 3
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:
    # Python 2
    from urllib2 import Request, urlopen, HTTPError, URLError

import weewx
import weewx.units
import weewx.drivers
import weewx.wxformulas

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

    # How many times per minute to poll the MicroServer
    polls_per_minute = 4

    # Number of seconds to shift polling earlier so loop packet completes
    # processing before the top of the minute.
    poll_lead_seconds = 5

    # Number of retries to perform a quick retry
    quick_retries = 3
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
        'windSpeed': 'mtWindSpeed',
        'windDir': 'mtAdjWindDir',
        'windGust': 'mt2MinWindGustSpeed',
        'windGustDir': 'mt2MinWindGustDir',

        'outTemp': 'mtTemp1',
        'windchill': 'mtWindChill',
        'dewpoint': 'mtDewPoint',
        'heatindex': 'mtHeatIndex',
        'extraTemp1': 'mtTemp_2',
        'extraTemp2': 'mtTemp_3',
        'extraTemp3': 'mtTemp_4',

        'rainTotal': 'mtRainThisMonth',
        'rainRate': 'mtRainRate',

        'barometer': 'mtAdjBaromPress',

        'outHumidity': 'mtRelHumidity',
        'radiation': 'mtSolarRadiaton',
    }

    # Map device units from XML attribute to WeeWX units.
    # See http://www.weewx.com/docs/customizing.htm#units
    UNITS_MAP = {
        'degreeC': weewx.METRICWX,
        'degreeF': weewx.US,
        'inchesHg': weewx.US,
        'inchesPerHour': weewx.US,
        'inchesRain': weewx.US,
        'kmPerHour': weewx.METRIC,
        #'knots': weewx.US,
        'metersPerSecond': weewx.METRICWX,
        'mmPerHour': weewx.METRICWX,
        'mmRain': weewx.METRICWX,
        'mph': weewx.US,
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
        self.polls_per_minute = int(stn_dict.get('polls_per_minute', 4))
        loginf("polls_per_minute is %s" % self.polls_per_minute)
        self.poll_interval = 60 / self.polls_per_minute
        loginf("poll interval is %s" % self.poll_interval)
        self.poll_lead_seconds = int(stn_dict.get('poll_lead_seconds', 5))
        loginf("poll_lead_seconds is %s" % self.poll_lead_seconds)
        self.sensor_map = dict(ColumbiaMicroServerDriver.DEFAULT_SENSOR_MAP)
        if 'sensor_map' in stn_dict:
            self.sensor_map.update(stn_dict['sensor_map'])
        loginf("sensor map: %s" % self.sensor_map)
        self.quick_retries = int(stn_dict.get('quick_retries', 3))
        self.last_rain_total = None

    @property
    def hardware_name(self):
        return "Columbia Weather Systems MicroServer"

    def genLoopPackets(self):
        pkt_grp = None
        ntries = 0
        # Assume the first time being called is the last polling interval for 
        # the minute so all packet types are returned from the first poll 
        # after startup. This is only an issue if loop packets are being  
        # returned to web pages for near real-time updates.
        last_poll_this_minute = True
        while True:
            try:
                data = ColumbiaMicroServerStation.get_data(self.station_url)
                logdbg("genLoopPackets: raw data: %s" % data)
                pkt_grp = ColumbiaMicroServerStation.parse_data(data)
                ntries = 0
            except weewx.WeeWxIOError as e:
                logerr("genLoopPackets: failed attempt %s of %s: %s" % (ntries, self.quick_retries, e))
                ntries += 1
                # First few retries are made quickly then more slowly
                if ntries <= self.quick_retries:
                    self._wait_for_next_poll_interval()
                else:
                    # Wait until the next major poll interval this minute
                    while not self._wait_for_next_poll_interval():
                        pass
                continue
            # Iterate over each packet group returning the packet type and dict
            for pkt_type, pkt in pkt_grp.items():
                logdbg("genLoopPackets: parsed packet: %s" % pkt)
                packet_time = int(time.time() + 0.5)
                # If not a wind packet type, don't returning the packet unless
                # this is the last polling interval for the minute.
                if pkt_type != 'wind' and not last_poll_this_minute:
                    continue
                packet = {'dateTime': packet_time}
                # Translate from input packet field names to output names
                for field in self.sensor_map:
                    if self.sensor_map[field] in pkt:
                        packet[field] = pkt[self.sensor_map[field]]
                # Translate the base_units type to one of the WeeWX unit types
                base_units = pkt['base_units']
                if base_units in ColumbiaMicroServerDriver.UNITS_MAP:
                    packet['usUnits'] = ColumbiaMicroServerDriver.UNITS_MAP[base_units]
                else:
                    # If wind speed is in knots, convert to mph which is a 
                    # supported unit type.
                    if pkt_type == 'wind' and base_units == 'knots':
                        packet['usUnits'] = weewx.US
                        packet['windSpeed'] = weewx.units.conversionDict['knot']['miles_per_hour'](packet['windSpeed'])
                        packet['windGust'] = weewx.units.conversionDict['knot']['miles_per_hour'](packet['windGust'])
                    # Else if a generic packet type, then it's not US or metric 
                    # specific so pick one
                    elif base_units == 'generic':
                        packet['usUnits'] = weewx.US
                    else:
                        logerr("genLoopPackets: error with unknown base_units: %s" % base_units)
                # For a rain packet group, calculate the delta from the last rain packet
                if pkt_type == 'rain':
                    self._calculate_rain_delta(packet)
                yield packet
            # Wait until the next polling interval
            last_poll_this_minute = self._wait_for_next_poll_interval()
            time.sleep(1.0)

    def _wait_for_next_poll_interval(self):
        """Wait until the next polling interval less poll leading seconds so 
        the last poll time is before the top of the minute enabling it to 
        complete just before each archive interval. Returns True if this is the
        last poll interval in the minute, otherwise false."""
        while (int(time.time()) + self.poll_lead_seconds) % int(self.poll_interval) != 0:
            time.sleep(0.5)
        last_poll_time = 60 - self.poll_lead_seconds
        return(time.gmtime(time.time()).tm_sec in range(last_poll_time-1, last_poll_time+2))

    def _calculate_rain_delta(self, packet):
        """Convert from rain total to rain delta."""
        packet['rain'] = weewx.wxformulas.calculate_rain(packet['rainTotal'], self.last_rain_total)
        self.last_rain_total = packet['rainTotal']

class ColumbiaMicroServerStation(object):
    # Map is used when parsing the MicroServer XML to determine if an input 
    # element should be passed back or not, and if so, what packet group it
    # belongs to. Each group can have it's own unit type as the MicroServer
    # supports configuring each group with different units.
    XML_INPUT_ELEMENTS = {
        'mtWindSpeed': 'wind',
        'mtAdjWindDir': 'wind',
        'mt2MinWindGustSpeed': 'wind',
        'mt2MinWindGustDir': 'wind',

        'mtTemp1': 'temp',
        'mtWindChill': 'temp',
        'mtDewPoint': 'temp',
        'mtHeatIndex': 'temp',
        'mtTemp_2': 'temp',
        'mtTemp_3': 'temp',
        'mtTemp_4': 'temp',

        'mtRainThisMonth': 'rain',
        'mtRainRate': 'rain',

        'mtAdjBaromPress': 'pressure',

        'mtRelHumidity': 'generic',
        'mtSolarRadiaton': 'generic',
    }

    # List of input fields that should be used to determine which field should
    # be used to return the unit type for the associated packet group.
    XML_INPUT_UNIT_ELEMENTS = [
        'mtWindSpeed','mtTemp1','mtRainRate','mtRelHumidity','mtAdjBaromPress'
    ]

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
        """Parse the XML data which is a flat non-hierarchical record and return 
        a two-level dictionary hierarchy where each key is the field group and 
        associated with that, a dictionary with the fields and values associated 
        with that group."""
        import re
        pkt_grp = dict()
        # If closing tag is truncated or has excess junk like null bytes, 
        # fix before parsing.
        if data.startswith('<oriondata') and not data.endswith('</oriondata>'):
            data = re.sub('</ori(ondata)?.*$','</oriondata>', data)
            logerr("parse_data(): attempted to correct truncated data: %s" % data[-19:-1])
        try:
            elements = ElementTree.fromstring(data)
            if elements.tag == 'oriondata' and elements[0].tag == 'meas':
                for child in elements:
                    name = child.attrib['name']
                    # Ensure the correct tag and attribute is one to be recorded
                    if child.tag == 'meas' and name in ColumbiaMicroServerStation.XML_INPUT_ELEMENTS:
                        # Get the associated packet group for this field
                        pkt_type = ColumbiaMicroServerStation.XML_INPUT_ELEMENTS[name]
                        # Initialize a new dictionary for a packet group
                        if not pkt_type in pkt_grp:
                            pkt_grp[pkt_type] = dict()
                        # If the field is in the list to use for the unit type,
                        # save the unit type as the field 'base_units'.
                        if name in ColumbiaMicroServerStation.XML_INPUT_UNIT_ELEMENTS:
                            # If the packet type is 'generic' then it's a unit type that's
                            # neither US or metric such as degrees for wind direction.
                            if pkt_type == 'generic':
                                pkt_grp[pkt_type]['base_units'] = 'generic'
                            else:  
                                pkt_grp[pkt_type]['base_units'] = child.attrib['unit']
                        # Store the field and value in the dictionary for the associated packet type.
                        pkt_grp[pkt_type][name] = float(child.text)
            else:
                raise ElementTree.ParseError("invalid XML file. Missing <oriondata> and/or <meas/> tags detected.")
        except ElementTree.ParseError as e:
            logerr("ElementTree ParseError: %s for data: %s" % (e, data))
            raise weewx.WeeWxIOError(e)
        return pkt_grp

# Define a main entry point for basic testing of the station without weewx
# engine and service overhead.  Invoke this as follows from the weewx root directory:
# Test this driver outside of the weewxd daemon
#
# PYTHONPATH=bin python bin/user/columbia_ms.py --help

if __name__ == '__main__':
    import optparse

    usage = """%prog [options] [--debug] [--help]"""

    def main():
        import sys
        import json
        syslog.openlog('wee_' + DRIVER_SHORT_NAME, syslog.LOG_PID | syslog.LOG_CONS)
        parser = optparse.OptionParser(usage=usage)
        parser.add_option('--version', dest='version', action='store_true',
                          help='display driver version')
        parser.add_option('--debug', dest='debug', action='store_true',
                          help='display diagnostic information while running')
        parser.add_option('--config', dest='cfgfn', type=str, metavar="FILE",
                          help="Use configuration file FILE. Default is /etc/weewx/weewx.conf or /home/weewx/weewx.conf")
        parser.add_option('--url', dest='url', metavar="URL",
                          help='Full URL of the MicroServer including path info to XML data')
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
            json.dump(record, sys.stdout)
            exit(0)

        url = "http://%s:%s" % (options.host, options.port)
        if options.url:
            url = options.url
        print("get data from %s" % url)
        data = ColumbiaMicroServerStation.get_data(url)
        if options.debug:
            print("data: ", data)
        record = ColumbiaMicroServerStation.parse_data(data)
        #print("record: ", record)
        json.dump(record, sys.stdout)

    main()
