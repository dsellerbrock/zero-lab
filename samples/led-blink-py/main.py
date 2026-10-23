"""Zero Lab sample: blink the LED widget on GPIO27 once a second."""
from signal import pause

from gpiozero import LED

led = LED(27)
led.blink(on_time=0.5, off_time=0.5)
print("Ready: the LED widget on GPIO27 blinks once a second.", flush=True)
pause()
