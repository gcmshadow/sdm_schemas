#!/usr/bin/env python

# 
# LSST Data Management System
# Copyright 2008, 2009, 2010 LSST Corporation.
# 
# This product includes software developed by the
# LSST Project (http://www.lsst.org/).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the LSST License Statement and 
# the GNU General Public License along with this program.  If not, 
# see <http://www.lsstcorp.org/LegalNotices/>.
#


from lsst.cat.MySQLBase import MySQLBase
from lsst.cat.policyReader import PolicyReader

import getpass
import optparse
import os
import string
import sys

usage = """%prog -f policyFile [-t time]
"""


parser = optparse.OptionParser(usage)
parser.add_option("-d")
parser.add_option("-f")
parser.add_option("-g")
options, arguments = parser.parse_args()

if not options.f:
    sys.stderr.write(os.path.basename(sys.argv[0]) + usage[5:])
    sys.exit(1)



class CleanupExpiredRuns(MySQLBase):

    def __init__(self, dbHost, dbPort, gDb,
                 rootU, rootP, 
                 dFirstNotice, dFinalNotice):
        MySQLBase.__init__(self, dbHost, dbPort)
        if gDb == "":
            raise RuntimeError("Invalid (empty) global db name")
        if dcVer == "":
            raise RuntimeError("Invalid (empty) dcVer")
        self.globalDbName = gDb
        self.rootU = rootU
        self.rootP = rootP
        self.daysFirstNotice = dFirstNotice
        self.daysFinalNotice = dFinalNotice

        # Finds all runs that expired, which were not deleted yet.
        # Selects only these for which final notification was sent
        # to the users at least 24 hours ago.
        # Returns a list of database names for deletion"""
        self.cmdGetExpiredRuns = """
  SELECT dbName 
  FROM   RunInfo 
  WHERE  TIMESTAMPDIFF(HOUR, expDate, %s) > 23 # run definitely expired
    AND  delDate IS NULL                       # and it is not deleted yet
    AND  finalNotifDate IS NOT NULL            # and notification was sent
    AND  TIMESTAMPDIFF(HOUR, finalNotifDate, %s)>23 # ...at least 24 hours ago
""" % (now, now)

        # find all runs that will expire in <daysFirstNotice> or less days, 
        # and send first notification if it was not sent
        self.cmdGetRunsFirstNotice = """
  SELECT runInfoId, runName, dbName, expDate, initiator, dbName, dcVersion
  FROM   RunInfo
  WHERE  DATEDIFF(expDate, %s) <= %i
    AND  firstNotifDate IS NULL
""" % (now, self.daysFirstNotice)

        # find all runs that will expire in 1 day or less, for which
        # we sent first notification at least 6 days ago, and
        # send final notification
        self.cmdGetRunsFinalNotice = """
  SELECT runInfoId, runName, dbName, expDate, initiator, dbName, dcVersion
  FROM   RunInfo
  WHERE  DATEDIFF(expDate, %s) < %i
    AND  firstNotifDate IS NOT NULL
    AND  finalNotifDate IS NULL
""" % (now, self.daysFinalNotice)


    def emailNotices(self, firstN, finalN):
        print "emailNotices(%s, %s)" % (firstN, finalN)

        if not firstN and not finalN:
            return

        if not firstN:
            firstN = "   None"
        if not finalN:
            finalN = "   None"

        contents = """
Hello,

This is an automated notification listing runs
that will be deleted from the mysql database on 
lsst10. Information about each run is in the form
[runName, dcVersion, initiator, dbName]

Final notification (runs to be deleted in %s day(s)):

%s

First notification (runs to be deleted in %s day(s)):

%s

To prevent a run from being deleted, extend 
it by running the following mysql commands:

  USE %s
  SELECT extendRun('<runName>', '<dcVersion>', '<initiator>')

Regards,
The LSST Database Team

""" % (self.daysFinalNotice, finalN, self.daysFirstNotice, firstN, self.gDb)

        subject = "Purging expired runs"

        print """
*************
Email to: lsst-data
Subject: %s
%s
*************
""" % (subject, contents)


    def run(self):
        # Connect to database
        self.connect(self.rootU, self.rootP, self.globalDbName)

        # check available disk space and remember it for reporting
        dataDirSpaceAvailBefore = self.getDataDirSpaceAvail()

        # Find expired runs, delete them and record this
        dbNames = self.execCommandN(self.cmdGetExpiredRuns)
        for dbN in dbNames:
            print "  --> Deleting ", dbN[0], " <--"
            self.execCommand0("DROP DATABASE IF EXISTS %s" % dbN[0])
            self.execCommand0(
             "UPDATE RunInfo SET delDate=%s WHERE dbName='%s'" % (now, dbN[0]))

        # re-check disk space
        dataDirSpaceAvailAfter = self.getDataDirSpaceAvail()

        # Prepare final notices
        rows = self.execCommandN(self.cmdGetRunsFinalNotice)
        runIds = ""

        finalN = ""
        if len(rows) > 0:
            finalN = ""
            for row in rows:
                runInfoId = int(row[0])
                runIds += "%i," % runInfoId
                finalN += " - %s, %s, %s, %s\n" % \
                    (row[1], row[6], row[4], row[5])
                    # runName, dcVer, initiator, dbName

            #Remember the final notices where sent
            cmd = """
  UPDATE RunInfo
  SET    finalNotifDate=%s
  WHERE  runInfoId IN (%s)
""" % (now, runIds[:-1])
            self.execCommand0(cmd)

        # Prepare first notices
        rows = self.execCommandN(self.cmdGetRunsFirstNotice)
        firstN = ""
        if len(rows) > 0:
            firstN = ""
            for row in rows:
                runInfoId = int(row[0])
                runIds += "%i," % runInfoId
                firstN += " - %s, %s, %s, %s\n" % \
                    (row[1], row[6], row[4], row[5])
                    # runName, dcVer, initiator, dbName

            #Remember the first notices where sent
            cmd = """
  UPDATE RunInfo
  SET    firstNotifDate=%s
  WHERE  runInfoId IN (%s)
""" % (now, runIds[:-1])
            self.execCommand0(cmd)

            # Send the email with the notices
            self.emailNotices(firstN, finalN)

            # Disconnect from database
            self.disconnect()
            return


##########################################################

if options.d: # format: YYYY:MM:DD
    now = "'%s 00:00:01'" % options.d
else:
    now = "NOW()"

r = PolicyReader(options.f)
(host, port) = r.readAuthInfo()
(gDb, dcVer, dcDb, dummy1, dummy2) = r.readGlobalSetup()
(dFirstNotice, dFinalNotice) = r.readRunCleanup()

print """\n\n
  ******************************************************************
  *** Executing cleanupExpiredRun, now=%s, globalDB=%s
""" % (now, gDb)

# TODO: fetch mysql root user/password from file
rootU = raw_input("Enter mysql superuser account name: ")
rootP = getpass.getpass()

xx = CleanupExpiredRuns(host, port, gDb, rootU, rootP, 
                        dFirstNotice, dFinalNotice)
xx.run()
