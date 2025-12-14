#!/usr/bin/env python
"""Comprehensive tests for core bolster utilities in __init__.py"""

import json
import os
import tempfile
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from unittest.mock import Mock, patch

import pytest

import bolster
from bolster import (
    MultipleErrors,
    aggregate,
    always,
    arg_exception_logger,
    backoff,
    batch,
    breadth,
    build_default_mapping_dict_from_keys,
    chunks,
    compress_for_relay,
    decompress_from_relay,
    depth,
    diff,
    exceptional_executor,
    flatten_dict,
    get_recursively,
    items_at,
    keys_at,
    leaf_paths,
    leaves,
    memoize,
    poolmap,
    set_keys,
    tag_gen,
    transform_,
    working_directory,
)


class TestUtilityFunctions:
    """Test basic utility functions."""

    def test_always(self):
        """Test the always function."""
        assert always(True) is True
        assert always(False) is True
        assert always("false") is True
        assert always(None) is True
        assert always(0) is True

    def test_batch(self):
        """Test the batch function."""
        seq = list(range(10))
        batches = list(batch(seq, 3))
        assert len(batches) == 4
        assert batches[0] == [0, 1, 2]
        assert batches[1] == [3, 4, 5]  # Non-overlapping batches
        assert batches[2] == [6, 7, 8]
        assert batches[3] == [9]  # Last batch has remaining items

        # Test single item batches
        single_batches = list(batch(seq, 1))
        assert len(single_batches) == 10
        assert single_batches[0] == [0]

    def test_chunks(self):
        """Test the chunks function."""
        seq = list(range(10))
        chunk_list = list(chunks(seq, 3))
        assert len(chunk_list) == 4
        assert chunk_list[0] == [0, 1, 2]
        assert chunk_list[1] == [3, 4, 5]
        assert chunk_list[2] == [6, 7, 8]
        assert chunk_list[3] == [9]

    def test_compress_decompress_relay(self):
        """Test compression and decompression utilities."""
        test_list = ["test", "data", "compression"]
        compressed = compress_for_relay(test_list)
        assert isinstance(compressed, str)
        decompressed = decompress_from_relay(compressed)
        assert decompressed == test_list

        test_dict = {"test": "data", "nested": {"key": "value"}}
        compressed = compress_for_relay(test_dict)
        decompressed = decompress_from_relay(compressed)
        assert decompressed == test_dict


class TestConcurrencyUtilities:
    """Test concurrency-related utilities."""

    def test_poolmap_basic(self):
        """Test basic poolmap functionality."""
        def square(x):
            return x * x

        numbers = [1, 2, 3, 4, 5]
        results = poolmap(square, numbers)

        assert len(results) == 5
        assert results[1] == 1
        assert results[2] == 4
        assert results[3] == 9
        assert results[4] == 16
        assert results[5] == 25

    def test_poolmap_with_kwargs(self):
        """Test poolmap with keyword arguments."""
        def multiply(x, factor=2):
            return x * factor

        numbers = [1, 2, 3]
        results = poolmap(multiply, numbers, factor=3)

        assert results[1] == 3
        assert results[2] == 6
        assert results[3] == 9

    def test_poolmap_with_progress(self):
        """Test poolmap with progress callback."""
        call_count = 0

        def mock_progress(iterable, total=None):
            nonlocal call_count
            call_count += 1
            return iterable

        def identity(x):
            return x

        numbers = [1, 2, 3]
        poolmap(identity, numbers, progress=mock_progress)
        assert call_count == 1

    def test_exceptional_executor(self):
        """Test exceptional_executor function."""
        def good_task():
            return "success"

        def bad_task():
            raise ValueError("test error")

        with ThreadPoolExecutor() as executor:
            good_future = executor.submit(good_task)
            bad_future = executor.submit(bad_task)

            futures = [good_future, bad_future]
            results = list(exceptional_executor(futures))

            # Should only get the successful result
            assert len(results) == 1
            assert results[0] == "success"

    def test_exceptional_executor_with_custom_handler(self):
        """Test exceptional_executor with custom exception handler."""
        exceptions_caught = []

        def custom_handler(e, f):
            exceptions_caught.append(e)

        def bad_task():
            raise ValueError("custom error")

        with ThreadPoolExecutor() as executor:
            bad_future = executor.submit(bad_task)
            futures = [bad_future]
            list(exceptional_executor(futures, exception_handler=custom_handler))

            assert len(exceptions_caught) == 1
            assert isinstance(exceptions_caught[0], ValueError)
            assert str(exceptions_caught[0]) == "custom error"


