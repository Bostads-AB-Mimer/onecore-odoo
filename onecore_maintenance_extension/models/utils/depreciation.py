# -*- coding: utf-8 -*-
"""Utility functions for depreciation calculations."""

from datetime import date

from dateutil.relativedelta import relativedelta


def compute_linear_depreciation(
    purchase_price,
    economic_lifespan_months,
    installation_date,
    reference_date=None
):
    """Calculate current value using linear depreciation.

    Depreciation is calculated as:
        monthly_depreciation = purchase_price / economic_lifespan_months
        total_depreciation = monthly_depreciation * months_since_installation
        current_value = max(0, purchase_price - total_depreciation)

    Args:
        purchase_price: The original purchase price of the asset
        economic_lifespan_months: The expected lifespan in months
        installation_date: The date when the asset was installed
        reference_date: The date to calculate value for (defaults to today)

    Returns:
        The current depreciated value, never less than 0
    """
    if not purchase_price:
        return 0.0

    if not economic_lifespan_months or economic_lifespan_months <= 0:
        return purchase_price

    if not installation_date:
        return purchase_price

    # Handle string dates (YYYY-MM-DD format)
    if isinstance(installation_date, str):
        try:
            installation_date = date.fromisoformat(installation_date[:10])
        except (ValueError, TypeError):
            return purchase_price

    if reference_date is None:
        reference_date = date.today()

    # Calculate months since installation
    delta = relativedelta(reference_date, installation_date)
    months_since = delta.years * 12 + delta.months

    # Calculate depreciation
    monthly_depreciation = purchase_price / economic_lifespan_months
    total_depreciation = monthly_depreciation * months_since

    return max(0.0, purchase_price - total_depreciation)
