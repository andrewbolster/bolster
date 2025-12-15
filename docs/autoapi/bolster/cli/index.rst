bolster.cli
===========

.. py:module:: bolster.cli

.. autoapi-nested-parse::

   Console script for bolster.



Functions
---------

.. autoapisummary::

   bolster.cli.cli
   bolster.cli.get_precipitation
   bolster.cli.water_quality
   bolster.cli.ni_executive
   bolster.cli.cinema_listings
   bolster.cli.ni_house_prices


Module Contents
---------------

.. py:function:: cli(args=None)

   Bolster - A comprehensive Python utility library for data science and automation.

   Provides tools for data processing, web scraping, cloud services, and access to
   Northern Ireland and UK data sources. Use --help with any command for detailed usage.

   Available Commands:
       get-precipitation    # UK precipitation maps from Met Office
       water-quality        # NI water quality by postcode/zone
       ni-executive         # NI Executive historical data
       cinema-listings      # Cineworld movie showtimes
       ni-house-prices      # NI house price index data

   .. rubric:: Examples

   bolster water-quality BT1 5GS       # Water quality for postcode
   bolster ni-executive                 # NI Executive history
   bolster get-precipitation --help     # Show precipitation options
   bolster --version                    # Show version information


.. py:function:: get_precipitation(bounding_box, order_name, output)

   Download UK precipitation data from the Met Office and save as an image.

   This command retrieves precipitation map data from the UK Met Office API and saves
   it as a PNG image. Requires a Met Office API key and valid order name.

   Environment Variables:
       MET_OFFICE_API_KEY: Your Met Office API key (required)
       MAP_IMAGES_ORDER_NAME: Default order name for precipitation data (optional)

   .. rubric:: Examples

   # Download precipitation map for entire UK
   bolster get-precipitation --order-name "your-order-name"

   # Download for specific region (Northern Ireland)
   bolster get-precipitation --bounding-box "-8.5,54.0,-5.0,55.5" --order-name "your-order-name"

   # Save to custom filename
   bolster get-precipitation --output "ni_rain.png" --order-name "your-order-name"


.. py:function:: water_quality(postcode, zone_code, output_format)

   Get water quality information for a Northern Ireland postcode or zone.

   Provides water quality data including hardness classification, chemical parameters,
   and compliance information from Northern Ireland Water.

   .. rubric:: Examples

   bolster water-quality BT1 5GS     # Lookup by postcode
   bolster water-quality --zone-code BALM  # Lookup by zone code
   bolster water-quality BT7 --format json  # JSON output


.. py:function:: ni_executive(output_format, save)

   Get Northern Ireland Executive composition and dissolution data.

   Retrieves historical data about NI Executive periods including establishment
   dates, dissolution dates, duration, and interregnum periods.

   .. rubric:: Examples

   bolster ni-executive                    # Display as table
   bolster ni-executive --format json     # JSON output
   bolster ni-executive --save executive.csv  # Save to CSV file


.. py:function:: cinema_listings(site_code, screening_date, output_format)

   Get current movie listings from Cineworld cinema.

   Retrieves movie showtimes and information for a specific Cineworld location.
   Default location is Belfast (site code 117).

   .. rubric:: Examples

   bolster cinema-listings                     # Belfast, today
   bolster cinema-listings --site-code 105    # Different location
   bolster cinema-listings --date 2024-03-20  # Specific date


.. py:function:: ni_house_prices(output_format, save)

   Get Northern Ireland house price index data.

   Downloads and processes the latest NI house price statistics from official sources,
   including price trends by property type, region, and time period.

   .. rubric:: Examples

   bolster ni-house-prices                     # Display as CSV
   bolster ni-house-prices --format json      # JSON output
   bolster ni-house-prices --save prices.csv  # Save to file


