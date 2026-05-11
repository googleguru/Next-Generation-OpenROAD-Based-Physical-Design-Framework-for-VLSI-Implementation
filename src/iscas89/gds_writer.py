from __future__ import annotations
import struct
import time
from pathlib import Path

from .layout_engine import LayoutResult


# GDS II record type constants
_HEADER      = 0x0002
_BGNLIB      = 0x0102
_LIBNAME     = 0x0206
_UNITS       = 0x0305
_ENDLIB      = 0x0400
_BGNSTR      = 0x0502
_STRNAME     = 0x0606
_ENDSTR      = 0x0700
_BOUNDARY    = 0x0800
_PATH        = 0x0900
_SREF        = 0x0A00
_TEXT        = 0x0C06
_LAYER       = 0x0D02
_DATATYPE    = 0x0E02
_WIDTH       = 0x1003
_XY          = 0x1103
_ENDEL       = 0x1200
_TEXTTYPE    = 0x1502
_STRING      = 0x1606
_PRESENTATION = 0x1706
_PATHTYPE    = 0x2102

# Scale: 1 GDS unit = 1 nm → user unit = 1 μm → db_unit/user_unit = 1e3
_DB_PER_USER = 1000  # nm per μm
_CELL_UNIT_UM = 0.38  # 380 nm per placement unit (FreePDK45 site width)


class GDSWriter:
    """
    Writes a binary GDS II file from a LayoutResult.
    Outputs: cell boundary rectangles on layer 0, wire paths on layer 1, labels on layer 5.
    """

    def write(self, layout: LayoutResult, output_path: Path) -> Path:
        output_path = Path(output_path)
        buf = bytearray()
        now = _gds_timestamp()

        buf += _record(_HEADER, struct.pack(">h", 600))  # GDS version 6
        buf += _record(_BGNLIB, now + now)
        buf += _record(_LIBNAME, _pad_string(f"{layout.circuit_name}_lib"))
        # UNITS: 1e-3 m/unit (μm), 1e-9 m/unit (nm db unit)
        buf += _record(_UNITS,
                        struct.pack(">d", 1e-6) + struct.pack(">d", 1e-9))

        # One structure for the full design
        buf += _record(_BGNSTR, now + now)
        buf += _record(_STRNAME, _pad_string(layout.circuit_name))

        # Write cells as boundary rectangles
        for cell in layout.cells:
            x0 = int(cell.x * _CELL_UNIT_UM * _DB_PER_USER)
            y0 = int(cell.y * _CELL_UNIT_UM * _DB_PER_USER)
            x1 = int((cell.x + cell.w) * _CELL_UNIT_UM * _DB_PER_USER)
            y1 = int((cell.y + cell.h) * _CELL_UNIT_UM * _DB_PER_USER)

            layer = 2 if cell.is_ff else (4 if cell.is_pi else 0)
            buf += _boundary(layer, x0, y0, x1, y1)

            # Text label
            cx = (x0 + x1) // 2
            cy = (y0 + y1) // 2
            label = cell.gtype if len(cell.name) > 6 else cell.name
            buf += _text(5, cx, cy, label[:8])

        # Write routing segments as paths on layer 1
        for net in layout.nets:
            for x1f, y1f, x2f, y2f in net.segments:
                px1 = int(x1f * _CELL_UNIT_UM * _DB_PER_USER)
                py1 = int(y1f * _CELL_UNIT_UM * _DB_PER_USER)
                px2 = int(x2f * _CELL_UNIT_UM * _DB_PER_USER)
                py2 = int(y2f * _CELL_UNIT_UM * _DB_PER_USER)
                if px1 == px2 and py1 == py2:
                    continue
                buf += _path(1, 50, [(px1, py1), (px2, py2)])

        # Die boundary on layer 10
        dw = int(layout.die_w * _CELL_UNIT_UM * _DB_PER_USER)
        dh = int(layout.die_h * _CELL_UNIT_UM * _DB_PER_USER)
        buf += _boundary(10, 0, 0, dw, dh)

        buf += _record(_ENDSTR, b"")
        buf += _record(_ENDLIB, b"")

        output_path.write_bytes(bytes(buf))
        return output_path


def _record(record_type: int, data: bytes) -> bytes:
    length = 4 + len(data)
    if length % 2:
        data += b"\x00"
        length += 1
    return struct.pack(">HH", length, record_type) + data


def _pad_string(s: str) -> bytes:
    b = s.encode("ascii")[:32]
    if len(b) % 2:
        b += b"\x00"
    return b


def _boundary(layer: int, x0: int, y0: int, x1: int, y1: int) -> bytes:
    buf = b""
    buf += _record(_BOUNDARY, b"")
    buf += _record(_LAYER, struct.pack(">h", layer))
    buf += _record(_DATATYPE, struct.pack(">h", 0))
    pts = struct.pack(">iiiiiiiiiii",
                       x0, y0, x1, y0, x1, y1, x0, y1, x0, y0, 0)[:-4]
    xy_data = struct.pack(">10i", x0, y0, x1, y0, x1, y1, x0, y1, x0, y0)
    buf += _record(_XY, xy_data)
    buf += _record(_ENDEL, b"")
    return buf


def _path(
    layer: int, width_nm: int, pts: list[tuple[int, int]]
) -> bytes:
    buf = b""
    buf += _record(_PATH, b"")
    buf += _record(_LAYER, struct.pack(">h", layer))
    buf += _record(_DATATYPE, struct.pack(">h", 0))
    buf += _record(_PATHTYPE, struct.pack(">h", 1))
    buf += _record(_WIDTH, struct.pack(">i", width_nm))
    xy_data = b"".join(struct.pack(">ii", x, y) for x, y in pts)
    buf += _record(_XY, xy_data)
    buf += _record(_ENDEL, b"")
    return buf


def _text(layer: int, x: int, y: int, s: str) -> bytes:
    buf = b""
    buf += _record(_TEXT, b"")
    buf += _record(_LAYER, struct.pack(">h", layer))
    buf += _record(_TEXTTYPE, struct.pack(">h", 0))
    buf += _record(_PRESENTATION, struct.pack(">h", 0x0005))
    buf += _record(_XY, struct.pack(">ii", x, y))
    buf += _record(_STRING, _pad_string(s))
    buf += _record(_ENDEL, b"")
    return buf


def _gds_timestamp() -> bytes:
    t = time.localtime()
    return struct.pack(">6h", t.tm_year, t.tm_mon, t.tm_mday,
                        t.tm_hour, t.tm_min, t.tm_sec)
