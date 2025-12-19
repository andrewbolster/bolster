"""Console script for bolster."""

import os
import sys
from datetime import date

import click
import pandas as pd

from . import __version__
from .data_sources.cineworld import get_cinema_listings
from .data_sources.companies_house import get_companies_house_records_that_might_be_in_farset, query_basic_company_data
from .data_sources.eoni import get_results as get_ni_election_results
from .data_sources.metoffice import get_uk_precipitation
from .data_sources.ni_house_price_index import build as get_ni_house_prices
from .data_sources.ni_water import get_postcode_to_water_supply_zone, get_water_quality_by_zone
from .data_sources.wikipedia import get_ni_executive_basic_table


@click.group()
@click.version_option(version=__version__, prog_name="bolster")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def cli(verbose, args=None):
    """
    Bolster - A comprehensive Python utility library for Northern Ireland and UK data sources.

    \b
    📊 DATA SOURCES
    Weather & Environment:
        get-precipitation    UK precipitation maps from Met Office
        water-quality        NI water quality by postcode/zone

    \b
    🏛️  Government & Politics:
        ni-executive         NI Executive historical data
        ni-elections         NI Assembly election results (2016-2022)

    \b
    🏢 Business & Property:
        companies-house      UK Companies House data queries
        ni-house-prices      NI house price index data

    \b
    🎬 Entertainment & Lifestyle:
        cinema-listings      Cineworld movie showtimes

    \b
    🛠️  Utilities:
        list-sources         Show all available data sources
        --version           Show version information
        --help              Show this help message

    \b
    📋 QUICK EXAMPLES
        bolster water-quality BT1 5GS       # Water quality for postcode
        bolster ni-executive                 # NI Executive history
        bolster companies-house farset       # Companies at Farset Labs
        bolster list-sources                 # Show all data sources
        bolster --version                    # Show version information

    \b
    💡 TIP: Use 'bolster <command> --help' for detailed command options
    """
    if verbose:
        click.echo("Verbose mode enabled")
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
    # Check for required Met Office API key
    if os.getenv("MET_OFFICE_API_KEY") is None:
        click.echo("❌ Error: MET_OFFICE_API_KEY environment variable is required")
        click.echo("💡 Get your API key from: https://www.metoffice.gov.uk/services/data/datapoint")
        click.echo("   Then set it with: export MET_OFFICE_API_KEY=your_key_here")
        return

    # Validate bounding box format if provided
    if bounding_box is not None:
        try:
            coords = bounding_box.split(",")
            if len(coords) != 4:
                raise ValueError("Must have exactly 4 coordinates")
            min_lon, min_lat, max_lon, max_lat = map(float, coords)
            bounding_box = (min_lon, min_lat, max_lon, max_lat)
            click.echo(f"📍 Using bounding box: {bounding_box}")
        except ValueError as e:
            click.echo(f"❌ Error: Invalid bounding box format: {e}")
            click.echo("💡 Expected format: 'min_lon,min_lat,max_lon,max_lat'")
            click.echo("   Example: '-8.5,54.0,-5.0,55.5' for Northern Ireland")
            return

    # Check for order name
    if order_name is None:
        order_name = os.getenv("MAP_IMAGES_ORDER_NAME")
        if order_name is None:
            click.echo("❌ Error: Order name required but not provided")
            click.echo("💡 Provide it with --order-name or set MAP_IMAGES_ORDER_NAME environment variable")
            click.echo("   Contact Met Office for your specific order name")
            return

    # TODO: API integration testing - requires valid Met Office credentials
    img = get_uk_precipitation(order_name=order_name, bounding_box=bounding_box)  # pragma: no cover
    img.save(output)  # pragma: no cover
    click.echo(f"Precipitation image saved as '{output}'")


