"""Zero Lab sample: read an analog Knob through the emulated MCP3008 ADC (SPI0 CE0, channel 0)."""
import time

from gpiozero import MCP3008

knob = MCP3008(channel=0)
last = None
print("Ready: turn the analog Knob (MCP3008 channel 0).", flush=True)
while True:
    value = round(knob.value, 3)  # 0.0-1.0
    if value != last:
        print(f"adc={value:.3f}", flush=True)
        last = value
    time.sleep(0.05)
