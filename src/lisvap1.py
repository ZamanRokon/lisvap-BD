# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division, print_function, unicode_literals)

import datetime
import sys

from lisvap import __date__, __version__
from lisvap.utils import LisSettings, TimeProfiler, FileNamesManager, usage
from lisvap.utils.tools import checkdate, DynamicFrame
from lisvap.lisvapdynamic import LisvapModelDyn
from lisvap.lisvapinitial import LisvapModelIni


class LisvapModel(LisvapModelIni, LisvapModelDyn):
    """ Joining the initial and the dynamic part of the Lisvap model """


def lisvapexe(settings):
    tp = TimeProfiler()
    step_start = settings.binding['StepStart']
    step_end = settings.binding['StepEnd']
    timestep_stride = int(settings.binding['DtSec'])
    start_date = datetime.datetime.strptime(step_start, '%d/%m/%Y %H:%M')
    end_date = datetime.datetime.strptime(step_end, '%d/%m/%Y %H:%M')
    start_date_simulation = datetime.datetime.strptime(settings.binding['CalendarDayStart'], '%d/%m/%Y %H:%M')
    timestep_start = int((start_date - start_date_simulation).total_seconds() / timestep_stride) + 1
    timestep_end = int((end_date - start_date_simulation).total_seconds() / timestep_stride) + 1
    checkdate('StepStart', 'StepEnd')
    print('Start date: {} ({}) - End date: {} ({})'.format(step_start, timestep_start, step_end, timestep_end))

    if settings.flags['loud']:
        print('%-6s %10s %11s\n' % ('Step', 'Date', 'ET0'))

    lisvap_model = LisvapModel()
    dynfmw = DynamicFrame(lisvap_model, firstTimestep=timestep_start, lastTimeStep=timestep_end)
    dynfmw.run()

    if settings.flags['printtime']:
        tp.report()


def main():
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)
    settingsxml = sys.argv[1]  # setting.xml file
    lissettings = LisSettings(settingsxml)
    fileManager = FileNamesManager(lissettings.binding.get('PathOut'))
    if not lissettings.valid():
        sys.exit(1)
    # Run LISVAP without printing banner
    lisvapexe(lissettings)


if __name__ == "__main__":
    sys.exit(main())