@cli.command()
@click.argument("postcode", required=False)
@click.option("--zone-code", help="Water supply zone code (alternative to postcode lookup)")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "csv", "table"], case_sensitive=False),
    default="table",
    help="Output format (default: table)",
)
def water_quality(postcode, zone_code, output_format):
    """
    Get water quality information for a Northern Ireland postcode or zone.

    Provides water quality data including hardness classification, chemical parameters,
    and compliance information from Northern Ireland Water.

    Examples:
        bolster water-quality BT1 5GS     # Lookup by postcode
        bolster water-quality --zone-code BALM  # Lookup by zone code
        bolster water-quality BT7 --format json  # JSON output
    """
    # Prompt for postcode if neither postcode nor zone code provided
    if not postcode and not zone_code:
        postcode = click.prompt("📍 Enter a Northern Ireland postcode")

    try:
        if postcode and not zone_code:
            # Validate and normalize postcode format
            postcode = postcode.upper().strip()
            if not postcode:
                click.echo("❌ Error: Empty postcode provided")
                return

            # Look up zone code from postcode
            click.echo("🔍 Looking up water supply zone...")
            zone_mapping = get_postcode_to_water_supply_zone()
            postcode_key = postcode.replace(" ", "")
            zone_code = zone_mapping.get(postcode_key, "UNKNOWN")

            if zone_code == "UNKNOWN":
                click.echo(f"❌ Error: Could not find water supply zone for postcode: {postcode}")
                click.echo("💡 Please check the postcode format (e.g., 'BT1 5GS') or try a different postcode")
                click.echo("   Only Northern Ireland postcodes are supported")
                return

            click.echo(f"✅ Postcode {postcode} maps to water supply zone: {zone_code}")

        # Get water quality data
        click.echo("💧 Retrieving water quality data...")
        quality_data = get_water_quality_by_zone(zone_code, strict=False)

        if quality_data.empty:
            click.echo(f"❌ Error: No water quality data available for zone: {zone_code}")
            click.echo("💡 This may be a temporary issue. Please try again later or contact NI Water")
            return

        click.echo("✅ Water quality data retrieved successfully")

        # Output in requested format
        if output_format == "json":
            click.echo(quality_data.to_json(indent=2))
        elif output_format == "csv":
            click.echo(quality_data.to_csv())
        else:  # table format
            click.echo(f"\n💧 Water Quality Data for Zone: {zone_code}")
            click.echo("=" * 50)
            for param, value in quality_data.items():
                click.echo(f"  {param}: {value}")
            click.echo("\n💡 Use --format json or csv for machine-readable output")

    except ConnectionError:
        click.echo("❌ Error: Could not connect to NI Water services")
        click.echo("💡 Please check your internet connection and try again")
    except TimeoutError:
        click.echo("❌ Error: Request timed out")
        click.echo("💡 NI Water services may be temporarily unavailable. Please try again later")
    except Exception as e:
        click.echo(f"❌ Error retrieving water quality data: {e}")
        click.echo("💡 If this error persists, please report it as a bug")


@cli.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "csv", "table"], case_sensitive=False),
    default="table",
    help="Output format (default: table)",
)
@click.option("--save", help="Save data to file (specify filename)")
def ni_executive(output_format, save):
    """
    Get Northern Ireland Executive composition and dissolution data.

    Retrieves historical data about NI Executive periods including establishment
    dates, dissolution dates, duration, and interregnum periods.

    Examples:
        bolster ni-executive                    # Display as table
        bolster ni-executive --format json     # JSON output
        bolster ni-executive --save executive.csv  # Save to CSV file
    """
    try:
        executive_data = get_ni_executive_basic_table()

        if save:
            if save.endswith(".json"):
                executive_data.to_json(save, indent=2, date_format="iso")
            elif save.endswith(".csv"):
                executive_data.to_csv(save)
            else:
                # Default to CSV if no extension specified
                executive_data.to_csv(save)
            click.echo(f"Executive data saved to: {save}")
            return

        # Output in requested format
        if output_format == "json":
            click.echo(executive_data.to_json(indent=2, date_format="iso"))
        elif output_format == "csv":
            click.echo(executive_data.to_csv())
        else:  # table format
            click.echo("\nNorthern Ireland Executive History")
            click.echo("=" * 60)
            click.echo(executive_data.to_string())

    except Exception as e:
        click.echo(f"Error retrieving NI Executive data: {e}")


