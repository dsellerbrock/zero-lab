# adc-knob-py

Turn the analog Knob widget; the program reads it with `gpiozero.MCP3008(channel=0).value` and prints adc=<0.000-1.000>.
Zero Lab's Pi has an emulated MCP3008 ADC on SPI0 (CE0), so this is the same code as on a real Pi with that chip.
Open layout.json, drop this folder on Your code, press Build and run.
