# Columbia Weather Systems MicroServer Driver for WeeWX

weewx-columbia-ms

Copyright 2020 by William Burton\
Distributed under terms of the GPLv3

This is a WeeWX driver that retrieves data from a Columbia Weather Systems 
MicroServer. The MicroServer supports a variety of Columbia weather stations.
This driver has been tested against WeeWX 3.9.2 under Python 2.7 
and WeeWX 4 under Python 3.6.

To obtain weather data from the MicroServer, this driver polls the MicroServer 
via HTTP downloading the Enhanced XML version of the current data from 
/tmp/latestsampledata_u.xml at the specified host and port. For more 
information on the format, see the Columbia Weather Systems MicroServer 
User Manual, Appendix B, Enhanced Web Server available at 
http://columbiaweather.com/resources/manuals-and-brochures in PDF format.

There is not currently a predefined way to upload historical data into WeeWX.
However, if the MicroServer daily log files have been manually downloaded, it 
should be possible to configure the wee_import utility to import one file at a 
time.

## Installation

1) install weewx, select 'Simulator' driver
   `http://weewx.com/docs/usersguide.htm#installing`

1) download the driver
   `wget https://github.com/bburton/weewx-columbia-ms/releases/download/v0.1.0/weewx-columbia-ms-0.2.0.tar.gz`

1) install the driver
   `sudo wee_extension --install weewx-columbia-ms-0.2.0.tar.gz`

1) configure the driver
   `sudo wee_config --reconfigure --driver=user.columbia-ms'

1) start weewx
   `sudo /etc/init.d/weewx start`

## Driver options

Use the host and port options to tell the driver where to find the MicroServer:

```
[ColumbiaMicroServer]
    driver = user.columbia-ms
    port = 80
    host = 192.168.0.50
    poll_interval = 10  # how often to query the MicroServer, in seconds
    max_tries = 3
    retry_wait = 5  
```

## TODO

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
configuration class based on the import implementations used with the 
wee_import utility. This requires the following functionality:

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
   on the MicroServer but were previously downloaded by other means. Since the
   MicroServer logs records at a one minute interval, the import process needs 
   to have the ability to resample the data to match the archive interval as 
   configured in weewx.conf.  

## Non-goals

The MicroServer does not have any API's to support the following functions:
* Query of hardware status
* Setting hardware configuration
* Obtain historical data in the same format as the current data.

Since there already exists a full-featured web-based administration console, 
spending much effort to duplicate the console functionality is probably not 
worth the effort as screen-scraping and reverse-engineering would have to be
done.
