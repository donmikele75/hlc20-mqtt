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


# Response frame: 15 <hi> <lo>  -> value is 16-bit BIG-ENDIAN (verified live on COM8).
# 0xD8F1 (-9999) = module not configured; 0xFFFF (-1) = sensor open/error.
_UNCONFIGURED = -9999


def _decode(resp: bytes) -> int | None:
    i = resp.find(0x15)
    if i < 0 or i + 2 >= len(resp):
        return None
    raw = (resp[i + 1] << 8) | resp[i + 2]
    raw = raw - 65536 if raw > 32767 else raw
    return None if raw == _UNCONFIGURED else raw


def hlc_read(ser: serial.Serial, mod: int) -> int | None:
    """Read live module output (type F1, idx 0). Returns raw signed 16-bit BE."""
    cmd = bytes([0x98, 0x00, mod & 0xFF, 0xF1, 0x00])
    ser.reset_input_buffer()
    ser.write(cmd)
    time.sleep(READ_DELAY)
    return _decode(ser.read(64))


def hlc_read_param(ser: serial.Serial, mod: int, idx: int) -> int | None:
    """Read setting parameter (type 01). Returns raw signed 16-bit BE."""
    cmd = bytes([0x98, 0x00, mod & 0xFF, 0x01, idx & 0xFF])
    ser.reset_input_buffer()
    ser.write(cmd)
    time.sleep(READ_DELAY)
    return _decode(ser.read(64))
