# -*- coding: utf-8 -*-
"""Image processing utilities for component wizard.

Provides functions for compressing, detecting MIME types, and converting
images to data URL format for API calls.
"""
import base64
import io
import logging

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Max image dimension (width or height) for AI analysis
MAX_IMAGE_DIMENSION = 1920
# JPEG quality for compressed images
JPEG_QUALITY = 85

_logger = logging.getLogger(__name__)


def detect_image_mime_type(image_data):
    """Detect MIME type from image magic bytes.

    Args:
        image_data: Either base64 string or raw bytes

    Returns:
        str: MIME type string (e.g., 'image/jpeg', 'image/png')
    """
    # If it's a base64 string, decode first few bytes for detection
    if isinstance(image_data, str):
        try:
            header_bytes = base64.b64decode(image_data[:32])
        except Exception:
            return 'image/jpeg'
    else:
        header_bytes = image_data[:16] if len(image_data) >= 16 else image_data

    # Check magic bytes for common image formats
    if header_bytes[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    elif header_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    elif header_bytes[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    elif header_bytes[:4] == b'RIFF' and len(header_bytes) >= 12 and header_bytes[8:12] == b'WEBP':
        return 'image/webp'
    return 'image/jpeg'  # fallback


def compress_image(image_base64, logger=None):
    """Compress and resize image if too large.

    Resizes images to max MAX_IMAGE_DIMENSION pixels on longest side
    and compresses as JPEG with JPEG_QUALITY quality.

    Args:
        image_base64: Base64-encoded image string
        logger: Optional logger instance for debug output

    Returns:
        tuple: (compressed_base64_string, mime_type)
    """
    log = logger or _logger

    if not HAS_PIL:
        log.warning("PIL not available, skipping image compression")
        return image_base64, detect_image_mime_type(image_base64)

    try:
        # Decode base64 to bytes
        image_bytes = base64.b64decode(image_base64)

        # Open image with PIL
        img = Image.open(io.BytesIO(image_bytes))

        # Get original dimensions
        original_width, original_height = img.size
        log.info(f"Original image size: {original_width}x{original_height}")

        # Check if resizing is needed
        if original_width <= MAX_IMAGE_DIMENSION and original_height <= MAX_IMAGE_DIMENSION:
            # Image is small enough, check if it's already JPEG
            if img.format == 'JPEG':
                log.info("Image already small enough and JPEG, no compression needed")
                return image_base64, 'image/jpeg'

        # Calculate new dimensions maintaining aspect ratio
        if original_width > original_height:
            if original_width > MAX_IMAGE_DIMENSION:
                new_width = MAX_IMAGE_DIMENSION
                new_height = int(original_height * (MAX_IMAGE_DIMENSION / original_width))
            else:
                new_width, new_height = original_width, original_height
        else:
            if original_height > MAX_IMAGE_DIMENSION:
                new_height = MAX_IMAGE_DIMENSION
                new_width = int(original_width * (MAX_IMAGE_DIMENSION / original_height))
            else:
                new_width, new_height = original_width, original_height

        # Resize if dimensions changed
        if (new_width, new_height) != (original_width, original_height):
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            log.info(f"Resized image to: {new_width}x{new_height}")

        # Convert to RGB if necessary (for JPEG compatibility)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # Save as JPEG to buffer
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
        compressed_bytes = buffer.getvalue()

        # Encode back to base64
        compressed_base64 = base64.b64encode(compressed_bytes).decode('utf-8')

        original_size = len(image_base64)
        compressed_size = len(compressed_base64)
        log.info(f"Image compressed: {original_size} -> {compressed_size} bytes ({100 * compressed_size / original_size:.1f}%)")

        return compressed_base64, 'image/jpeg'

    except Exception as e:
        log.warning(f"Image compression failed, using original: {e}")
        return image_base64, detect_image_mime_type(image_base64)


def image_to_data_url(image_binary, mime_type=None, compress=True, logger=None):
    """Convert image to data URL format.

    Handles both:
    - Already base64-encoded strings (from Odoo Binary fields)
    - Raw binary data

    Args:
        image_binary: Image data (base64 string or bytes)
        mime_type: Optional MIME type override. If None, auto-detected.
        compress: If True, compress large images before creating data URL.
        logger: Optional logger instance for debug output

    Returns:
        str: Data URL in format "data:<mime_type>;base64,<data>"
    """
    log = logger or _logger

    if not image_binary:
        return None

    # Odoo Binary fields return base64 as string or bytes
    if isinstance(image_binary, str):
        base64_string = image_binary
    elif isinstance(image_binary, bytes):
        try:
            # Check if already base64 (ASCII-decodable)
            decoded_str = image_binary.decode('ascii')
            base64.b64decode(decoded_str)  # Validate it's valid base64
            base64_string = decoded_str
        except (UnicodeDecodeError, ValueError):
            # It's raw binary data, encode it
            base64_string = base64.b64encode(image_binary).decode('utf-8')
    else:
        log.warning(f"Unexpected image_binary type: {type(image_binary)}")
        return None

    # Compress image if requested (for API calls)
    if compress:
        base64_string, mime_type = compress_image(base64_string, logger=log)
    elif mime_type is None:
        # Auto-detect MIME type if not provided and not compressing
        mime_type = detect_image_mime_type(base64_string)

    return f"data:{mime_type};base64,{base64_string}"