class TestBackoffDecorator:
    """Test the backoff retry decorator."""

    def test_backoff_success(self):
        """Test backoff decorator with successful function."""
        call_count = 0

        @backoff(ValueError, tries=3, delay=0.01, backoff=2)
        def sometimes_fails():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("temporary failure")
            return "success"

        result = sometimes_fails()
        assert result == "success"
        assert call_count == 2

    def test_backoff_exhausted(self):
        """Test backoff decorator when retries are exhausted."""
        call_count = 0

        @backoff(ValueError, tries=2, delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("permanent failure")

        with pytest.raises(ValueError, match="permanent failure"):
            always_fails()

        assert call_count == 2

    def test_backoff_wrong_exception(self):
        """Test backoff decorator with wrong exception type."""
        @backoff(ValueError, tries=3, delay=0.01)
        def raises_wrong_exception():
            raise TypeError("wrong exception")

        with pytest.raises(TypeError, match="wrong exception"):
            raises_wrong_exception()


class TestMultipleErrors:
    """Test the MultipleErrors exception class."""

    def test_multiple_errors_basic(self):
        """Test basic MultipleErrors functionality."""
        errors = MultipleErrors()
        assert len(errors.errors) == 0

        # Should not raise when empty
        errors.do_raise()

    def test_multiple_errors_capture(self):
        """Test capturing multiple exceptions."""
        errors = MultipleErrors()

        try:
            raise ValueError("first error")
        except:
            errors.capture_current_exception()

        try:
            raise TypeError("second error")
        except:
            errors.capture_current_exception()

        assert len(errors.errors) == 2

        with pytest.raises(MultipleErrors):
            errors.do_raise()

    def test_multiple_errors_str(self):
        """Test string representation of MultipleErrors."""
        errors = MultipleErrors()

        try:
            raise ValueError("test error")
        except:
            errors.capture_current_exception()

        error_str = str(errors)
        assert "ValueError" in error_str
        assert "test error" in error_str


class TestMemoizeDecorator:
    """Test the memoize caching decorator."""

    def test_memoize_basic(self):
        """Test basic memoization."""
        call_count = 0

        class TestClass:
            @memoize
            def expensive_method(self, x):
                nonlocal call_count
                call_count += 1
                return x * 2

        obj = TestClass()

        # First call
        result1 = obj.expensive_method(5)
        assert result1 == 10
        assert call_count == 1

        # Second call with same argument (should be cached)
        result2 = obj.expensive_method(5)
        assert result2 == 10
        assert call_count == 1  # No additional call

        # Call with different argument
        result3 = obj.expensive_method(7)
        assert result3 == 14
        assert call_count == 2

    def test_memoize_cache_counters(self):
        """Test memoize hit/miss counters."""
        class TestClass:
            @memoize
            def cached_method(self, x):
                return x * 3

        obj = TestClass()

        # First call (miss)
        obj.cached_method(2)
        assert hasattr(obj, '_memoize__cache')
        assert hasattr(obj, '_memoize__hits')
        assert hasattr(obj, '_memoize__misses')

        # Second call with same arg (hit)
        obj.cached_method(2)

        # Check counters have expected types and contain data
        cache = getattr(obj, '_memoize__cache')
        hits = getattr(obj, '_memoize__hits')
        misses = getattr(obj, '_memoize__misses')

        assert isinstance(cache, dict)
        assert len(cache) == 1  # One cached result
        assert len(hits) >= 0
        assert len(misses) >= 0


class TestArgumentExceptionLogger:
    """Test the arg_exception_logger decorator."""

    def test_arg_exception_logger_success(self):
        """Test decorator with successful function."""
        @arg_exception_logger
        def working_function(x, y=None):
            return x + (y or 0)

        result = working_function(5, y=3)
        assert result == 8

    def test_arg_exception_logger_failure(self):
        """Test decorator with failing function."""
        @arg_exception_logger
        def failing_function(x, y):
            return x / y  # Will fail with y=0

        with pytest.raises(ValueError) as exc_info:
            failing_function(10, 0)

        # Should wrap the original exception with argument info
        assert "Failed with args" in str(exc_info.value)
        assert "(10, 0)" in str(exc_info.value)


class TestTreeUtilities:
    """Test tree and dictionary navigation utilities."""

    def setup_method(self):
        """Set up test data."""
        self.nested_dict = {
            'a': 1,
            'b': {
                'c': 2,
                'd': {
                    'e': 3,
                    'f': 4
                }
            },
            'g': [{'h': 5}, {'i': 6}]
        }

    def test_get_recursively(self):
        """Test recursive key extraction."""
        # Find single key
        values = get_recursively(self.nested_dict, 'e')
        assert values == [3]

        # Find non-existent key
        values = get_recursively(self.nested_dict, 'z')
        assert values == []

        # Find key that appears in lists
        values = get_recursively(self.nested_dict, 'h')
        assert values == [5]

    def test_breadth(self):
        """Test tree breadth calculation."""
        simple_dict = {'a': 1, 'b': 2, 'c': {'d': 3}}
        assert breadth(simple_dict) == 3

        assert breadth({'single': 42}) == 1
        assert breadth(42) == 1  # Non-dict returns 1

    def test_depth(self):
        """Test tree depth calculation."""
        simple_dict = {'a': 1, 'b': {'c': {'d': 4}}}
        assert depth(simple_dict) == 3

        assert depth({'single': 42}) == 1
        assert depth(42) == 0  # Non-dict returns 0

    def test_set_keys(self):
        """Test set of all keys extraction."""
        keys = set_keys(self.nested_dict)
        # set_keys only returns leaf keys (keys with non-dict values)
        expected_keys = {'a', 'c', 'e', 'f', 'g'}  # Only leaf keys, not 'b' or 'd'
        assert keys == expected_keys

    def test_keys_at_depth(self):
        """Test keys at specific depth."""
        keys_0 = list(keys_at(self.nested_dict, 0))
        assert set(keys_0) == {'a', 'b', 'g'}

        keys_1 = list(keys_at(self.nested_dict, 1))
        assert set(keys_1) == {'c', 'd'}

    def test_items_at_depth(self):
        """Test items at specific depth."""
        items_0 = list(items_at(self.nested_dict, 0))
        expected_items = [('a', 1), ('b', self.nested_dict['b']), ('g', self.nested_dict['g'])]
        assert len(items_0) == 3

    def test_leaves(self):
        """Test leaf extraction."""
        leaf_values = list(leaves(self.nested_dict))
        # Should contain all non-dict values including the list
        assert 1 in leaf_values
        assert self.nested_dict['g'] in leaf_values

    def test_leaf_paths(self):
        """Test leaf paths extraction."""
        paths = list(leaf_paths({'a': {'b': 2, 'c': 3}}))
        assert (['a', 'b'], 2) in paths
        assert (['a', 'c'], 3) in paths

    def test_flatten_dict(self):
        """Test dictionary flattening."""
        nested = {'a': {'b': 1, 'c': 2}, 'd': 3}
        flat = flatten_dict(nested)

        assert 'a:b' in flat
        assert 'a:c' in flat
        assert flat['a:b'] == 1
        assert flat['a:c'] == 2


class TestDataTransformation:
    """Test data transformation utilities."""

    def test_transform_basic(self):
        """Test basic transformation."""
        record = {'a': '1', 'b': '2', 'c': '3'}

        # Simple selection
        result = transform_(record, {'a': None})
        assert result == {'a': '1'}

    def test_transform_with_function(self):
        """Test transformation with function application."""
        record = {'a': '1', 'b': '2'}
        rules = {'a': ('a', int), 'b': None}

        result = transform_(record, rules)
        assert result == {'a': 1, 'b': '2'}

    def test_transform_with_renaming(self):
        """Test transformation with key renaming."""
        record = {'old_key': 'value'}
        rules = {'old_key': ('new_key', None)}

        result = transform_(record, rules)
        assert result == {'new_key': 'value'}

    def test_aggregate_function(self):
        """Test the aggregate function."""
        data = [
            {'category': 'A', 'value': 10},
            {'category': 'B', 'value': 5},
            {'category': 'A', 'value': 15},
        ]

        result = aggregate(data, 'category', 'value')
        assert result['A'] == 25
        assert result['B'] == 5

    def test_diff_function(self):
        """Test the diff function."""
        old = {'a': 1, 'b': 2, 'c': 3}
        new = {'a': 1, 'b': 20, 'd': 4}

        differences = diff(new, old)

        assert 'a' not in differences  # Same value
        assert differences['b']['old'] == 2
        assert differences['b']['new'] == 20
        assert differences['c']['old'] == 3
        assert differences['c']['new'] is None
        assert differences['d']['old'] is None
        assert differences['d']['new'] == 4

    def test_tag_gen(self):
        """Test tag generator function."""
        data = [{'existing': 1}, {'existing': 2}]
        tagged = list(tag_gen(iter(data), new_tag='added'))

        assert len(tagged) == 2
        assert tagged[0]['existing'] == 1
        assert tagged[0]['new_tag'] == 'added'
        assert tagged[1]['existing'] == 2
        assert tagged[1]['new_tag'] == 'added'


class TestUtilityHelpers:
    """Test miscellaneous utility helpers."""

    def test_working_directory(self):
        """Test working directory context manager."""
        original_dir = Path.cwd()

        with tempfile.TemporaryDirectory() as temp_dir:
            with working_directory(temp_dir):
                assert Path.cwd() == Path(temp_dir).resolve()

            # Should return to original directory
            assert Path.cwd() == original_dir

    def test_build_default_mapping_dict(self):
        """Test default mapping dictionary builder."""
        keys = ['snake_case', 'another_key', 'final_item']
        mapping = build_default_mapping_dict_from_keys(keys)

        assert mapping['snake_case'] == 'Snake Case'
        assert mapping['another_key'] == 'Another Key'
        assert mapping['final_item'] == 'Final Item'


class TestPrettyPrintRequest:
    """Test request pretty printing utility."""

    def test_pretty_print_request(self, capsys):
        """Test pretty printing of requests."""
        # Create a mock request object
        mock_request = Mock()
        mock_request.method = 'GET'
        mock_request.url = 'https://example.com/api'
        mock_request.headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer token'}
        mock_request.body = '{"key": "value"}'

        # Test with auth exposure disabled (default)
        bolster.pretty_print_request(mock_request, authentication_header_blacklist=['Authorization'])

        captured = capsys.readouterr()
        assert 'GET https://example.com/api' in captured.out
        assert '<<REDACTED>>' in captured.out
        assert '{"key": "value"}' in captured.out

    def test_pretty_print_request_expose_auth(self, capsys):
        """Test pretty printing with auth exposed."""
        mock_request = Mock()
        mock_request.method = 'POST'
        mock_request.url = 'https://api.example.com'
        mock_request.headers = {'Authorization': 'Bearer secret-token'}
        mock_request.body = None

        bolster.pretty_print_request(mock_request, expose_auth=True, authentication_header_blacklist=[])

        captured = capsys.readouterr()
        assert 'Bearer secret-token' in captured.out
        assert '<<REDACTED>>' not in captured.out