"""Shared image upload validation used by chat messages and profile avatars."""

MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_AVATAR_SIZE = 2 * 1024 * 1024
MAX_IMAGE_DIMENSION = 8000
ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


def _validate_image(upload, max_size=None):
    """Return an error string if the uploaded file is not a usable image."""
    if max_size is None:
        max_size = MAX_IMAGE_SIZE
    if upload.size > max_size:
        return f"Image is too large. Maximum size is {max_size // (1024 * 1024)} MB."
    if upload.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        return "Only JPEG, PNG, WebP, and GIF images are allowed."
    try:
        from PIL import Image

        image = Image.open(upload)
        width, height = image.size
        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            return (
                "Image dimensions are too large. "
                f"Maximum is {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION}."
            )
        image.verify()
        if image.format not in ALLOWED_IMAGE_FORMATS:
            return "Only JPEG, PNG, WebP, and GIF images are allowed."
        upload.seek(0)
    except Exception:
        return "Uploaded file is not a valid image."
    return None


def _validate_avatar(upload):
    """Avatar uploads use a smaller size cap than chat images."""
    return _validate_image(upload, max_size=MAX_AVATAR_SIZE)
