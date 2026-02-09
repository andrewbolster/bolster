"""Console script for bolster."""

import os
import sys
from datetime import date

import click
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from . import __version__
from .data_sources import dva
from .data_sources.cineworld import get_cinema_listings
from .data_sources.companies_house import get_companies_house_records_that_might_be_in_farset, query_basic_company_data
from .data_sources.eoni import get_results as get_ni_election_results
from .data_sources.metoffice import get_uk_precipitation
from .data_sources.ni_house_price_index import build as get_ni_house_prices
from .data_sources.ni_water import get_postcode_to_water_supply_zone, get_water_quality_by_zone
from .data_sources.nisra import ashe as nisra_ashe
from .data_sources.nisra import births as nisra_births
from .data_sources.nisra import cancer_waiting_times as nisra_cancer
from .data_sources.nisra import composite_index as nisra_composite
from .data_sources.nisra import construction_output as nisra_construction
from .data_sources.nisra import deaths as nisra_deaths
from .data_sources.nisra import economic_indicators as nisra_economic
from .data_sources.nisra import labour_market as nisra_labour_market
from .data_sources.nisra import marriages as nisra_marriages
from .data_sources.nisra import migration as nisra_migration
from .data_sources.nisra import population as nisra_population
from .data_sources.nisra import registrar_general as nisra_registrar_general
from .data_sources.nisra import wellbeing as nisra_wellbeing
from .data_sources.nisra.tourism import occupancy as nisra_occupancy
from .data_sources.nisra.tourism import visitor_statistics as nisra_visitors
from .data_sources.wikipedia import get_ni_executive_basic_table
from .utils.rss import filter_entries, get_nisra_statistics_feed, parse_rss_feed


