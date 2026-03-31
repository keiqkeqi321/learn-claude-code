"""
Unit tests for mypackage/helpers.py module.

Tests cover string manipulation, data processing, and list operations.
"""

import unittest
from datetime import datetime
from mypackage.helpers import (
    format_timestamp,
    truncate_string,
    safe_json_loads,
    merge_dicts,
    chunk_list,
    flatten_list,
)


class TestFormatTimestamp(unittest.TestCase):
    """Test format_timestamp function."""
    
    def test_default_format_with_none(self) -> None:
        """Test formatting with None (uses current time)."""
        result = format_timestamp()
        # Should be a string in default format
        self.assertIsInstance(result, str)
        # Should match the format pattern (YYYY-MM-DD HH:MM:SS)
        parts = result.split(' ')
        self.assertEqual(len(parts), 2)
        date_parts = parts[0].split('-')
        self.assertEqual(len(date_parts), 3)
        
    def test_custom_datetime(self) -> None:
        """Test formatting with custom datetime object."""
        dt = datetime(2024, 1, 15, 10, 30, 45)
        result = format_timestamp(dt)
        self.assertEqual(result, "2024-01-15 10:30:45")
        
    def test_custom_format(self) -> None:
        """Test formatting with custom format string."""
        dt = datetime(2024, 12, 25, 8, 15, 0)
        result = format_timestamp(dt, fmt="%Y-%m-%d")
        self.assertEqual(result, "2024-12-25")
        
    def test_iso_format(self) -> None:
        """Test ISO format."""
        dt = datetime(2024, 6, 15, 14, 30, 0)
        result = format_timestamp(dt, fmt="%Y-%m-%dT%H:%M:%S")
        self.assertEqual(result, "2024-06-15T14:30:00")
        
    def test_time_only_format(self) -> None:
        """Test time-only format."""
        dt = datetime(2024, 1, 1, 15, 45, 30)
        result = format_timestamp(dt, fmt="%H:%M:%S")
        self.assertEqual(result, "15:45:30")


class TestTruncateString(unittest.TestCase):
    """Test truncate_string function."""
    
    def test_no_truncation_needed(self) -> None:
        """Test when string is shorter than max_length."""
        result = truncate_string("Hello", max_length=10)
        self.assertEqual(result, "Hello")
        
    def test_truncation_occurs(self) -> None:
        """Test when string exceeds max_length."""
        result = truncate_string("Hello World", max_length=8)
        self.assertEqual(result, "Hello...")
        self.assertEqual(len(result), 8)
        
    def test_exact_length(self) -> None:
        """Test when string is exactly max_length."""
        result = truncate_string("Hello", max_length=5)
        self.assertEqual(result, "Hello")
        
    def test_custom_suffix(self) -> None:
        """Test with custom suffix."""
        result = truncate_string("Hello World", max_length=9, suffix="***")
        self.assertEqual(result, "Hello ***")
        
    def test_empty_string(self) -> None:
        """Test with empty string."""
        result = truncate_string("", max_length=10)
        self.assertEqual(result, "")
        
    def test_very_long_suffix(self) -> None:
        """Test with suffix longer than max_length."""
        # This tests edge case behavior
        result = truncate_string("Hello", max_length=3, suffix="...")
        # "Hello" has length 5, max_length is 3
        # Truncation: text[:3-3] + "..." = "" + "..." = "..."
        self.assertEqual(result, "...")
        self.assertEqual(len(result), 3)
        
    def test_default_max_length(self) -> None:
        """Test default max_length of 100."""
        long_string = "x" * 150
        result = truncate_string(long_string)
        self.assertEqual(len(result), 100)
        self.assertTrue(result.endswith("..."))


class TestSafeJsonLoads(unittest.TestCase):
    """Test safe_json_loads function."""
    
    def test_valid_json_object(self) -> None:
        """Test parsing valid JSON object."""
        result = safe_json_loads('{"key": "value", "number": 42}')
        self.assertEqual(result, {"key": "value", "number": 42})
        
    def test_valid_json_array(self) -> None:
        """Test parsing valid JSON array."""
        result = safe_json_loads('[1, 2, 3, 4]')
        self.assertEqual(result, [1, 2, 3, 4])
        
    def test_valid_json_string(self) -> None:
        """Test parsing valid JSON string."""
        result = safe_json_loads('"hello world"')
        self.assertEqual(result, "hello world")
        
    def test_invalid_json_default_dict(self) -> None:
        """Test invalid JSON returns default dict."""
        result = safe_json_loads('not valid json')
        self.assertEqual(result, {})
        
    def test_invalid_json_custom_default(self) -> None:
        """Test invalid JSON returns custom default."""
        result = safe_json_loads('invalid', default=None)
        self.assertIsNone(result)
        
    def test_invalid_json_list_default(self) -> None:
        """Test invalid JSON with list default."""
        result = safe_json_loads('bad json', default=[])
        self.assertEqual(result, [])
        
    def test_invalid_json_with_none_data(self) -> None:
        """Test with None as data (TypeError case)."""
        result = safe_json_loads(None, default="fallback")
        self.assertEqual(result, "fallback")
        
    def test_empty_string(self) -> None:
        """Test empty string."""
        result = safe_json_loads('', default="empty")
        self.assertEqual(result, "empty")