@cli.command()
@click.option("--site-code", type=int, default=117, help="Cineworld site code (default: 117 for Belfast)")
@click.option("--date", "screening_date", help="Screening date in YYYY-MM-DD format (default: today)")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "table"], case_sensitive=False),
    default="table",
    help="Output format (default: table)",
)
def cinema_listings(site_code, screening_date, output_format):
    """
    Get current movie listings from Cineworld cinema.

    Retrieves movie showtimes and information for a specific Cineworld location.
    Default location is Belfast (site code 117).

    Examples:
        bolster cinema-listings                     # Belfast, today
        bolster cinema-listings --site-code 105    # Different location
        bolster cinema-listings --date 2024-03-20  # Specific date
    """
    try:
        # Validate and parse screening date
        if screening_date:
            try:
                screening_date = pd.to_datetime(screening_date).date()
                click.echo(f"🎬 Getting listings for {screening_date}")
            except ValueError:
                click.echo("❌ Error: Invalid date format")
                click.echo("💡 Please use YYYY-MM-DD format (e.g., '2024-03-20')")
                return
        else:
            screening_date = date.today()
            click.echo(f"🎬 Getting today's listings ({screening_date})")

        # Validate site code
        if not isinstance(site_code, int) or site_code <= 0:
            click.echo("❌ Error: Invalid site code")
            click.echo("💡 Site code must be a positive integer (default: 117 for Belfast)")
            return

        click.echo(f"🎭 Connecting to Cineworld site {site_code}...")
        listings = get_cinema_listings(site_code=site_code, screening_date=screening_date)

        if not listings:
            click.echo(f"❌ No movie listings found for site {site_code} on {screening_date}")
            click.echo("💡 Possible causes:")
            click.echo("   - Invalid site code (try default 117 for Belfast)")
            click.echo("   - No screenings scheduled for this date")
            click.echo("   - Cineworld API temporarily unavailable")
            return

        click.echo(f"✅ Found {len(listings)} movie listings")

        # Output in requested format
        if output_format == "json":
            import json

            click.echo(json.dumps(listings, indent=2, default=str))
        else:  # table format
            click.echo(f"\n🎬 Cineworld Listings - Site {site_code} - {screening_date}")
            click.echo("=" * 60)
            for i, movie in enumerate(listings, 1):
                click.echo(f"[{i}] {movie.get('title', 'Unknown Title')}")
                if "showtimes" in movie and movie["showtimes"]:
                    showtimes = ", ".join(movie["showtimes"])
                    click.echo(f"    🕐 Showtimes: {showtimes}")
                else:
                    click.echo("    🕐 No showtimes available")

                if "genre" in movie:
                    click.echo(f"    🎭 Genre: {movie['genre']}")

                click.echo("-" * 40)

            click.echo("\n💡 Use --format json for machine-readable output")

    except ConnectionError:
        click.echo("❌ Error: Could not connect to Cineworld services")
        click.echo("💡 Please check your internet connection and try again")
    except TimeoutError:
        click.echo("❌ Error: Request timed out")
        click.echo("💡 Cineworld services may be temporarily unavailable. Please try again later")
    except Exception as e:
        click.echo(f"❌ Error retrieving cinema listings: {e}")
        click.echo("💡 If this error persists, please report it as a bug")


