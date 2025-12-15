# Bolster

![PyPI](https://img.shields.io/pypi/v/bolster?style=for-the-badge)
![Python](https://img.shields.io/pypi/pyversions/bolster?style=for-the-badge)
![License](https://img.shields.io/pypi/l/bolster?style=for-the-badge)
![GitHub Actions](https://img.shields.io/github/actions/workflow/status/andrewbolster/bolster/test.yml?branch=master&style=for-the-badge)
![Code Coverage](https://img.shields.io/codecov/c/github/andrewbolster/bolster?style=for-the-badge)
![Documentation](https://img.shields.io/readthedocs/bolster?style=for-the-badge)

> **Bolster's Brain, you've been warned** 🧠

A comprehensive Python utility library for data science, web scraping, cloud services, and general development workflows. Originally designed as a personal toolkit, Bolster has evolved into a robust collection of utilities that enhance productivity across data analysis, system administration, and software development tasks.

## 🚀 Quick Start

### Installation

```bash
pip install bolster
```

### Basic Usage

```python
import bolster

# Efficient data processing with built-in progress tracking
data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
results = bolster.poolmap(lambda x: x**2, data)
print(results)  # {1: 1, 2: 4, 3: 9, 4: 16, ...}


# Smart retry logic with exponential backoff
@bolster.backoff(Exception, tries=3, delay=1, backoff=2)
def unreliable_api_call():
    # Your potentially failing code here
    return "Success!"


# Efficient tree/dict navigation
nested_data = {
    "users": {
        "active": [{"name": "Alice", "age": 25}, {"name": "Bob", "age": 30}],
        "inactive": [{"name": "Charlie", "age": 35}],
    }
}

# Find all ages recursively
ages = bolster.get_recursively(nested_data, "age")
print(ages)  # [25, 30, 35]

# Flatten nested structures
flat = bolster.flatten_dict(nested_data)
print(flat["users:active:0:name"])  # 'Alice'
```

## 🎯 Core Features

### Concurrency & Performance

- **`poolmap()`**: ThreadPoolExecutor wrapper with progress monitoring and robust error handling
- **`exceptional_executor()`**: Graceful handling of failed futures in concurrent operations
- **`backoff()`**: Exponential backoff retry decorator for unreliable operations
- **`memoize()`**: Instance method caching with hit/miss tracking for performance optimization

### Data Processing & Transformation

- **`aggregate()`**: Pandas-like groupby operations for dictionaries and lists
- **`transform_()`**: Flexible data transformation with key mapping and function application
- **`batch()` / `chunks()`**: Efficient sequence partitioning for processing large datasets
- **Compression utilities**: `compress_for_relay()` / `decompress_from_relay()` for data serialization

### Tree & Dictionary Navigation

- **`get_recursively()`**: Extract values from deeply nested structures by key
- **`flatten_dict()`**: Convert nested dictionaries to flat key-value pairs
- **Tree analysis**: `breadth()`, `depth()`, `leaves()`, `leaf_paths()` for structure inspection
- **Path navigation**: `keys_at()`, `items_at()` for level-specific data access

### Development & Debugging

- **`arg_exception_logger()`**: Decorator for debugging function calls with automatic argument logging
- **`MultipleErrors`**: Accumulate and handle multiple exceptions in complex workflows
- **`working_directory()`**: Context manager for safe directory operations
- **`pretty_print_request()`**: HTTP request debugging with automatic auth redaction

## 📊 Data Sources

Bolster includes specialized modules for working with Northern Ireland and UK data sources:

### Northern Ireland Water Quality

```python
from bolster.data_sources.ni_water import get_water_quality, get_water_quality_by_zone

# Get comprehensive water quality data for all NI supply zones
df = get_water_quality()
print(df.shape)  # Shows number of zones and parameters

# Get specific zone data
zone_data = get_water_quality_by_zone("BALM")  # Belfast Malone area
print(f"Hardness: {zone_data['NI Hardness Classification']}")
```

### Electoral Office for Northern Ireland (EONI)

```python
from bolster.data_sources.eoni import get_election_results

# Get Assembly election results
results_2016 = get_election_results(2016)
results_2022 = get_election_results(2022)

# Compare party performance across elections
comparison = bolster.diff(results_2022, results_2016)
```

### Companies House Data

```python
from bolster.data_sources.companies_house import search_companies, get_company_details

# Search for companies
results = search_companies("Technology")

# Get detailed company information
company = get_company_details("12345678")  # Company number
print(f"{company['name']} - Status: {company['status']}")
```

### UK Met Office

```python
from bolster.data_sources.metoffice import get_precipitation_data

# Get weather data for a specific location
weather = get_precipitation_data("Belfast", start_date="2024-01-01", end_date="2024-01-31")
```

### Northern Ireland House Price Index

```python
from bolster.data_sources.nihpi import get_house_price_index

# Get latest house price data
hpi_data = get_house_price_index()
print(f"Current average price: £{hpi_data['average_price']:,.0f}")
```

## ☁️ Cloud Services

### AWS Integration

```python
from bolster.aws import get_session, S3Handler, DynamoHandler

# Get configured AWS session
session = get_session(profile="production")

# S3 operations with best practices
s3 = S3Handler(session)
s3.upload_file("local_file.txt", "bucket-name", "remote/path/file.txt")

# DynamoDB operations
dynamo = DynamoHandler(session)
items = dynamo.scan_table("user-data", filters={"status": "active"})
```

### Azure Integration

```python
from bolster.azure import AzureHandler

# Azure Blob Storage operations
azure = AzureHandler(connection_string="DefaultEndpointsProtocol=https;...")
azure.upload_blob("container", "blob_name", data)
```

## 🌐 Web Scraping & HTTP

```python
from bolster.web import safe_request, parse_html_table

# Robust HTTP requests with automatic retries
response = safe_request("https://api.example.com/data", max_retries=3, timeout=30)

# Parse HTML tables into pandas DataFrames
tables = parse_html_table("https://example.com/tables")
print(tables[0].head())  # First table as DataFrame
```

## 🖥️ Command Line Interface

Bolster includes a CLI for common operations:

```bash
# Get precipitation data
bolster get-precipitation --location "Belfast" --start-date "2024-01-01"

# Get help on available commands
bolster --help
```

## 🔧 Advanced Examples

### Concurrent Data Processing

```python
import bolster
from datetime import datetime


# Process large datasets with progress tracking
def process_user_data(user_id):
    # Simulate data processing
    return {"user_id": user_id, "processed_at": datetime.now()}


user_ids = range(1000)  # 1000 users to process

# Process with automatic progress bar and error handling
results = bolster.poolmap(
    process_user_data,
    user_ids,
    max_workers=10,
    progress=True,  # Shows progress bar
)

print(f"Processed {len(results)} users successfully")
```

### Smart Caching and Memoization

```python
class DataProcessor:
    @bolster.memoize
    def expensive_calculation(self, data_hash):
        # Expensive operation that we want to cache
        import time

        time.sleep(2)  # Simulate expensive operation
        return f"Processed: {data_hash}"


processor = DataProcessor()

# First call - takes 2 seconds
result1 = processor.expensive_calculation("abc123")

# Second call with same input - returns immediately from cache
result2 = processor.expensive_calculation("abc123")

# Check cache performance
print(f"Cache hits: {len(processor._memoize__hits)}")
print(f"Cache misses: {len(processor._memoize__misses)}")
```

### Robust API Integration with Backoff

```python
import requests
import bolster


@bolster.backoff((requests.RequestException, ConnectionError), tries=5, delay=1, backoff=2)
def fetch_api_data(url):
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


# This will automatically retry with exponential backoff on failure
data = fetch_api_data("https://api.unreliable-service.com/data")
```

### Complex Data Transformation

```python
# Transform API response to database format
api_response = {
    "user_name": "john_doe",
    "user_email": "john@example.com",
    "account_type": "premium",
    "signup_timestamp": "2024-01-01T12:00:00Z",
}

# Define transformation rules
rules = {
    "user_name": ("username", str.upper),  # Rename and transform
    "user_email": ("email", None),  # Keep as-is but rename
    "account_type": ("tier", lambda x: x.title()),  # Transform value
    "signup_timestamp": ("created_at", bolster.parse_iso_datetime),
}

# Apply transformation
db_record = bolster.transform_(api_response, rules)
print(db_record)
# {'username': 'JOHN_DOE', 'email': 'john@example.com',
#  'tier': 'Premium', 'created_at': datetime(2024, 1, 1, 12, 0, 0)}
```

## 🏗️ Development Setup

### Prerequisites

- Python 3.8+ (3.9, 3.10, 3.11, 3.12 supported)
- PDM (Python Dependency Management)

### Installation for Development

```bash
# Clone the repository
git clone https://github.com/andrewbolster/bolster.git
cd bolster

# Install with development dependencies
pdm install -G dev

# Install pre-commit hooks
pdm run pre-commit install

# Run tests
pdm run pytest

# Run with coverage
pdm run pytest --cov=bolster --cov-report=html

# Build documentation
cd docs
pdm run make html
```

### Running Tests

```bash
# Run all tests
pdm run pytest

# Run with verbose output and coverage
pdm run pytest -v --cov=bolster --cov-report=term-missing

# Run specific test file
pdm run pytest tests/test_core_utilities.py

# Run doctests
pdm run pytest --doctest-modules src/bolster/
```

## 📚 Documentation

- **Full Documentation**: [https://bolster.readthedocs.io](https://bolster.readthedocs.io)
- **API Reference**: Auto-generated from docstrings
- **Examples**: See `/notebooks` directory for Jupyter notebook examples
- **Data Sources**: Detailed documentation for each data source module

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

### Development Guidelines

1. **Testing**: Ensure all new features have comprehensive tests
1. **Documentation**: Add docstrings and update README for new features
1. **Code Style**: Follow the existing code style (enforced by ruff)
1. **Type Hints**: Include type annotations for all public functions
1. **Performance**: Consider performance implications for data processing functions

## 📄 License

This project is licensed under the GNU General Public License v3 (GPLv3) - see the [LICENSE](LICENSE) file for details.

## 🐛 Bug Reports

If you encounter any bugs or issues, please file a bug report at:
[https://github.com/andrewbolster/bolster/issues](https://github.com/andrewbolster/bolster/issues)

## 🔗 Links

- **PyPI**: [https://pypi.org/project/bolster/](https://pypi.org/project/bolster/)
- **GitHub**: [https://github.com/andrewbolster/bolster](https://github.com/andrewbolster/bolster)
- **Documentation**: [https://bolster.readthedocs.io](https://bolster.readthedocs.io)
- **Author**: [Andrew Bolster](https://github.com/andrewbolster)

______________________________________________________________________

*Built with ❤️ for data science, automation, and general productivity enhancement.*
