"""Zero Lab sample: read the Knob widget as a 4-bit number on GPIO5, 6, 13, 19 (lowest bit first)."""
import time

from gpiozero import DigitalInputDevice

bits = [DigitalInputDevice(p) for p in (5, 6, 13, 19)]
last = None
print("Ready: turn the Knob widget (GPIO5, 6, 13, 19).", flush=True)
while True:
    value = sum(b.value << i for i, b in enumerate(bits))
    if value != last:
        print(f"knob={value}", flush=True)
        last = value
    time.sleep(0.05)
