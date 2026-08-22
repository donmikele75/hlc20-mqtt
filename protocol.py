"""HLC-20 serial protocol: open connection, read live output, read setting."""
import time

import serial

BAUD_RATE  = 38400
READ_DELAY = 0.15   # s between TX and first RX byte


def hlc_open(host: str, port: int) -> tuple[serial.Serial, str | None]:
    """Open TCP socket to serial server, perform HLC handshake."""
    url = f"socket://{host}:{port}"
    ser = serial.serial_for_url(url, baudrate=BAUD_RATE, timeout=0.5)
    ser.write(bytes.fromhex("953073"))
    time.sleep(1.0)
    resp = ser.read(64)
    return ser, resp.hex(" ").upper() if resp else None


def hlc_read(ser: serial.Serial, mod: int) -> int | None:
    """Read live module output (type F1, idx 0). Returns raw signed 16-bit LE."""
    cmd = bytes([0x98, 0x00, mod & 0xFF, 0xF1, 0x00])
    ser.write(cmd)
    time.sleep(READ_DELAY)
    resp = ser.read(64)
    if not resp or len(resp) < 3:
        return None
    raw = resp[1] | (resp[2] << 8)
    return raw - 65536 if raw > 32767 else raw


def hlc_read_param(ser: serial.Serial, mod: int, idx: int) -> int | None:
    """Read setting parameter (type 01). Returns raw signed 16-bit LE."""
    cmd = bytes([0x98, 0x00, mod & 0xFF, 0x01, idx & 0xFF])
    ser.write(cmd)
    time.sleep(READ_DELAY)
    resp = ser.read(64)
    if not resp or len(resp) < 3:
        return None
    raw = resp[1] | (resp[2] << 8)
    return raw - 65536 if raw > 32767 else raw
