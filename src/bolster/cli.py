"""Console script for bolster."""

import os
import sys

import click

from . import __version__
from .data_sources.metoffice import get_uk_precipitation


@click.group()
@click.version_option(version=__version__, prog_name='bolster')
def cli(args=None):
    """
    Bolster - A comprehensive Python utility library for data science and automation.

    Provides tools for data processing, web scraping, cloud services, and access to
    Northern Ireland and UK data sources. Use --help with any command for detailed usage.

    Examples:
        bolster get-precipitation --help    # Show precipitation command options
        bolster --version                   # Show version information
    """
    pass


@cli.command()
@click.option(
    "--bounding-box",
    default=None,
    help="Geographic bounding box as 'min_lon,min_lat,max_lon,max_lat' (e.g., '-10.0,49.0,2.0,61.0' for UK)",
)
@click.option(
    "--order-name",
    default=os.getenv("MAP_IMAGES_ORDER_NAME"),
    help="Met Office API order name for precipitation data (or set MAP_IMAGES_ORDER_NAME env var)",
)
@click.option(
    "--output",
    default="precipitation.png",
    help="Output filename for the precipitation map image (default: precipitation.png)",
)
def get_precipitation(bounding_box, order_name, output):
    """
    Download UK precipitation data from the Met Office and save as an image.

    This command retrieves precipitation map data from the UK Met Office API and saves
    it as a PNG image. Requires a Met Office API key and valid order name.

    Environment Variables:
        MET_OFFICE_API_KEY: Your Met Office API key (required)
        MAP_IMAGES_ORDER_NAME: Default order name for precipitation data (optional)

    Examples:
        # Download precipitation map for entire UK
        bolster get-precipitation --order-name "your-order-name"

        # Download for specific region (Northern Ireland)
        bolster get-precipitation --bounding-box "-8.5,54.0,-5.0,55.5" --order-name "your-order-name"

        # Save to custom filename
        bolster get-precipitation --output "ni_rain.png" --order-name "your-order-name"
    """
    assert os.getenv("MET_OFFICE_API_KEY") is not None, "MET_OFFICE_API_KEY not set in environment"
    if bounding_box is not None:
        try:
            min_lon, min_lat, max_lon, max_lat = map(float, bounding_box.split(","))
            bounding_box = (min_lon, min_lat, max_lon, max_lat)
            click.echo(f"Bounding box: {bounding_box}")
        except ValueError:
            click.echo("Invalid bounding box format. Use min_lon,min_lat,max_lon,max_lat.")

    if order_name is None:
        order_name = os.getenv("MAP_IMAGES_ORDER_NAME")
        if order_name is None:
            click.echo("Order name not provided and MAP_IMAGES_ORDER_NAME not set in environment.")
            return

    img = get_uk_precipitation(order_name=order_name, bounding_box=bounding_box)
    img.save(output)
    click.echo(f"Precipitation image saved as '{output}'")


if __name__ == "__main__":
    sys.exit(cli())  # pragma: no cover
