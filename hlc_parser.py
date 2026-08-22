"""Parse Hanazeder HLC-20 .hlc Delphi binary config file: extract mod → labels."""
import struct
from typing import Optional

# 14-byte pattern that follows each label; byte 14 = mod_nr, byte 15 = 0x01
_PATTERN = bytes([
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x02, 0x00, 0x00, 0x00, 0x10, 0x02,
    0x00, 0x00,
])


def _wstring_before(data: bytes, pos: int) -> Optional[str]:
    """Scan backwards for a WideString with 4-byte BE length prefix + UTF-16 BE body."""
    for back in range(4, 500):
        lp = pos - back
        if lp < 0:
            break
        length = struct.unpack_from(">I", data, lp)[0]
        expected_end = lp + 4 + length
        if 2 <= length <= 300 and length % 2 == 0 and expected_end + 1 == pos:
            raw = data[lp + 4 : expected_end]
            try:
                s = raw.decode("utf-16-be")
                if len(s) >= 3 and all(32 <= ord(c) or c in "\n\r\t" for c in s):
                    return s.strip()
            except Exception:
                pass
    return None


def parse_hlc(data: bytes) -> dict[int, list[str]]:
    """
    Scan binary .hlc data for all module-pattern occurrences.
    Returns {mod_nr: [label, ...]} sorted by mod_nr.
    """
    module_map: dict[int, list[str]] = {}
    pos = 0
    while True:
        pos = data.find(_PATTERN, pos)
        if pos == -1:
            break
        if pos + 15 >= len(data) or data[pos + 15] != 0x01:
            pos += 1
            continue
        mod_nr = data[pos + 14]
        name = _wstring_before(data, pos)
        if name and 3 <= len(name) <= 60:
            module_map.setdefault(mod_nr, [])
            if name not in module_map[mod_nr]:
                module_map[mod_nr].append(name)
        pos += 1
    return module_map
