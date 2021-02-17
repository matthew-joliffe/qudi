import pyvisa
import numpy as np

__address__ = 'TCPIP0::K-M9537A-40368::inst0::INSTR'

class AWG():

    segment_id = 1

    def __init__(self, sampling_freq):
        self.sampling_freq = sampling_freq
        rm = pyvisa.ResourceManager()
        self.awg = rm.open_resource(__address__, timeout = 5000, read_termination = '\n', write_termination ='\n')

        print(self.awg.query("*IDN?"))
        self.awg.write("*RST") # reset awg to default
        #awg.write(':TRAC1:MARK 0') #not sure what to do with this just yet
        self.awg.write(f'FREQ:RAST {self.sampling_freq}GHz')
        self.awg.write(':INIT:CONT 0')
        self.awg.write(':INIT:CONT2 0') # continuous mode off
        self.awg.write('INIT:GATE 0')
        self.awg.write('INIT:GATE2 0') # gated mode off
        self.awg.write('FUNC:MODE ARB') # allow an arbitrary function
        self.awg.write('OUTP:ROUT DC') # uses "AMP out" output of AWG
        self.awg.write('OUTP2:ROUT DC')
        self.awg.write('OUTP1 on')
        self.awg.write('OUTP2 on') #set output on so it can be triggered faster later
        self.awg.write(f'TRAC1:SEL {self.segment_id}') # select segement to be excecuted
        self.awg.write(f'TRAC2:SEL {self.segment_id}')

    def convert_to_bytes(self, cmd, amp=1):
        #takes a numpy array between bounds [-1:1] and returns AWG compatible bytes data
    
        return ((16*np.int16(cmd*2047*amp))).tobytes() #I also don't know why the data needs to be in this format, but it does

    def create_waveform(self, waveform_array, channel = 1, amp = 1):
        cmd_list = []
        max_chunk_length = 499000000
        for i in range(0, len(waveform_array), max_chunk_length):
            waveform_array_short = waveform_array[i:i+max_chunk_length]
            if type(waveform_array) != bytes:
                bytes_array = self.convert_to_bytes(waveform_array_short, amp)
            else:
                bytes_array = waveform_array_short
            header = self.create_header(bytes_array, channel, i)
            cmd = header + bytes_array
            cmd_list.append(cmd)
        return cmd_list

    def create_header(self, bytescmd, channel = 1, offset = 0):
    
        len_bytes = len(bytescmd)
        len_nbytes = len(str(len(bytescmd)))
        return f"TRAC{channel}:DATA {self.segment_id},{offset},#".encode("ascii") + str(len_nbytes).encode('ascii') + str(len_bytes).encode('ascii')

    def correct_waveform_length(self, waveform_len):
        # the waveform must be length 320+int*64
        
        if waveform_len < 320:
            k = 320
        else:
            n = np.floor((waveform_len-320)/64)
            k = int(320+64*n)
        return k

    def write_waveform(self, bytescmd, channel=1):
        offset = 1
        total_len = 0
        for waveform in bytescmd:   
            overcount_val = 16 + offset + int(waveform[offset+15:offset+16].decode('UTF-8'))
            total_len += int((len(waveform)-overcount_val)/2)
            offset = len(str(total_len))
        #overcount_val = 17 + int(bytescmd[16:17].decode('UTF-8'))
        #self.awg.write(f'TRAC{channel}:DEF {self.segment_id},{(len(bytescmd)-overcount_val)/2}') # create waveform segment and define number of data points
        self.awg.write(f'TRAC{channel}:DEF {self.segment_id},{total_len}')
        for bytes_form in bytescmd:
            self.awg.write_raw(bytes_form)

    def output_on(self):
        self.awg.write('INIT:IMM')

    def create_upload_waveform(self, cmd, channel = 1, amp = 1):
        k = self.correct_waveform_length(len(cmd))
        cmd = cmd[:k]
        waveform_cmd = self.create_waveform(cmd, channel, amp)
        self.write_waveform(waveform_cmd, channel)
        return cmd

    def set_amplitude(self, amp):
        #set an amplitude between 0.15-1V
        self.awg.write(f'DC:VOLT:AMPL {amp}')
        print(self.get_amplitude())

    def get_amplitude(self):
        return self.awg.query('DC:VOLT:AMPL?')

    def set_sampling_freq(self, freq):
        #set sampling freq in GHz
        self.awg.write(f'FREQ:RAST {freq}GHz')
         
    def query(self, query):
        return self.awg.query(query)

    def write(self, cmd):
        self.awg.write(cmd)

    def write_raw(self, cmd):
        self.awg.write_raw(cmd)