"""Zero Lab sample: the Button widget (GPIO17) lights the LED widget (GPIO27)."""
from signal import pause

from gpiozero import LED, Button

led = LED(27)
button = Button(17)  # pull_up=True: pressed reads low, like the Button widget's default (idle high)
button.when_pressed = lambda: (led.on(), print("pressed", flush=True))
button.when_released = lambda: (led.off(), print("released", flush=True))
print("Ready: press the Button widget (GPIO17); the LED widget (GPIO27) follows.", flush=True)
pause()
