"""Recover fixed-size EMG frames using consecutive device timestamps."""


def pop_emg_frame(buffer, frame_size, sample_ticks):
    """Pop one frame only after validating two following frame boundaries.

    Zero bytes also occur in ADC payloads, so a zero alone cannot identify a
    data-packet header. Three headers and two sampling intervals disambiguate
    the boundary without interpreting floating electrode voltages as framing.
    Keep incomplete input for the next serial read.
    """
    required = 2 * frame_size + 4
    for offset in range(max(0, len(buffer) - required + 1)):
        positions = [offset + i * frame_size for i in range(3)]
        if any(buffer[position] != 0 for position in positions):
            continue
        ticks = [int.from_bytes(buffer[p + 1:p + 4], 'little') for p in positions]
        steps = [(ticks[i + 1] - ticks[i]) % (1 << 24) for i in range(2)]
        if all(step > 0 and abs(step - sample_ticks) <= 1 for step in steps):
            frame = bytes(buffer[offset:offset + frame_size])
            del buffer[:offset + frame_size]
            return frame
    # A valid header may still begin in the final incomplete lookahead.
    if len(buffer) >= required:
        del buffer[:len(buffer) - required + 1]
    return None
