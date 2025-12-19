"""
This module provides functions to retrieve cinema listings from the Cineworld API.

The main function in this module is `get_cinema_listings`, which takes a site code and a screening date as input and returns a dictionary containing the cinema listings for that date.

Site Code 117 maps to Belfast, you're on your own for the rest.

Example usage:
    cinema_listings = get_cinema_listings(117)
    list(cinema_listings[0].keys())
    # Output: ['id', 'name', 'length', 'posterLink', 'videoLink', 'link', 'weight', 'releaseYear', 'attributeIds', 'date', 'site_code']

"""

from datetime import date
from typing import Any, Dict, List

import requests

from ..utils.web import session


def get_cinema_listings(site_code: int = 117, screening_date: date = date.today()) -> List[Dict[str, Any]]:
    """
    Get cinema listings from the Cineworld API.

    Args:
        site_code (int): The site code of the cinema. Defaults to 117; Belfast
        screening_date (date): The date for which to retrieve the listings. Defaults to today's date.

    Returns:
        dict: A dictionary containing the cinema listings.

    Raises:
        requests.exceptions.RequestException: If there was an error making the API request.

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
    except requests.exceptions.RequestException as e:
        raise e
