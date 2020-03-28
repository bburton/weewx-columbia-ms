Files in weewx-columbia-ws/test

All files matching latestsampledata_u*.xml are actual downloads from
a Columbia Weather MicroServer attached to a Pulsar 600 weather station by
performing an HTTP GET of the URL, http://<host>:<port>/tmp/latestsampledata_u.xml. 
When downloaded, the output is returned in one long line. To make it easier to
view, the files were copied and the XML pretty-printed. Those files have an 
_fmt.xml suffix.

Files Description
--------------------------------------------------------------------------------
latestsampledata_u_us1.xml - US Units, sample #1
latestsampledata_u_us2.xml - US Units, sample #2
latestsampledata_u_metric1.xml - Metric Units, sample #1
latestsampledata_u_metric2.xml - Metric Units, sample #2
latestsampledata_u_metric3_knots.xml - Metric Units, sample #3, Wind speed knots
