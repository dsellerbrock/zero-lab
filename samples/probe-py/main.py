"""Zero Lab sample: a 2 Hz square wave on GPIO24 for the Probe widget (4 edges per second)."""
from signal import pause

from gpiozero import LED

out = LED(24)
out.blink(on_time=0.25, off_time=0.25)
print("Ready: GPIO24 toggles at 2 Hz; watch the Probe widget.", flush=True)
pause()
