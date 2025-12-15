bolster.data_sources.cineworld
==============================

.. py:module:: bolster.data_sources.cineworld

.. autoapi-nested-parse::

   This module provides functions to retrieve cinema listings from the Cineworld API.

   The main function in this module is `get_cinema_listings`, which takes a site code and a screening date as input and returns a dictionary containing the cinema listings for that date.

   Site Code 117 maps to Belfast, you're on your own for the rest.

   Example usage:
       cinema_listings = get_cinema_listings(117)
       list(cinema_listings[0].keys())
       # Output: ['id', 'name', 'length', 'posterLink', 'videoLink', 'link', 'weight', 'releaseYear', 'attributeIds', 'date', 'site_code']



Functions
---------

.. autoapisummary::

   bolster.data_sources.cineworld.get_cinema_listings


Module Contents
---------------

.. py:function:: get_cinema_listings(site_code = 117, screening_date = date.today())

   Get cinema listings from the Cineworld API.

   :param site_code: The site code of the cinema. Defaults to 117; Belfast
   :type site_code: int
   :param screening_date: The date for which to retrieve the listings. Defaults to today's date.
   :type screening_date: date

   :returns: A dictionary containing the cinema listings.
   :rtype: dict

   :raises requests.exceptions.RequestException: If there was an error making the API request.

   >>> cinema_listings = get_cinema_listings(117)
   >>> set(cinema_listings[0].keys()).issuperset({'id', 'name','link','weight','releaseYear','releaseDate','attributeIds','date','site_code'})
   True
   >>> list(cinema_listings[0].keys()) # This is likely to break from upstream changes
   ['id', 'name', 'length', 'posterLink', 'videoLink', 'link', 'weight', 'releaseYear', 'releaseDate', 'attributeIds', 'date', 'site_code']
