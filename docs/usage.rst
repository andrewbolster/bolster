=====
Usage
=====

Basic Usage
-----------

To use Bolster in a project::

    import bolster

Core Functions
--------------

Concurrency and Performance
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Bolster provides powerful utilities for concurrent processing and performance optimization.

**Parallel Processing with Progress Tracking:**

.. code-block:: python

    import bolster

    # Process data in parallel with automatic progress monitoring
    def process_item(item):
        # Your processing logic here
        return item ** 2

    data = range(1000)
    results = bolster.poolmap(
        process_item,
        data,
        max_workers=4,
        progress=True  # Shows progress bar if tqdm is available
    )
    print(f"Processed {len(results)} items")

**Exponential Backoff Retry:**

.. code-block:: python

    import requests
    import bolster

    @bolster.backoff((requests.RequestException, ConnectionError),
                    tries=5, delay=1, backoff=2)
    def fetch_api_data(url):
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()

    # This will automatically retry with exponential backoff on failure
    data = fetch_api_data("https://api.example.com/data")

**Instance Method Caching:**

.. code-block:: python

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

Data Processing and Transformation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Working with Nested Data Structures:**

.. code-block:: python

    # Extract values from deeply nested structures
    nested_data = {
        'users': {
            'active': [{'name': 'Alice', 'age': 25}, {'name': 'Bob', 'age': 30}],
            'inactive': [{'name': 'Charlie', 'age': 35}]
        }
    }

    # Find all ages recursively
    ages = bolster.get_recursively(nested_data, 'age')
    print(ages)  # [25, 30, 35]

    # Flatten nested structures
    flat = bolster.flatten_dict(nested_data)
    print(flat['users:active:0:name'])  # 'Alice'

**Data Transformation:**

.. code-block:: python

    # Transform API response to database format
    api_response = {
        'user_name': 'john_doe',
        'user_email': 'john@example.com',
        'account_type': 'premium'
    }

    # Define transformation rules
    rules = {
        'user_name': ('username', str.upper),  # Rename and transform
        'user_email': ('email', None),         # Keep as-is but rename
        'account_type': ('tier', lambda x: x.title())  # Transform value
    }

    # Apply transformation
    db_record = bolster.transform_(api_response, rules)
    print(db_record)
    # {'username': 'JOHN_DOE', 'email': 'john@example.com', 'tier': 'Premium'}

**Batch Processing:**

.. code-block:: python

    # Process large datasets in chunks
    large_dataset = range(10000)

    # Split into batches of 100
    for batch in bolster.batch(large_dataset, 100):
        process_batch(batch)

    # Or use chunks for generators
    for chunk in bolster.chunks(large_dataset, 100):
        process_chunk(chunk)

Data Sources
------------

Northern Ireland Water Quality
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from bolster.data_sources.ni_water import get_water_quality, get_water_quality_by_zone

    # Get comprehensive water quality data for all NI supply zones
    df = get_water_quality()
    print(df.shape)  # Shows number of zones and parameters

    # Get specific zone data
    zone_data = get_water_quality_by_zone('BALM')  # Belfast Malone area
    print(f"Hardness: {zone_data['NI Hardness Classification']}")

Electoral Data (EONI)
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from bolster.data_sources.eoni import get_election_results

    # Get Assembly election results
    results_2022 = get_election_results(2022)
    results_2016 = get_election_results(2016)

    # Compare elections using diff utility
    comparison = bolster.diff(results_2022, results_2016)

Companies House Data
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from bolster.data_sources.companies_house import search_companies, get_company_details

    # Search for companies
    results = search_companies("Technology")

    # Get detailed company information
    company = get_company_details("12345678")  # Company number
    print(f"{company['name']} - Status: {company['status']}")

Command Line Interface
----------------------

Bolster includes a CLI for common operations:

**Get Precipitation Data:**

.. code-block:: bash

    # Download precipitation data with default settings
    bolster get-precipitation --order-name "your-order-name"

    # Download for specific region (Northern Ireland)
    bolster get-precipitation \
        --bounding-box "-8.5,54.0,-5.0,55.5" \
        --order-name "your-order-name" \
        --output "ni_rain.png"

**Environment Variables:**

Set these environment variables for the CLI:

- ``MET_OFFICE_API_KEY``: Your Met Office API key (required)
- ``MAP_IMAGES_ORDER_NAME``: Default order name for precipitation data (optional)

Advanced Features
-----------------

Error Handling
~~~~~~~~~~~~~~

**Multiple Exception Accumulation:**

.. code-block:: python

    exceptions = bolster.MultipleErrors()

    try:
        do_risky_thing_with(this)  # raises ValueError
    except:
        exceptions.capture_current_exception()

    try:
        do_other_thing_with(this)  # raises AttributeError
    except:
        exceptions.capture_current_exception()

    # Raise all accumulated exceptions at once
    exceptions.do_raise()

**Future Exception Handling:**

.. code-block:: python

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def risky_task(item):
        if item % 5 == 0:
            raise ValueError(f"Failed on {item}")
        return item * 2

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(risky_task, i) for i in range(20)]

        # Handle exceptions gracefully without stopping execution
        for result in bolster.exceptional_executor(futures):
            print(f"Got result: {result}")

Development Utilities
~~~~~~~~~~~~~~~~~~~~~

**Directory Context Manager:**

.. code-block:: python

    from pathlib import Path

    with bolster.working_directory("/tmp"):
        # All file operations happen in /tmp
        Path("test.txt").write_text("Hello World")

    # Back to original directory
    print(Path.cwd())

**HTTP Request Debugging:**

.. code-block:: python

    import requests

    req = requests.Request('POST', 'https://api.example.com',
                          headers={'Authorization': 'Bearer secret-token'},
                          json={'data': 'test'})
    prepared = req.prepare()

    # Debug request with automatic auth header redaction
    bolster.pretty_print_request(
        prepared,
        authentication_header_blacklist=['Authorization']
    )

Tree and Dictionary Analysis
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Analyze nested data structures
    tree_data = {
        'root': {
            'branch1': {'leaf1': 1, 'leaf2': 2},
            'branch2': {'leaf3': 3, 'leaf4': {'deep': 4}}
        }
    }

    print(f"Tree depth: {bolster.depth(tree_data)}")      # 4
    print(f"Tree breadth: {bolster.breadth(tree_data)}")  # 4 (total leaves)

    # Get all leaf values
    leaves = list(bolster.leaves(tree_data))
    print(leaves)  # [1, 2, 3, 4]

    # Get keys at specific depth level
    level_2_keys = list(bolster.keys_at(tree_data, 2))
    print(level_2_keys)  # ['leaf1', 'leaf2', 'leaf3', 'leaf4']

Data Serialization
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Compress data for efficient storage/transmission
    data = {'large': 'dataset', 'with': ['many', 'items']}

    compressed = bolster.compress_for_relay(data)
    print(f"Compressed size: {len(compressed)} characters")

    # Decompress back to original
    decompressed = bolster.decompress_from_relay(compressed)
    assert decompressed == data