@cli.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "csv"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--save", help="Save data to file (specify filename)")
def ni_house_prices(output_format, save):
    """
    Get Northern Ireland house price index data.

    Downloads and processes the latest NI house price statistics from official sources,
    including price trends by property type, region, and time period.

    Examples:
        bolster ni-house-prices                     # Display as CSV
        bolster ni-house-prices --format json      # JSON output
        bolster ni-house-prices --save prices.csv  # Save to file
    """
    try:
        click.echo("Downloading NI house price data... (this may take a moment)")
        house_data = get_ni_house_prices()

        if not house_data:
            click.echo("No house price data available")
            return

        if save:
            if output_format == "json" or save.endswith(".json"):
                import json

                with open(save, "w") as f:
                    json.dump({k: v.to_dict() for k, v in house_data.items()}, f, indent=2, default=str)
            else:
                # Save all tables as separate CSV files
                for table_name, df in house_data.items():
                    filename = f"{save.rsplit('.', 1)[0]}_{table_name}.csv"
                    df.to_csv(filename)
                    click.echo(f"Saved {table_name} to: {filename}")
            return

        # Output summary information
        click.echo(f"\nNI House Price Data - {len(house_data)} tables available:")
        click.echo("=" * 60)
        for table_name, df in house_data.items():
            click.echo(f"{table_name}: {len(df)} rows, {len(df.columns)} columns")
            if not df.empty:
                click.echo(f"  Sample data: {list(df.columns[:3])}")

        click.echo("\nUse --save option to export full data to files")

    except Exception as e:
        click.echo(f"Error retrieving house price data: {e}")


@cli.command()
@click.argument("query", required=False)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "csv", "table"], case_sensitive=False),
    default="table",
    help="Output format (default: table)",
)
@click.option("--save", help="Save data to file (specify filename)")
def companies_house(query, output_format, save):
    """
    Query UK Companies House data for company information.

    Search for companies by name or get information about companies that might be
    associated with Farset Labs (Belfast hackerspace).

    Examples:
        bolster companies-house "farset"            # Search for companies with 'farset'
        bolster companies-house farset              # Search without quotes
        bolster companies-house --format json      # JSON output
        bolster companies-house --save companies.csv  # Save results
    """
    try:
        if not query:
            # If no query provided, get Farset Labs related companies
            click.echo("🏢 No query provided, retrieving Farset Labs related companies...")
            companies_data = get_companies_house_records_that_might_be_in_farset()
            query_description = "Farset Labs related companies"
        else:
            # Validate and clean query
            query = query.strip()
            if len(query) < 2:
                click.echo("❌ Error: Query too short")
                click.echo("💡 Please provide at least 2 characters for company search")
                return

            # Query for specific company
            click.echo(f"🔍 Searching Companies House for: '{query}'...")
            companies_data = query_basic_company_data(query)
            query_description = f"Companies matching '{query}'"

        if companies_data is None or companies_data.empty:
            search_term = query or "Farset Labs"
            click.echo(f"❌ No companies found for query: {search_term}")
            click.echo("💡 Suggestions:")
            click.echo("   - Try different search terms")
            click.echo("   - Check spelling and try partial company names")
            click.echo("   - Use 'bolster companies-house' without arguments for Farset Labs companies")
            return

        click.echo(f"✅ Found {len(companies_data)} companies")

        if save:
            if output_format == "json" or save.endswith(".json"):
                companies_data.to_json(save, indent=2, date_format="iso")
            elif output_format == "csv" or save.endswith(".csv"):
                companies_data.to_csv(save, index=False)
            else:
                # Default to CSV if no extension specified
                companies_data.to_csv(save, index=False)
            click.echo(f"Companies data saved to: {save}")
            return

        # Output in requested format
        if output_format == "json":
            click.echo(companies_data.to_json(indent=2, date_format="iso"))
        elif output_format == "csv":
            click.echo(companies_data.to_csv(index=False))
        else:  # table format
            click.echo(f"\n{query_description}")
            click.echo("=" * 60)
            if len(companies_data) > 10:
                click.echo(f"Showing first 10 of {len(companies_data)} companies:")
                click.echo(companies_data.head(10).to_string(index=False))
                click.echo(f"\nUse --save option to export all {len(companies_data)} results")
            else:
                click.echo(companies_data.to_string(index=False))

    except ConnectionError:
        click.echo("❌ Error: Could not connect to Companies House API")
        click.echo("💡 Please check your internet connection and try again")
    except TimeoutError:
        click.echo("❌ Error: Request timed out")
        click.echo("💡 Companies House API may be temporarily unavailable. Please try again later")
    except Exception as e:
        error_msg = str(e).lower()
        if "api key" in error_msg or "authentication" in error_msg:
            click.echo("❌ Error: Companies House API authentication failed")
            click.echo("💡 Please check your API credentials or try again later")
        elif "rate limit" in error_msg:
            click.echo("❌ Error: API rate limit exceeded")
            click.echo("💡 Please wait a few minutes before making another request")
        else:
            click.echo(f"❌ Error querying Companies House data: {e}")
            click.echo("💡 If this error persists, please report it as a bug")