class TestMergeDicts(unittest.TestCase):
    """Test merge_dicts function."""
    
    def test_simple_merge(self) -> None:
        """Test merging two simple dictionaries."""
        base = {"a": 1, "b": 2}
        updates = {"c": 3, "d": 4}
        result = merge_dicts(base, updates)
        self.assertEqual(result, {"a": 1, "b": 2, "c": 3, "d": 4})
        
    def test_overwrite_values(self) -> None:
        """Test that updates overwrite base values."""
        base = {"a": 1, "b": 2}
        updates = {"b": 20, "c": 3}
        result = merge_dicts(base, updates)
        self.assertEqual(result, {"a": 1, "b": 20, "c": 3})
        
    def test_nested_merge(self) -> None:
        """Test recursive merge of nested dictionaries."""
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        updates = {"b": {"e": 4}, "f": 5}
        result = merge_dicts(base, updates)
        self.assertEqual(result, {"a": 1, "b": {"c": 2, "d": 3, "e": 4}, "f": 5})
        
    def test_deep_nested_merge(self) -> None:
        """Test deeply nested merge."""
        base = {"level1": {"level2": {"a": 1}}}
        updates = {"level1": {"level2": {"b": 2}, "level2b": 3}}
        result = merge_dicts(base, updates)
        self.assertEqual(result, {"level1": {"level2": {"a": 1, "b": 2}, "level2b": 3}})
        
    def test_base_not_modified(self) -> None:
        """Test that original base dict is not modified."""
        base = {"a": 1}
        updates = {"b": 2}
        result = merge_dicts(base, updates)
        self.assertEqual(base, {"a": 1})
        self.assertEqual(result, {"a": 1, "b": 2})
        
    def test_empty_updates(self) -> None:
        """Test merging with empty updates dict."""
        base = {"a": 1, "b": 2}
        updates = {}
        result = merge_dicts(base, updates)
        self.assertEqual(result, {"a": 1, "b": 2})
        
    def test_empty_base(self) -> None:
        """Test merging with empty base dict."""
        base = {}
        updates = {"a": 1}
        result = merge_dicts(base, updates)
        self.assertEqual(result, {"a": 1})
        
    def test_non_dict_value_overwrites_dict(self) -> None:
        """Test that non-dict value overwrites dict value."""
        base = {"a": {"nested": "value"}}
        updates = {"a": "simple"}
        result = merge_dicts(base, updates)
        self.assertEqual(result, {"a": "simple"})


class TestChunkList(unittest.TestCase):
    """Test chunk_list function."""
    
    def test_even_chunks(self) -> None:
        """Test splitting into even chunks."""
        result = chunk_list([1, 2, 3, 4, 6, 8], 2)
        self.assertEqual(result, [[1, 2], [3, 4], [6, 8]])
        
    def test_uneven_chunks(self) -> None:
        """Test splitting with remainder."""
        result = chunk_list([1, 2, 3, 4, 5], 2)
        self.assertEqual(result, [[1, 2], [3, 4], [5]])
        
    def test_single_chunk(self) -> None:
        """Test with chunk_size larger than list."""
        result = chunk_list([1, 2, 3], 10)
        self.assertEqual(result, [[1, 2, 3]])
        
    def test_chunk_size_one(self) -> None:
        """Test with chunk_size of 1."""
        result = chunk_list([1, 2, 3], 1)
        self.assertEqual(result, [[1], [2], [3]])
        
    def test_empty_list(self) -> None:
        """Test with empty list."""
        result = chunk_list([], 5)
        self.assertEqual(result, [])
        
    def test_invalid_chunk_size_zero(self) -> None:
        """Test that zero chunk_size raises ValueError."""
        with self.assertRaises(ValueError) as context:
            chunk_list([1, 2, 3], 0)
        self.assertIn("must be positive", str(context.exception))
        
    def test_invalid_chunk_size_negative(self) -> None:
        """Test that negative chunk_size raises ValueError."""
        with self.assertRaises(ValueError) as context:
            chunk_list([1, 2, 3], -1)
        self.assertIn("must be positive", str(context.exception))
        
    def test_chunk_mixed_types(self) -> None:
        """Test chunking list with mixed types."""
        result = chunk_list([1, "a", 2.5, None, True], 2)
        self.assertEqual(result, [[1, "a"], [2.5, None], [True]])


class TestFlattenList(unittest.TestCase):
    """Test flatten_list function."""
    
    def test_normal_flatten(self) -> None:
        """Test flattening nested list."""
        result = flatten_list([[1, 2], [3, 4], [5, 6]])
        self.assertEqual(result, [1, 2, 3, 4, 5, 6])
        
    def test_empty_outer_list(self) -> None:
        """Test flattening empty list."""
        result = flatten_list([])
        self.assertEqual(result, [])
        
    def test_empty_inner_lists(self) -> None:
        """Test flattening with empty inner lists."""
        result = flatten_list([[1, 2], [], [3]])
        self.assertEqual(result, [1, 2, 3])
        
    def test_single_element_sublists(self) -> None:
        """Test with single element sublists."""
        result = flatten_list([[1], [2], [3]])
        self.assertEqual(result, [1, 2, 3])
        
    def test_single_sublist(self) -> None:
        """Test with single sublist."""
        result = flatten_list([[1, 2, 3]])
        self.assertEqual(result, [1, 2, 3])
        
    def test_mixed_types(self) -> None:
        """Test flattening list with mixed types."""
        result = flatten_list([["a", "b"], [1, 2], [None, True]])
        self.assertEqual(result, ["a", "b", 1, 2, None, True])
        
    def test_preserves_order(self) -> None:
        """Test that order is preserved."""
        result = flatten_list([[3, 1], [4, 1], [5, 9]])
        self.assertEqual(result, [3, 1, 4, 1, 5, 9])


if __name__ == "__main__":
    unittest.main()