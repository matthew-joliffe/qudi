# -*- coding: utf-8 -*-

"""
This hardware module is written to integrate the Photometrics Prime 95B camera. It uses a python wrapper PyVcam
to wrap over the PVCAM SDK.
---

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

from core.module import Base
from core.configoption import ConfigOption

from interface.camera_interface import CameraInterface
from interface.odmr_counter_interface import ODMRCounterInterface

# Python wrapper for wrapping over the PVCAM SDK. Functions can be found
# in PyVCAM/camera.py
from pyvcam import pvc
from pyvcam.camera import Camera
from pyvcam import constants as const


class Prime95B(Base, CameraInterface):
    """ Hardware class for Prime95B

    Example config for copy-paste:

    mycamera:
        module.Class: 'camera.prime95b.Prime95B'

    """
    # Camera name to be displayed in GUI
    _camera_name = 'Prime95B'

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self.const = const
        pvc.init_pvcam()
        # Generator function to detect a connected camera
        self.cam = next(Camera.detect_camera())
        self.cam.open()
        self.cam.exp_mode = "Ext Trig Internal"
        self.cam.exp_res = 0
        self.exp_time = self.cam.exp_time = 1
        nx_px, ny_px = self._get_detector()
        self._width, self._height = nx_px, ny_px
        self._live = False

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        self.stop_acquisition()
        self._shut_down()

    def get_name(self):
        """ Retrieve an identifier of the camera that the GUI can print

        @return string: name for the camera
        """
        return self.cam.name

    def get_size(self):
        """ Retrieve size of the image in pixel

        @return tuple: Size (width, height)
        """
        return self.cam.shape

    def support_live_acquisition(self):
        """ Return whether or not the camera can take care of live acquisition

        @return bool: True if supported, False if not
        """
        return True

    def start_live_acquisition(self):
        """ Start a continuous acquisition

        @return bool: Success ?
        """
        self.cam.start_live()  
        self._live = True

        return True

    def start_single_acquisition(self):
        """ Start a single acquisition

        @return bool: Success ?
        """
        return True

    def stop_acquisition(self):
        """ Stop/abort live or single acquisition

        @return bool: Success ?
        """
        if self._live:
            self._live = False
            self.cam.stop_live()
        return True

    def get_acquired_data(self):
        """ Return an array of last acquired image.

        @return numpy array: image data in format [[row],[row]...]

        Each pixel might be a float, integer or sub pixels
        """
        if self._live:
            # .reshape(self.cam.sensor_size[::-1])
            image_array = self.cam.get_live_frame()
        else:
            # .reshape(self.cam.sensor_size[::-1])#exp_time = self.exp_time
            image_array = self.cam.get_frame()

        return image_array

    def set_exposure(self, exposure):
        """ Set the exposure time in mseconds. For this python wrapper for camera hardware it only changes the value
        in the camera instance class and sets the value after image is clicked.
        Hence there maybe a discrepancy between the cam.exp_time value and the value from get_param()

        @param float time: desired new exposure time

        @return bool: Success?
        """
        # self.cam.set_param(const.PARAM_EXPOSURE_TIME, int(exposure))
        self.cam.exp_time = self.exp_time = int(exposure)
        return True

    def get_exposure(self):
        """ Get the exposure time in mseconds. Different from get_param which returns the true value. This returns
        the value as assigned to the camera class.

        @return float exposure time
        """
        return self.cam.exp_time

    def set_gain(self, gain):
        """ Set the gain

        @param float gain: desired new gain

        @return float: new exposure gain
        """
        self.cam.gain = gain
        return self.cam.gain

    def get_gain(self):
        """ Get the gain

        @return float: exposure gain
        """
        return self.cam.gain

    def get_ready_state(self):
        """ Is the camera ready for an acquisition ?

        @return bool: ready ?
        """
        if self.cam.is_open:
            return True
        else:
            return False

    def _shut_down(self):
        try:
            self.cam.close()
            pvc.uninit_pvcam()
            return True
        except BaseException:
            return False

    def _get_detector(self):
        '''Returns the camera's sensor size

        @return tuple: (width pixrls, heigth pixels)
        '''
        return self.cam.sensor_size

    def get_max_gain(self):
        '''Returns the camera's maximum possible gain value. Determined also by the current speed index.

        @return float: maximum gain
        '''
        return self.cam.get_param(const.PARAM_GAIN_INDEX,
                                  const.ATTR_MAX)

    def get_max_exp(self):
        '''Returns the camera's maximum possible exposure value.

        @return float: maximum exposure
        '''
        return self.cam.get_param(const.PARAM_EXPOSURE_TIME,
                                  const.ATTR_MAX)

    def set_exposure_mode(self, exp_mode):
        '''Sets the exposure to exp_mode passed. Determines trigger behaviour. See constants.py for
        allowed values

        @param exp_mode str: string which is the key to the exposure mode dict in constants.py
        @return bool: always True
        '''
        self.cam.exp_mode = exp_mode
        return True

    def get_exposure_mode(self):
        '''Returns the current exposure mode of the cammera.

        @return str: exp_mode
        '''

        return self.cam.exp_mode

    def avail_exposure_mode(self):
        '''Possibly returns a dict of available exposure modes for the camera.

        @return dict: dict of availabel exposure modes
        '''
        return self.cam.read_enum(const.PARAM_EXPOSURE_MODE)

    def set_speed_index(self, index):
        '''Sets the speed table index. This allows moving between 16bit and 12bit modes corresponding
        also to different max gain values. The default index is 0(?) and is corresponding to 16bit images.

        @param int: index
        '''
        indices = self.cam.get_param(const.PARAM_SPDTAB_INDEX,
                                     const.ATTR_COUNT)
        if index >= indices:
            raise ValueError(
                '{} only supports '
                'speed indices < {}.'.format(
                    self._camera_name, indices))
        self.cam.speed_table_index = index

    def get_sequence(self, num_frames):
        '''Gets a sequence of images that are num_frames in nmumbers.

        @param int: num_frames
        @return ndarray: 3darray of images of shape (num_frames, 1200, 1200) for image size with default roi of
                        (1200, 1200)
        '''
        if self.get_ready_state():
            self.frames = self.cam.get_sequence(num_frames)
            return self.frames
        else:
            return False