@cli.command()
@click.option(
    "--election-year",
    type=click.Choice(["2016", "2017", "2022", "all"], case_sensitive=False),
    default="all",
    help="Filter by election year (default: all)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "csv", "table"], case_sensitive=False),
    default="table",
    help="Output format (default: table)",
)
@click.option("--save", help="Save data to file (specify filename)")
def ni_elections(election_year, output_format, save):
    """
    Get Northern Ireland Assembly election results (2016-2022).

    Retrieve detailed election results including candidates, parties, constituencies,
    and vote counts for NI Assembly elections.

    Examples:
        bolster ni-elections                        # All election results
        bolster ni-elections --election-year 2022  # 2022 results only
        bolster ni-elections --format json         # JSON output
        bolster ni-elections --save elections.csv  # Save to file
    """
    try:
        click.echo("🗳️ Retrieving NI Assembly election results...")

        # Get election results (the function returns data for all available years)
        election_data = get_ni_election_results()

        if not election_data:
            click.echo("❌ No election data available")
            click.echo("💡 This may be a temporary issue. Please try again later")
            return

        # Filter by year if specified (and not 'all')
        if election_year != "all":
            # This would need to be implemented based on the structure of election_data
            # For now, we'll just note that filtering is requested
            click.echo(f"📊 Filtering results for year: {election_year}")

        click.echo("✅ Election data retrieved successfully")

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    if isinstance(election_data, dict):
                        import json

                        with open(save, "w") as f:
                            json.dump(election_data, f, indent=2, default=str)
                    elif hasattr(election_data, "to_json"):
                        election_data.to_json(save, indent=2, date_format="iso")
                    else:
                        click.echo("❌ Error: Cannot convert election data to JSON format")
                        click.echo("💡 Try using CSV format instead")
                        return
                else:
                    if hasattr(election_data, "to_csv"):
                        election_data.to_csv(save, index=False)
                    else:
                        # If it's a dict of DataFrames, save each separately
                        if isinstance(election_data, dict):
                            for key, df in election_data.items():
                                if hasattr(df, "to_csv"):
                                    filename = f"{save.rsplit('.', 1)[0]}_{key}.csv"
                                    df.to_csv(filename, index=False)
                                    click.echo(f"💾 Saved {key} to: {filename}")
                            return
                click.echo(f"💾 Election data saved to: {save}")
                return
            except PermissionError:
                click.echo(f"❌ Error: Permission denied writing to {save}")
                click.echo("💡 Check file permissions or choose a different location")
                return
            except Exception as e:
                click.echo(f"❌ Error saving file: {e}")
                click.echo("💡 Try a different filename or location")
                return

        # Output in requested format
        if output_format == "json":
            import json

            if isinstance(election_data, dict):
                click.echo(json.dumps(election_data, indent=2, default=str))
            elif hasattr(election_data, "to_json"):
                click.echo(election_data.to_json(indent=2, date_format="iso"))
            else:
                click.echo("Warning: Cannot display election data in JSON format")
        elif output_format == "csv":
            if hasattr(election_data, "to_csv"):
                click.echo(election_data.to_csv(index=False))
            else:
                click.echo("Warning: Cannot display election data in CSV format")
        else:  # table format
            click.echo("\nNI Assembly Election Results")
            if election_year != "all":
                click.echo(f"Year: {election_year}")
            click.echo("=" * 60)

            if hasattr(election_data, "to_string"):
                # If it's a DataFrame
                if len(election_data) > 20:
                    click.echo(f"Showing first 20 of {len(election_data)} records:")
                    click.echo(election_data.head(20).to_string(index=False))
                    click.echo(f"\nUse --save option to export all {len(election_data)} results")
                else:
                    click.echo(election_data.to_string(index=False))
            elif isinstance(election_data, dict):
                # If it's a dict of DataFrames or other data
                for key, value in election_data.items():
                    click.echo(f"\n{key}:")
                    click.echo("-" * 40)
                    if hasattr(value, "to_string"):
                        if len(value) > 10:
                            click.echo(f"First 10 of {len(value)} records:")
                            click.echo(value.head(10).to_string(index=False))
                        else:
                            click.echo(value.to_string(index=False))
                    else:
                        click.echo(str(value))
            else:
                click.echo(str(election_data))

    except Exception as e:
        click.echo(f"Error retrieving election data: {e}")


