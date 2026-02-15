"""UK Met Office Weather Data and Map Images Integration.

Data Source: The UK Met Office provides weather data and map images through their DataHub API
at https://data.hub.api.metoffice.gov.uk/. This module accesses weather forecast data including
precipitation, temperature, pressure, and land cover information. The API provides high-resolution
weather map images suitable for visualization and analysis applications.

Update Frequency: Weather forecast data is updated multiple times daily, typically every 3-6 hours
depending on the forecast model. Map images are generated continuously as new forecast data becomes
available. Historical data snapshots are preserved for analysis and comparison purposes.

Example:
    Generate weather images and access forecast data:

        >>> import os
        >>> # Set required API key (requires Met Office DataHub account)
        >>> os.environ['MET_OFFICE_API_KEY'] = 'your-api-key'
        >>> os.environ['MAP_IMAGES_ORDER_NAME'] = 'your-order-name'

        >>> from bolster.data_sources import metoffice
        >>> # Get UK precipitation forecast image
        >>> image = metoffice.get_uk_precipitation('your-order')
        >>> image.save('uk_precipitation_forecast.png')

        >>> # Access weather data validation
        >>> weather_data = {'date': '2024-01-01', 'blocks': [...]}
        >>> is_valid = metoffice.validate_weather_data(weather_data)
        >>> print(f"Weather data valid: {is_valid}")

This module provides utilities for fetching weather data from the Met Office API, processing
forecast information, and generating visualization-ready weather map images.

See the Met Office DataHub documentation for API details:
https://datahub.metoffice.gov.uk/docs/f/category/map-images/type/map-images/api-documentation
"""

import logging
import os
import re
from datetime import datetime, timedelta
from functools import lru_cache
from io import BytesIO
from itertools import groupby
from typing import Optional
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFilter

from bolster import NetworkError
from bolster.utils.web import session

logger = logging.getLogger(__name__)

# assert os.getenv('MET_OFFICE_API_KEY') is not None, "MET_OFFICE_API_KEY not set in .env file"
# assert os.getenv('MAP_IMAGES_ORDER_NAME') is not None, "MAP_IMAGES_ORDER_NAME not set in .env file"

BASE_URL = "https://data.hub.api.metoffice.gov.uk/map-images/1.0.0"

### API Client Functions

# Configure API key for Met Office requests
_api_headers = {"Accept": "application/json", "apikey": f"{os.getenv('MET_OFFICE_API_KEY')}"}


def get_order_latest(order_name: str) -> dict:
    """Get the latest status for a Met Office data order."""
    url = f"{BASE_URL}/orders/{order_name.lower()}/latest"  # pragma: no cover
    # TODO: Network integration testing - requires valid Met Office API key and order
    response = session.get(url, headers=_api_headers)  # pragma: no cover
    if response.status_code == 200:  # pragma: no cover
        return response.json()  # pragma: no cover
    # pragma: no cover
    raise NetworkError(
        f"Failed to fetch order status: {response.text}", status_code=response.status_code, url=url
    )  # pragma: no cover


def get_file_meta(order_name: str, file_id: str) -> dict:
    """Get metadata for a specific file in a Met Office order."""
    url = f"{BASE_URL}/orders/{order_name.lower()}/latest/{quote(file_id)}"  # To handle + in the file_id  # pragma: no cover
    # TODO: Network integration testing - requires valid Met Office API key and order
    response = session.get(url, headers=_api_headers)  # pragma: no cover
    if response.status_code == 200:  # pragma: no cover
        return response.json()  # pragma: no cover
    # pragma: no cover
    raise NetworkError(
        f"Failed to fetch order status: {response.text}", status_code=response.status_code, url=url
    )  # pragma: no cover


@lru_cache
def get_file(order_name: str, file_id: str) -> bytes:
    """Download and cache a file from a Met Office order."""
    url = f"{BASE_URL}/orders/{order_name.lower()}/latest/{quote(file_id)}/data"  # To handle + in the file_id  # pragma: no cover
    # TODO: Network integration testing - requires valid Met Office API key and order
    response = session.get(url, headers={**_api_headers, **{"Accept": "application/octet-stream"}})  # pragma: no cover
    if response.status_code == 200:  # pragma: no cover
        return response.content  # pragma: no cover
    # pragma: no cover
    raise NetworkError(
        f"Failed to fetch order status: {response.text}", status_code=response.status_code, url=url
    )  # pragma: no cover


### Data Filtering

is_my_date = re.compile(r".*_\d{10}$")  # Ends with 10 digits


