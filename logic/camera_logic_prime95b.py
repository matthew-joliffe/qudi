# -*- coding: utf-8 -*-

"""
A module for controlling a camera.

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

from core.connector import Connector
from core.configoption import ConfigOption
from core.util.mutex import Mutex
from logic.generic_logic import GenericLogic
from qtpy import QtCore
import matplotlib.pyplot as plt
import matplotlib as mpl

import datetime
from collections import OrderedDict


class CameraLogic(GenericLogic):
    """
    Control a camera.
    """

    # declare connectors
    hardware = Connector(interface='CameraInterface')
    savelogic = Connector(interface='SaveLogic')
    _max_fps = ConfigOption('default_exposure', 20)
    _fps = _max_fps

    # signals
    sigUpdateDisplay = QtCore.Signal()
    sigAcquisitionFinished = QtCore.Signal()
    sigVideoFinished = QtCore.Signal()
    sigROISet = QtCore.Signal(dict)
    timer = None

    enabled = False

    _exposure = 1.
    _gain = 1.
    _last_image = None

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

        self.threadlock = Mutex()

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self._hardware = self.hardware()
        self._save_logic = self.savelogic()

        self.enabled = False

        self.get_exposure()
        self.get_gain()

        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.loop)

    def on_deactivate(self):
        """ Perform required deactivation. """
        self._hardware.on_deactivate()

    def get_sensor(self):
        '''Returns the sensor size which is independent of the ROI.
        @return tuple: (sensor width, sensor height) ~ (1200, 1200)
        '''
        return self._hardware._get_detector()

    def get_size(self):
        '''Returns the image size which is dependant on the size of the ROI. Default ROI is the sensor size.
        @return tuple: (ROI width, ROI height)
        '''
        return self._hardware.get_size()

    def set_image_roi(self, data):
        '''Sets the ROI in the image. This selection of ROI is done in the GUI. A single rectangular ROI
        is currently implemented. The Prime95B does allow for multiple rectangulare ROIs which is a possible
        future addition. The cam.roi instance takes (x_start, x_end, y_start, y_end) with all in ints.
        The GUI has a snap the ROI to pixels feature which also makes sure only int values are passed into the dict.

        @param dict: {'pos': the coord. of the bottom left corner of the ROI,
                    'size': the size of the ROI as tuple, i.e, size + pos gives coord. of top-right corner of ROI}
        '''
        pos = data['pos']
        size = data['size']
        x1, y1 = (*pos,)
        x2, y2 = (*size,)
        self._hardware.cam.roi = tuple(int(el)
                                       for el in (x1, x2 + x1, y1, y2 + y1))

    def set_exposure(self, time):
        """ Set exposure of hardware """
        if self.enabled:
            self.enabled = False
        self._hardware.set_exposure(time)
        self.get_exposure()

    def get_exposure(self):
        """ Get exposure of hardware """
        self._exposure = self._hardware.get_exposure()
        self._fps = min(1 / self._exposure, self._max_fps)
        return self._exposure

    def set_gain(self, gain):
        '''Sets the gain of camera. Changes the camera class variable basically. Max values is 1 for 16bit and
        1,2,3 for 12bit. Default is 16bit.
        @param int: gain
        '''
        self._hardware.set_gain(gain)

    def get_gain(self):
        '''Returns the gain values from the camera class instance.
        @return int: gain
        '''
        gain = self._hardware.get_gain()
        self._gain = gain
        return gain

    def start_single_acquistion(self):
        """Does a single image acquisitiong ans updates the _last_image variable as well as the display.
        """
        self._hardware.start_single_acquisition()
        self._last_image = self._hardware.get_acquired_data()
        self.sigUpdateDisplay.emit()
        self.sigAcquisitionFinished.emit()

    def start_loop(self):
        """ Start the data recording loop.
        The loop delay was flawed in the original logic code wherein the delay was dependant on the exp_time.
        Here a minmum delay of 100ms is set so as to allow the GUI enough time to update the display. A very
        short delay or none at all will cause the GUI tp freeze.
        """
        self.enabled = True
        self.timer.start(100)  # 0*1/self._fps)

        if self._hardware.support_live_acquisition():
            self._hardware.start_live_acquisition()
        else:
            self._hardware.start_single_acquisition()

    def stop_loop(self):
        """ Stop the data recording loop.
        """
        self.timer.stop()
        self.enabled = False
        self._hardware.stop_acquisition()
        self.sigVideoFinished.emit()

    def loop(self):
        """ Execute step in the data recording loop: save one of each control and process values
        """
        self._last_image = self._hardware.get_acquired_data()
        self.sigUpdateDisplay.emit()
        if self.enabled:
            self.timer.start(100)  # 0 * 1 / self._fps)
            if not self._hardware.support_live_acquisition():
                # the hardware has to check it's not busy
                self._hardware.start_single_acquisition()

    def get_last_image(self):
        """ Return last acquired image """
        return self._last_image

    def set_trigger_seq(self, mode):
        """Used to set camera to edge trigger for all frames in a sequence.
        For applying the exposure mode.

        @param str: mode
        """
        self.enabled = False
        self._hardware.stop_acquisition()
        self._hardware.set_exposure_mode(mode)

    def start_trigger_seq(self, num_frames):
        """Start the sequnce of frame collection. Used currently to collect frames after setting the edge trigger
        exp. mode.
        """
        self._last_image = self._hardware.get_sequence(num_frames)

    def save_xy_data(self, colorscale_range=None, percentile_range=None):
        """ Save the current confocal xy data to file.

        Two files are created.  The first is the imagedata, which has a text-matrix of count values
        corresponding to the pixel matrix of the image.  Only count-values are saved here.

        The second file saves the full raw data with x, y, z, and counts at every pixel.

        A figure is also saved.

        @param: list colorscale_range (optional) The range [min, max] of the display colour scale (for the figure)

        @param: list percentile_range (optional) The percentile range [min, max] of the color scale
        """
        filepath = self._save_logic.get_path_for_module('Camera')
        timestamp = datetime.datetime.now()
        # Prepare the metadata parameters (common to both saved files):
        parameters = OrderedDict()

        parameters['Gain'] = self._gain
        parameters['Exposure time (s)'] = self._exposure
        # Prepare a figure to be saved

        axes = ['X', 'Y']
        xy_pixels = self._hardware.get_size()
        image_extent = [0,
                        xy_pixels[0],
                        0,
                        xy_pixels[1]]

        fig = self.draw_figure(data=self._last_image,
                               image_extent=image_extent,
                               scan_axis=axes,
                               cbar_range=colorscale_range,
                               percentile_range=percentile_range)

        # data for the text-array "image":
        image_data = OrderedDict()
        image_data['XY image data.'] = self._last_image
        filelabel = 'xy_image'
        self._save_logic.save_data(image_data,
                                   filepath=filepath,
                                   timestamp=timestamp,
                                   parameters=parameters,
                                   filelabel=filelabel,
                                   fmt='%.6e',
                                   delimiter='\t',
                                   plotfig=fig)

        # prepare the full raw data in an OrderedDict:
        # data = OrderedDict()
        # data['x position (m)'] = self.xy_image[:, :, 0].flatten()
        # data['y position (m)'] = self.xy_image[:, :, 1].flatten()
        # data['z position (m)'] = self.xy_image[:, :, 2].flatten()
        #
        #
        # # Save the raw data to file
        # filelabel = 'xy_image_data'
        # self._save_logic.save_data(data,
        #                            filepath=filepath,
        #                            timestamp=timestamp,
        #                            parameters=parameters,
        #                            filelabel=filelabel,
        #                            fmt='%.6e',cc
        #                            delimiter='\t')

        self.log.debug('Image saved.')
        return

    def draw_figure(
            self,
            data,
            image_extent,
            scan_axis=None,
            cbar_range=None,
            percentile_range=None,
            crosshair_pos=None):
        """ Create a 2-D color map figure of the scan image.

        @param: array data: The NxM array of count values from a scan with NxM pixels.

        @param: list image_extent: The scan range in the form [hor_min, hor_max, ver_min, ver_max]

        @param: list axes: Names of the horizontal and vertical axes in the image

        @param: list cbar_range: (optional) [color_scale_min, color_scale_max].  If not supplied then a default of
                                 data_min to data_max will be used.

        @param: list percentile_range: (optional) Percentile range of the chosen cbar_range.

        @param: list crosshair_pos: (optional) crosshair position as [hor, vert] in the chosen image axes.

        @return: fig fig: a matplotlib figure object to be saved to file.
        """
        if scan_axis is None:
            scan_axis = ['X', 'Y']

        # If no colorbar range was given, take full range of data
        if cbar_range is None:
            cbar_range = [np.min(data), np.max(data)]

        # Scale color values using SI prefix
        prefix = ['', 'k', 'M', 'G']
        prefix_count = 0
        image_data = data
        draw_cb_range = np.array(cbar_range)
        image_dimension = image_extent.copy()

        while draw_cb_range[1] > 1000:
            image_data = image_data / 1000
            draw_cb_range = draw_cb_range / 1000
            prefix_count = prefix_count + 1

        c_prefix = prefix[prefix_count]

        # Scale axes values using SI prefix
        axes_prefix = ['', 'm', r'$\mathrm{\mu}$', 'n']
        x_prefix_count = 0
        y_prefix_count = 0

        while np.abs(image_dimension[1] - image_dimension[0]) < 1:
            image_dimension[0] = image_dimension[0] * 1000.
            image_dimension[1] = image_dimension[1] * 1000.
            x_prefix_count = x_prefix_count + 1

        while np.abs(image_dimension[3] - image_dimension[2]) < 1:
            image_dimension[2] = image_dimension[2] * 1000.
            image_dimension[3] = image_dimension[3] * 1000.
            y_prefix_count = y_prefix_count + 1

        x_prefix = axes_prefix[x_prefix_count]
        y_prefix = axes_prefix[y_prefix_count]

        # Use qudi style
        plt.style.use(self._save_logic.mpl_qd_style)

        # Create figure
        fig, ax = plt.subplots()

        # Create image plot
        cfimage = ax.imshow(image_data,
                            # reference the right place in qd
                            cmap=plt.get_cmap('inferno'),
                            origin="lower",
                            vmin=draw_cb_range[0],
                            vmax=draw_cb_range[1],
                            interpolation='none',
                            extent=image_dimension
                            )

        ax.set_aspect(1)
        ax.set_xlabel(scan_axis[0] + ' position (' + x_prefix + 'm)')
        ax.set_ylabel(scan_axis[1] + ' position (' + y_prefix + 'm)')
        ax.spines['bottom'].set_position(('outward', 10))
        ax.spines['left'].set_position(('outward', 10))
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.get_xaxis().tick_bottom()
        ax.get_yaxis().tick_left()

        # draw the crosshair position if defined
        if crosshair_pos is not None:
            trans_xmark = mpl.transforms.blended_transform_factory(
                ax.transData,
                ax.transAxes)

            trans_ymark = mpl.transforms.blended_transform_factory(
                ax.transAxes,
                ax.transData)

            ax.annotate('',
                        xy=(crosshair_pos[0] * np.power(1000,
                                                        x_prefix_count),
                            0),
                        xytext=(crosshair_pos[0] * np.power(1000,
                                                            x_prefix_count),
                                -0.01),
                        xycoords=trans_xmark,
                        arrowprops=dict(facecolor='#17becf',
                                        shrink=0.05),
                        )

            ax.annotate('',
                        xy=(0,
                            crosshair_pos[1] * np.power(1000,
                                                        y_prefix_count)),
                        xytext=(-0.01,
                                crosshair_pos[1] * np.power(1000,
                                                            y_prefix_count)),
                        xycoords=trans_ymark,
                        arrowprops=dict(facecolor='#17becf',
                                        shrink=0.05),
                        )

        # Draw the colorbar
        # , fraction=0.046, pad=0.08, shrink=0.75)
        cbar = plt.colorbar(cfimage, shrink=0.8)
        cbar.set_label('Fluorescence (' + c_prefix + 'c/s)')

        # remove ticks from colorbar for cleaner image
        cbar.ax.tick_params(which=u'both', length=0)

        # If we have percentile information, draw that to the figure
        if percentile_range is not None:
            cbar.ax.annotate(str(percentile_range[0]),
                             xy=(-0.3, 0.0),
                             xycoords='axes fraction',
                             horizontalalignment='right',
                             verticalalignment='center',
                             rotation=90
                             )
            cbar.ax.annotate(str(percentile_range[1]),
                             xy=(-0.3, 1.0),
                             xycoords='axes fraction',
                             horizontalalignment='right',
                             verticalalignment='center',
                             rotation=90
                             )
            cbar.ax.annotate('(percentile)',
                             xy=(-0.3, 0.5),
                             xycoords='axes fraction',
                             horizontalalignment='right',
                             verticalalignment='center',
                             rotation=90
                             )
        return fig
