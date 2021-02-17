# -*- coding: utf-8 -*-

"""
This file contains the Qudi Hardware module NICard class for use with a CMOS camera ODMR measurements.

Qudi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Qudi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Qudi. If not, see <http://www.gnu.org/licenses/>.

Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""

import numpy as np
import re

import PyDAQmx as daq

from core.module import Base
from core.configoption import ConfigOption
from interface.slow_counter_interface import SlowCounterInterface
from interface.slow_counter_interface import SlowCounterConstraints
from interface.slow_counter_interface import CountingMode
from interface.odmr_counter_interface import ODMRCounterInterface
from interface.confocal_scanner_interface import ConfocalScannerInterface


class NationalInstrumentsXSeries(Base, ODMRCounterInterface):
    """ A National Instruments device that can count and control microvave generators.

    !!!!!! NI USB 63XX, NI PCIe 63XX and NI PXIe 63XX DEVICES ONLY !!!!!!

    See [National Instruments X Series Documentation](@ref nidaq-x-series) for details.

    stable: Kay Jahnke, Alexander Stark

    Example config for copy-paste:

    nicard_6323:
        module.Class: 'national_instruments_x_series_prime95b_2.NationalInstrumentsXSeries'
        clock_frequency: 5
        clock_channel: '/Dev1/Ctr1'
        smiq_channel: '/Dev1/Ctr3'
        switch_channel: '/Dev1/Ctr2'
        cam_channel: '/Dev1/Ctr0'
        scanner_clock_channel:
            '/Dev1/Ctr1'

    """

    # config options
    _clock_channel = ConfigOption('clock_channel', missing='error')
    _cam_channel = ConfigOption('cam_channel', missing='error')
    _smiq_channel = ConfigOption('smiq_channel', missing='error')
    _switch_channel = ConfigOption('switch_channel', missing='error')
    _default_clock_frequency = ConfigOption(
        'default_clock_frequency', 5, missing='info')

    # confocal scanner
    _default_scanner_clock_frequency = ConfigOption(
        'default_scanner_clock_frequency', 5, missing='info')
    _scanner_clock_channel = ConfigOption(
        'scanner_clock_channel', missing='warn')

    _RWTimeout = ConfigOption('read_write_timeout', default=10)
    _counting_edge_rising = ConfigOption('counting_edge_rising', default=True)

    def on_activate(self):
        """ Starts up the NI Card at activation.
        """
        # the tasks used on that hardware device:
        self._counter_daq_tasks = list()
        self._counter_analog_daq_task = None
        self._clock_daq_task = None
        self._scanner_clock_daq_task = None
        self._scanner_ao_task = None
        self._scanner_counter_daq_tasks = list()
        self._line_length = None
        self._odmr_length = None
        self._gated_counter_daq_task = None
        self._scanner_analog_daq_task = None
        self._odmr_pulser_daq_task = None
        self._oversampling = 0
        self._lock_in_active = False
        self._scanner_counter_channels = ['Prime95B']

    def reset_hardware(self):
        """ Resets the NI hardware, so the connection is lost and other
            programs can access it.

        @return int: error code (0:OK, -1:error)
        """
        retval = 0
        chanlist = [
            self._odmr_trigger_channel,
            self._clock_channel,
            self._scanner_clock_channel,
            self._gate_in_channel
        ]
        chanlist.extend(self._scanner_ao_channels)
        chanlist.extend(self._photon_sources)
        chanlist.extend(self._counter_channels)
        chanlist.extend(self._scanner_counter_channels)

        devicelist = []
        for channel in chanlist:
            if channel is None:
                continue
            match = re.match(
                r'^/(?P<dev>[0-9A-Za-z\- ]+[0-9A-Za-z\-_ ]*)/(?P<chan>[0-9A-Za-z]+)',
                channel)
            if match:
                devicelist.append(match.group('dev'))
            else:
                self.log.error(
                    'Did not find device name in {0}.'.format(channel))
        for device in set(devicelist):
            self.log.info('Reset device {0}.'.format(device))
            try:
                daq.DAQmxResetDevice(device)
            except BaseException:
                self.log.exception(
                    'Could not reset NI device {0}'.format(device))
                retval = -1
        return retval

    def on_deactivate(self, scanner=True):
        """ Shut down the NI card.
        """
        try:
            my_tasks = [
                self._scanner_clock_daq_task,
                self._smiq_clock_daq_task,
                self._switch_clock_daq_task,
                self._cam_clock_daq_task]
            for my_task in my_tasks:
                # Stop the clock task:
                daq.DAQmxStopTask(my_task)

                # After stopping delete all the configuration of the clock:
                daq.DAQmxClearTask(my_task)

            # Set the task handle to None as a safety
            if scanner:
                self._scanner_clock_daq_task = None
            else:
                self._clock_daq_task = None
        except BaseException:
            return -1

        self.reset_hardware()
        return 0

    def get_odmr_channels(self):
        ch = list()
        if self._scanner_counter_channels:
            ch.append(self._scanner_counter_channels[0])
        return ch

    @property
    def oversampling(self):
        return self._oversampling

    @oversampling.setter
    def oversampling(self, val):
        if not isinstance(val, (int, float)):
            self.log.error('oversampling has to be int of float.')
        else:
            self._oversampling = int(val)

    @property
    def lock_in_active(self):
        return self._lock_in_active

    @lock_in_active.setter
    def lock_in_active(self, val):
        if not isinstance(val, bool):
            self.log.error('lock_in_active has to be boolean.')
        else:
            self._lock_in_active = val
            if self._lock_in_active:
                self.log.warn(
                    'You just switched the ODMR counter to Lock-In-mode. \n'
                    'Please make sure you connected all triggers correctly:\n'
                    '  {0:s} is the microwave trigger channel\n'
                    '  {1:s} is the switching channel for the lock in\n'
                    ''.format(
                        self._odmr_trigger_line,
                        self._odmr_switch_line))

    def set_up_odmr(self, counter_channel=None, photon_source=None,
                    clock_channel=None, odmr_trigger_channel=None):
        """ Configures the actual counter with a given clock.

        @param string counter_channel: if defined, this is the physical channel
                                       of the counter
        @param string photon_source: if defined, this is the physical channel
                                     where the photons are to count from
        @param string clock_channel: if defined, this specifies the clock for
                                     the counter
        @param string odmr_trigger_channel: if defined, this specifies the
                                            trigger output for the microwave

        @return int: error code (0:OK, -1:error)
        """
        if self._scanner_clock_daq_task is None and clock_channel is None:
            self.log.error(
                'No clock running, call set_up_clock before starting the counter.')
            return -1
        if self._scanner_counter_daq_tasks:
            self.log.error(
                'Another counter is already running, close this one first.')
            return -1
        if self._scanner_ai_channels and self._scanner_analog_daq_task is not None:
            self.log.error(
                'Another analog is already running, close this one first.')
            return -1

        my_clock_channel = clock_channel if clock_channel else self._scanner_clock_channel

        if self._scanner_counter_channels and self._photon_sources:
            my_counter_channel = counter_channel if counter_channel else self._scanner_counter_channels[
                0]
            my_photon_source = photon_source if photon_source else self._photon_sources[0]

            # this task will count photons with binning defined by the clock_channel
            # task = daq.TaskHandle()
            try:
                # create task for the counter
                daq.DAQmxCreateTask('ODMRCounter', daq.byref(task))

                # set up semi period width measurement in photon ticks, i.e. the width
                # of each pulse (high and low) generated by pulse_out_task is measured
                # in photon ticks.
                #   (this task creates a channel to measure the time between state
                #    transitions of a digital signal and adds the channel to the task
                #    you choose)
                daq.DAQmxCreateCISemiPeriodChan(
                    # define to which task to# connect this function
                    task,
                    # use this counter channel
                    my_counter_channel,
                    # name to assign to it
                    'ODMR Counter',
                    # Expected minimum count value
                    0,
                    # Expected maximum count value
                    self._max_counts / self._scanner_clock_frequency,
                    # units of width measurement, here photon ticks
                    daq.DAQmx_Val_Ticks,
                    '')

                # connect the pulses from the clock to the counter
                daq.DAQmxSetCISemiPeriodTerm(
                    task,
                    my_counter_channel,
                    my_clock_channel + 'InternalOutput')

                # define the source of ticks for the counter as
                # self._photon_source
                daq.DAQmxSetCICtrTimebaseSrc(
                    task,
                    my_counter_channel,
                    my_photon_source)

                self._scanner_counter_daq_tasks.append(task)

            except BaseException:
                self.log.exception(
                    'Error while setting up the digital counter of ODMR scan.')
                return -1

        try:
            # Analog task
            if self._scanner_ai_channels:
                atask = daq.TaskHandle()
                daq.DAQmxCreateTask('ODMRAnalog', daq.byref(atask))

                daq.DAQmxCreateAIVoltageChan(
                    atask,
                    ', '.join(self._scanner_ai_channels),
                    'ODMR Analog',
                    daq.DAQmx_Val_RSE,
                    -10,
                    10,
                    daq.DAQmx_Val_Volts,
                    ''
                )
                self._scanner_analog_daq_task = atask

            # start and stop pulse task to correctly initiate idle state high
            # voltage.
            daq.DAQmxStartTask(self._scanner_clock_daq_task)
            # otherwise, it will be low until task starts, and MW will receive
            # wrong pulses.
            daq.DAQmxStopTask(self._scanner_clock_daq_task)

            if self.lock_in_active:
                ptask = daq.TaskHandle()
                daq.DAQmxCreateTask('ODMRPulser', daq.byref(ptask))
                daq.DAQmxCreateDOChan(
                    ptask,
                    '{0:s}, {1:s}'.format(
                        self._odmr_trigger_line,
                        self._odmr_switch_line),
                    "ODMRPulserChannel",
                    daq.DAQmx_Val_ChanForAllLines)

                self._odmr_pulser_daq_task = ptask

            # connect the clock to the trigger channel to give triggers for the
            # microwave
            # daq.DAQmxConnectTerms(
            #     self._scanner_clock_channel + 'InternalOutput',
            #     self._odmr_trigger_channel,

            #     daq.DAQmx_Val_DoNotInvertPolarity)
            # ##Connect terms to use as a trigger
            # daq.DAQmxConnectTerms(
            #     self._scanner_clock_channel + 'InternalOutput',
            #     self._odmr_camera_channel,
            #     daq.DAQmx_Val_DoNotInvertPolarity)
            # daq.DAQmxConnectTerms(
            #     self._scanner_clock_channel + 'InternalOutput',
            #     '/Dev1/PFI11',
            #     daq.DAQmx_Val_DoNotInvertPolarity)
        except BaseException:
            self.log.exception('Error while setting up ODMR scan.')
            return -1
        return 0

    def set_up_clock(
            self,
            clock_frequency=None,
            clock_channel=None,
            scanner=False,
            idle=False,
            delay=2.0):
        """ Configures the hardware clock of the NiDAQ card to give the timing.

        @param float clock_frequency: if defined, this sets the frequency of
                                      the clock in Hz
        @param string clock_channel: if defined, this is the physical channel
                                     of the clock within the NI card.
        @param bool scanner: if set to True method will set up a clock function
                             for the scanner, otherwise a clock function for a
                             counter will be set.
        @param bool idle: set whether idle situation of the counter (where
                          counter is doing nothing) is defined as
                                True  = 'Voltage High/Rising Edge'
                                False = 'Voltage Low/Falling Edge'

        @return int: error code (0:OK, -1:error)
        """

        if not scanner and self._clock_daq_task is not None:
            self.log.error(
                'Another counter clock is already running, close this one first.')
            return -1

        if scanner and self._scanner_clock_daq_task is not None:
            self.log.error(
                'Another scanner clock is already running, close this one first.')
            return -1

        # Create handle for task, this task will generate pulse signal for
        # photon counting
        my_clock_daq_task = daq.TaskHandle()
        smiq = daq.TaskHandle()
        switch = daq.TaskHandle()
        cam = daq.TaskHandle()

        # assign the clock frequency, if given
        if clock_frequency is not None:
            if not scanner:
                self._clock_frequency = float(clock_frequency)
            else:
                self._scanner_clock_frequency = float(clock_frequency)
                self._smiq_clock_frequency = float(clock_frequency) / 2.
                self._switch_clock_frequency = float(clock_frequency) / 2.
                self._cam_clock_frequency = float(clock_frequency)
        else:
            if not scanner:
                self._clock_frequency = self._default_clock_frequency
            else:
                self._scanner_clock_frequency = self._default_scanner_clock_frequency

        # use the correct clock in this method
        if scanner:
            my_clock_frequency = self._scanner_clock_frequency * 2
        else:
            my_clock_frequency = self._clock_frequency * 2

        # assign the clock channel, if given
        if clock_channel is not None:
            if not scanner:
                self._clock_channel = clock_channel
            else:
                self._scanner_clock_channel = clock_channel

        # use the correct clock channel in this method
        if scanner:
            my_clock_channel = self._scanner_clock_channel
            self._smiq_channel = self._smiq_channel
            self._switch_channel = self._switch_channel
            self._cam_channel = self._cam_channel
        else:
            my_clock_channel = self._clock_channel

        # check whether only one clock pair is available, since some NI cards
        # only one clock channel pair.
        if self._scanner_clock_channel == self._clock_channel:
            if not ((self._clock_daq_task is None) and (
                    self._scanner_clock_daq_task is None)):
                self.log.error(
                    'Only one clock channel is available!\n'
                    'Another clock is already running, close this one first '
                    'in order to use it for your purpose!')
                return -1

        # Adjust the idle state if necessary
        my_idle = daq.DAQmx_Val_High if idle else daq.DAQmx_Val_Low
        try:
            # create task for clock
            task_name = 'ScannerClock' if scanner else 'CounterClock'
            daq.DAQmxCreateTask(task_name, daq.byref(my_clock_daq_task))

            # create a digital clock channel with specific clock frequency:
            daq.DAQmxCreateCOPulseChanFreq(
                # The task to which to add the channels
                my_clock_daq_task,
                # which channel is used?
                my_clock_channel,
                # Name to assign to task (NIDAQ uses by # default the physical channel name as
                # the virtual channel name. If name is specified, then you must use the name
                # when you refer to that channel in other NIDAQ functions)
                'Clock Producer',
                # units, Hertz in our case
                daq.DAQmx_Val_Hz,
                # idle state
                my_idle,
                # initial delay
                delay,
                my_clock_frequency / 2,
                0.5)

            daq.DAQmxCfgImplicitTiming(
                # Define task
                my_clock_daq_task,
                daq.DAQmx_Val_ContSamps,
                # buffer length which stores temporarily the number of
                # generated samples
                1000)
            ##############################
            # Configure SMIQ trigger clock
            ##############################
            duty_cycle = 0.1
            d = 0
            daq.DAQmxCreateTask('mySmiqTask', daq.byref(smiq))
            # Create channel to generate digital pulses that freq and dutyCycle
            # define and adds the channel to the task
            daq.DAQmxCreateCOPulseChanFreq(
                smiq,
                self._smiq_channel,  # The name of the counter to use to create virtual channels
                "mySmiqChannel",  # The name to assign to the created virtual channel
                daq.DAQmx_Val_Hz,  # The units in which to specify freq.
                daq.DAQmx_Val_Low,  # The resting state of the output terminal.
                d,
                # The amount of time in seconds to wait before generating the
                # first pulse.
                self._smiq_clock_frequency,
                # The frequency at which to generate pulses.
                duty_cycle,
                # The width of the pulse divided by the pulse period.
            )

            j = 1000
            # # Sets only the number of samples to acquire or generate without specifying timing.
            daq.DAQmxCfgImplicitTiming(
                smiq,
                # daq.DAQmx_Val_ContSamps,
                daq.DAQmx_Val_ContSamps,
                # Acquire or generate samples until you stop the task.
                j  # the buffer size
            )
            daq.DAQmxCfgDigEdgeStartTrig(
                smiq,
                my_clock_channel + 'InternalOutput',
                daq.DAQmx_Val_Rising
            )
            ##############################
            # Configure switch trigger clock
            ##############################
            duty_cycle = 0.5
            d = 0
            daq.DAQmxCreateTask('mySwitchTask', daq.byref(switch))
            # Create channel to generate digital pulses that freq and dutyCycle
            # define and adds the channel to the task
            daq.DAQmxCreateCOPulseChanFreq(
                switch,
                self._switch_channel,  # The name of the counter to use to create virtual channels
                "mySwitchChannel",  # The name to assign to the created virtual channel
                daq.DAQmx_Val_Hz,  # The units in which to specify freq.
                daq.DAQmx_Val_High,
                # The resting state of the output terminal.
                d,
                # The amount of time in seconds to wait before generating the
                # first pulse.
                self._switch_clock_frequency,
                # The frequency at which to generate pulses.
                duty_cycle,
                # The width of the pulse divided by the pulse period.
            )

            j = 1000
            # # Sets only the number of samples to acquire or generate without specifying timing.
            daq.DAQmxCfgImplicitTiming(
                switch,
                # daq.DAQmx_Val_ContSamps,
                daq.DAQmx_Val_ContSamps,
                # Acquire or generate samples until you stop the task.
                j  # the buffer size
            )
            daq.DAQmxCfgDigEdgeStartTrig(
                switch,
                my_clock_channel + 'InternalOutput',
                daq.DAQmx_Val_Rising
            )
            ##############################
            # Configure cam trigger clock
            ##############################
            duty_cycle = 0.1
            d = (1. / self._cam_clock_frequency) / 4.
            daq.DAQmxCreateTask('myCamTask', daq.byref(cam))
            # Create channel to generate digital pulses that freq and dutyCycle
            # define and adds the channel to the task
            daq.DAQmxCreateCOPulseChanFreq(
                cam,
                self._cam_channel,  # The name of the counter to use to create virtual channels
                "myCamChannel",  # The name to assign to the created virtual channel
                daq.DAQmx_Val_Hz,  # The units in which to specify freq.
                daq.DAQmx_Val_Low,  # The resting state of the output terminal.
                d,
                # The amount of time in seconds to wait before generating the
                # first pulse.
                self._cam_clock_frequency,
                # The frequency at which to generate pulses.
                duty_cycle,
                # The width of the pulse divided by the pulse period.
            )

            j = 1000
            # # Sets only the number of samples to acquire or generate without specifying timing.
            daq.DAQmxCfgImplicitTiming(
                cam,
                # daq.DAQmx_Val_ContSamps,
                daq.DAQmx_Val_ContSamps,
                # Acquire or generate samples until you stop the task.
                j  # the buffer size
            )
            daq.DAQmxCfgDigEdgeStartTrig(
                cam,
                my_clock_channel + 'InternalOutput',
                daq.DAQmx_Val_Rising
            )

            if scanner:
                self._scanner_clock_daq_task = my_clock_daq_task
                # Added the daq tasks to class variables
                self._smiq_clock_daq_task = smiq
                self._switch_clock_daq_task = switch
                self._cam_clock_daq_task = cam
            else:
                # actually start the preconfigured clock task
                daq.DAQmxStartTask(my_clock_daq_task)
                self._clock_daq_task = my_clock_daq_task
        except BaseException:
            self.log.exception('Error while setting up clock.')
            return -1
        return 0

    def set_up_odmr_clock(self, clock_frequency=None, clock_channel=None):
        """ Configures the hardware clock of the NiDAQ card to give the timing.

        @param float clock_frequency: if defined, this sets the frequency of
                                      the clock
        @param string clock_channel: if defined, this is the physical channel
                                     of the clock

        @return int: error code (0:OK, -1:error)
        """

        return self.set_up_clock(
            clock_frequency=clock_frequency,
            clock_channel=clock_channel,
            scanner=True,
            idle=False)

    def set_odmr_length(self, length=100):
        """ Sets up the trigger sequence for the ODMR and the triggered microwave.

        @param int length: length of microwave sweep in pixel

        @return int: error code (0:OK, -1:error)
        """
        self._odmr_length = length
        try:
            daq.DAQmxCfgImplicitTiming(
                # define task
                self._scanner_clock_daq_task,
                daq.DAQmx_Val_FiniteSamps,
                self._odmr_length)
                # + 1)

        except BaseException:
            self.log.exception('Error while setting up ODMR counter.')
            return -1
        return 0

    def count_odmr(self, length=100):
        """ Sweeps the microwave and returns the counts on that sweep.

        @param int length: length of microwave sweep in pixel

        @return float[]: the photon counts per second
        """
        # check if length setup is correct, if not, adjust.
        if self._odmr_pulser_daq_task:
            odmr_length_to_set = length * self.oversampling * 2
        else:
            odmr_length_to_set = length * 2

        if self.set_odmr_length(odmr_length_to_set) < 0:
            self.log.error(
                'An error arose while setting the odmr lenth to {}.'.format(odmr_length_to_set))
            return True, np.array([-1.])

        try:
            daq.DAQmxStartTask(self._scanner_clock_daq_task)
            daq.DAQmxStartTask(self._smiq_clock_daq_task)
            daq.DAQmxStartTask(self._switch_clock_daq_task)
            daq.DAQmxStartTask(self._cam_clock_daq_task)

            # return False, all_data
            return False, np.full((len(self.get_odmr_channels()), 1), [-1.])
        except BaseException:
            self.log.exception('Error while counting for ODMR.')
            return True, np.full((len(self.get_odmr_channels()), 1), [-1.])

    def stop_tasks(self):
        """Extra stop task to accomodate camera"""
        # stop the counter task
        try:
            daq.DAQmxWaitUntilTaskDone(
                # define task
                self._scanner_clock_daq_task,
                # maximal timeout for the counter times the positions
                self._RWTimeout * 2 * self._odmr_length)
            daq.DAQmxStopTask(self._scanner_clock_daq_task)
            daq.DAQmxStopTask(self._smiq_clock_daq_task)
            daq.DAQmxStopTask(self._switch_clock_daq_task)
            daq.DAQmxStopTask(self._cam_clock_daq_task)
        except BaseException:
            self.log.exception('Error while stopping tasks.')

    def close_odmr(self):
        """ Closes the odmr and cleans up afterwards.
        Also wait until trigger sequence is done (maybe) so as to allow camera to complete
        acquisition.

        @return int: error code (0:OK, -1:error)
        """
        retval = 0
        try:
            # disconnect the trigger channel
            # Added this here so camera won't stall waiting for an incomplete
            # trigger sequence
            daq.DAQmxWaitUntilTaskDone(
                # define task
                self._scanner_clock_daq_task,
                # maximal timeout for the counter times the positions
                self._RWTimeout * 2 * self._odmr_length)

        except BaseException:
            self.log.exception('Error while disconnecting ODMR clock channel.')
            retval = -1

        return retval

    def close_clock(self, scanner=False):
        """ Closes the clock and cleans up afterwards.

        @param bool scanner: specifies if the counter- or scanner- function
                             should be used to close the device.
                                True = scanner
                                False = counter

        @return int: error code (0:OK, -1:error)
        """
        if scanner:
            my_tasks = [
                self._scanner_clock_daq_task,
                self._smiq_clock_daq_task,
                self._switch_clock_daq_task,
                self._cam_clock_daq_task]
        else:
            my_task = self._clock_daq_task
        try:
            for my_task in my_tasks:
                # Stop the clock task:
                daq.DAQmxStopTask(my_task)

                # After stopping delete all the configuration of the clock:
                daq.DAQmxClearTask(my_task)

            # Set the task handle to None as a safety
            if scanner:
                self._scanner_clock_daq_task = None
            else:
                self._clock_daq_task = None
        except BaseException:
            self.log.exception('Could not close clock.')
            return -1
        return 0

    def close_odmr_clock(self):
        """ Closes the odmr and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        return self.close_clock(scanner=True)
