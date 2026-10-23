"""Zero Lab sample: report the Switch widget on GPIO22."""
from signal import pause

from gpiozero import DigitalInputDevice

switch = DigitalInputDevice(22)  # the Switch drives the pin high when on
switch.when_activated = lambda: print("switch=1", flush=True)
switch.when_deactivated = lambda: print("switch=0", flush=True)
print(f"Ready: flip the Switch widget (GPIO22). switch={switch.value}", flush=True)
pause()
