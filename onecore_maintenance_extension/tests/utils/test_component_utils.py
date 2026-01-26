# -*- coding: utf-8 -*-
"""Tests for component utility functions (depreciation and image utils)."""

import base64
import unittest
from datetime import date
from unittest.mock import Mock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("onecore")
class TestDepreciation(TransactionCase):
    """Tests for compute_linear_depreciation utility function."""

    def test_depreciation_basic_calculation(self):
        """Standard linear depreciation calculation."""
        from odoo.addons.onecore_maintenance_extension.models.utils.depreciation import compute_linear_depreciation

        # 12000 SEK over 120 months (10 years), 60 months elapsed = 50% depreciated
        result = compute_linear_depreciation(
            purchase_price=12000,
            economic_lifespan_months=120,
            installation_date=date(2020, 1, 1),
            reference_date=date(2025, 1, 1)
        )
        self.assertEqual(result, 6000.0)

    def test_depreciation_no_purchase_price_returns_zero(self):
        """Returns 0 when purchase_price is None or 0."""
        from odoo.addons.onecore_maintenance_extension.models.utils.depreciation import compute_linear_depreciation

        result_none = compute_linear_depreciation(
            purchase_price=None,
            economic_lifespan_months=120,
            installation_date=date(2020, 1, 1),
            reference_date=date(2025, 1, 1)
        )
        self.assertEqual(result_none, 0.0)

        result_zero = compute_linear_depreciation(
            purchase_price=0,
            economic_lifespan_months=120,
            installation_date=date(2020, 1, 1),
            reference_date=date(2025, 1, 1)
        )
        self.assertEqual(result_zero, 0.0)

    def test_depreciation_no_lifespan_returns_price(self):
        """Returns full price when lifespan is 0 or negative."""
        from odoo.addons.onecore_maintenance_extension.models.utils.depreciation import compute_linear_depreciation

        result_zero = compute_linear_depreciation(
            purchase_price=10000,
            economic_lifespan_months=0,
            installation_date=date(2020, 1, 1),
            reference_date=date(2025, 1, 1)
        )
        self.assertEqual(result_zero, 10000)

        result_negative = compute_linear_depreciation(
            purchase_price=10000,
            economic_lifespan_months=-12,
            installation_date=date(2020, 1, 1),
            reference_date=date(2025, 1, 1)
        )
        self.assertEqual(result_negative, 10000)

    def test_depreciation_no_date_returns_price(self):
        """Returns full price when no installation date provided."""
        from odoo.addons.onecore_maintenance_extension.models.utils.depreciation import compute_linear_depreciation

        result = compute_linear_depreciation(
            purchase_price=10000,
            economic_lifespan_months=120,
            installation_date=None,
            reference_date=date(2025, 1, 1)
        )
        self.assertEqual(result, 10000)

    def test_depreciation_fully_depreciated_returns_zero(self):
        """Returns 0 when asset is fully depreciated (past lifespan)."""
        from odoo.addons.onecore_maintenance_extension.models.utils.depreciation import compute_linear_depreciation

        # 120 months lifespan, 150 months elapsed
        result = compute_linear_depreciation(
            purchase_price=12000,
            economic_lifespan_months=120,
            installation_date=date(2010, 1, 1),
            reference_date=date(2025, 1, 1)
        )
        self.assertEqual(result, 0.0)

    def test_depreciation_string_date_input(self):
        """Handles string date input (YYYY-MM-DD format)."""
        from odoo.addons.onecore_maintenance_extension.models.utils.depreciation import compute_linear_depreciation

        result = compute_linear_depreciation(
            purchase_price=12000,
            economic_lifespan_months=120,
            installation_date="2020-01-01",
            reference_date=date(2025, 1, 1)
        )
        self.assertEqual(result, 6000.0)

    def test_depreciation_custom_reference_date(self):
        """Uses provided reference_date when specified."""
        from odoo.addons.onecore_maintenance_extension.models.utils.depreciation import compute_linear_depreciation

        # 24 months elapsed = 20% depreciated
        result = compute_linear_depreciation(
            purchase_price=12000,
            economic_lifespan_months=120,
            installation_date=date(2020, 1, 1),
            reference_date=date(2022, 1, 1)
        )
        self.assertEqual(result, 9600.0)

    def test_depreciation_invalid_date_string(self):
        """Returns price for unparseable date strings."""
        from odoo.addons.onecore_maintenance_extension.models.utils.depreciation import compute_linear_depreciation

        result = compute_linear_depreciation(
            purchase_price=10000,
            economic_lifespan_months=120,
            installation_date="invalid-date",
            reference_date=date(2025, 1, 1)
        )
        self.assertEqual(result, 10000)