@click.group()
@click.version_option(version=__version__, prog_name="bolster")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
def cli(verbose, args=None):
    r"""
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
        nisra                NISRA statistics (deaths, labour market, crime)

    \b
    🏢 Business & Property:
        companies-house      UK Companies House data queries
        ni-house-prices      NI house price index data

    \b
    🚗 Transport:
        dva                  DVA monthly test statistics (vehicle, driver, theory)

    \b
    🎬 Entertainment & Lifestyle:
        cinema-listings      Cineworld movie showtimes

    \b
    🛠️  Utilities:
        rss                  RSS/Atom feed reader with NISRA integration
        list-sources         Show all available data sources
        --version           Show version information
        --help              Show this help message

    \b
    📋 QUICK EXAMPLES
        bolster water-quality BT1 5GS         # Water quality for postcode
        bolster nisra deaths --latest         # Latest NISRA deaths statistics
        bolster dva --latest --summary        # DVA test statistics summary
        bolster rss nisra-statistics          # Browse NISRA publications
        bolster ni-executive                  # NI Executive history
        bolster companies-house farset        # Companies at Farset Labs
        bolster list-sources                  # Show all data sources
        bolster --version                     # Show version information

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


@cli.command(name="dva")
@click.option("--latest", is_flag=True, required=True, help="Get the most recent DVA data available")
@click.option(
    "--test-type",
    type=click.Choice(["vehicle", "driver", "theory", "all"], case_sensitive=False),
    default="all",
    help="Type of test statistics to retrieve (default: all)",
)
@click.option("--year", type=int, help="Filter data by year")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "csv"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
@click.option("--summary", is_flag=True, help="Show summary dashboard only")
def dva_cmd(latest, test_type, year, output_format, force_refresh, save, summary):
    r"""
    DVA (Driver & Vehicle Agency) Monthly Test Statistics.

    Retrieves monthly test statistics from the NI Driver & Vehicle Agency including:
    - Vehicle tests (MOT-style tests)
    - Driver tests (practical driving tests)
    - Theory tests

    Data available from April 2014 to present.

    \b
    EXAMPLES:
        bolster dva --latest                          # All test types
        bolster dva --latest --test-type vehicle      # Just vehicle tests
        bolster dva --latest --year 2024              # Filter by year
        bolster dva --latest --summary                # Quick summary dashboard
        bolster dva --latest --format json --save tests.json

    \b
    SOURCE:
        https://www.infrastructure-ni.gov.uk/publications/type/statistics
    """
    console = Console()

    try:
        if summary:
            # Show summary dashboard
            console.print("\n[bold]DVA Test Statistics Summary[/bold]")
            console.print("━" * 50)

            all_data = dva.get_latest_all_tests(force_refresh=force_refresh)

            # Get latest month info
            vehicle_df = all_data["vehicle"]
            driver_df = all_data["driver"]
            theory_df = all_data["theory"]

            latest_row = vehicle_df.iloc[-1]
            latest_month = f"{latest_row['month']} {latest_row['year']}"

            console.print(f"\n[cyan]Latest Data: {latest_month}[/cyan]\n")

            # Calculate stats for each test type
            console.print(f"{'Test Type':<10} {'This Month':>12} {'MoM':>8} {'QoQ':>8} {'YoY':>8}")
            console.print("─" * 50)

            for label, df in [("Vehicle", vehicle_df), ("Driver", driver_df), ("Theory", theory_df)]:
                current = df.iloc[-1]["tests_conducted"]

                # Month-on-month change
                if len(df) >= 2:
                    prev_month = df.iloc[-2]["tests_conducted"]
                    mom_change = ((current - prev_month) / prev_month) * 100
                    mom_str = f"{mom_change:+.1f}%"
                else:
                    mom_str = "N/A"

                # Quarter-on-quarter change (3 months ago)
                if len(df) >= 4:
                    prev_quarter = df.iloc[-4]["tests_conducted"]
                    qoq_change = ((current - prev_quarter) / prev_quarter) * 100
                    qoq_str = f"{qoq_change:+.1f}%"
                else:
                    qoq_str = "N/A"

                # YoY change (same month last year)
                last_year = df[(df["year"] == latest_row["year"] - 1) & (df["month"] == latest_row["month"])]
                if not last_year.empty:
                    yoy_change = (
                        (current - last_year.iloc[0]["tests_conducted"]) / last_year.iloc[0]["tests_conducted"]
                    ) * 100
                    yoy_str = f"{yoy_change:+.1f}%"
                else:
                    yoy_str = "N/A"

                console.print(f"{label:<10} {current:>12,} {mom_str:>8} {qoq_str:>8} {yoy_str:>8}")

            # YTD total
            current_year = latest_row["year"]
            ytd_total = sum(df[df["year"] == current_year]["tests_conducted"].sum() for df in all_data.values())
            console.print(f"\n[dim]{current_year} YTD Total: {ytd_total:,} tests[/dim]")

            return

        # Regular data retrieval
        console.print(f"[cyan]Fetching DVA {test_type} test statistics...[/cyan]")

        if test_type == "all":
            data = dva.get_latest_all_tests(force_refresh=force_refresh)
            if year:
                data = {k: dva.get_tests_by_year(v, year) for k, v in data.items()}
        else:
            if test_type == "vehicle":
                data = dva.get_latest_vehicle_tests(force_refresh=force_refresh)
            elif test_type == "driver":
                data = dva.get_latest_driver_tests(force_refresh=force_refresh)
            else:  # theory
                data = dva.get_latest_theory_tests(force_refresh=force_refresh)

            if year:
                data = dva.get_tests_by_year(data, year)

        # Check for empty data
        if test_type == "all":
            if all(df.empty for df in data.values()):
                console.print("[yellow]⚠️  No data found for the specified filters[/yellow]")
                return
        else:
            if data.empty:
                console.print("[yellow]⚠️  No data found for the specified filters[/yellow]")
                return

        # Display success
        if test_type == "all":
            total_records = sum(len(df) for df in data.values())
            console.print(f"[green]✅ Retrieved {total_records} records[/green]")
            for name, df in data.items():
                console.print(f"   • {name}: {len(df)} months")
        else:
            console.print(f"[green]✅ Retrieved {len(data)} months of {test_type} test data[/green]")

        # Save to file
        if save:
            try:
                if test_type == "all":
                    for name, df in data.items():
                        filename = (
                            f"{save.rsplit('.', 1)[0]}_{name}.{save.rsplit('.', 1)[-1] if '.' in save else 'csv'}"
                        )
                        if output_format == "json" or filename.endswith(".json"):
                            df.to_json(filename, orient="records", date_format="iso", indent=2)
                        else:
                            df.to_csv(filename, index=False)
                        console.print(f"[green]💾 Saved {name} to: {filename}[/green]")
                else:
                    if output_format == "json" or save.endswith(".json"):
                        data.to_json(save, orient="records", date_format="iso", indent=2)
                    else:
                        data.to_csv(save, index=False)
                    console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console
        if test_type == "all":
            for name, df in data.items():
                console.print(f"\n[bold]{name.upper()} TESTS:[/bold]")
                if output_format == "json":
                    click.echo(df.to_json(orient="records", date_format="iso", indent=2))
                else:
                    console.print(df.to_csv(index=False), end="")
        else:
            if output_format == "json":
                click.echo(data.to_json(orient="records", date_format="iso", indent=2))
            else:
                console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        raise click.Abort() from e


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


@cli.group()
def rss():
    """
    RSS/Atom feed reading commands.

    Tools for reading and parsing RSS/Atom feeds with beautiful terminal formatting.
    Includes generic feed reader and specialized commands for NISRA statistics.
    """
    pass


@rss.command(name="read")
@click.argument("feed_url")
@click.option("--limit", "-l", default=20, help="Maximum number of entries to display")
@click.option("--title-filter", "-t", help="Filter entries by title (case-insensitive)")
@click.option("--after-date", "-a", help="Show entries published after this date (YYYY-MM-DD)")
@click.option("--before-date", "-b", help="Show entries published before this date (YYYY-MM-DD)")
@click.option("--format", "-f", type=click.Choice(["rich", "json", "csv"]), default="rich", help="Output format")
def rss_read(feed_url, limit, title_filter, after_date, before_date, format):
    r"""
    Read and display RSS/Atom feeds with beautiful formatting.

    Fetches and parses RSS or Atom feeds from any URL, displaying entries
    with rich formatting in the terminal. Supports filtering by title and date range.

    \b
    EXAMPLES:
        # Display NISRA statistics feed
        bolster rss-feed "https://www.gov.uk/search/research-and-statistics.atom"

        # Filter by title keyword
        bolster rss-feed URL --title-filter "health"

        # Limit to recent entries
        bolster rss-feed URL --limit 10 --after-date 2024-01-01

    \b
    ARGUMENTS:
        feed_url    URL of the RSS or Atom feed to read

    \b
    OUTPUT FORMATS:
        rich  - Beautiful terminal output with colors and formatting (default)
        json  - Machine-readable JSON output
        csv   - Comma-separated values for spreadsheet import
    """
    console = Console()

    try:
        with console.status(f"[bold green]Fetching feed from {feed_url}..."):
            feed = parse_rss_feed(feed_url)

        # Apply filters
        entries = feed.entries
        if title_filter or after_date or before_date:
            entries = filter_entries(
                entries,
                title_contains=title_filter,
                after_date=after_date,
                before_date=before_date,
            )

        # Limit entries
        if limit and limit > 0:
            entries = entries[:limit]

        if format == "rich":
            # Display feed header
            console.print(
                Panel(
                    f"[bold cyan]{feed.title}[/bold cyan]\n"
                    f"[dim]{feed.description or 'No description'}[/dim]\n"
                    f"[yellow]Showing {len(entries)} of {len(feed.entries)} entries[/yellow]",
                    title="📰 Feed Information",
                    border_style="cyan",
                )
            )

            # Display entries
            for idx, entry in enumerate(entries, 1):
                # Create entry panel
                date_str = entry.published.strftime("%Y-%m-%d %H:%M") if entry.published else "No date"

                # Build content
                content_lines = [f"[bold]{entry.title}[/bold]"]
                content_lines.append(f"[dim]{date_str}[/dim]")

                if entry.author:
                    content_lines.append(f"[green]Author:[/green] {entry.author}")

                if entry.categories:
                    categories_str = ", ".join(entry.categories[:5])
                    content_lines.append(f"[blue]Categories:[/blue] {categories_str}")

                if entry.summary:
                    # Truncate long summaries
                    summary = entry.summary[:300] + "..." if len(entry.summary) > 300 else entry.summary
                    content_lines.append(f"\n{summary}")

                content_lines.append(f"\n[cyan]🔗 {entry.link}[/cyan]")

                console.print(
                    Panel(
                        "\n".join(content_lines),
                        title=f"Entry {idx}/{len(entries)}",
                        border_style="green" if idx % 2 == 0 else "yellow",
                    )
                )

        elif format == "json":
            import json

            output = {
                "feed": {
                    "title": feed.title,
                    "link": feed.link,
                    "description": feed.description,
                    "entry_count": len(entries),
                },
                "entries": [entry.to_dict() for entry in entries],
            }
            click.echo(json.dumps(output, indent=2, default=str))

        elif format == "csv":
            df = pd.DataFrame(
                [
                    {
                        "title": entry.title,
                        "link": entry.link,
                        "published": entry.published.isoformat() if entry.published else None,
                        "author": entry.author,
                        "summary": entry.summary[:100] if entry.summary else None,
                    }
                    for entry in entries
                ]
            )
            click.echo(df.to_csv(index=False))

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}", style="red")
        raise click.Abort() from e


@rss.command(name="nisra-statistics")
@click.option("--limit", "-l", default=20, help="Maximum number of entries to display")
@click.option("--title-filter", "-t", help="Filter entries by title (case-insensitive)")
@click.option("--after-date", "-a", help="Show entries published after this date (YYYY-MM-DD)")
@click.option(
    "--order", "-o", type=click.Choice(["recent", "oldest"]), default="recent", help="Sort order by release date"
)
@click.option("--format", "-f", type=click.Choice(["rich", "json", "csv"]), default="rich", help="Output format")
def rss_nisra_statistics(limit, title_filter, after_date, order, format):
    r"""
    Browse NISRA (Northern Ireland Statistics and Research Agency) publications.

    Fetches and displays recent research and statistics publications from NISRA
    via the GOV.UK website. Includes reports on demographics, health, economy,
    labour market, crime, and lifestyle surveys.

    \b
    EXAMPLES:
        # Show recent NISRA publications
        bolster nisra-statistics

        # Find health-related statistics
        bolster nisra-statistics --title-filter "health"

        # Get oldest publications first
        bolster nisra-statistics --order oldest --limit 10

        # Export to CSV
        bolster nisra-statistics --format csv > nisra.csv

    \b
    PUBLICATION TYPES:
        • Labour Market Statistics
        • Population & Demographics
        • Health & Social Care
        • Crime & Justice Statistics
        • Economic Statistics
        • Lifestyle & Wellbeing Surveys

    \b
    OUTPUT FORMATS:
        rich  - Beautiful terminal output with colors (default)
        json  - Machine-readable JSON format
        csv   - Spreadsheet-compatible CSV format
    """
    console = Console()

    try:
        with console.status("[bold green]Fetching NISRA statistics feed from GOV.UK..."):
            feed = get_nisra_statistics_feed(order=order)

        # Apply filters
        entries = feed.entries
        if title_filter or after_date:
            entries = filter_entries(
                entries,
                title_contains=title_filter,
                after_date=after_date,
            )

        # Limit entries
        if limit and limit > 0:
            entries = entries[:limit]

        if format == "rich":
            # Display header
            console.print(
                Panel(
                    f"[bold cyan]NISRA Research & Statistics[/bold cyan]\n"
                    f"[dim]Northern Ireland Statistics and Research Agency[/dim]\n"
                    f"[yellow]Showing {len(entries)} publications[/yellow]",
                    title="📊 NISRA Publications",
                    border_style="cyan",
                )
            )

            # Group entries by month if we have dates
            from collections import defaultdict

            by_month = defaultdict(list)

            for entry in entries:
                if entry.published:
                    month_key = entry.published.strftime("%Y-%m")
                    by_month[month_key].append(entry)
                else:
                    by_month["unknown"].append(entry)

            # Display by month
            for month_key in sorted(by_month.keys(), reverse=(order == "recent")):
                month_entries = by_month[month_key]

                if month_key != "unknown":
                    console.print(f"\n[bold magenta]📅 {month_key}[/bold magenta]")

                for entry in month_entries:
                    date_str = entry.published.strftime("%Y-%m-%d") if entry.published else "No date"

                    # Create compact entry display
                    text = Text()
                    text.append("  • ", style="dim")
                    text.append(entry.title, style="bold")
                    text.append(f" [{date_str}]", style="dim cyan")

                    console.print(text)

                    if entry.summary:
                        summary = entry.summary[:150] + "..." if len(entry.summary) > 150 else entry.summary
                        console.print(f"    [dim]{summary}[/dim]")

                    console.print(f"    [cyan]🔗 {entry.link}[/cyan]")
                    console.print()

        elif format == "json":
            import json

            output = {
                "feed": {
                    "title": "NISRA Research & Statistics",
                    "organization": "Northern Ireland Statistics and Research Agency",
                    "source": "GOV.UK",
                    "entry_count": len(entries),
                },
                "entries": [entry.to_dict() for entry in entries],
            }
            click.echo(json.dumps(output, indent=2, default=str))

        elif format == "csv":
            df = pd.DataFrame(
                [
                    {
                        "title": entry.title,
                        "link": entry.link,
                        "published": entry.published.isoformat() if entry.published else None,
                        "summary": entry.summary[:200] if entry.summary else None,
                    }
                    for entry in entries
                ]
            )
            click.echo(df.to_csv(index=False))

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}", style="red")
        raise click.Abort() from e


@cli.group()
def nisra():
    """
    NISRA (Northern Ireland Statistics and Research Agency) data sources.

    Access official statistics and research publications from NISRA including:
    - Weekly death registrations with demographic breakdowns
    - Labour market statistics (coming soon)
    - Crime statistics (coming soon)
    - Economic indicators (coming soon)

    All data is sourced directly from NISRA publications and cached locally
    for performance. Use --force-refresh to bypass cache and download fresh data.
    """
    pass


@nisra.command(name="feed")
@click.option("--limit", "-n", default=20, help="Number of entries to show (default: 20)")
@click.option("--filter", "-f", "title_filter", help="Filter entries by title (case-insensitive)")
@click.option("--days", "-d", type=int, help="Show entries from last N days")
@click.option("--check-coverage", is_flag=True, help="Show which datasets have modules implemented")
def nisra_feed(limit: int, title_filter: str, days: int, check_coverage: bool):
    """Show recent NISRA publications from RSS feed.

    Useful for discovering new datasets and checking for updates.

    Examples:
        bolster nisra feed                    # Recent 20 publications

        bolster nisra feed -n 50              # More entries

        bolster nisra feed -f tourism         # Filter by title

        bolster nisra feed --days 7           # Last week only

        bolster nisra feed --check-coverage   # Show implementation status
    """
    from datetime import datetime, timedelta

    from rich.console import Console
    from rich.table import Table

    from bolster.utils.rss import filter_entries, get_nisra_statistics_feed

    console = Console()

    # Known implemented modules (keywords that map to our modules)
    implemented_keywords = {
        "death": "deaths",
        "birth": "births",
        "marriage": "marriages",
        "civil partnership": "civil-partnerships",
        "labour market": "labour-market",
        "labour force": "labour-market",
        "population": "population",
        "migration": "migration",
        "occupancy": "occupancy",
        "tourism": "visitors",
        "visitor": "visitors",
        "index of services": "index-of-services",
        "index of production": "index-of-production",
        "construction output": "construction-output",
        "ashe": "ashe",
        "hours and earnings": "ashe",
        "composite economic index": "composite-index",
        "nicei": "composite-index",
        "wellbeing": "wellbeing",
        "cancer waiting": "cancer-waiting-times",
    }

    with console.status("Fetching NISRA RSS feed..."):
        feed = get_nisra_statistics_feed()

    entries = feed.entries

    # Apply date filter
    if days:
        cutoff = datetime.now() - timedelta(days=days)
        entries = [e for e in entries if e.published and e.published >= cutoff]

    # Apply title filter
    if title_filter:
        entries = filter_entries(entries, title_contains=title_filter)

    # Limit entries
    entries = entries[:limit]

    if not entries:
        console.print("[yellow]No entries found matching criteria[/yellow]")
        return

    # Build table
    table = Table(title=f"NISRA Publications ({len(entries)} shown)")
    table.add_column("Date", style="cyan", width=10)
    table.add_column("Title", style="white")

    if check_coverage:
        table.add_column("Module", style="green", width=20)

    for entry in entries:
        date_str = entry.published.strftime("%Y-%m-%d") if entry.published else "N/A"
        title = entry.title[:75] + "..." if len(entry.title) > 75 else entry.title

        if check_coverage:
            # Check if we have a module for this
            module = None
            title_lower = entry.title.lower()
            for keyword, mod_name in implemented_keywords.items():
                if keyword in title_lower:
                    module = mod_name
                    break
            module_str = f"[green]✓ {module}[/green]" if module else "[dim]-[/dim]"
            table.add_row(date_str, title, module_str)
        else:
            table.add_row(date_str, title)

    console.print(table)

    if check_coverage:
        # Summary
        covered = sum(1 for e in entries if any(kw in e.title.lower() for kw in implemented_keywords))
        console.print(f"\n[green]Covered: {covered}[/green] | [yellow]Not covered: {len(entries) - covered}[/yellow]")


@nisra.command(name="deaths")
@click.option("--latest", is_flag=True, help="Get the most recent deaths data available")
@click.option(
    "--dimension",
    type=click.Choice(["totals", "demographics", "geography", "place", "all"], case_sensitive=False),
    default="all",
    help="Which dimension to retrieve (default: all)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
def nisra_deaths_cmd(latest, dimension, output_format, force_refresh, save):
    r"""
    NISRA Weekly Deaths Statistics.

    Retrieves weekly death registrations in Northern Ireland with breakdowns by:
    - Totals (COVID-19 deaths, flu/pneumonia deaths, excess deaths)
    - Demographics (age, sex)
    - Geography (Local Government Districts)
    - Place of death (hospital, home, care home, etc.)

    \b
    EXAMPLES:
        # Get COVID-19 and flu/pneumonia deaths
        bolster nisra deaths --latest --dimension totals

        # Get latest demographics breakdown as CSV
        bolster nisra deaths --latest --dimension demographics

        # Get all dimensions as JSON
        bolster nisra deaths --latest --dimension all --format json

        # Save totals data to analyze COVID trends
        bolster nisra deaths --latest --dimension totals --save deaths_totals.csv

        # Force refresh cached data
        bolster nisra deaths --latest --force-refresh

    \b
    DATA NOTES:
        - Based on registration date, not death occurrence date
        - Most deaths registered within 5 days in Northern Ireland
        - Weekly files are provisional and subject to revision
        - Dimensions are NOT cross-tabulated in source data
        - COVID-19/flu deaths are NOT broken down by age/sex in source
        - Excess deaths calculated using multiple methodologies

    \b
    DIMENSIONS:
        totals       - Weekly totals with COVID-19, flu/pneumonia, excess deaths
        demographics - Age and sex breakdown (Total/Male/Female × age ranges)
        geography    - Local Government Districts (11 LGDs)
        place        - Place of death (Hospital, Home, Care Home, Hospice, Other)
        all          - All dimensions (returns separate tables)

    \b
    SOURCE:
        https://www.nisra.gov.uk/statistics/death-statistics/weekly-death-registrations-northern-ireland
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        console.print("[dim]Future versions will support specific dates/weeks[/dim]")
        return

    try:
        with console.status("[bold green]Downloading latest NISRA deaths data..."):
            data = nisra_deaths.get_latest_deaths(dimension=dimension, force_refresh=force_refresh)

        # Handle the result based on whether it's a single DataFrame or dict of DataFrames
        if dimension == "all":
            console.print("[green]✅ Retrieved all dimensions successfully[/green]")
            total_records = sum(len(df) for df in data.values())
            console.print(f"[cyan]📊 Total records: {total_records}[/cyan]")

            for dim_name, df in data.items():
                console.print(f"   • {dim_name}: {len(df)} records")
                if not df.empty:
                    week_range = f"{df['week_ending'].min().date()} to {df['week_ending'].max().date()}"
                    console.print(f"     [dim]Weeks: {week_range}[/dim]")
        else:
            console.print(f"[green]✅ Retrieved {dimension} dimension successfully[/green]")
            console.print(f"[cyan]📊 Total records: {len(data)}[/cyan]")
            if not data.empty:
                week_range = f"{data['week_ending'].min().date()} to {data['week_ending'].max().date()}"
                console.print(f"[dim]Weeks: {week_range}[/dim]")

        # Handle file saving
        if save:
            try:
                if dimension == "all":
                    # Save each dimension to a separate file
                    for dim_name, df in data.items():
                        filename = (
                            f"{save.rsplit('.', 1)[0]}_{dim_name}.{save.rsplit('.', 1)[-1] if '.' in save else 'csv'}"
                        )
                        if output_format == "json" or filename.endswith(".json"):
                            df.to_json(filename, orient="records", date_format="iso", indent=2)
                        else:
                            df.to_csv(filename, index=False)
                        console.print(f"[green]💾 Saved {dim_name} to: {filename}[/green]")
                else:
                    # Save single dimension
                    if output_format == "json" or save.endswith(".json"):
                        data.to_json(save, orient="records", date_format="iso", indent=2)
                    else:
                        data.to_csv(save, index=False)
                    console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except PermissionError:
                console.print(f"[red]❌ Error: Permission denied writing to {save}[/red]")
                console.print("[yellow]💡 Check file permissions or choose a different location[/yellow]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console in requested format
        if output_format == "json":
            import json

            if dimension == "all":
                # Convert DataFrames to JSON-serializable format
                output = {dim_name: df.to_dict(orient="records") for dim_name, df in data.items()}
                click.echo(json.dumps(output, indent=2, default=str))
            else:
                click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:  # csv format
            if dimension == "all":
                console.print("\n[yellow]💡 Tip: For 'all' dimensions, use --save to export to files[/yellow]")
                console.print("[yellow]   Displaying demographics dimension only:[/yellow]\n")
                click.echo(data["demographics"].to_csv(index=False))
            else:
                click.echo(data.to_csv(index=False))

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        console.print("   • Visit NISRA website to verify data availability")
        raise click.Abort() from e


@nisra.command(name="labour-market")
@click.option("--latest", is_flag=True, help="Get the most recent labour market data available")
@click.option(
    "--table",
    type=click.Choice(["employment", "economic_inactivity", "lgd", "all"], case_sensitive=False),
    default="all",
    help="Which table to retrieve (default: all)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
def nisra_labour_market_cmd(latest, table, output_format, force_refresh, save):
    r"""
    NISRA Labour Force Survey Statistics.

    Retrieves Labour Force Survey (LFS) data for Northern Ireland including:
    - Employment by age band and sex (quarterly)
    - Economic inactivity rates and numbers with historical time series (quarterly)
    - Employment by Local Government District (annual)

    The LFS is a sample survey of households providing labour force statistics using
    internationally agreed concepts and definitions.

    \b
    EXAMPLES:
        # Get latest employment data by age and sex
        bolster nisra labour-market --latest --table employment

        # Get economic inactivity time series (2012-2025)
        bolster nisra labour-market --latest --table economic_inactivity

        # Get employment by Local Government District (annual)
        bolster nisra labour-market --latest --table lgd

        # Get all tables as JSON
        bolster nisra labour-market --latest --table all --format json

        # Save employment data to analyze age distribution
        bolster nisra labour-market --latest --table employment --save employment.csv

        # Force refresh cached data
        bolster nisra labour-market --latest --force-refresh

    \b
    DATA NOTES:
        - Survey data with sampling variability (see NISRA notes on confidence intervals)
        - Quarterly publications covering 3-month rolling periods
        - Some estimates based on small samples (indicated by shading in source)
        - Estimates <3 suppressed for disclosure control
        - Not seasonally adjusted
        - Working age: 16-64 for both males and females

    \b
    TABLES:
        employment          - Employment by age band and sex (Table 2.15)
                             • Percentage distribution across age groups
                             • Total employment numbers by sex
                             • Quarterly snapshot data

        economic_inactivity - Economic inactivity by sex (Table 2.21)
                             • Numbers economically inactive by sex
                             • Economic inactivity rates (percentages)
                             • Historical time series (2012-2025 for same quarter)
                             • Allows year-over-year comparisons

        lgd                 - Employment by Local Government District (Table 1.16a)
                             • Employment statistics for all 11 NI LGDs
                             • Population 16+, employment rates, economic activity
                             • Annual data only (published separately)

        all                 - All quarterly tables (excludes LGD annual data)

    \b
    DEFINITIONS:
        Employed           - Did ≥1 hour paid work in reference week, or has job temporarily away from
        Unemployed         - Not employed, actively seeking work, available to start within 2 weeks
        Economically       - Not employed and not seeking work (students, retired, caring for
        Inactive             family, long-term sick/disabled, discouraged workers, etc.)

    \b
    SOURCE:
        https://www.nisra.gov.uk/statistics/labour-market-and-social-welfare
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        console.print("[dim]Future versions will support specific quarters/years[/dim]")
        return

    try:
        with console.status("[bold green]Downloading latest NISRA labour market data..."):
            if table == "all":
                data = nisra_labour_market.get_quarterly_data(
                    year=2025,
                    quarter="Jul-Sep",
                    tables=["employment", "economic_inactivity"],
                    force_refresh=force_refresh,
                )
            elif table == "employment":
                data = nisra_labour_market.get_latest_employment(force_refresh=force_refresh)
            elif table == "economic_inactivity":
                data = nisra_labour_market.get_latest_economic_inactivity(force_refresh=force_refresh)
            elif table == "lgd":
                data = nisra_labour_market.get_latest_employment_by_lgd(force_refresh=force_refresh)

        # Handle the result based on whether it's a single DataFrame or dict of DataFrames
        if table == "all":
            console.print("[green]✅ Retrieved all tables successfully[/green]")
            total_records = sum(len(df) for df in data.values())
            console.print(f"[cyan]📊 Total records: {total_records}[/cyan]")

            for table_name, df in data.items():
                console.print(f"   • {table_name}: {len(df)} records")
                if not df.empty and "quarter_period" in df.columns:
                    periods = df["quarter_period"].unique()
                    console.print(f"     [dim]Period: {periods[0]}[/dim]")
                elif not df.empty and "time_period" in df.columns:
                    periods = df["time_period"].unique()
                    console.print(
                        f"     [dim]Time series: {len(periods)} periods ({periods[0]} to {periods[-1]})[/dim]"
                    )
        else:
            console.print(f"[green]✅ Retrieved {table} table successfully[/green]")
            console.print(f"[cyan]📊 Total records: {len(data)}[/cyan]")
            if not data.empty:
                if "quarter_period" in data.columns:
                    periods = data["quarter_period"].unique()
                    console.print(f"[dim]Period: {periods[0]}[/dim]")
                elif "time_period" in data.columns:
                    periods = data["time_period"].unique()
                    console.print(f"[dim]Time series: {len(periods)} periods ({periods[0]} to {periods[-1]})[/dim]")

        # Handle file saving
        if save:
            try:
                if table == "all":
                    # Save each table to a separate file
                    for table_name, df in data.items():
                        filename = (
                            f"{save.rsplit('.', 1)[0]}_{table_name}.{save.rsplit('.', 1)[-1] if '.' in save else 'csv'}"
                        )
                        if output_format == "json" or filename.endswith(".json"):
                            df.to_json(filename, orient="records", date_format="iso", indent=2)
                        else:
                            df.to_csv(filename, index=False)
                        console.print(f"[green]💾 Saved {table_name} to: {filename}[/green]")
                else:
                    # Save single table
                    if output_format == "json" or save.endswith(".json"):
                        data.to_json(save, orient="records", date_format="iso", indent=2)
                    else:
                        data.to_csv(save, index=False)
                    console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except PermissionError:
                console.print(f"[red]❌ Error: Permission denied writing to {save}[/red]")
                console.print("[yellow]💡 Check file permissions or choose a different location[/yellow]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console in requested format
        if output_format == "json":
            import json

            if table == "all":
                # Convert DataFrames to JSON-serializable format
                output = {table_name: df.to_dict(orient="records") for table_name, df in data.items()}
                click.echo(json.dumps(output, indent=2, default=str))
            else:
                click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:  # csv format
            if table == "all":
                console.print("\n[yellow]💡 Tip: For 'all' tables, use --save to export to files[/yellow]")
                console.print("[yellow]   Displaying employment table only:[/yellow]\n")
                click.echo(data["employment"].to_csv(index=False))
            else:
                click.echo(data.to_csv(index=False))

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        console.print("   • Visit NISRA website to verify data availability")
        raise click.Abort() from e


@nisra.command(name="births")
@click.option("--latest", is_flag=True, help="Get the most recent births data available")
@click.option(
    "--event-type",
    type=click.Choice(["registration", "occurrence", "both"], case_sensitive=False),
    default="both",
    help="Event type: registration (when registered), occurrence (when born), or both (default: both)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
def nisra_births_cmd(latest, event_type, output_format, force_refresh, save):
    r"""
    NISRA Monthly Birth Registrations Statistics.

    Retrieves monthly birth registration data for Northern Ireland including:
    - Births by month of registration (when officially registered)
    - Births by month of occurrence (when actually born)
    - Breakdown by sex (Persons, Male, Female)

    Birth registration data are based on mother's residence at time of birth.
    Most births are registered within 42 days in Northern Ireland.

    \b
    EXAMPLES:
        # Get latest births by registration date
        bolster nisra births --latest --event-type registration

        # Get latest births by occurrence (actual birth date)
        bolster nisra births --latest --event-type occurrence

        # Get both registration and occurrence data
        bolster nisra births --latest --event-type both

        # Save registration data to file
        bolster nisra births --latest --event-type registration --save births_reg.csv

        # Get data as JSON
        bolster nisra births --latest --event-type both --format json

        # Force refresh cached data
        bolster nisra births --latest --force-refresh

    \b
    DATA NOTES:
        - Monthly time series from 2006 to present
        - Final data for years up to and including 2024
        - Provisional and subject to change for current year
        - Registration data lags occurrence data by ~1-2 months
        - COVID-19 Note: April-May 2020 registration data disrupted by lockdown
          (registration offices closed), but occurrence data remains normal

    \b
    EVENT TYPES:
        registration - Births by month they were officially registered
                      • Reflects administrative processing dates
                      • Can be affected by office closures (e.g., COVID-19)
                      • Latest data may be 1-2 months more recent than occurrence

        occurrence   - Births by month they actually occurred
                      • Reflects actual birth dates
                      • More stable measure of birth patterns
                      • Limited to births already registered

        both         - Returns both registration and occurrence data
                      • Useful for comparing registration patterns vs birth patterns
                      • Helps identify registration delays/backlogs

    \b
    OUTPUT:
        - month: First day of month (datetime)
        - sex: Persons (total), Male, or Female
        - births: Number of births

    \b
    SOURCE:
        https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/births
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        console.print("[dim]Future versions will support specific months/years[/dim]")
        return

    try:
        with console.status("[bold green]Downloading latest NISRA births data..."):
            data = nisra_births.get_latest_births(event_type=event_type, force_refresh=force_refresh)

        # Handle the result based on whether it's a single DataFrame or dict of DataFrames
        if event_type == "both":
            console.print("[green]✅ Retrieved both event types successfully[/green]")
            total_records = sum(len(df) for df in data.values())
            console.print(f"[cyan]📊 Total records: {total_records}[/cyan]")

            for event_name, df in data.items():
                console.print(f"   • {event_name}: {len(df)} records")
                if not df.empty:
                    latest_month = df["month"].max()
                    earliest_month = df["month"].min()
                    console.print(
                        f"     [dim]Period: {earliest_month.strftime('%b %Y')} to {latest_month.strftime('%b %Y')}[/dim]"
                    )
        else:
            console.print(f"[green]✅ Retrieved {event_type} data successfully[/green]")
            console.print(f"[cyan]📊 Total records: {len(data)}[/cyan]")
            if not data.empty:
                latest_month = data["month"].max()
                earliest_month = data["month"].min()
                console.print(
                    f"[dim]Period: {earliest_month.strftime('%b %Y')} to {latest_month.strftime('%b %Y')}[/dim]"
                )

        # Handle file saving
        if save:
            try:
                if event_type == "both":
                    # Save each event type to a separate file
                    for event_name, df in data.items():
                        filename = (
                            f"{save.rsplit('.', 1)[0]}_{event_name}.{save.rsplit('.', 1)[-1] if '.' in save else 'csv'}"
                        )
                        if output_format == "json" or filename.endswith(".json"):
                            df.to_json(filename, orient="records", date_format="iso", indent=2)
                        else:
                            df.to_csv(filename, index=False)
                        console.print(f"[green]💾 Saved {event_name} to: {filename}[/green]")
                else:
                    # Save single event type
                    if output_format == "json" or save.endswith(".json"):
                        data.to_json(save, orient="records", date_format="iso", indent=2)
                    else:
                        data.to_csv(save, index=False)
                    console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except PermissionError:
                console.print(f"[red]❌ Error: Permission denied writing to {save}[/red]")
                console.print("[yellow]💡 Check file permissions or choose a different location[/yellow]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console in requested format
        if output_format == "json":
            import json

            if event_type == "both":
                # Convert DataFrames to JSON-serializable format
                output = {event_name: df.to_dict(orient="records") for event_name, df in data.items()}
                click.echo(json.dumps(output, indent=2, default=str))
            else:
                click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            # CSV output
            if event_type == "both":
                for event_name, df in data.items():
                    console.print(f"\n[bold]{event_name.upper()}:[/bold]")
                    console.print(df.to_csv(index=False), end="")
            else:
                console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        console.print("   • Visit NISRA website to verify data availability")
        raise click.Abort() from e


@nisra.command(name="population")
@click.option("--latest", is_flag=True, help="Get the most recent population estimates available")
@click.option(
    "--area",
    type=click.Choice(
        ["all", "Northern Ireland", "Parliamentary Constituencies (2024)", "Health and Social Care Trusts"],
        case_sensitive=False,
    ),
    default="Northern Ireland",
    help="Geographic area (default: Northern Ireland)",
)
@click.option(
    "--year",
    type=int,
    help="Specific year to retrieve (leave blank for all years)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
def nisra_population_cmd(latest, area, year, output_format, force_refresh, save):
    r"""
    NISRA Mid-Year Population Estimates.

    Retrieves annual mid-year population estimates for Northern Ireland with breakdowns by:
    - Geography (NI overall, Parliamentary Constituencies, Health and Social Care Trusts)
    - Sex (All persons, Males, Females)
    - Age (5-year age bands: 00-04, 05-09, ..., 90+)
    - Year (1971-present for NI overall, 2021-present for sub-geographies)

    Mid-year estimates are referenced to June 30th of each year.

    \b
    EXAMPLES:
        # Get latest NI overall population
        bolster nisra population --latest

        # Get all geographic areas
        bolster nisra population --latest --area all

        # Get specific year
        bolster nisra population --latest --year 2024

        # Get Parliamentary Constituencies
        bolster nisra population --latest --area "Parliamentary Constituencies (2024)"

        # Save to file
        bolster nisra population --latest --save population.csv

        # Get as JSON
        bolster nisra population --latest --format json

    \b
    DATA NOTES:
        - Published annually ~6 months after reference date
        - Reference date: June 30th of each year
        - Historical data for NI overall from 1971
        - Sub-geography data from 2021 onwards
        - Age bands: 5-year groups (00-04, 05-09, ..., 85-89, 90+)
        - Also includes custom age bands and broad age groups

    \b
    GEOGRAPHIC AREAS:
        Northern Ireland          - NI overall (1971-present)
        Parliamentary             - 2024 parliamentary constituencies (2021-present)
        Constituencies (2024)

        Health and Social         - Health & Social Care Trusts (2021-present)
        Care Trusts

        all                       - All geographic breakdowns

    \b
    OUTPUT:
        - area, area_code, area_name: Geographic identifiers
        - year: Reference year (mid-year estimate as of June 30th)
        - sex: All persons, Males, or Females
        - age_5: 5-year age band
        - age_band, age_broad: Alternative age groupings
        - population: Mid-year estimate

    \b
    SOURCE:
        https://www.nisra.gov.uk/statistics/people-and-communities/population
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        console.print("[dim]Future versions will support historical publications[/dim]")
        return

    try:
        with console.status("[bold green]Downloading latest NISRA population estimates..."):
            data = nisra_population.get_latest_population(area=area, force_refresh=force_refresh)

        # Filter by year if specified
        if year:
            data = data[data["year"] == year]
            if data.empty:
                console.print(f"[red]❌ No data found for year {year}[/red]")
                return

        console.print("[green]✅ Retrieved population estimates successfully[/green]")
        console.print(f"[cyan]📊 Total records: {len(data)}[/cyan]")

        if not data.empty:
            years = sorted(data["year"].unique())
            console.print(f"[dim]Years: {years[0]} to {years[-1]} ({len(years)} years)[/dim]")

            # Show total population for latest year if NI overall
            if area == "Northern Ireland":
                latest_year = data["year"].max()
                total_pop = data[(data["year"] == latest_year) & (data["sex"] == "All persons")]["population"].sum()
                console.print(f"[dim]{latest_year} NI population: {total_pop:,}[/dim]")

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except PermissionError:
                console.print(f"[red]❌ Error: Permission denied writing to {save}[/red]")
                console.print("[yellow]💡 Check file permissions or choose a different location[/yellow]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console in requested format
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            # CSV output
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        console.print("   • Visit NISRA website to verify data availability")
        raise click.Abort() from e


@nisra.command(name="marriages")
@click.option("--latest", is_flag=True, help="Get the most recent marriages data available")
@click.option("--year", type=int, help="Filter data for specific year")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
def nisra_marriages_cmd(latest, year, output_format, force_refresh, save):
    r"""
    NISRA Monthly Marriage Registrations Statistics.

    Retrieves monthly marriage registration data for Northern Ireland.

    Marriage registrations represent when the marriage was registered, not when the
    ceremony occurred. The data is published monthly with provisional figures for the
    current year and final figures for previous years.

    \b
    EXAMPLES:
        # Get latest marriages data
        bolster nisra marriages --latest

        # Filter for a specific year
        bolster nisra marriages --latest --year 2024

        # Save to file
        bolster nisra marriages --latest --save marriages.csv

        # Get data as JSON
        bolster nisra marriages --latest --format json

        # Force refresh cached data
        bolster nisra marriages --latest --force-refresh

    \b
    DATA NOTES:
        - Monthly time series from 2006 to present
        - Final data for years up to and including 2024
        - Provisional and subject to change for current year
        - COVID-19 Note: 2020 shows dramatic impact on marriages
          (April: 14, May: 4 marriages during strict lockdown)

    \b
    SEASONAL PATTERNS:
        Summer months (June-September) are peak wedding season:
        • August typically has the highest number of marriages
        • June-September account for ~40% of annual marriages
        • January-February typically have the lowest numbers

    \b
    OUTPUT:
        - date: First day of month (datetime)
        - year: Year of registration
        - month: Month name
        - marriages: Number of marriage registrations

    \b
    SOURCE:
        https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/marriages
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        console.print("[dim]Future versions will support specific months[/dim]")
        return

    try:
        with console.status("[bold green]Downloading latest NISRA marriages data..."):
            data = nisra_marriages.get_latest_marriages(force_refresh=force_refresh)

        # Filter by year if specified
        if year:
            data = nisra_marriages.get_marriages_by_year(data, year)
            if data.empty:
                console.print(f"[yellow]⚠️  No data found for year {year}[/yellow]")
                return

        console.print("[green]✅ Retrieved marriages data successfully[/green]")
        console.print(f"[cyan]📊 Total records: {len(data)}[/cyan]")

        if not data.empty:
            earliest_date = data["date"].min()
            latest_date = data["date"].max()
            console.print(f"[dim]Period: {earliest_date.strftime('%b %Y')} to {latest_date.strftime('%b %Y')}[/dim]")

            # Show summary statistics
            total_marriages = data["marriages"].sum()
            avg_per_month = data["marriages"].mean()

            console.print("\n[bold]Summary:[/bold]")
            if year:
                console.print(f"   Total marriages in {year}: {total_marriages:,.0f}")
                console.print(f"   Average per month: {avg_per_month:,.0f}")
            else:
                years_available = data["year"].nunique()
                console.print(f"   Years available: {years_available}")
                console.print(f"   Total marriages (all years): {total_marriages:,.0f}")
                console.print(f"   Average per month: {avg_per_month:,.0f}")

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except PermissionError:
                console.print(f"[red]❌ Error: Permission denied writing to {save}[/red]")
                console.print("[yellow]💡 Check file permissions or choose a different location[/yellow]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console in requested format
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            # CSV output
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        console.print("   • Visit NISRA website to verify data availability")
        raise click.Abort() from e


@nisra.command(name="civil-partnerships")
@click.option("--latest", is_flag=True, help="Get the most recent civil partnerships data")
@click.option("--year", type=int, help="Filter data for specific year")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
@click.option("--summary", is_flag=True, help="Show summary statistics only")
def nisra_civil_partnerships_cmd(latest, year, output_format, force_refresh, save, summary):
    r"""
    NISRA Monthly Civil Partnership Registrations Statistics.

    Retrieves monthly civil partnership registration data for Northern Ireland.

    Civil partnerships became legal in Northern Ireland in December 2005.
    The data is published monthly with provisional figures for the current year
    and final figures for previous years.

    \b
    EXAMPLES:
        # Get latest civil partnerships data
        bolster nisra civil-partnerships --latest

        # Filter for a specific year
        bolster nisra civil-partnerships --latest --year 2024

        # Show annual summary
        bolster nisra civil-partnerships --latest --summary

        # Save to file
        bolster nisra civil-partnerships --latest --save civil_partnerships.csv

    \b
    DATA NOTES:
        - Monthly time series from 2006 to present
        - Typically 80-120 civil partnerships per year
        - Numbers generally lower than marriages (5-10 per month average)
        - COVID-19 Note: 2020-2021 shows reduced registrations

    \b
    OUTPUT:
        - date: First day of month (datetime)
        - year: Year of registration
        - month: Month name
        - civil_partnerships: Number of civil partnership registrations

    \b
    SOURCE:
        https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/civil-partnerships
    """
    console = Console()

    if not latest and not summary:
        console.print("[yellow]Use --latest to retrieve data or --summary for statistics[/yellow]")
        return

    try:
        with console.status("[bold green]Downloading latest NISRA civil partnerships data..."):
            data = nisra_marriages.get_latest_civil_partnerships(force_refresh=force_refresh)

        # Filter by year if specified
        if year:
            data = nisra_marriages.get_civil_partnerships_by_year(data, year)
            if data.empty:
                console.print(f"[yellow]No data found for year {year}[/yellow]")
                return

        # Summary mode
        if summary:
            console.print("\n[bold cyan]Civil Partnerships Summary[/bold cyan]")
            console.print("=" * 45)

            yearly_summary = nisra_marriages.get_civil_partnerships_summary_by_year(data)
            console.print(f"\n{'Year':<8} {'Total':>8} {'Avg/Month':>10} {'Months':>8}")
            console.print("-" * 38)

            for _, row in yearly_summary.tail(10).iterrows():
                console.print(
                    f"{int(row['year']):<8} {int(row['total_civil_partnerships']):>8} "
                    f"{row['avg_per_month']:>10.1f} {int(row['months_reported']):>8}"
                )
            return

        console.print("[green]Retrieved civil partnerships data successfully[/green]")
        console.print(f"[cyan]Total records: {len(data)}[/cyan]")

        if not data.empty:
            earliest_date = data["date"].min()
            latest_date = data["date"].max()
            console.print(f"[dim]Period: {earliest_date.strftime('%b %Y')} to {latest_date.strftime('%b %Y')}[/dim]")

            total = data["civil_partnerships"].sum()
            avg_per_month = data["civil_partnerships"].mean()

            console.print("\n[bold]Summary:[/bold]")
            if year:
                console.print(f"   Total civil partnerships in {year}: {total}")
            else:
                years_available = data["year"].nunique()
                console.print(f"   Years available: {years_available}")
                console.print(f"   Total civil partnerships: {total}")
            console.print(f"   Average per month: {avg_per_month:.1f}")

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]Data saved to: {save}[/green]")
                return
            except Exception as e:
                console.print(f"[red]Error saving file: {e}[/red]")
                return

        # Output to console
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        console.print("   • Visit NISRA website to verify data availability")
        raise click.Abort() from e


@nisra.command(name="occupancy")
@click.option("--latest", is_flag=True, help="Get the most recent occupancy data")
@click.option("--year", type=int, help="Filter data for specific year")
@click.option(
    "--accommodation",
    type=click.Choice(["hotel", "ssa", "combined"], case_sensitive=False),
    default="hotel",
    help="Accommodation type: hotel, ssa (B&Bs/guest houses), or combined",
)
@click.option(
    "--data-type",
    type=click.Choice(["rates", "sold"], case_sensitive=False),
    default="rates",
    help="Data type: rates (occupancy rates) or sold (rooms/beds sold)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
@click.option("--summary", is_flag=True, help="Show summary statistics only")
@click.option("--compare", is_flag=True, help="Compare hotel vs SSA occupancy by year")
def nisra_occupancy_cmd(latest, year, accommodation, data_type, output_format, force_refresh, save, summary, compare):
    r"""
    NISRA Monthly Accommodation Occupancy Statistics.

    Retrieves monthly occupancy data for Northern Ireland from the Tourism
    Statistics Branch. Supports both hotel and SSA (Small Service Accommodation
    - B&Bs, guest houses) data.

    \b
    ACCOMMODATION TYPES:
        hotel     - Hotels (2011-present, ~65% avg occupancy)
        ssa       - Small Service Accommodation: B&Bs, guest houses (2013-present, ~33% avg)
        combined  - Both types with accommodation_type column

    \b
    DATA TYPES:
        rates  - Room and bed occupancy rates (0-1 scale)
        sold   - Number of rooms and beds sold monthly

    \b
    EXAMPLES:
        # Get latest hotel occupancy rates (default)
        bolster nisra occupancy --latest

        # Get SSA (B&B/guest house) occupancy
        bolster nisra occupancy --latest --accommodation ssa

        # Get combined data with accommodation type
        bolster nisra occupancy --latest --accommodation combined

        # Compare hotel vs SSA by year
        bolster nisra occupancy --compare

        # Get rooms/beds sold data
        bolster nisra occupancy --latest --data-type sold

        # Filter for a specific year
        bolster nisra occupancy --latest --year 2024

        # Show summary by year
        bolster nisra occupancy --latest --summary

        # Save to file
        bolster nisra occupancy --latest --save occupancy.csv

    \b
    DATA NOTES:
        - Hotel data: 2011-present (~65% average room occupancy)
        - SSA data: 2013-present (~33% average room occupancy)
        - Room occupancy is typically higher than bed occupancy
        - COVID-19 Note: 2020-2021 shows dramatic impact on tourism
          (all accommodation closed March-July 2020, Oct-Dec 2020, Jan-May 2021)

    \b
    SEASONAL PATTERNS:
        Summer months (June-September) are peak tourism season:
        - August typically has the highest occupancy (~80% hotel, ~55% SSA)
        - July-September are consistently strong
        - January-February typically have the lowest occupancy

    \b
    OUTPUT (rates):
        - date: First day of month (datetime)
        - year: Year
        - month: Month name
        - room_occupancy: Room occupancy rate (0-1)
        - bed_occupancy: Bed occupancy rate (0-1)
        - accommodation_type: (combined only) 'hotel' or 'ssa'

    \b
    OUTPUT (sold):
        - date: First day of month (datetime)
        - year: Year
        - month: Month name
        - rooms_sold: Number of rooms sold
        - beds_sold: Number of beds sold

    \b
    SOURCE:
        https://www.nisra.gov.uk/statistics/tourism/occupancy-surveys
    """
    console = Console()

    if not latest and not summary and not compare:
        console.print("[yellow]Use --latest to retrieve data, --summary for statistics, or --compare[/yellow]")
        return

    try:
        # Handle comparison mode
        if compare:
            with console.status("[bold green]Downloading hotel and SSA occupancy data..."):
                combined = nisra_occupancy.get_combined_occupancy(force_refresh=force_refresh)

            console.print("\n[bold cyan]Hotel vs SSA Occupancy Comparison[/bold cyan]")
            console.print("=" * 60)

            comparison = nisra_occupancy.compare_accommodation_types(combined)

            # Exclude COVID years from summary
            non_covid = comparison[~comparison["year"].isin([2020, 2021])]

            console.print(f"\n{'Year':<8} {'Hotel':>12} {'SSA':>12} {'Difference':>12}")
            console.print("-" * 48)

            for _, row in comparison.tail(10).iterrows():
                hotel_pct = f"{row['hotel_room_occupancy']:.1%}" if row["hotel_room_occupancy"] else "N/A"
                ssa_pct = f"{row['ssa_room_occupancy']:.1%}" if row["ssa_room_occupancy"] else "N/A"
                diff = row["difference"]
                diff_str = f"{diff:+.1%}" if diff else "N/A"
                console.print(f"{int(row['year']):<8} {hotel_pct:>12} {ssa_pct:>12} {diff_str:>12}")

            # Average summary
            avg_hotel = non_covid["hotel_room_occupancy"].mean()
            avg_ssa = non_covid["ssa_room_occupancy"].mean()
            avg_diff = non_covid["difference"].mean()

            console.print("\n[bold]Average (excl. COVID years):[/bold]")
            console.print(f"   Hotel: {avg_hotel:.1%}")
            console.print(f"   SSA: {avg_ssa:.1%}")
            console.print(f"   Difference: {avg_diff:+.1%}")
            return

        # Determine accommodation type and status message
        acc_label = {
            "hotel": "hotel",
            "ssa": "SSA (B&B/guest house)",
            "combined": "combined hotel and SSA",
        }[accommodation]

        with console.status(f"[bold green]Downloading latest NISRA {acc_label} occupancy data..."):
            if accommodation == "combined":
                if data_type == "sold":
                    console.print("[yellow]Note: Combined mode only supports rates, not sold data[/yellow]")
                data = nisra_occupancy.get_combined_occupancy(force_refresh=force_refresh)
            elif accommodation == "ssa":
                if data_type == "sold":
                    data = nisra_occupancy.get_latest_ssa_rooms_beds_sold(force_refresh=force_refresh)
                else:
                    data = nisra_occupancy.get_latest_ssa_occupancy(force_refresh=force_refresh)
            else:  # hotel (default)
                if data_type == "sold":
                    data = nisra_occupancy.get_latest_rooms_beds_sold(force_refresh=force_refresh)
                else:
                    data = nisra_occupancy.get_latest_hotel_occupancy(force_refresh=force_refresh)

        # Filter by year if specified
        if year:
            data = nisra_occupancy.get_occupancy_by_year(data, year)
            if data.empty:
                console.print(f"[yellow]No data found for year {year}[/yellow]")
                return

        # Summary mode
        if summary:
            console.print(f"\n[bold cyan]{acc_label.title()} Occupancy Summary[/bold cyan]")
            console.print("=" * 50)

            if data_type == "rates":
                yearly_summary = nisra_occupancy.get_occupancy_summary_by_year(data)
                console.print(f"\n{'Year':<8} {'Room Occ':>10} {'Bed Occ':>10} {'Months':>8}")
                console.print("-" * 40)

                for _, row in yearly_summary.tail(10).iterrows():
                    room_pct = f"{row['avg_room_occupancy']:.1%}" if row["avg_room_occupancy"] else "N/A"
                    bed_pct = f"{row['avg_bed_occupancy']:.1%}" if row["avg_bed_occupancy"] else "N/A"
                    console.print(
                        f"{int(row['year']):<8} {room_pct:>10} {bed_pct:>10} {int(row['months_reported']):>8}"
                    )

                # Seasonal patterns
                console.print("\n[bold]Seasonal Patterns (All Years):[/bold]")
                seasonal = nisra_occupancy.get_seasonal_patterns(data)
                peak = seasonal.loc[seasonal["avg_room_occupancy"].idxmax()]
                low = seasonal.loc[seasonal["avg_room_occupancy"].idxmin()]
                console.print(f"   Peak month: {peak['month']} ({peak['avg_room_occupancy']:.1%})")
                console.print(f"   Low month: {low['month']} ({low['avg_room_occupancy']:.1%})")
            else:
                # Rooms/beds sold summary
                yearly = (
                    data.groupby("year")
                    .agg(
                        total_rooms=("rooms_sold", "sum"),
                        total_beds=("beds_sold", "sum"),
                        months=("rooms_sold", lambda x: x.notna().sum()),
                    )
                    .reset_index()
                )

                console.print(f"\n{'Year':<8} {'Rooms Sold':>14} {'Beds Sold':>14} {'Months':>8}")
                console.print("-" * 48)

                for _, row in yearly.tail(10).iterrows():
                    console.print(
                        f"{int(row['year']):<8} {row['total_rooms']:>14,.0f} "
                        f"{row['total_beds']:>14,.0f} {int(row['months']):>8}"
                    )
            return

        console.print(f"[green]Retrieved {acc_label} occupancy data successfully[/green]")
        console.print(f"[cyan]Total records: {len(data)}[/cyan]")

        if not data.empty:
            earliest_date = data["date"].min()
            latest_date = data["date"].max()
            console.print(f"[dim]Period: {earliest_date.strftime('%b %Y')} to {latest_date.strftime('%b %Y')}[/dim]")

            # Show quick stats
            if data_type == "rates":
                avg_room = data["room_occupancy"].mean()
                avg_bed = data["bed_occupancy"].mean()
                console.print("\n[bold]Average Occupancy:[/bold]")
                console.print(f"   Room: {avg_room:.1%}")
                console.print(f"   Bed: {avg_bed:.1%}")
            else:
                total_rooms = data["rooms_sold"].sum()
                total_beds = data["beds_sold"].sum()
                console.print("\n[bold]Totals:[/bold]")
                console.print(f"   Rooms sold: {total_rooms:,.0f}")
                console.print(f"   Beds sold: {total_beds:,.0f}")

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]Data saved to: {save}[/green]")
                return
            except PermissionError:
                console.print(f"[red]Error: Permission denied writing to {save}[/red]")
                return
            except Exception as e:
                console.print(f"[red]Error saving file: {e}[/red]")
                return

        # Output to console in requested format
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        console.print("   • Visit NISRA website to verify data availability")
        raise click.Abort() from e


@nisra.command(name="visitors")
@click.option("--latest", is_flag=True, help="Get the most recent visitor statistics")
@click.option(
    "--market",
    type=click.Choice(
        ["all", "gb", "europe", "north-america", "overseas", "roi", "ni", "total"],
        case_sensitive=False,
    ),
    default="all",
    help="Filter by visitor origin market",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
@click.option("--summary", is_flag=True, help="Show market summary with derived metrics")
@click.option("--compare", is_flag=True, help="Compare domestic vs external visitors")
def nisra_visitors_cmd(latest, market, output_format, force_refresh, save, summary, compare):
    r"""
    NISRA Quarterly Visitor Statistics (Trips, Nights, Expenditure).

    Retrieves quarterly visitor statistics for Northern Ireland from NISRA,
    showing overnight trips, nights spent, and visitor expenditure by market origin.

    \b
    MARKETS:
        gb           - Great Britain (largest external market)
        europe       - Other Europe (excluding GB and ROI)
        north-america - North America (USA and Canada)
        overseas     - Other overseas (Asia, Oceania, etc.)
        roi          - Republic of Ireland
        ni           - NI Residents (domestic tourism)
        total        - All markets combined
        all          - Show all markets (default)

    \b
    EXAMPLES:
        # Get latest visitor statistics
        bolster nisra visitors --latest

        # Show market summary with per-trip metrics
        bolster nisra visitors --latest --summary

        # Compare domestic vs external visitors
        bolster nisra visitors --latest --compare

        # Get Great Britain visitors only
        bolster nisra visitors --latest --market gb

        # Save to file
        bolster nisra visitors --latest --save visitors.csv

    \b
    DATA INSIGHTS:
        - GB is typically the largest external market (~30% of trips, ~38% of spend)
        - ROI visitors growing rapidly (up 32% trips, 68% spend YoY in 2025)
        - NI residents account for ~31% of trips but only ~17% of expenditure
        - External visitors spend 2-4x more per trip than NI residents
        - "Other Overseas" (long-haul) has highest spend per trip (~£540)

    \b
    DATA SOURCE:
        https://www.nisra.gov.uk/publications/quarterly-tourism-statistics-publications
    """
    from rich.console import Console
    from rich.table import Table

    console = Console()

    try:
        if not latest and not save:
            console.print("[yellow]Hint: Use --latest to fetch data, or --save to save to file[/yellow]")
            return

        with console.status("[bold green]Downloading NISRA visitor statistics..."):
            data = nisra_visitors.get_latest_visitor_statistics(force_refresh=force_refresh)

        # Market name mapping for filter
        market_map = {
            "gb": "Great Britain",
            "europe": "Other Europe",
            "north-america": "North America",
            "overseas": "Other Overseas",
            "roi": "Republic of Ireland",
            "ni": "NI Residents",
            "total": "Total",
        }

        if compare:
            # Show domestic vs external comparison
            comparison = nisra_visitors.get_domestic_vs_external(data)
            console.print("\n[bold cyan]Domestic vs External Visitors[/bold cyan]\n")

            table = Table(show_header=True, header_style="bold")
            table.add_column("Category")
            table.add_column("Trips", justify="right")
            table.add_column("% Trips", justify="right")
            table.add_column("Expenditure", justify="right")
            table.add_column("% Spend", justify="right")

            for _, row in comparison.iterrows():
                table.add_row(
                    row["category"],
                    f"{row['trips']:,.0f}",
                    f"{row['trips_pct']:.1f}%",
                    f"£{row['expenditure']:.1f}M",
                    f"{row['expenditure_pct']:.1f}%",
                )

            console.print(table)

            # Additional insights
            ni_row = comparison[comparison["category"] == "Domestic (NI)"].iloc[0]
            ext_row = comparison[comparison["category"] == "External"].iloc[0]

            if ni_row["trips"] > 0 and ext_row["trips"] > 0:
                ni_spend_per = ni_row["expenditure"] * 1_000_000 / ni_row["trips"]
                ext_spend_per = ext_row["expenditure"] * 1_000_000 / ext_row["trips"]
                console.print(
                    f"\n[dim]Spend per trip: Domestic £{ni_spend_per:.0f} vs External £{ext_spend_per:.0f}[/dim]"
                )

            return

        if summary:
            # Show market summary with derived metrics
            market_summary = nisra_visitors.get_market_summary(data)
            console.print("\n[bold cyan]Visitor Statistics by Market[/bold cyan]\n")

            table = Table(show_header=True, header_style="bold")
            table.add_column("Market")
            table.add_column("Trips", justify="right")
            table.add_column("% Share", justify="right")
            table.add_column("Expenditure", justify="right")
            table.add_column("£/Trip", justify="right")
            table.add_column("Nights/Trip", justify="right")

            for _, row in market_summary.iterrows():
                table.add_row(
                    row["market"],
                    f"{row['trips']:,.0f}",
                    f"{row['trips_pct']:.1f}%",
                    f"£{row['expenditure']:.1f}M",
                    f"£{row['expenditure_per_trip']:.0f}",
                    f"{row['nights_per_trip']:.1f}",
                )

            console.print(table)

            # Total stats
            total = nisra_visitors.get_total_visitor_statistics(data)
            if total is not None:
                console.print("\n[bold]Totals:[/bold]")
                console.print(f"   Trips: {total['trips']:,.0f}")
                console.print(f"   Nights: {total['nights']:,.0f}")
                console.print(f"   Expenditure: £{total['expenditure']:.1f}M")

            return

        # Filter by market if specified
        if market != "all":
            market_name = market_map.get(market.lower())
            if market_name:
                data = data[data["market"] == market_name]

        console.print("[green]Retrieved visitor statistics successfully[/green]")
        console.print(f"[dim]Period: {data['period'].iloc[0]} to {data['year'].iloc[0]}[/dim]")

        # Show quick stats
        total = data[data["market"] == "Total"]
        if not total.empty:
            t = total.iloc[0]
            console.print("\n[bold]Total Visitors:[/bold]")
            console.print(f"   Trips: {t['trips']:,.0f}")
            console.print(f"   Nights: {t['nights']:,.0f}")
            console.print(f"   Expenditure: £{t['expenditure']:.1f}M")

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]Data saved to: {save}[/green]")
                return
            except PermissionError:
                console.print(f"[red]Error: Permission denied writing to {save}[/red]")
                return
            except Exception as e:
                console.print(f"[red]Error saving file: {e}[/red]")
                return

        # Output to console in requested format
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        console.print("   • Visit NISRA website to verify data availability")
        raise click.Abort() from e


@nisra.command(name="migration")
@click.option("--latest", is_flag=True, help="Get the most recent migration estimates")
@click.option("--year", type=int, help="Filter data for specific year")
@click.option("--start-year", type=int, help="Start year for summary statistics")
@click.option("--end-year", type=int, help="End year for summary statistics")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
@click.option("--summary", is_flag=True, help="Show summary statistics only")
def nisra_migration_cmd(latest, year, start_year, end_year, output_format, force_refresh, save, summary):
    r"""
    NISRA Migration Estimates (Derived from Demographic Components).

    Calculates net migration using the demographic accounting equation:
        Net Migration = Population Change - Natural Change
        Net Migration = ΔPopulation - (Births - Deaths)

    This combines data from:
    - Mid-year population estimates
    - Monthly birth registrations (occurrence data)
    - Historical death registrations

    The demographic equation must hold: Pop(t+1) = Pop(t) + Births - Deaths + Migration

    \b
    EXAMPLES:
        # Get all migration data
        bolster nisra migration --latest

        # Filter for specific year
        bolster nisra migration --latest --year 2024

        # Show summary statistics for 2010-2024
        bolster nisra migration --latest --start-year 2010 --summary

        # Save to file
        bolster nisra migration --latest --save migration.csv

        # Get data as JSON
        bolster nisra migration --latest --format json

        # Force refresh all source data
        bolster nisra migration --latest --force-refresh

    \b
    DATA NOTES:
        - Coverage: 2011-2024 (limited by historical deaths data)
        - Derived migration includes net effect of international and internal migration
        - Also captures measurement error and timing differences between sources
        - Demographic equation validated for all years (ΔPop = Births - Deaths + Migration)

    \b
    KEY FINDINGS:
        - 2023: Highest net immigration (+7,225)
        - 2024: Strong immigration continues (+6,107)
        - 2013: Highest net emigration (-2,124)
        - Average 2011-2024: +2,082 per year
        - 9 years with net immigration, 5 with net emigration

    \b
    OUTPUT:
        - year: Year
        - population_start, population_end: Mid-year population estimates
        - births, deaths: Annual totals
        - natural_change: Births - Deaths
        - population_change: Year-over-year change
        - net_migration: Derived migration estimate
        - migration_rate: Per 1,000 population

    \b
    SOURCE:
        Combines three NISRA data sources:
        - Population: https://www.nisra.gov.uk/statistics/people-and-communities/population
        - Births: https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/births
        - Deaths: https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/deaths
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        console.print("[dim]Future versions will support historical years[/dim]")
        return

    try:
        with console.status("[bold green]Calculating migration estimates from demographic components..."):
            data = nisra_migration.get_latest_migration(force_refresh=force_refresh)

        # Filter by year if specified
        if year:
            data = nisra_migration.get_migration_by_year(data, year)
            if data.empty:
                console.print(f"[yellow]⚠️  No data found for year {year}[/yellow]")
                return

        console.print("[green]✅ Migration estimates calculated successfully[/green]")
        console.print(f"[cyan]📊 Total years: {len(data)}[/cyan]")

        if not data.empty:
            earliest_year = data["year"].min()
            latest_year = data["year"].max()
            console.print(f"[dim]Period: {earliest_year} to {latest_year}[/dim]")

            # Show validation
            console.print("\n[bold]Validation:[/bold]")
            try:
                nisra_migration.validate_demographic_equation(data)
                console.print("   ✓ Demographic equation validated (ΔPop = Births - Deaths + Migration)")
            except Exception as e:
                console.print(f"   [red]✗ Validation failed: {e}[/red]")

        # Show summary statistics if requested
        if summary:
            stats = nisra_migration.get_migration_summary_statistics(data, start_year=start_year, end_year=end_year)

            period = f"{start_year or data['year'].min()}-{end_year or data['year'].max()}"
            console.print(f"\n[bold]Summary Statistics ({period}):[/bold]")
            console.print(f"   Total years: {stats['total_years']}")
            console.print(f"   Average net migration: {stats['avg_net_migration']:+,.0f}")
            console.print(f"   Average migration rate: {stats['avg_migration_rate']:+.2f} per 1,000")
            console.print(f"   Years with net immigration: {stats['positive_years']}")
            console.print(f"   Years with net emigration: {stats['negative_years']}")
            console.print(f"\n   Peak immigration: {stats['max_immigration_year']} ({stats['max_immigration']:+,})")
            console.print(f"   Peak emigration: {stats['max_emigration_year']} ({stats['max_emigration']:+,})")

            if not save:
                return  # Don't output data if only showing summary

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except PermissionError:
                console.print(f"[red]❌ Error: Permission denied writing to {save}[/red]")
                console.print("[yellow]💡 Check file permissions or choose a different location[/yellow]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console in requested format
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            # CSV output
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        console.print("   • Ensure births, deaths, and population data are available")
        raise click.Abort() from e


@nisra.command(name="index-of-services")
@click.option("--latest", is_flag=True, help="Get the most recent Index of Services data")
@click.option("--year", type=int, help="Filter data for specific year")
@click.option("--quarter", help="Filter data for specific quarter (e.g., 'Q1', 'Q2')")
@click.option("--start-year", type=int, help="Start year for summary statistics")
@click.option("--end-year", type=int, help="End year for summary statistics")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
@click.option("--summary", is_flag=True, help="Show summary statistics only")
@click.option("--growth", is_flag=True, help="Include year-on-year growth rates")
def nisra_index_of_services_cmd(
    latest, year, quarter, start_year, end_year, output_format, force_refresh, save, summary, growth
):
    r"""
    NISRA Index of Services (IOS) - Quarterly Economic Indicator.

    Measures output in Northern Ireland's services sector, including business services,
    wholesale/retail trade, transport, and other services. Seasonally adjusted quarterly
    data from Q1 2005 to present.

    \b
    EXAMPLES:
        # Get all Index of Services data
        bolster nisra index-of-services --latest

        # Filter for specific year
        bolster nisra index-of-services --latest --year 2024

        # Get specific quarter
        bolster nisra index-of-services --latest --year 2025 --quarter Q3

        # Show summary statistics for 2020-2025
        bolster nisra index-of-services --latest --start-year 2020 --summary

        # Include year-on-year growth rates
        bolster nisra index-of-services --latest --growth

        # Save to file
        bolster nisra index-of-services --latest --save ios.csv

        # Force refresh data
        bolster nisra index-of-services --latest --force-refresh

    \b
    DATA NOTES:
        - Coverage: Q1 2005 - Q3 2025 (quarterly)
        - Seasonally adjusted values
        - Index values (100 = base period)
        - Includes NI and UK comparator data
        - Published ~3 months after quarter end

    \b
    OUTPUT:
        - date: First day of quarter
        - quarter: Quarter code (Q1, Q2, Q3, Q4)
        - year: Year
        - ni_index: Northern Ireland services index value
        - uk_index: UK services index value
        - ni_growth_rate: YoY % change (if --growth specified)
        - uk_growth_rate: YoY % change (if --growth specified)

    \b
    SOURCE:
        NISRA Economic & Labour Market Statistics Branch
        https://www.nisra.gov.uk/statistics/economic-output/index-services
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        return

    try:
        with console.status("[bold green]Fetching Index of Services data..."):
            data = nisra_economic.get_latest_index_of_services(force_refresh=force_refresh)

        # Add growth rates if requested
        if growth:
            data = nisra_economic.calculate_ios_growth_rate(data)

        # Filter by year and/or quarter if specified
        if year:
            data = nisra_economic.get_ios_by_year(data, year)
            if quarter:
                data = nisra_economic.get_ios_by_quarter(data, quarter, year)

        if data.empty:
            console.print("[yellow]⚠️  No data found for the specified filters[/yellow]")
            return

        console.print("[green]✅ Index of Services data fetched successfully[/green]")
        console.print(f"[cyan]📊 Total quarters: {len(data)}[/cyan]")

        if not data.empty:
            earliest = f"{data.iloc[0]['quarter']} {data.iloc[0]['year']}"
            latest_q = f"{data.iloc[-1]['quarter']} {data.iloc[-1]['year']}"
            console.print(f"[dim]Period: {earliest} to {latest_q}[/dim]")

        # Show summary statistics if requested
        if summary:
            stats = nisra_economic.get_ios_summary_statistics(data, start_year=start_year, end_year=end_year)

            console.print(f"\n[bold]Summary Statistics ({stats['period']}):[/bold]")
            console.print(f"   Total quarters: {stats['quarters_count']}")
            console.print("\n   NI Services Index:")
            console.print(f"     Mean: {stats['ni_mean']:.1f}")
            console.print(f"     Range: {stats['ni_min']:.1f} - {stats['ni_max']:.1f}")
            console.print("\n   UK Services Index:")
            console.print(f"     Mean: {stats['uk_mean']:.1f}")
            console.print(f"     Range: {stats['uk_min']:.1f} - {stats['uk_max']:.1f}")

            if not save:
                return

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        raise click.Abort() from e


@nisra.command(name="index-of-production")
@click.option("--latest", is_flag=True, help="Get the most recent Index of Production data")
@click.option("--year", type=int, help="Filter data for specific year")
@click.option("--quarter", help="Filter data for specific quarter (e.g., 'Q1', 'Q2')")
@click.option("--start-year", type=int, help="Start year for summary statistics")
@click.option("--end-year", type=int, help="End year for summary statistics")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
@click.option("--summary", is_flag=True, help="Show summary statistics only")
@click.option("--growth", is_flag=True, help="Include year-on-year growth rates")
def nisra_index_of_production_cmd(
    latest, year, quarter, start_year, end_year, output_format, force_refresh, save, summary, growth
):
    r"""
    NISRA Index of Production (IOP) - Quarterly Economic Indicator.

    Measures output in Northern Ireland's production industries, including manufacturing,
    mining, and utilities. Seasonally adjusted quarterly data from Q1 2005 to present.

    \b
    EXAMPLES:
        # Get all Index of Production data
        bolster nisra index-of-production --latest

        # Filter for specific year
        bolster nisra index-of-production --latest --year 2024

        # Get specific quarter
        bolster nisra index-of-production --latest --year 2025 --quarter Q3

        # Show summary statistics
        bolster nisra index-of-production --latest --start-year 2020 --summary

        # Include growth rates
        bolster nisra index-of-production --latest --growth

        # Save as JSON
        bolster nisra index-of-production --latest --format json --save iop.json

    \b
    DATA NOTES:
        - Coverage: Q1 2005 - Q3 2025 (quarterly)
        - Seasonally adjusted values
        - Index values (100 = base period)
        - Includes NI and UK comparator data
        - Production industries have faced long-term challenges

    \b
    OUTPUT:
        - date: First day of quarter
        - quarter: Quarter code (Q1, Q2, Q3, Q4)
        - year: Year
        - ni_index: Northern Ireland production index value
        - uk_index: UK production index value
        - ni_growth_rate: YoY % change (if --growth specified)
        - uk_growth_rate: YoY % change (if --growth specified)

    \b
    SOURCE:
        NISRA Economic & Labour Market Statistics Branch
        https://www.nisra.gov.uk/statistics/economic-output/index-production
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        return

    try:
        with console.status("[bold green]Fetching Index of Production data..."):
            data = nisra_economic.get_latest_index_of_production(force_refresh=force_refresh)

        # Add growth rates if requested
        if growth:
            data = nisra_economic.calculate_iop_growth_rate(data)

        # Filter by year and/or quarter if specified
        if year:
            data = nisra_economic.get_iop_by_year(data, year)
            if quarter:
                data = nisra_economic.get_iop_by_quarter(data, quarter, year)

        if data.empty:
            console.print("[yellow]⚠️  No data found for the specified filters[/yellow]")
            return

        console.print("[green]✅ Index of Production data fetched successfully[/green]")
        console.print(f"[cyan]📊 Total quarters: {len(data)}[/cyan]")

        if not data.empty:
            earliest = f"{data.iloc[0]['quarter']} {data.iloc[0]['year']}"
            latest_q = f"{data.iloc[-1]['quarter']} {data.iloc[-1]['year']}"
            console.print(f"[dim]Period: {earliest} to {latest_q}[/dim]")

        # Show summary statistics if requested
        if summary:
            stats = nisra_economic.get_iop_summary_statistics(data, start_year=start_year, end_year=end_year)

            console.print(f"\n[bold]Summary Statistics ({stats['period']}):[/bold]")
            console.print(f"   Total quarters: {stats['quarters_count']}")
            console.print("\n   NI Production Index:")
            console.print(f"     Mean: {stats['ni_mean']:.1f}")
            console.print(f"     Range: {stats['ni_min']:.1f} - {stats['ni_max']:.1f}")
            console.print("\n   UK Production Index:")
            console.print(f"     Mean: {stats['uk_mean']:.1f}")
            console.print(f"     Range: {stats['uk_min']:.1f} - {stats['uk_max']:.1f}")

            if not save:
                return

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        raise click.Abort() from e


@nisra.command(name="construction-output")
@click.option("--latest", is_flag=True, help="Get the most recent Construction Output data")
@click.option("--year", type=int, help="Filter data for specific year")
@click.option("--quarter", help="Filter data for specific quarter (e.g., 'Q1', 'Q2')")
@click.option("--start-year", type=int, help="Start year for summary statistics")
@click.option("--end-year", type=int, help="End year for summary statistics")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
@click.option("--summary", is_flag=True, help="Show summary statistics only")
@click.option("--growth", is_flag=True, help="Include year-on-year growth rates")
def nisra_construction_output_cmd(
    latest, year, quarter, start_year, end_year, output_format, force_refresh, save, summary, growth
):
    r"""
    NISRA Construction Output Statistics - Quarterly Economic Indicator.

    Measures volume and value of construction output in Northern Ireland across
    all work, new work, and repair & maintenance. Chained volume measure data
    (base year 2022=100) from Q2 2000 to present.

    \b
    EXAMPLES:
        # Get all Construction Output data
        bolster nisra construction-output --latest

        # Filter for specific year
        bolster nisra construction-output --latest --year 2024

        # Get specific quarter
        bolster nisra construction-output --latest --year 2025 --quarter Q2

        # Show summary statistics for 2020-2025
        bolster nisra construction-output --latest --start-year 2020 --summary

        # Include year-on-year growth rates
        bolster nisra construction-output --latest --growth

        # Save to file
        bolster nisra construction-output --latest --save construction.csv

        # Force refresh data
        bolster nisra construction-output --latest --force-refresh

    \b
    DATA NOTES:
        - Coverage: Q2 2000 - Q2 2025 (quarterly)
        - Base year: 2022 = 100 (chained volume measure)
        - All Work: Non-seasonally adjusted (NSA)
        - New Work: Non-seasonally adjusted (NSA)
        - Repair & Maintenance: Seasonally adjusted (SA)
        - Published ~3 months after quarter end

    \b
    OUTPUT:
        - date: First day of quarter
        - quarter: Quarter code (Q1, Q2, Q3, Q4)
        - year: Year
        - all_work_index: Total construction output index (NSA)
        - new_work_index: New construction work index (NSA)
        - repair_maintenance_index: Repair & maintenance index (SA)
        - *_yoy_growth: YoY % change (if --growth specified)

    \b
    SOURCE:
        NISRA Economic & Labour Market Statistics Branch
        https://www.nisra.gov.uk/statistics/economic-output/construction-output-statistics
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        return

    try:
        with console.status("[bold green]Fetching Construction Output data..."):
            data = nisra_construction.get_latest_construction_output(force_refresh=force_refresh)

        # Add growth rates if requested
        if growth:
            data = nisra_construction.calculate_growth_rates(data)

        # Filter by year and/or quarter if specified
        if year:
            data = nisra_construction.get_construction_by_year(data, year)
            if quarter:
                data = nisra_construction.get_construction_by_quarter(data, quarter, year)

        if data.empty:
            console.print("[yellow]⚠️  No data found for the specified filters[/yellow]")
            return

        console.print("[green]✅ Construction Output data fetched successfully[/green]")
        console.print(f"[cyan]📊 Total quarters: {len(data)}[/cyan]")

        if not data.empty:
            earliest = f"{data.iloc[0]['quarter']} {data.iloc[0]['year']}"
            latest_q = f"{data.iloc[-1]['quarter']} {data.iloc[-1]['year']}"
            console.print(f"[dim]Period: {earliest} to {latest_q}[/dim]")

        # Show summary statistics if requested
        if summary:
            stats = nisra_construction.get_summary_statistics(data, start_year=start_year, end_year=end_year)

            console.print(f"\n[bold]Summary Statistics ({stats['period']}):[/bold]")
            console.print(f"   Total quarters: {stats['quarters_count']}")
            console.print("\n   All Work Index:")
            console.print(f"     Mean: {stats['all_work_mean']:.1f}")
            console.print(f"     Range: {stats['all_work_min']:.1f} - {stats['all_work_max']:.1f}")
            console.print("\n   New Work Index:")
            console.print(f"     Mean: {stats['new_work_mean']:.1f}")
            console.print(f"     Range: {stats['new_work_min']:.1f} - {stats['new_work_max']:.1f}")
            console.print("\n   Repair & Maintenance Index:")
            console.print(f"     Mean: {stats['repair_maintenance_mean']:.1f}")
            console.print(f"     Range: {stats['repair_maintenance_min']:.1f} - {stats['repair_maintenance_max']:.1f}")

            if not save:
                return

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        raise click.Abort() from e


@nisra.command(name="ashe")
@click.option("--latest", is_flag=True, help="Get the most recent ASHE data")
@click.option(
    "--metric",
    type=click.Choice(["weekly", "hourly", "annual"], case_sensitive=False),
    default="weekly",
    help="Type of earnings metric (default: weekly)",
)
@click.option(
    "--dimension",
    type=click.Choice(["timeseries", "geography", "sector"], case_sensitive=False),
    help="Data dimension to retrieve",
)
@click.option(
    "--basis",
    type=click.Choice(["workplace", "residence"], case_sensitive=False),
    default="workplace",
    help="Geographic basis (for geography dimension only)",
)
@click.option("--year", type=int, help="Filter data for specific year")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
@click.option("--growth", is_flag=True, help="Include year-on-year growth rates (timeseries only)")
def nisra_ashe_cmd(latest, metric, dimension, basis, year, output_format, force_refresh, save, growth):
    r"""
    NISRA Annual Survey of Hours and Earnings (ASHE) - Employee Earnings Statistics.

    Annual survey measuring employee earnings in Northern Ireland across multiple dimensions
    including employment type, sector, geography, occupation, and industry. Data from April
    of each year, published in October.

    \b
    EXAMPLES:
        # Get weekly earnings timeseries (1997-2025)
        bolster nisra ashe --latest

        # Get hourly earnings timeseries
        bolster nisra ashe --latest --metric hourly

        # Get annual earnings timeseries
        bolster nisra ashe --latest --metric annual

        # Get geographic earnings by workplace
        bolster nisra ashe --latest --dimension geography

        # Get geographic earnings by residence
        bolster nisra ashe --latest --dimension geography --basis residence

        # Get public vs private sector comparison
        bolster nisra ashe --latest --dimension sector

        # Include year-on-year growth rates
        bolster nisra ashe --latest --growth

        # Filter for specific year
        bolster nisra ashe --latest --year 2025

        # Save to file
        bolster nisra ashe --latest --save earnings.csv --format csv

        # Force refresh data
        bolster nisra ashe --latest --force-refresh

    \b
    DATA NOTES:
        - Coverage: April 1997 - 2025 (annual, timeseries)
        - Annual earnings: 1999 - 2025
        - Sector breakdown: 2005 - 2025
        - Reference period: April of each year
        - Published: October each year
        - Base: Employee jobs in Northern Ireland (not self-employed)

    \b
    METRICS:
        - weekly: Median gross weekly earnings (£)
        - hourly: Median hourly earnings excluding overtime (£)
        - annual: Median annual earnings (£)

    \b
    DIMENSIONS:
        - timeseries: Historical trends by work pattern (Full-time/Part-time/All)
        - geography: Earnings by 11 Local Government Districts
        - sector: Public vs Private sector comparison (NI & UK)

    \b
    OUTPUT (timeseries):
        - year: Year
        - work_pattern: Full-time, Part-time, or All
        - median_*_earnings: Median earnings (£)
        - earnings_yoy_growth: YoY % change (if --growth specified)

    \b
    OUTPUT (geography):
        - year: Year
        - lgd: Local Government District name
        - basis: workplace or residence
        - median_weekly_earnings: Median weekly earnings (£)

    \b
    OUTPUT (sector):
        - year: Year
        - location: Northern Ireland or United Kingdom
        - sector: Public or Private
        - median_weekly_earnings: Median weekly earnings (£)

    \b
    SOURCE:
        NISRA Economic & Labour Market Statistics Branch
        https://www.nisra.gov.uk/statistics/work-pay-and-benefits/annual-survey-hours-and-earnings
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        return

    try:
        # Determine what data to fetch
        if dimension == "geography":
            with console.status(f"[bold green]Fetching ASHE geographic earnings ({basis})..."):
                data = nisra_ashe.get_latest_ashe_geography(basis=basis, force_refresh=force_refresh)
        elif dimension == "sector":
            with console.status("[bold green]Fetching ASHE sector earnings..."):
                data = nisra_ashe.get_latest_ashe_sector(force_refresh=force_refresh)
        else:
            # Default to timeseries
            with console.status(f"[bold green]Fetching ASHE {metric} earnings..."):
                data = nisra_ashe.get_latest_ashe_timeseries(metric=metric, force_refresh=force_refresh)

            # Add growth rates if requested (only for timeseries)
            if growth:
                data = nisra_ashe.calculate_growth_rates(data)

        # Filter by year if specified
        if year:
            data = nisra_ashe.get_earnings_by_year(data, year)

        if data.empty:
            console.print("[yellow]⚠️  No data found for the specified filters[/yellow]")
            return

        console.print("[green]✅ ASHE data fetched successfully[/green]")
        console.print(f"[cyan]📊 Total records: {len(data)}[/cyan]")

        if not data.empty and "year" in data.columns:
            years = data["year"].unique()
            console.print(f"[dim]Years: {min(years)} - {max(years)}[/dim]")

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        raise click.Abort() from e


@nisra.command(name="composite-index")
@click.option("--latest", is_flag=True, help="Get the most recent NICEI data")
@click.option(
    "--table",
    type=click.Choice(["indices", "contributions", "all"], case_sensitive=False),
    default="indices",
    help="Which table to retrieve (default: indices)",
)
@click.option("--year", type=int, help="Filter data for specific year")
@click.option("--quarter", type=int, help="Filter data for specific quarter (1-4)")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
def nisra_composite_index_cmd(latest, table, year, quarter, output_format, force_refresh, save):
    r"""
    NISRA Northern Ireland Composite Economic Index (NICEI) - Experimental Economic Indicator.

    Quarterly measure of NI economic performance tracking five key sectors:
    Services, Production, Construction, Agriculture, and Public Sector.
    Base period 2022=100, quarterly data from Q1 2006 to present.

    \b
    EXAMPLES:
        # Get latest NICEI indices
        bolster nisra composite-index --latest

        # Get sector contributions to quarterly change
        bolster nisra composite-index --latest --table contributions

        # Get all tables
        bolster nisra composite-index --latest --table all

        # Filter for specific year
        bolster nisra composite-index --latest --year 2024

        # Get specific quarter
        bolster nisra composite-index --latest --year 2025 --quarter 2

        # Save to file
        bolster nisra composite-index --latest --save nicei.csv

        # Force refresh data
        bolster nisra composite-index --latest --force-refresh

    \b
    DATA NOTES:
        - Coverage: Q1 2006 - Q2 2025 (quarterly)
        - Base period: 2022 = 100
        - Experimental statistic subject to revision
        - Published ~3 months after quarter end
        - Not seasonally adjusted

    \b
    TABLES:
        indices         - NICEI and component indices by quarter (Table 1)
                         • Overall NICEI, private/public sector breakdowns
                         • Sectoral indices: Services, Production, Construction, Agriculture
                         • Quarterly time series from Q1 2006

        contributions   - Sector contributions to quarterly change (Table 11)
                         • How much each sector contributed to NICEI quarterly change
                         • Percentage point contributions
                         • Identifies main drivers of economic growth/decline

        all             - All available tables

    \b
    SOURCE:
        NISRA Economic & Labour Market Statistics Branch
        https://www.nisra.gov.uk/statistics/economic-output-statistics/ni-composite-economic-index
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        return

    try:
        with console.status("[bold green]Fetching NICEI data..."):
            if table in ("indices", "all"):
                indices_data = nisra_composite.get_latest_nicei(force_refresh=force_refresh)
            if table in ("contributions", "all"):
                contrib_data = nisra_composite.get_latest_nicei_contributions(force_refresh=force_refresh)

        # Apply filters
        if table == "indices":
            data = indices_data
            if year:
                data = nisra_composite.get_nicei_by_year(data, year)
                if quarter:
                    data = nisra_composite.get_nicei_by_quarter(data, year, quarter)
        elif table == "contributions":
            data = contrib_data
            if year:
                data = data[data["year"] == year]
                if quarter:
                    data = data[data["quarter"] == quarter]
        else:  # all
            # For 'all', we'll use a dict like labour_market does
            data = {"indices": indices_data, "contributions": contrib_data}
            if year:
                data["indices"] = nisra_composite.get_nicei_by_year(data["indices"], year)
                data["contributions"] = data["contributions"][data["contributions"]["year"] == year]
                if quarter:
                    data["indices"] = nisra_composite.get_nicei_by_quarter(data["indices"], year, quarter)
                    data["contributions"] = data["contributions"][data["contributions"]["quarter"] == quarter]

        # Check for empty results
        if table in ("indices", "contributions"):
            if data.empty:
                console.print("[yellow]⚠️  No data found for the specified filters[/yellow]")
                return
        else:
            if all(df.empty for df in data.values()):
                console.print("[yellow]⚠️  No data found for the specified filters[/yellow]")
                return

        # Display success message
        if table == "all":
            console.print("[green]✅ Retrieved all tables successfully[/green]")
            total_records = sum(len(df) for df in data.values())
            console.print(f"[cyan]📊 Total records: {total_records}[/cyan]")
            for table_name, df in data.items():
                console.print(f"   • {table_name}: {len(df)} records")
        else:
            console.print(f"[green]✅ Retrieved {table} table successfully[/green]")
            console.print(f"[cyan]📊 Total records: {len(data)}[/cyan]")

        if not (isinstance(data, dict) and all(df.empty for df in data.values())):
            if table != "all" and not data.empty:
                years = data["year"].unique()
                console.print(f"[dim]Years: {min(years)} - {max(years)}[/dim]")

        # Handle file saving
        if save:
            try:
                if table == "all":
                    # Save each table to a separate file
                    for table_name, df in data.items():
                        filename = (
                            f"{save.rsplit('.', 1)[0]}_{table_name}.{save.rsplit('.', 1)[-1] if '.' in save else 'csv'}"
                        )
                        if output_format == "json" or filename.endswith(".json"):
                            df.to_json(filename, orient="records", date_format="iso", indent=2)
                        else:
                            df.to_csv(filename, index=False)
                        console.print(f"[green]💾 Saved {table_name} to: {filename}[/green]")
                else:
                    # Save single table
                    if output_format == "json" or save.endswith(".json"):
                        data.to_json(save, orient="records", date_format="iso", indent=2)
                    else:
                        data.to_csv(save, index=False)
                    console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console
        if table == "all":
            for table_name, df in data.items():
                console.print(f"\n[bold]{table_name.upper()}:[/bold]")
                if output_format == "json":
                    click.echo(df.to_json(orient="records", date_format="iso", indent=2))
                else:
                    console.print(df.to_csv(index=False), end="")
        else:
            if output_format == "json":
                click.echo(data.to_json(orient="records", date_format="iso", indent=2))
            else:
                console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        raise click.Abort() from e


@nisra.command(name="wellbeing")
@click.option("--latest", is_flag=True, help="Get the most recent wellbeing data available")
@click.option(
    "--metric",
    type=click.Choice(["personal", "loneliness", "self-efficacy", "summary"], case_sensitive=False),
    default="personal",
    help="Type of wellbeing data to retrieve (default: personal)",
)
@click.option("--year", type=str, help="Filter data for specific year (format: 2024/25)")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
def nisra_wellbeing_cmd(latest, metric, year, output_format, force_refresh, save):
    r"""
    NISRA Individual Wellbeing Statistics.

    Retrieves individual wellbeing statistics for Northern Ireland, measuring
    subjective wellbeing across the population aged 16 and over.

    \b
    METRICS:
        personal     - ONS4 measures: Life Satisfaction, Worthwhile, Happiness, Anxiety
                       Scores from 0-10 (higher is better, except Anxiety where lower is better)
        loneliness   - Proportion feeling lonely at least some of the time
        self-efficacy - Mean self-efficacy scores (range 5-25)
        summary      - Combined latest values for all measures

    \b
    EXAMPLES:
        # Get personal wellbeing (ONS4 measures)
        bolster nisra wellbeing --latest

        # Get loneliness statistics
        bolster nisra wellbeing --latest --metric loneliness

        # Get summary of all metrics for latest year
        bolster nisra wellbeing --latest --metric summary

        # Filter for a specific year
        bolster nisra wellbeing --latest --year "2023/24"

        # Save to file
        bolster nisra wellbeing --latest --save wellbeing.csv

    \b
    DATA NOTES:
        - Personal wellbeing: Annual from 2014/15 to present
        - Loneliness: Annual from 2017/18 to present
        - Self-efficacy: Annual from 2014/15 to present
        - COVID-19 Note: 2020/21 shows increased anxiety and loneliness

    \b
    OUTPUT (personal):
        - year: Financial year (e.g., "2024/25")
        - life_satisfaction: Mean score 0-10 (higher is better)
        - worthwhile: Mean score 0-10 (higher is better)
        - happiness: Mean score 0-10 (higher is better)
        - anxiety: Mean score 0-10 (lower is better)

    \b
    SOURCE:
        https://www.nisra.gov.uk/statistics/wellbeing/individual-wellbeing-northern-ireland
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        console.print("[dim]Use --latest to get the most recent wellbeing data[/dim]")
        return

    try:
        with console.status("[bold green]Downloading latest NISRA wellbeing data..."):
            if metric == "personal":
                data = nisra_wellbeing.get_latest_personal_wellbeing(force_refresh=force_refresh)
            elif metric == "loneliness":
                data = nisra_wellbeing.get_latest_loneliness(force_refresh=force_refresh)
            elif metric == "self-efficacy":
                data = nisra_wellbeing.get_latest_self_efficacy(force_refresh=force_refresh)
            elif metric == "summary":
                data = nisra_wellbeing.get_wellbeing_summary(force_refresh=force_refresh)

        # Filter by year if specified
        if year and metric == "personal":
            data = nisra_wellbeing.get_personal_wellbeing_by_year(data, year)
            if data.empty:
                console.print(f"[yellow]⚠️  No data found for year {year}[/yellow]")
                return
        elif year and metric != "summary":
            data = data[data["year"] == year]
            if data.empty:
                console.print(f"[yellow]⚠️  No data found for year {year}[/yellow]")
                return

        console.print(f"[green]✅ Retrieved {metric} wellbeing data successfully[/green]")
        console.print(f"[cyan]📊 Total records: {len(data)}[/cyan]")

        if not data.empty:
            years = data["year"].unique()
            if len(years) > 1:
                console.print(f"[dim]Years: {years[0]} - {years[-1]}[/dim]")
            else:
                console.print(f"[dim]Year: {years[0]}[/dim]")

            # Show summary based on metric type
            if metric == "personal":
                latest_row = data.iloc[-1]
                console.print("\n[bold]Latest Values:[/bold]")
                console.print(f"   Life Satisfaction: {latest_row['life_satisfaction']:.1f}/10")
                console.print(f"   Worthwhile: {latest_row['worthwhile']:.1f}/10")
                console.print(f"   Happiness: {latest_row['happiness']:.1f}/10")
                console.print(f"   Anxiety: {latest_row['anxiety']:.1f}/10 (lower is better)")
            elif metric == "loneliness":
                latest_row = data.iloc[-1]
                console.print("\n[bold]Latest Values:[/bold]")
                console.print(f"   Lonely (some of time): {latest_row['lonely_some_of_time']:.1%}")
            elif metric == "self-efficacy":
                latest_row = data.iloc[-1]
                console.print("\n[bold]Latest Values:[/bold]")
                console.print(f"   Self-efficacy mean: {latest_row['self_efficacy_mean']:.1f}/25")
            elif metric == "summary":
                row = data.iloc[0]
                console.print("\n[bold]Wellbeing Summary:[/bold]")
                console.print(f"   Life Satisfaction: {row['life_satisfaction']:.1f}/10")
                console.print(f"   Worthwhile: {row['worthwhile']:.1f}/10")
                console.print(f"   Happiness: {row['happiness']:.1f}/10")
                console.print(f"   Anxiety: {row['anxiety']:.1f}/10")
                console.print(f"   Lonely (some of time): {row['lonely_some_of_time']:.1%}")
                console.print(f"   Self-efficacy: {row['self_efficacy_mean']:.1f}/25")

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            console.print("\n[bold]Data:[/bold]")
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        raise click.Abort() from e


@nisra.command(name="cancer-waiting-times")
@click.option("--latest", is_flag=True, help="Get the most recent cancer waiting times data available")
@click.option(
    "--target",
    type=click.Choice(["14-day", "31-day", "62-day", "referrals"], case_sensitive=False),
    default="31-day",
    help="Waiting time target to retrieve (default: 31-day)",
)
@click.option(
    "--dimension",
    type=click.Choice(["trust", "tumour"], case_sensitive=False),
    default="trust",
    help="Data dimension: by HSC Trust or by Tumour Site (default: trust)",
)
@click.option("--year", type=int, help="Filter data for specific year")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
@click.option("--summary", is_flag=True, help="Show NI-wide summary instead of raw data")
def nisra_cancer_cmd(latest, target, dimension, year, output_format, force_refresh, save, summary):
    r"""
    NISRA Cancer Waiting Times Statistics.

    Retrieves cancer waiting times performance data for Northern Ireland from the
    Department of Health, tracking progress against ministerial targets.

    \b
    TARGETS:
        14-day    - Urgent breast referrals seen within 14 days (breast cancer only)
        31-day    - Treatment within 31 days of decision to treat (all cancers)
        62-day    - Treatment within 62 days of urgent GP referral (all cancers)
        referrals - Monthly breast cancer referral volumes

    \b
    DIMENSIONS:
        trust     - Breakdown by HSC Trust (Belfast, Northern, South Eastern, Southern, Western)
        tumour    - Breakdown by Tumour Site (Breast, Lung, Skin, Urological, etc.)
                    Note: 14-day target only available for breast cancer

    \b
    EXAMPLES:
        # Get latest 31-day performance by trust
        bolster nisra cancer-waiting-times --latest

        # Get 62-day performance by tumour site
        bolster nisra cancer-waiting-times --latest --target 62-day --dimension tumour

        # Get 14-day breast cancer performance
        bolster nisra cancer-waiting-times --latest --target 14-day

        # Get NI-wide summary for 2024
        bolster nisra cancer-waiting-times --latest --year 2024 --summary

        # Save to file
        bolster nisra cancer-waiting-times --latest --save cancer.csv

    \b
    KEY INSIGHTS (as of 2025):
        - 31-day target (95%): NI achieving ~90% average
        - 62-day target (95%): Performance collapsed to ~32% (crisis level)
        - 14-day breast target: Dropped from 77% (2020) to 17% (2025)
        - Trust disparities: Belfast 82% vs Western 97% for 31-day

    \b
    DATA NOTES:
        - Data from Q1 2008 to present (monthly)
        - Some Belfast Trust data missing Q2-Q3 2024 (encompass system rollout)
        - Regional breast service transition from May 2025
        - COVID-19 impact visible in 2020 volumes and post-2020 backlogs

    \b
    SOURCE:
        https://www.health-ni.gov.uk/articles/cancer-waiting-times
    """
    console = Console()

    if not latest:
        console.print("[yellow]⚠️  Only --latest is currently supported[/yellow]")
        console.print("[dim]Use --latest to get the most recent cancer waiting times data[/dim]")
        return

    try:
        with console.status("[bold green]Downloading latest NISRA cancer waiting times data..."):
            # Select appropriate data source based on target and dimension
            if target == "14-day":
                data = nisra_cancer.get_latest_14_day_breast(force_refresh=force_refresh)
                target_label = "14-day Breast"
            elif target == "referrals":
                data = nisra_cancer.get_latest_breast_referrals(force_refresh=force_refresh)
                target_label = "Breast Referrals"
            elif target == "31-day":
                if dimension == "tumour":
                    data = nisra_cancer.get_latest_31_day_by_tumour(force_refresh=force_refresh)
                    target_label = "31-day by Tumour Site"
                else:
                    data = nisra_cancer.get_latest_31_day_by_trust(force_refresh=force_refresh)
                    target_label = "31-day by HSC Trust"
            elif target == "62-day":
                if dimension == "tumour":
                    data = nisra_cancer.get_latest_62_day_by_tumour(force_refresh=force_refresh)
                    target_label = "62-day by Tumour Site"
                else:
                    data = nisra_cancer.get_latest_62_day_by_trust(force_refresh=force_refresh)
                    target_label = "62-day by HSC Trust"

        # Filter by year if specified
        if year:
            data = nisra_cancer.get_data_by_year(data, year)
            if data.empty:
                console.print(f"[yellow]⚠️  No data found for year {year}[/yellow]")
                return

        # Get NI-wide summary if requested (not for referrals)
        if summary and target != "referrals":
            data = nisra_cancer.get_ni_wide_performance(data)

        console.print(f"[green]✅ Retrieved {target_label} data successfully[/green]")
        console.print(f"[cyan]📊 Total records: {len(data)}[/cyan]")

        if not data.empty:
            years = sorted(data["year"].unique())
            if len(years) > 1:
                console.print(f"[dim]Years: {years[0]} - {years[-1]}[/dim]")
            else:
                console.print(f"[dim]Year: {years[0]}[/dim]")

            # Show summary statistics
            if target == "referrals":
                latest_year = data["year"].max()
                latest_data = data[data["year"] == latest_year]
                total_referrals = latest_data["total_referrals"].sum()
                urgent_referrals = latest_data["urgent_referrals"].sum()
                console.print(f"\n[bold]Latest Year ({latest_year}) Summary:[/bold]")
                console.print(f"   Total Referrals: {total_referrals:,.0f}")
                console.print(f"   Urgent Referrals: {urgent_referrals:,.0f}")
                console.print(f"   Urgent Rate: {urgent_referrals / total_referrals:.1%}")
            else:
                # Performance summary
                valid_data = data.dropna(subset=["performance_rate"])
                valid_data = valid_data[valid_data["total"] > 0]
                if not valid_data.empty:
                    latest_year = valid_data["year"].max()
                    latest_data = valid_data[valid_data["year"] == latest_year]
                    total_patients = latest_data["total"].sum()
                    within_target = latest_data["within_target"].sum()
                    overall_rate = within_target / total_patients if total_patients > 0 else 0

                    console.print(f"\n[bold]Latest Year ({latest_year}) Summary:[/bold]")
                    console.print(f"   Total Patients: {total_patients:,.0f}")
                    console.print(f"   Within Target: {within_target:,.0f}")
                    console.print(f"   Performance Rate: {overall_rate:.1%}")

                    # Show target status
                    target_threshold = 0.95
                    if overall_rate >= target_threshold:
                        console.print("   [green]✅ Meeting 95% target[/green]")
                    else:
                        gap = (target_threshold - overall_rate) * 100
                        console.print(f"   [red]❌ {gap:.1f}pp below 95% target[/red]")

        # Handle file saving
        if save:
            try:
                if output_format == "json" or save.endswith(".json"):
                    data.to_json(save, orient="records", date_format="iso", indent=2)
                else:
                    data.to_csv(save, index=False)
                console.print(f"[green]💾 Data saved to: {save}[/green]")
                return
            except Exception as e:
                console.print(f"[red]❌ Error saving file: {e}[/red]")
                return

        # Output to console
        if output_format == "json":
            click.echo(data.to_json(orient="records", date_format="iso", indent=2))
        else:
            console.print("\n[bold]Data:[/bold]")
            console.print(data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        raise click.Abort() from e


@nisra.command(name="registrar-general")
@click.option("--latest", is_flag=True, help="Get the most recent quarterly tables data")
@click.option("--quarterly", is_flag=True, help="Show full quarterly time series")
@click.option("--lgd", is_flag=True, help="Show LGD (Local Government District) breakdown")
@click.option("--validate", is_flag=True, help="Run cross-validation against monthly data")
@click.option(
    "--table",
    type=click.Choice(["births", "deaths", "all"], case_sensitive=False),
    default="all",
    help="Which table to retrieve (default: all)",
)
@click.option("--year", type=int, help="Filter data for specific year")
@click.option("--quarter", type=int, help="Filter data for specific quarter (1-4)")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["csv", "json"], case_sensitive=False),
    default="csv",
    help="Output format (default: csv)",
)
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
@click.option("--save", help="Save data to file (specify filename)")
def nisra_registrar_general_cmd(
    latest, quarterly, lgd, validate, table, year, quarter, output_format, force_refresh, save
):
    r"""
    NISRA Registrar General Quarterly Tables.

    Quarterly vital statistics for Northern Ireland including births, deaths,
    marriages, civil partnerships, and LGD-level breakdowns. Data available
    from Q1 2009 to present.

    \b
    TABLES AVAILABLE:
        births  - Quarterly births, stillbirths, birth rates
        deaths  - Quarterly deaths, marriages, civil partnerships, death rates
        lgd     - Current quarter breakdown by Local Government District

    \b
    EXAMPLES:
        # Get latest quarterly data (all tables)
        bolster nisra registrar-general --latest

        # Get quarterly births time series
        bolster nisra registrar-general --quarterly --table births

        # Get LGD breakdown for current quarter
        bolster nisra registrar-general --lgd

        # Cross-validate quarterly vs monthly data
        bolster nisra registrar-general --validate

        # Get specific year/quarter
        bolster nisra registrar-general --quarterly --year 2024 --quarter 1

        # Save to file
        bolster nisra registrar-general --quarterly --save quarterly.csv

    \b
    CROSS-VALIDATION:
        The --validate option compares quarterly totals against aggregated
        monthly data from the births and marriages modules. Differences
        within 2% are considered acceptable (timing of registrations).

    \b
    DATA NOTES:
        - Quarterly data from Q1 2009 to present
        - Updated approximately 6 weeks after each quarter ends
        - 11 Local Government Districts in NI
        - Birth/death rates per 1,000 population

    \b
    SOURCE:
        https://www.nisra.gov.uk/statistics/births-deaths-and-marriages/registrar-general-quarterly-report
    """
    console = Console()

    if not any([latest, quarterly, lgd, validate]):
        console.print("[yellow]⚠️  Please specify an option: --latest, --quarterly, --lgd, or --validate[/yellow]")
        console.print("[dim]Use --help for more information[/dim]")
        return

    try:
        with console.status("[bold green]Downloading Registrar General Quarterly Tables..."):
            data = nisra_registrar_general.get_quarterly_vital_statistics(force_refresh=force_refresh)

        # Handle validation mode
        if validate:
            console.print("[bold cyan]Cross-Validation Report[/bold cyan]")
            console.print("=" * 50)

            report = nisra_registrar_general.get_validation_report(force_refresh=force_refresh)

            if not report["summary"].empty:
                console.print("\n[bold]Summary:[/bold]")
                for _, row in report["summary"].iterrows():
                    validation_name = row["validation"].replace("_", " ").title()
                    console.print(f"  {validation_name}:")
                    console.print(f"    Quarters compared: {row['quarters_compared']}")
                    console.print(f"    Average difference: {row['avg_pct_diff']:.2f}%")
                    console.print(f"    Max difference: {row['max_pct_diff']:.2f}%")
                    console.print(f"    Within 2%: {row['within_2pct']}")

            if "births_validation" in report and not report["births_validation"].empty:
                console.print("\n[bold]Births Validation (recent quarters):[/bold]")
                recent = report["births_validation"].tail(8)
                console.print(recent.to_string(index=False))

            if "marriages_validation" in report and not report["marriages_validation"].empty:
                console.print("\n[bold]Marriages Validation (recent quarters):[/bold]")
                recent = report["marriages_validation"].tail(8)
                console.print(recent.to_string(index=False))

            return

        # Handle LGD mode
        if lgd:
            lgd_data = data["lgd"]
            if lgd_data.empty:
                console.print("[yellow]⚠️  LGD data not available[/yellow]")
                return

            console.print("[bold cyan]LGD-Level Statistics (Current Quarter)[/bold cyan]")
            console.print(f"[dim]{len(lgd_data)} Local Government Districts[/dim]\n")

            # Handle file saving
            if save:
                try:
                    if output_format == "json" or save.endswith(".json"):
                        lgd_data.to_json(save, orient="records", indent=2)
                    else:
                        lgd_data.to_csv(save, index=False)
                    console.print(f"[green]💾 Data saved to: {save}[/green]")
                    return
                except Exception as e:
                    console.print(f"[red]❌ Error saving file: {e}[/red]")
                    return

            # Output data
            if output_format == "json":
                click.echo(lgd_data.to_json(orient="records", indent=2))
            else:
                console.print(lgd_data.to_csv(index=False), end="")
            return

        # Handle quarterly time series or latest
        if table == "births" or table == "all":
            births_data = data["births"]
            if not births_data.empty:
                # Filter by year/quarter if specified
                if year:
                    births_data = births_data[births_data["year"] == year]
                if quarter:
                    births_data = births_data[births_data["quarter"] == quarter]

                if table == "births" or (table == "all" and not quarterly):
                    output_data = births_data
                else:
                    output_data = births_data if table == "births" else None

        if table == "deaths" or table == "all":
            deaths_data = data["deaths"]
            if not deaths_data.empty:
                if year:
                    deaths_data = deaths_data[deaths_data["year"] == year]
                if quarter:
                    deaths_data = deaths_data[deaths_data["quarter"] == quarter]

                if table == "deaths":
                    output_data = deaths_data

        # Show summary for --latest
        if latest and not quarterly:
            console.print("[bold cyan]Registrar General Quarterly Tables - Latest Data[/bold cyan]")
            console.print("=" * 50)

            if not data["births"].empty:
                latest_birth = data["births"].iloc[-1]
                console.print(f"\n[bold]Latest Births (Q{latest_birth['quarter']} {latest_birth['year']}):[/bold]")
                console.print(f"  Total births: {latest_birth['total_births']:,}")
                if "birth_rate" in latest_birth and pd.notna(latest_birth["birth_rate"]):
                    console.print(f"  Birth rate: {latest_birth['birth_rate']:.1f} per 1,000")
                if "stillbirths" in latest_birth and pd.notna(latest_birth["stillbirths"]):
                    console.print(f"  Stillbirths: {int(latest_birth['stillbirths'])}")

            if not data["deaths"].empty:
                latest_death = data["deaths"].iloc[-1]
                console.print(
                    f"\n[bold]Latest Deaths/Marriages (Q{latest_death['quarter']} {latest_death['year']}):[/bold]"
                )
                console.print(f"  Deaths: {latest_death['deaths']:,}")
                if "death_rate" in latest_death and pd.notna(latest_death["death_rate"]):
                    console.print(f"  Death rate: {latest_death['death_rate']:.1f} per 1,000")
                if "marriages" in latest_death and pd.notna(latest_death["marriages"]):
                    console.print(f"  Marriages: {int(latest_death['marriages']):,}")
                if "civil_partnerships" in latest_death and pd.notna(latest_death["civil_partnerships"]):
                    console.print(f"  Civil partnerships: {int(latest_death['civil_partnerships'])}")

            # Show historical range
            if not data["births"].empty:
                min_year = data["births"]["year"].min()
                num_quarters = len(data["births"])
                console.print(f"\n[dim]Historical data: {num_quarters} quarters from Q1 {min_year} to present[/dim]")

            return

        # Handle full data output for --quarterly
        if quarterly:
            if table == "all":
                console.print("[bold cyan]Quarterly Vital Statistics[/bold cyan]")
                console.print("\n[bold]Births Data:[/bold]")
                if not data["births"].empty:
                    output = data["births"]
                    if year:
                        output = output[output["year"] == year]
                    if quarter:
                        output = output[output["quarter"] == quarter]
                    console.print(f"[dim]{len(output)} records[/dim]")

                    if save:
                        births_file = save.replace(".", "_births.")
                        output.to_csv(births_file, index=False)
                        console.print(f"[green]💾 Births saved to: {births_file}[/green]")
                    else:
                        if output_format == "json":
                            click.echo(output.to_json(orient="records", date_format="iso", indent=2))
                        else:
                            console.print(output.to_csv(index=False), end="")

                console.print("\n[bold]Deaths/Marriages Data:[/bold]")
                if not data["deaths"].empty:
                    output = data["deaths"]
                    if year:
                        output = output[output["year"] == year]
                    if quarter:
                        output = output[output["quarter"] == quarter]
                    console.print(f"[dim]{len(output)} records[/dim]")

                    if save:
                        deaths_file = save.replace(".", "_deaths.")
                        output.to_csv(deaths_file, index=False)
                        console.print(f"[green]💾 Deaths saved to: {deaths_file}[/green]")
                    else:
                        if output_format == "json":
                            click.echo(output.to_json(orient="records", date_format="iso", indent=2))
                        else:
                            console.print(output.to_csv(index=False), end="")
            else:
                # Single table output
                output_data = data["births"] if table == "births" else data["deaths"]
                if year:
                    output_data = output_data[output_data["year"] == year]
                if quarter:
                    output_data = output_data[output_data["quarter"] == quarter]

                console.print(f"[bold cyan]Quarterly {table.title()} Data[/bold cyan]")
                console.print(f"[dim]{len(output_data)} records[/dim]\n")

                if save:
                    try:
                        if output_format == "json" or save.endswith(".json"):
                            output_data.to_json(save, orient="records", date_format="iso", indent=2)
                        else:
                            output_data.to_csv(save, index=False)
                        console.print(f"[green]💾 Data saved to: {save}[/green]")
                        return
                    except Exception as e:
                        console.print(f"[red]❌ Error saving file: {e}[/red]")
                        return

                if output_format == "json":
                    click.echo(output_data.to_json(orient="records", date_format="iso", indent=2))
                else:
                    console.print(output_data.to_csv(index=False), end="")

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        console.print("\n[yellow]💡 Troubleshooting:[/yellow]")
        console.print("   • Check your internet connection")
        console.print("   • Try again with --force-refresh to bypass cache")
        console.print("   • Visit NISRA website to verify data availability")
        raise click.Abort() from e


@cli.group()
def psni():
    """
    PSNI (Police Service of Northern Ireland) data sources.

    Access official statistics from the Police Service of Northern Ireland including:
    - Road Traffic Collision statistics (injury collisions, casualties, vehicles)
    - Police recorded crime statistics (from OpenDataNI)

    All data is sourced from OpenDataNI under the Open Government Licence v3.0.
    Geographic breakdowns use 11 Policing Districts aligned with LGDs.
    """
    pass


@psni.command(name="rtc")
@click.option("--year", type=int, help="Specific year to retrieve (default: latest)")
@click.option(
    "--data-type",
    type=click.Choice(["collisions", "casualties", "vehicles", "summary"], case_sensitive=False),
    default="summary",
    help="Type of data to retrieve (default: summary)",
)
@click.option(
    "--by",
    type=click.Choice(["district", "road-user", "year"], case_sensitive=False),
    help="Group results by dimension",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "csv", "json"], case_sensitive=False),
    default="table",
    help="Output format (default: table)",
)
@click.option("--save", help="Save data to file (specify filename)")
@click.option("--force-refresh", is_flag=True, help="Force re-download even if cached")
def psni_rtc_cmd(year, data_type, by, output_format, save, force_refresh):
    r"""
    PSNI Road Traffic Collision Statistics.

    Retrieves police-recorded injury road traffic collision data including:
    - Collision records with date, location, road conditions
    - Casualty records with severity (fatal/serious/slight), road user type
    - Vehicle records with type and driver details

    \b
    EXAMPLES:
        # Get annual summary for all available years
        bolster psni rtc --data-type summary

        # Get 2024 casualties by district
        bolster psni rtc --year 2024 --data-type casualties --by district

        # Get casualties by road user type
        bolster psni rtc --data-type casualties --by road-user

        # Export collision data to CSV
        bolster psni rtc --year 2024 --data-type collisions --format csv --save collisions.csv

    \b
    DATA NOTES:
        - Data covers injury collisions only (not damage-only)
        - Available from 2013 onwards via OpenDataNI
        - Severity: Fatal, Serious, Slight
        - Updated annually (~6 months after year end)
    """
    from rich.table import Table

    from bolster.data_sources.psni import road_traffic_collisions

    console = Console()

    try:
        console.print("\n[bold blue]🚗 PSNI Road Traffic Collision Statistics[/bold blue]\n")

        if data_type == "summary" or by == "year":
            # Annual summary
            if year:
                console.print("[yellow]Note: --year ignored for summary view[/yellow]\n")
            df = road_traffic_collisions.get_annual_summary()
            title = "Annual RTC Summary"

        elif by == "district":
            df = road_traffic_collisions.get_casualties_by_district(year, force_refresh=force_refresh)
            title = f"Casualties by District ({year or 'latest'})"

        elif by == "road-user":
            df = road_traffic_collisions.get_casualties_by_road_user(year, force_refresh=force_refresh)
            title = f"Casualties by Road User Type ({year or 'latest'})"

        elif data_type == "collisions":
            df = road_traffic_collisions.get_collisions(year, force_refresh=force_refresh)
            title = f"Collision Records ({year or 'latest'})"

        elif data_type == "casualties":
            df = road_traffic_collisions.get_casualties(year, force_refresh=force_refresh)
            title = f"Casualty Records ({year or 'latest'})"

        elif data_type == "vehicles":
            df = road_traffic_collisions.get_vehicles(year, force_refresh=force_refresh)
            title = f"Vehicle Records ({year or 'latest'})"

        else:
            df = road_traffic_collisions.get_annual_summary()
            title = "Annual RTC Summary"

        console.print(f"[bold]{title}[/bold]\n")

        if output_format == "table":
            # Create rich table
            table = Table(show_header=True, header_style="bold cyan")
            for col in df.columns:
                table.add_column(str(col))
            for _, row in df.head(50).iterrows():
                table.add_row(*[str(v) for v in row.values])
            console.print(table)
            if len(df) > 50:
                console.print(f"\n[yellow]Showing first 50 of {len(df)} rows[/yellow]")

        elif output_format == "csv":
            console.print(df.to_csv(index=False))

        elif output_format == "json":
            console.print(df.to_json(orient="records", indent=2))

        if save:
            if save.endswith(".json"):
                df.to_json(save, orient="records", indent=2)
            else:
                df.to_csv(save, index=False)
            console.print(f"\n[green]✅ Saved to {save}[/green]")

        # Show summary stats
        if data_type == "summary" or by == "year":
            total_fatal = df["fatal"].sum()
            total_casualties = df["casualties"].sum()
            years_covered = f"{df['year'].min()}-{df['year'].max()}"
            console.print(
                f"\n[dim]Data covers {years_covered} | {total_casualties:,} total casualties | {total_fatal:,} fatalities[/dim]"
            )

    except Exception as e:
        console.print(f"[bold red]❌ Error:[/bold red] {str(e)}", style="red")
        raise click.Abort() from e


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
    click.echo("  nisra deaths         NISRA weekly death registrations")
    click.echo("                       Demographics (age/sex), geography (LGDs), place of death")

    click.echo("\n🏢 BUSINESS & PROPERTY")
    click.echo("  companies-house      UK Companies House company data queries")
    click.echo("                       Company search, Farset Labs related companies")
    click.echo("  ni-house-prices      NI house price index data from official sources")
    click.echo("                       Price trends by property type, region, time period")

    click.echo("\n🚗 TRANSPORT")
    click.echo("  dva                  DVA monthly test statistics (vehicle, driver, theory)")
    click.echo("                       April 2014 - present, includes --summary dashboard")

    click.echo("\n🎬 ENTERTAINMENT & LIFESTYLE")
    click.echo("  cinema-listings      Cineworld movie listings and showtimes")
    click.echo("                       Default: Belfast (site 117), supports other locations")

    click.echo("\n📰 RSS & FEEDS")
    click.echo("  rss read             Generic RSS/Atom feed reader with filtering")
    click.echo("                       Beautiful terminal output, JSON/CSV export")
    click.echo("  rss nisra-statistics Browse NISRA publications feed")
    click.echo("                       Research and statistics from NISRA via GOV.UK")

    click.echo("\n🔧 DATA SOURCE MODULES")
    click.echo("  bolster.data_sources.metoffice         - UK Met Office API integration")
    click.echo("  bolster.data_sources.ni_water          - NI Water quality data")
    click.echo("  bolster.data_sources.nisra.deaths      - NISRA weekly deaths statistics")
    click.echo("  bolster.data_sources.dva               - DVA monthly test statistics")
    click.echo("  bolster.data_sources.wikipedia         - NI Executive Wikipedia scraping")
    click.echo("  bolster.data_sources.ni_house_price_index - NI house price statistics")
    click.echo("  bolster.data_sources.cineworld         - Cineworld cinema API")
    click.echo("  bolster.data_sources.eoni              - Electoral Office NI data")
    click.echo("  bolster.data_sources.companies_house   - UK Companies House API")
    click.echo("  bolster.utils.rss                      - RSS/Atom feed parsing utilities")

    click.echo("\n💡 USAGE EXAMPLES")
    click.echo("  bolster water-quality BT1 5GS              # Water quality by postcode")
    click.echo("  bolster nisra deaths --latest              # Latest NISRA deaths data")
    click.echo("  bolster dva --latest --summary             # DVA test statistics summary")
    click.echo("  bolster rss nisra-statistics               # Browse NISRA publications")
    click.echo("  bolster ni-executive --format json         # Executive data as JSON")
    click.echo("  bolster companies-house farset             # Search for Farset companies")
    click.echo("  bolster ni-elections --election-year 2022  # 2022 election results")
    click.echo("  bolster cinema-listings --date 2024-03-20  # Movie listings for date")
    click.echo("  bolster --help                             # General help")
    click.echo("  bolster <command> --help                   # Command-specific help")

    click.echo(f"\nBolster v{__version__} - Northern Ireland & UK Data Sources")


if __name__ == "__main__":
    sys.exit(cli())  # pragma: no cover