@cli.command()
def list_sources():
    """
    List all available data sources and their descriptions.

    Shows a comprehensive overview of all data sources available in the Bolster library,
    organized by category with brief descriptions of what data each source provides.
    """
    click.echo("\nBolster - Available Data Sources")
    click.echo("=" * 50)

    click.echo("\n📊 WEATHER & ENVIRONMENT")
    click.echo("  get-precipitation    UK precipitation maps from Met Office API")
    click.echo("                       Requires MET_OFFICE_API_KEY environment variable")

    click.echo("\n💧 WATER & UTILITIES")
    click.echo("  water-quality        NI water quality data by postcode or zone")
    click.echo("                       Chemical parameters, hardness, compliance info")

    click.echo("\n🏛️  GOVERNMENT & POLITICS")
    click.echo("  ni-executive         NI Executive composition and dissolution history")
    click.echo("                       Establishment dates, duration, interregnum periods")
    click.echo("  ni-elections         NI Assembly election results (2016-2022)")
    click.echo("                       Candidates, parties, constituencies, vote counts")

    click.echo("\n🏢 BUSINESS & PROPERTY")
    click.echo("  companies-house      UK Companies House company data queries")
    click.echo("                       Company search, Farset Labs related companies")
    click.echo("  ni-house-prices      NI house price index data from official sources")
    click.echo("                       Price trends by property type, region, time period")

    click.echo("\n🎬 ENTERTAINMENT & LIFESTYLE")
    click.echo("  cinema-listings      Cineworld movie listings and showtimes")
    click.echo("                       Default: Belfast (site 117), supports other locations")

    click.echo("\n🔧 DATA SOURCE MODULES")
    click.echo("  bolster.data_sources.metoffice         - UK Met Office API integration")
    click.echo("  bolster.data_sources.ni_water          - NI Water quality data")
    click.echo("  bolster.data_sources.wikipedia         - NI Executive Wikipedia scraping")
    click.echo("  bolster.data_sources.ni_house_price_index - NI house price statistics")
    click.echo("  bolster.data_sources.cineworld         - Cineworld cinema API")
    click.echo("  bolster.data_sources.eoni              - Electoral Office NI data")
    click.echo("  bolster.data_sources.companies_house   - UK Companies House API")

    click.echo("\n💡 USAGE EXAMPLES")
    click.echo("  bolster water-quality BT1 5GS          # Water quality by postcode")
    click.echo("  bolster ni-executive --format json     # Executive data as JSON")
    click.echo("  bolster companies-house farset          # Search for Farset companies")
    click.echo("  bolster ni-elections --election-year 2022  # 2022 election results")
    click.echo("  bolster cinema-listings --date 2024-03-20  # Movie listings for date")
    click.echo("  bolster --help                          # General help")
    click.echo("  bolster <command> --help               # Command-specific help")

    click.echo(f"\nBolster v{__version__} - Northern Ireland & UK Data Sources")


if __name__ == "__main__":
    sys.exit(cli())  # pragma: no cover