def filter_relevant_files(order_status: dict) -> list[dict]:
    """Filter order files to find UK precipitation radar data."""
    relevant_files = []

    for file in order_status["orderDetails"]["files"]:
        if is_my_date.match(file["fileId"]):
            # print(file['fileId'])
            *parameter_name, time_step, forecast_date = file["fileId"].split("_")

            parameter_name = "_".join(parameter_name)

            time_delta = int(time_step[2:])  # hours
            forecast_year = forecast_date[:4]
            forecast_month = forecast_date[4:6]
            forecast_day = forecast_date[6:8]
            forecast_hour = forecast_date[8:10]
            date = datetime(
                int(forecast_year),
                int(forecast_month),
                int(forecast_day),
                int(forecast_hour),
            )
            date += timedelta(hours=time_delta)

            relevant_files.append(
                {
                    "fileId": file["fileId"],
                    "parameter_name": parameter_name,
                    "date": date,
                    "delta": time_delta,
                }
            )

    # Sort the relevant files by date and delta, so we get the 'freshest' forecast first for a given time
    relevant_files.sort(key=lambda x: (x["date"], x["delta"]))

    return relevant_files


### Image Generation


def make_borders(data: bytes) -> Image.Image:
    """Create image borders from Met Office geographic data."""
    # Convert to grayscale
    img = Image.open(BytesIO(data))
    img = img.point(lambda i: 255 if i else 0)
    # Convert to binary image
    img = img.convert("1")
    # Apply edge detection filter
    img = img.filter(ImageFilter.FIND_EDGES)
    img.info["transparency"] = 0

    return img


def make_isolines(data: bytes) -> Image.Image:
    """Create weather isolines from Met Office data."""
    # Convert to grayscale
    img = Image.open(BytesIO(data)).convert("L")
    # Apply edge detection filter
    img = img.filter(ImageFilter.FIND_EDGES)
    # Convert to binary image
    img = img.convert("1")
    img.info["transparency"] = 0

    return img


def make_precipitation(data: bytes) -> Image.Image:
    """Process precipitation radar data into visualization image."""
    # Convert to grayscale
    img = Image.open(BytesIO(data)).convert("L")
    img = img.point(lambda i: 255 - i)
    img.info["transparency"] = 0

    return img


def generate_image(
    order_name: str, block: dict, bounding_box: Optional[tuple[int, int, int, int]] = (100, 250, 500, 550)
) -> Image.Image:
    """Generate composite weather visualization from Met Office data."""
    # TODO: Network integration testing - requires valid Met Office API key and order
    border = make_borders(get_file(order_name, block["land_cover"]))  # pragma: no cover
    isoline = make_isolines(get_file(order_name, block["mean_sea_level_pressure"]))  # pragma: no cover
    precipitation = make_precipitation(get_file(order_name, block["total_precipitation_rate"]))  # pragma: no cover

    background = Image.blend(isoline.convert("RGBA"), border.convert("RGBA"), alpha=0.5).convert(
        "L"
    )  # pragma: no cover
    background.info["transparency"] = 0  # pragma: no cover

    img = Image.blend(background.convert("RGBA"), precipitation.convert("RGBA"), alpha=0.5)  # pragma: no cover

    if bounding_box:  # pragma: no cover
        img = img.crop(bounding_box)  # pragma: no cover

    img = img.convert("1")  # pragma: no cover

    draw = ImageDraw.Draw(img)  # pragma: no cover
    draw.text((5, 5), block["date"].isoformat(), fill="white")  # pragma: no cover

    return img  # pragma: no cover


def get_uk_precipitation(order_name: str, bounding_box: Optional[tuple[int, int, int, int]] = None) -> Image.Image:
    """Get the latest UK precipitation forecast from the Met Office API and generate an image suitable for epaper display."""
    # TODO: Network integration testing - requires valid Met Office API key and order
    order_status = get_order_latest(order_name)  # pragma: no cover
    relevant_files = filter_relevant_files(order_status)  # pragma: no cover

    ## Project the relevant files into forecast blocks keyed by the forecasted date  # pragma: no cover
    forecast_blocks = {  # pragma: no cover
        dt: {blk["parameter_name"]: blk["fileId"] for blk in block}  # pragma: no cover
        for dt, block in groupby(relevant_files, key=lambda x: x["date"])  # pragma: no cover
    }  # pragma: no cover

    ## Get the forecast block with the key closest to the current datetime  # pragma: no cover
    closest_block = min(forecast_blocks.keys(), key=lambda x: abs(x - datetime.now()))  # pragma: no cover
    block = forecast_blocks[closest_block]  # pragma: no cover
    block["date"] = closest_block  # pragma: no cover

    return generate_image(order_name, block, bounding_box=bounding_box)  # pragma: no cover
