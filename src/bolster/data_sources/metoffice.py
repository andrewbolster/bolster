"""
This script fetches weather data from the Met Office API, processes it, and generates an image suitable for epaper display, and might be useful for other
applications as well. It uses the Pillow library for image processing and the requests library for API calls.

See [here](https://datahub.metoffice.gov.uk/docs/f/category/map-images/type/map-images/api-documentation) for more information on the API.

"""
import os
import re
from datetime import datetime
from datetime import timedelta
from functools import lru_cache
from io import BytesIO
from itertools import groupby

import requests
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFilter

# assert os.getenv('MET_OFFICE_API_KEY') is not None, "MET_OFFICE_API_KEY not set in .env file"
# assert os.getenv('MAP_IMAGES_ORDER_NAME') is not None, "MAP_IMAGES_ORDER_NAME not set in .env file"

BASE_URL = "https://data.hub.api.metoffice.gov.uk/map-images/1.0.0"

### API Client Functions

session = requests.Session()
session.headers.update(
    {"Accept": "application/json", "apikey": f"{os.getenv('MET_OFFICE_API_KEY')}"}
)


def get_order_latest(order_name):
    url = f"{BASE_URL}/orders/{order_name.lower()}/latest"
    response = session.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(
            f"Failed to fetch order status: {response.status_code} {response.text}"
        )


def get_file_meta(order_name, file_id):
    url = f"{BASE_URL}/orders/{order_name.lower()}/latest/{requests.utils.quote(file_id)}"  # To handle + in the file_id
    response = session.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(
            f"Failed to fetch order status: {response.status_code} {response.text}"
        )


@lru_cache
def get_file(order_name, file_id):
    url = f"{BASE_URL}/orders/{order_name.lower()}/latest/{requests.utils.quote(file_id)}/data"  # To handle + in the file_id
    response = session.get(
        url, headers={**session.headers, **{"Accept": "application/octet-stream"}}
    )
    if response.status_code == 200:
        return response.content
    else:
        raise Exception(
            f"Failed to fetch order status: {response.status_code} {response.text}"
        )


### Data Filtering

is_my_date = re.compile(r".*_\d{10}$")  # Ends with 10 digits


def filter_relevant_files(order_status):
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


def make_borders(data):
    # Convert to grayscale
    img = Image.open(BytesIO(data))
    img = img.point(lambda i: 255 if i else 0)
    # Convert to binary image
    img = img.convert("1")
    # Apply edge detection filter
    img = img.filter(ImageFilter.FIND_EDGES)
    img.info["transparency"] = 0

    return img


def make_isolines(data):
    # Convert to grayscale
    img = Image.open(BytesIO(data)).convert("L")
    # Apply edge detection filter
    img = img.filter(ImageFilter.FIND_EDGES)
    # Convert to binary image
    img = img.convert("1")
    img.info["transparency"] = 0

    return img


def make_precipitation(data):
    # Convert to grayscale
    img = Image.open(BytesIO(data)).convert("L")
    img = img.point(lambda i: 255 - i)
    img.info["transparency"] = 0

    return img


def generate_image(order_name, block, bounding_box=(100, 250, 500, 550)):
    border = make_borders(get_file(order_name, block["land_cover"]))
    isoline = make_isolines(get_file(order_name, block["mean_sea_level_pressure"]))
    precipitation = make_precipitation(
        get_file(order_name, block["total_precipitation_rate"])
    )

    background = Image.blend(
        isoline.convert("RGBA"), border.convert("RGBA"), alpha=0.5
    ).convert("L")
    background.info["transparency"] = 0

    img = Image.blend(
        background.convert("RGBA"), precipitation.convert("RGBA"), alpha=0.5
    )

    if bounding_box:
        img = img.crop(bounding_box)

    img = img.convert("1")

    draw = ImageDraw.Draw(img)
    draw.text((5, 5), block["date"].isoformat(), fill="white")

    return img


def get_uk_precipitation(order_name, bounding_box=None):
    """
    Get the latest UK precipitation forecast from the Met Office API and generate an image suitable for epaper display.
    """
    order_status = get_order_latest(order_name)
    relevant_files = filter_relevant_files(order_status)

    ## Project the relevant files into forecast blocks keyed by the forecasted date
    forecast_blocks = {
        dt: {blk["parameter_name"]: blk["fileId"] for blk in block}
        for dt, block in groupby(relevant_files, key=lambda x: x["date"])
    }

    ## Get the forecast block with the key closest to the current datetime
    closest_block = min(forecast_blocks.keys(), key=lambda x: abs(x - datetime.now()))
    block = forecast_blocks[closest_block]
    block["date"] = closest_block

    image = generate_image(order_name, block, bounding_box=bounding_box)

    return image
