"""Zero Lab sample: count 0-9 on the 7-segment widget (segments a-g on GPIO21, 20, 16, 12, 7, 8, 25)."""
import time

from gpiozero import LEDBoard

segments = LEDBoard(21, 20, 16, 12, 7, 8, 25)  # a, b, c, d, e, f, g
DIGITS = ["1111110", "0110000", "1101101", "1111001", "0110011",
          "1011011", "1011111", "1110000", "1111111", "1111011"]
print("Ready: watch the 7-segment widget count.", flush=True)
while True:
    for digit, pattern in enumerate(DIGITS):
        segments.value = tuple(int(c) for c in pattern)
        print(f"digit={digit}", flush=True)
        time.sleep(1)
