import io
import struct
import zlib

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image


def image_file(name="pic.png", fmt="PNG", content_type="image/png", data=None):
    """Build a small in-memory PNG upload to test image messages."""
    if data is None:
        buf = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(buf, format=fmt)
        data = buf.getvalue()
    return SimpleUploadedFile(name, data, content_type=content_type)


def huge_dimension_png():
    """A structurally valid PNG whose header claims 9000x9000 pixels (above the
    8000px cap but under Pillow's decompression-bomb threshold)."""
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="PNG")
    data = bytearray(buf.getvalue())
    # PNG: 0-7 signature, 8-11 length, 12-15 "IHDR", 16-19 width, 20-23 height,
    # 24-28 rest of IHDR data, 29-32 CRC over bytes 12-28.
    data[16:24] = struct.pack(">II", 9000, 9000)
    data[29:33] = struct.pack(">I", zlib.crc32(bytes(data[12:29])) & 0xFFFFFFFF)
    return SimpleUploadedFile("huge.png", bytes(data), content_type="image/png")
