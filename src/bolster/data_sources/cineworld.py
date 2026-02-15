"""Cineworld Cinema Listings Data Integration.

This module provides access to current cinema listings and film showtimes from Cineworld cinemas
across the UK through their public API. The data includes film information, screening times,
and cinema-specific details for planning cinema visits and entertainment analysis.

Data Source: Cineworld provides cinema listings through their public data API service at
https://www.cineworld.co.uk/uk/data-api-service/. The API delivers real-time information about
current films, screening times, and availability across all Cineworld cinema locations in the UK.
The service provides structured JSON data suitable for automated processing and integration.

Update Frequency: Cinema listings are updated continuously throughout the day as new showtimes
are scheduled and availability changes. The data reflects real-time cinema schedules with
immediate updates for booking availability, screening times, and new film releases.
Data is refreshed multiple times daily to maintain accuracy for current and upcoming showings.

Example:
    Retrieve current cinema listings for Belfast Cineworld:

        >>> from bolster.data_sources import cineworld
        >>> # Get today's listings for Belfast cinema (site code 117)
        >>> listings = cineworld.get_cinema_listings(117)
        >>> print(f"Found {len(listings)} films showing today")

        >>> # Check what data is available for each film
        >>> first_film = listings[0]
        >>> print(f"Film: {first_film['name']}")
        >>> print(f"Release Year: {first_film['releaseYear']}")

        >>> # Get listings for a specific date
        >>> from datetime import date, timedelta
        >>> tomorrow = date.today() + timedelta(days=1)
        >>> tomorrow_listings = cineworld.get_cinema_listings(117, tomorrow)

Site Code 117 maps to Belfast, you're on your own for the rest.
"""

import logging
from datetime import date
from typing import Any

from bolster.utils.web import session

logger = logging.getLogger(__name__)


def get_cinema_listings(site_code: int = 117, screening_date: date = None) -> list[dict[str, Any]]:
    """Get cinema listings from the Cineworld API.

    Args:
        site_code (int): The site code of the cinema. Defaults to 117; Belfast
        screening_date (date): The date for which to retrieve the listings. Defaults to today's date.

    Returns:
        dict: A dictionary containing the cinema listings.

    Raises:
        Exception: If there was an error making the API request.

    >>> cinema_listings = get_cinema_listings(117)
    >>> set(cinema_listings[0].keys()).issuperset({'id', 'name','link','weight','releaseYear','releaseDate','attributeIds','date','site_code'})
    True
    >>> list(cinema_listings[0].keys()) # This is likely to break from upstream changes
    ['id', 'name', 'length', 'posterLink', 'videoLink', 'link', 'weight', 'releaseYear', 'releaseDate', 'attributeIds', 'date', 'site_code']

    """
    if screening_date is None:
        screening_date = date.today()

    if not isinstance(screening_date, date):
        try:
            screening_date = date.fromisoformat(screening_date)
        except ValueError as e:
            raise ValueError("screening_date must be a date object or a string in the format 'YYYY-MM-DD'") from e

    url = f"https://www.cineworld.co.uk/uk/data-api-service/v1/quickbook/10108/film-events/in-cinema/{site_code}/at-date/{screening_date}"

    try:
        response = session.get(url)
        response.raise_for_status()
        listings = response.json()["body"]["films"]
        for list in listings:
            list["date"] = screening_date
            list["site_code"] = site_code
        return listings
    except Exception as e:
        raise e
