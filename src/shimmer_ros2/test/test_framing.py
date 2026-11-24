"""Check frame recovery with noise, payload zeros and counter rollover."""

from shimmer_ros2.shimmer_api.framing import pop_emg_frame


def frame(ticks):
    return b'\x00' + (ticks % (1 << 24)).to_bytes(3, 'little') + bytes(14)


def test_recovers_shifted_stream_with_payload_zeros():
    packets = [frame(1000 + 33 * i) for i in range(5)]
    buffer = bytearray(b'\xc0\x00\x00\x7f\xff' + b''.join(packets))
    assert pop_emg_frame(buffer, 18, 33) == packets[0]
    assert pop_emg_frame(buffer, 18, 33) == packets[1]


def test_partial_input_and_rollover():
    packets = b''.join(frame((1 << 24) - 20 + 33 * i) for i in range(4))
    buffer = bytearray()
    recovered = []
    for byte in packets:
        buffer.append(byte)
        result = pop_emg_frame(buffer, 18, 33)
        if result is not None:
            recovered.append(result)
    assert recovered[0] == packets[:18]
    assert recovered[1] == packets[18:36]


def test_rejects_false_headers_and_recovers_after_lost_byte():
    buffer = bytearray(bytes(100))
    assert pop_emg_frame(buffer, 18, 33) is None
    buffer.extend(frame(5000)[:-1] + frame(5033) + frame(5066) + frame(5099))
    assert pop_emg_frame(buffer, 18, 33) == frame(5033)


def test_stop_waits_through_initial_silence_and_drains_after_ack():
    from shimmer_ros2.shimmer_api.emg import ShimmerEMG

    class FakeSerial:
        timeout = 5.0

        def __init__(self):
            # Link setup silence, an ACK inside ADC data, queued data, then quiet.
            self.chunks = iter([b'', b'', b'\xff\x01', b'\x02', b'', b''])
            self.reads = 0
            self.reset = False

        def write(self, data):
            assert data == b'\x20'

        def read(self, size):
            self.reads += 1
            return next(self.chunks)

        def reset_input_buffer(self):
            self.reset = True

    class Logger:
        def info(self, message):
            pass

    device = ShimmerEMG('/dev/test', Logger(), None)
    device.ser = FakeSerial()
    device.stop_streaming()
    assert device.ser.reads == 6
    assert device.ser.reset
    assert device.ser.timeout == 5.0
