"""Console script for bolster."""

import os
import sys

import click

from .data_sources.metoffice import get_uk_precipitation


@click.group()
def cli(args=None):
    """Console script for bolster."""
    click.echo("Replace this message by putting your code into bolster.cli.main")
    click.echo("See click documentation at https://click.palletsprojects.com/")
    return 0


@cli.command()
@click.option(
    "--bounding-box",
    default=None,
    help="Bounding box for the area of interest (min_lon,min_lat,max_lon,max_lat)",
)
@click.option(
    "--order-name",
    default=os.getenv("MAP_IMAGES_ORDER_NAME"),
    help="Order name for the precipitation data",
)
def get_precipitation(bounding_box, order_name):
    """Get UK precipitation data. Requires MET_OFFICE_API_KEY to be set in the environment."""
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
    img.save("precipitation.png")
    click.echo("Precipitation image saved as 'precipitation.png'")


if __name__ == "__main__":
    sys.exit(cli())  # pragma: no cover
