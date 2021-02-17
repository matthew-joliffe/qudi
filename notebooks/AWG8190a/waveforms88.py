import numpy as np
import time


class waveforms():

    def __init__(self, sampling_rate, awg_freq, laser_pause):

        self.sampling_rate = sampling_rate
        self.awg_freq = awg_freq
        self.laser_pause = laser_pause #in ns
        
    def sine(self, duration, phase, freq):
        samples_ns = self.sampling_rate/1e9
        t = np.linspace(0, round(duration*samples_ns)-1, round(duration*samples_ns))
        freq = 2*np.pi*freq/samples_ns*1e-9
        phase = np.radians(phase)
        return np.sin(freq*t+phase).tolist()

    def zero(self, duration, offset=0):
        if offset < -1 or offset > 1:
            raise ValueError('offset must be between -1 and 1')
        if duration < 0:
            raise ValueError('duration cannot be negative')
        samples_ns = self.sampling_rate/1e9
        duration = int(round(duration*samples_ns))
        return duration * [offset]

    def sine_space(self, duration_sine, phase, duration_zero, freq, offset = 0):
        sin = self.sine(duration_sine, phase, freq)
        zero = self.zero(duration_zero, offset)
        return sin+zero

    def rabi(self, tau, tau_step, step_number, phase = 'x'):
        tau *= 1e9
        tau_step *= 1e9
        if phase == 'x':
            phase = 0
        elif phase == 'y':
            phase = 90
        arb_form = []
        laser_pause = self.zero(self.laser_pause)
        for i in range(step_number):
            sin = self.sine(tau+tau_step*i, phase, self.awg_freq)+laser_pause
            arb_form += sin
        return arb_form

    def rabi_double(self, tau, tau_step, step_number):
        tau *= 1e9
        tau_step *= 1e9
        arb_form_1 = []
        arb_form_2 = []
        laser_pause = self.zero(self.laser_pause)
        for i in range(step_number):
            sin_1 = self.sine(tau+tau_step*i, 0, self.awg_freq)+laser_pause
            sin_2 = self.sine(tau+tau_step*i, 90, self.awg_freq)+laser_pause
            arb_form_1 += sin_1
            arb_form_2 += sin_2
        return arb_form_1, arb_form_2

    def pulsed_ODMR(self, freq_start, freq_stop, freq_step, pi_pulse):
        freq_list = np.arange(freq_start, freq_stop+freq_step, freq_step)
        if not ((freq_stop-freq_start)/freq_step)%1 ==0:
            freq_list = freq_list[:-1]
        arb_form = []
        laser_pause = self.zero(self.laser_pause)
        for freq in freq_list:
            sin = self.sine(pi_pulse, 0, freq)+laser_pause
            arb_form += sin
        return arb_form

    def free_induction_decay(self,tau_start, tau_step, step_number, pi_half_pulse, pi_three_half_pulse, alternating):
        arb_form = []
        laser_pause = self.zero(self.laser_pause)
        for i in range(step_number):
            sin = self.sine_space(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), (tau_start+tau_step*i)*1e9, self.awg_freq)
            arb_form += sin
            sin = self.sine(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
            arb_form += sin + laser_pause
            if alternating:
                sin = self.sine_space(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), (tau_start+tau_step*i)*1e9, self.awg_freq)
                arb_form += sin
                sin = self.sine(pi_three_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                arb_form += sin + laser_pause
        return arb_form

    def hahn_echo(self, tau_start, tau_step, step_number, pi_half_pulse, pi_pulse, pi_three_half_pulse, alternating):
        arb_form = []
        laser_pause = self.zero(self.laser_pause)
        for i in range(step_number):
            sin = self.sine_space(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), (tau_start+tau_step*i)*1e9/2, self.awg_freq)
            arb_form += sin
            sin = self.sine_space(pi_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), (tau_start+tau_step*i)*1e9/2, self.awg_freq)
            arb_form += sin
            sin = self.sine(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
            arb_form += sin + laser_pause
            if alternating:
                sin = self.sine_space(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), (tau_start+tau_step*i)*1e9/2, self.awg_freq)
                arb_form += sin
                sin = self.sine_space(pi_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), (tau_start+tau_step*i)*1e9/2, self.awg_freq)
                arb_form += sin
                sin = self.sine(pi_three_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                arb_form += sin + laser_pause
        return arb_form

    def xy8(self, tau_start, tau_step, step_number, order, pi_half_pulse, pi_three_half_pulse, pi_pulse, alternating, pulse_type='square'):

        tau_start *= 1e9
        tau_step *= 1e9
        arb_form = []
        laser_pause = self.zero(self.laser_pause)

        if pulse_type == 'square':
            for i in range(step_number):
                x_half = self.sine(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                arb_form += x_half
                pulse_partial = []
                for _ in range(order):
                    pulse_partial = self.xy8_single(tau_start+tau_step*i, pi_pulse, len(arb_form))
                    arb_form += pulse_partial
                x_half = self.sine(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                arb_form += x_half + laser_pause

                if alternating:
                    x_half = self.sine(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                    arb_form += x_half
                    pulse_partial = []
                    for _ in range(order):
                        pulse_partial = self.xy8_single(tau_start+tau_step*i, pi_pulse, len(arb_form))
                        arb_form += pulse_partial
                    x_half = self.sine(pi_three_half_pulse, 360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                    arb_form += x_half + laser_pause

        elif pulse_type == 'BB1':

            for i in range(step_number):
                x_half = self.sine(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                arb_form += x_half
                pulse_partial = []
                for _ in range(order):
                    pulse_partial = self.xy8_single(tau_start+tau_step*i, pi_pulse, len(arb_form), pulse_type = 'BB1')
                    arb_form += pulse_partial
                x_half = self.sine(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                arb_form += x_half + laser_pause

                if alternating:
                    x_half = self.sine(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                    arb_form += x_half
                    pulse_partial = []
                    for _ in range(order):
                        pulse_partial = self.xy8_single(tau_start+tau_step*i, pi_pulse, len(arb_form), pulse_type = 'BB1')
                        arb_form += pulse_partial
                    x_half = self.sine(pi_three_half_pulse, 360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                    arb_form += x_half + laser_pause
        return arb_form

    def xy8_single(self, tau, pi_pulse, seq_len, pulse_type = 'square'):

        arb_form = []
        tau_half = tau/2
        arb_form += self.zero(tau_half)
        seq_len += len(arb_form)
        if pulse_type == 'square':
            for _ in range(2):
                x = self.sine_space(pi_pulse, 360*(self.awg_freq/self.sampling_rate)*seq_len, tau, self.awg_freq)
                arb_form += x
                seq_len += len(x)
                y = self.sine_space(pi_pulse, 90 + 360*(self.awg_freq/self.sampling_rate)*seq_len, tau, self.awg_freq)
                arb_form += y
                seq_len += len(y)

            y = self.sine_space(pi_pulse, 90 + 360*(self.awg_freq/self.sampling_rate)*seq_len, tau, self.awg_freq)
            arb_form += y
            seq_len += len(y)
            x = self.sine_space(pi_pulse, 360*(self.awg_freq/self.sampling_rate)*seq_len, tau, self.awg_freq)
            arb_form += x
            seq_len += len(x)

            y = self.sine_space(pi_pulse, 90 + 360*(self.awg_freq/self.sampling_rate)*seq_len, tau, self.awg_freq)
            arb_form += y
            seq_len += len(y)
            x = self.sine_space(pi_pulse, 360*(self.awg_freq/self.sampling_rate)*seq_len, tau_half, self.awg_freq)
            arb_form += x
            seq_len += len(x)

        elif pulse_type == 'BB1':
            for _ in range(2):
                x = self.BB1_pulse(pi_pulse, pi_pulse, 0, 360*(self.awg_freq/self.sampling_rate)*seq_len, self.awg_freq)
                x_tau = self.zero(tau)
                arb_form += x + x_tau
                seq_len += len(x) + len(x_tau)
                y = self. BB1_pulse(pi_pulse, pi_pulse, 90, 360*(self.awg_freq/self.sampling_rate)*seq_len, self.awg_freq)
                y_tau = self.zero(tau)
                arb_form += y + y_tau
                seq_len += len(y) + len(y_tau)

            y = self.BB1_pulse(pi_pulse, pi_pulse, 90, 360*(self.awg_freq/self.sampling_rate)*seq_len, self.awg_freq)
            arb_form += y + y_tau
            seq_len += len(y) + len(y_tau)
            x = self.BB1_pulse(pi_pulse, pi_pulse, 0, 360*(self.awg_freq/self.sampling_rate)*seq_len, self.awg_freq)
            arb_form += x + x_tau
            seq_len += len(x) + len(x_tau)

            y = self.BB1_pulse(pi_pulse, pi_pulse, 90, 360*(self.awg_freq/self.sampling_rate)*seq_len, self.awg_freq)
            arb_form += y + y_tau
            seq_len += len(y) + len(y_tau)
            x = self.BB1_pulse(pi_pulse, pi_pulse, 0,  360*(self.awg_freq/self.sampling_rate)*seq_len, self.awg_freq)
            x_tau_half = self.zero(tau/2)
            arb_form += x + x_tau_half
            seq_len += len(x) + len(x_tau_half)
        return arb_form

    def pi_pulse_test(self, pi_pulse, num_pulses, pulse_type='square'):

        samples_ns = self.sampling_rate/1e9
        print(f'pi pulse: {(round(pi_pulse*samples_ns))/12}')
        arb_form = []
        laser_pause = self.zero(self.laser_pause)

        if pulse_type == 'square':
            for i in range(num_pulses):
                for _ in range(i+1):
                    pi_pulse_form = self.sine_space(pi_pulse, 360*self.awg_freq/self.sampling_rate*len(arb_form), 20, self.awg_freq)
                    arb_form += pi_pulse_form
                arb_form += laser_pause

        elif pulse_type == 'BB1':
            pulse_pause = self.zero(20) 
            for i in range(num_pulses):
                for _ in range(i+1):
                    pi_pulse_form = self.BB1_pulse(pi_pulse, pi_pulse,90, 360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                    arb_form += pi_pulse_form + pulse_pause
                arb_form += laser_pause

        elif pulse_type == 'CORPSE':
            pulse_pause = self.zero(20) 
            for i in range(num_pulses):
                for _ in range(i+1):
                    pi_pulse_form = self.CORPSE_pulse(pi_pulse, pi_pulse,0, 360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                    arb_form += pi_pulse_form + pulse_pause
                arb_form += laser_pause

        elif pulse_type == 'CORinBB':
            pulse_pause = self.zero(20) 
            for i in range(num_pulses):
                for _ in range(i+1):
                    pi_pulse_form = self.CORinBB_pulse(pi_pulse, pi_pulse,0, 360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                    arb_form += pi_pulse_form + pulse_pause
                arb_form += laser_pause

        else:
            raise ValueError('pulse type not supported')
        return arb_form

    def coupling(self, tau0, step_number, freq2, pi_half_a, pi_a, pi_three_half_a, pi_b, alternating):
        tau0 *=1e9
        arb_form = []
        laser_pause = self.zero(self.laser_pause)
        tau_list = np.linspace(10, tau0-10-pi_b, step_number)
        
        for i in range(step_number):
            sin = self.sine_space(pi_half_a,  360*self.awg_freq/self.sampling_rate*len(arb_form), tau0, self.awg_freq)
            arb_form += sin
            sin = self.sine_space(pi_a,  360*self.awg_freq/self.sampling_rate*len(arb_form),tau_list[i] , self.awg_freq)
            arb_form += sin
            sin = self.sine_space(pi_b, 0,tau_list[-(i+1)], freq2)
            arb_form += sin
            sin = self.sine(pi_half_a,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
            arb_form += sin + laser_pause

            if alternating:
                sin = self.sine_space(pi_half_a,  360*self.awg_freq/self.sampling_rate*len(arb_form), tau0, self.awg_freq)
                arb_form += sin
                sin = self.sine_space(pi_a,  360*self.awg_freq/self.sampling_rate*len(arb_form),tau_list[i] , self.awg_freq)
                arb_form += sin
                sin = self.sine_space(pi_b, 0,tau_list[-(i+1)], freq2)
                arb_form += sin
                sin = self.sine(pi_three_half_a,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
                arb_form += sin + laser_pause
        return arb_form

    def T1(self, tau_start, tau_step, step_number, pi_pulse, alternating):
        tau_start *= 1e9
        tau_step *= 1e9
        arb_form = []
        laser_pause = self.zero(self.laser_pause)
        for i in range(step_number):
            wait = self.zero(tau_start+i*tau_step)
            arb_form += wait+laser_pause
            if alternating:
                wait = self.sine_space(pi_pulse, 0, tau_start+i*tau_step, self.awg_freq)
                arb_form += wait + laser_pause
        return arb_form

    def KDD(self, tau_start, tau_step, step_number, pi_half_pulse, pi_pulse, pi_three_half_pulse, alternating):

        tau_start *= 1e9
        tau_step *= 1e9
        arb_form = []
        laser_pause = self.zero(self.laser_pause)

        for i in range(step_number):
            x_half = self.sine_space(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), (tau_start+tau_step*i)/2, self.awg_freq)
            arb_form += x_half
            for _ in range(2):
                KDD_partial = self.knill_pulse(pi_pulse, 0, 360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq, tau = tau_start+tau_step*i)
                arb_form += KDD_partial
                KDD_partial = self.knill_pulse(pi_pulse, 90, 360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq, tau = tau_start+tau_step*i)
                arb_form += KDD_partial
            x_half = self.sine(pi_half_pulse,  360*self.awg_freq/self.sampling_rate*len(arb_form), self.awg_freq)
            arb_form = x_half + laser_pause
        return arb_form

    def BB1_pulse(self, duration, pi_pulse, axis, offset, freq):

        BB1_pulse = []
        theta = duration/pi_pulse*np.pi
        psi = self._psi_bb1(theta)
        pulse_pause = self.zero(5)

        pi_partial = self.sine(pi_pulse, axis+offset+psi+360*self.awg_freq/self.sampling_rate*len(BB1_pulse), freq)
        BB1_pulse += pi_partial + pulse_pause
        two_pi_partial = self.sine(2*pi_pulse, -2*axis+3*psi+offset+360*self.awg_freq/self.sampling_rate*len(BB1_pulse), freq)
        BB1_pulse += two_pi_partial + pulse_pause
        pi_partial = self.sine(pi_pulse, axis+offset+psi+360*self.awg_freq/self.sampling_rate*len(BB1_pulse), freq)
        BB1_pulse += pi_partial + pulse_pause
        arb_partial = self.sine(duration, axis+offset+360*self.awg_freq/self.sampling_rate*len(BB1_pulse), freq)
        BB1_pulse += arb_partial

        return BB1_pulse


    def _psi_bb1(self, theta):
        return np.rad2deg(np.arccos(-theta/(4*np.pi)))
        
    def CORPSE_pulse(self, duration, pi_pulse,axis, offset, freq):

        CORPSE_pulse = []
        theta = duration/pi_pulse*np.pi
        psi = self._psi_corpse(pi_pulse, theta)
        pulse_pause = self.zero(5)

        arb_partial = self.sine(duration/2 - psi, axis+offset, freq)
        CORPSE_pulse += arb_partial + pulse_pause
        arb_partial = self.sine(2*pi_pulse - 2*psi, axis + offset + 180 + 360*self.awg_freq/self.sampling_rate*len(CORPSE_pulse), freq)
        CORPSE_pulse += arb_partial + pulse_pause
        arb_partial = self.sine(duration/2 - psi, axis + offset + 360*self.awg_freq/self.sampling_rate*len(CORPSE_pulse), freq)
        CORPSE_pulse += arb_partial

        return CORPSE_pulse

    def _psi_corpse(self, pi_pulse, theta):
        return np.arcsin(np.sin(theta/2)/2)*pi_pulse/np.pi

    def knill_pulse(self, pi_pulse, axis, offset, freq, tau = 5):
        
        knill_pulse = []
        tau_pause = self.zero(tau)

        knill_partial = self.sine(pi_pulse, axis + offset + 30 + 360*self.awg_freq/self.sampling_rate*len(knill_pulse), freq)
        knill_pulse += knill_partial + tau_pause
        knill_partial = self.sine(pi_pulse, axis + offset + 0 + 360*self.awg_freq/self.sampling_rate*len(knill_pulse), freq)
        knill_pulse += knill_partial + tau_pause
        knill_partial = self.sine(pi_pulse, axis + offset + 90 + 360*self.awg_freq/self.sampling_rate*len(knill_pulse), freq)
        knill_pulse += knill_partial + tau_pause
        knill_partial = self.sine(pi_pulse, axis + offset + 0 + 360*self.awg_freq/self.sampling_rate*len(knill_pulse), freq)
        knill_pulse += knill_partial + tau_pause
        knill_partial = self.sine(pi_pulse, axis + offset + 30 + 360*self.awg_freq/self.sampling_rate*len(knill_pulse), freq)
        knill_pulse += knill_partial 

        return knill_pulse

    def CORinBB_pulse(self, duration, pi_pulse, axis, offset, freq):

        CORinBB_pulse = []
        theta = duration/pi_pulse*np.pi
        psi = self._psi_corpse(pi_pulse, theta)
        psi_2 = self._psi_CORinBB(pi_pulse, theta)
        pulse_pause = self.zero(5)

        arb_partial = self.sine(pi_pulse, axis + offset + psi_2, self.awg_freq)
        CORinBB_pulse += arb_partial + pulse_pause
        arb_partial = self.sine(2*pi_pulse, axis + offset + 3*psi_2 +  360*self.awg_freq/self.sampling_rate*len(CORinBB_pulse), freq)
        CORinBB_pulse += arb_partial + pulse_pause
        arb_partial = self.sine(pi_pulse, axis + offset + psi_2 +  360*self.awg_freq/self.sampling_rate*len(CORinBB_pulse), freq)
        CORinBB_pulse += arb_partial + pulse_pause
        arb_partial = self.sine(2*pi_pulse + duration/2 - psi, axis + offset +  360*self.awg_freq/self.sampling_rate*len(CORinBB_pulse), freq)
        CORinBB_pulse += arb_partial + pulse_pause
        arb_partial = self.sine(2*pi_pulse - 2*psi, axis + offset + 180 + 360*self.awg_freq/self.sampling_rate*len(CORinBB_pulse), freq)
        CORinBB_pulse += arb_partial + pulse_pause
        arb_partial = self.sine(duration/2 - psi, axis + offset +  360*self.awg_freq/self.sampling_rate*len(CORinBB_pulse), freq)
        CORinBB_pulse += arb_partial 
    
        return CORinBB_pulse

    def _psi_CORinBB(self, pi_pulse, theta):
        return np.arccos(-theta/(4*pi_pulse))*pi_pulse/np.pi