@tagged("onecore")
class TestImageUtils(TransactionCase):
    """Tests for image utility functions."""

    def test_detect_mime_type_jpeg(self):
        """Detects JPEG from magic bytes."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import detect_image_mime_type

        # JPEG magic bytes: FF D8 FF
        jpeg_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00'
        result = detect_image_mime_type(jpeg_bytes)
        self.assertEqual(result, 'image/jpeg')

    def test_detect_mime_type_png(self):
        """Detects PNG from magic bytes."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import detect_image_mime_type

        # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
        png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
        result = detect_image_mime_type(png_bytes)
        self.assertEqual(result, 'image/png')

    def test_detect_mime_type_gif(self):
        """Detects GIF format from magic bytes."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import detect_image_mime_type

        # GIF87a magic bytes
        gif87_bytes = b'GIF87a\x00\x00\x00\x00'
        result_87 = detect_image_mime_type(gif87_bytes)
        self.assertEqual(result_87, 'image/gif')

        # GIF89a magic bytes
        gif89_bytes = b'GIF89a\x00\x00\x00\x00'
        result_89 = detect_image_mime_type(gif89_bytes)
        self.assertEqual(result_89, 'image/gif')

    def test_detect_mime_type_webp(self):
        """Detects WebP format from magic bytes."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import detect_image_mime_type

        # WebP magic bytes: RIFF....WEBP
        webp_bytes = b'RIFF\x00\x00\x00\x00WEBP'
        result = detect_image_mime_type(webp_bytes)
        self.assertEqual(result, 'image/webp')

    def test_detect_mime_type_unknown_defaults_jpeg(self):
        """Falls back to jpeg for unknown format."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import detect_image_mime_type

        unknown_bytes = b'\x00\x00\x00\x00\x00\x00\x00\x00'
        result = detect_image_mime_type(unknown_bytes)
        self.assertEqual(result, 'image/jpeg')

    def test_detect_mime_type_base64_string(self):
        """Handles base64 string input for detection."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import detect_image_mime_type

        # JPEG magic bytes encoded in base64
        jpeg_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00'
        jpeg_base64 = base64.b64encode(jpeg_bytes).decode('utf-8')
        result = detect_image_mime_type(jpeg_base64)
        self.assertEqual(result, 'image/jpeg')

    def test_image_to_data_url_basic(self):
        """Creates valid data URL from image bytes."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import image_to_data_url

        # Simple test with small image-like data
        test_data = b'\xff\xd8\xff\xe0test_image_data'
        test_base64 = base64.b64encode(test_data).decode('utf-8')

        # Use compress=False to avoid PIL dependency in test
        result = image_to_data_url(test_base64, compress=False)

        self.assertIsNotNone(result)
        self.assertTrue(result.startswith('data:image/'))
        self.assertIn(';base64,', result)

    def test_image_to_data_url_none_returns_none(self):
        """Returns None for None input."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import image_to_data_url

        result = image_to_data_url(None)
        self.assertIsNone(result)

    def test_image_to_data_url_empty_returns_none(self):
        """Returns None for empty input."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import image_to_data_url

        result = image_to_data_url(b'')
        self.assertIsNone(result)

        result_str = image_to_data_url('')
        self.assertIsNone(result_str)

    def test_image_to_data_url_handles_bytes(self):
        """Accepts raw bytes input."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import image_to_data_url

        # Raw bytes (not base64)
        raw_bytes = b'\xff\xd8\xff\xe0raw_image_bytes'

        result = image_to_data_url(raw_bytes, compress=False)

        self.assertIsNotNone(result)
        self.assertTrue(result.startswith('data:image/jpeg;base64,'))

    def test_image_to_data_url_handles_base64_string(self):
        """Accepts base64 string input."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import image_to_data_url

        test_data = b'\xff\xd8\xff\xe0test_data'
        base64_string = base64.b64encode(test_data).decode('utf-8')

        result = image_to_data_url(base64_string, compress=False)

        self.assertIsNotNone(result)
        self.assertTrue(result.startswith('data:image/jpeg;base64,'))

    def test_image_to_data_url_mime_override(self):
        """Uses provided mime_type when specified."""
        from odoo.addons.onecore_maintenance_extension.models.utils.image_utils import image_to_data_url

        test_data = b'test_data'
        base64_string = base64.b64encode(test_data).decode('utf-8')

        result = image_to_data_url(
            base64_string,
            mime_type='image/png',
            compress=False
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.startswith('data:image/png;base64,'))

    def test_compress_image_no_pil(self):
        """Returns original when PIL is unavailable."""
        from odoo.addons.onecore_maintenance_extension.models.utils import image_utils

        # Temporarily disable PIL
        original_has_pil = image_utils.HAS_PIL
        image_utils.HAS_PIL = False

        try:
            test_data = b'\xff\xd8\xff\xe0test'
            base64_string = base64.b64encode(test_data).decode('utf-8')

            result, mime = image_utils.compress_image(base64_string)

            self.assertEqual(result, base64_string)
            self.assertEqual(mime, 'image/jpeg')
        finally:
            image_utils.HAS_PIL = original_has_pil
