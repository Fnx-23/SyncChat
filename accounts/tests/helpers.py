import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image


def avatar_file(name="avatar.png", content_type="image/png"):
    """A small in-memory PNG upload for avatar form tests."""
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type=content_type)
