"""Zero Lab sample: count 0000-9999 on an HT16K33 4-digit 7-segment backpack (I2C1, address 0x70)."""
import time

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus

ADDR = 0x70
FONT = [0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F]  # 0-9, segments a-g = bits 0-6, dot = bit 7

bus = SMBus(1)
bus.write_byte(ADDR, 0x21)  # oscillator on
bus.write_byte(ADDR, 0x81)  # display on, no blink
bus.write_byte(ADDR, 0xEF)  # full brightness
print("Ready: watch the 7-segment widget (I2C HT16K33) count.", flush=True)
n = 0
while True:
    d = [FONT[int(c)] for c in f"{n:04d}"]
    # Adafruit layout: digits at RAM 0, 2, 6, 8; the colon is bit 1 of RAM 4 (on for odd counts)
    bus.write_i2c_block_data(ADDR, 0x00, [d[0], 0, d[1], 0, 0x02 * (n % 2), 0, d[2], 0, d[3], 0])
    print(f"count={n:04d}", flush=True)
    n = (n + 1) % 10000
    time.sleep(0.5)
