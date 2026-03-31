"""
Helper utilities for common operations.

This module provides additional utility functions for string manipulation,
data processing, and other common tasks.
"""

from typing import Any, List, Dict, Optional
from datetime import datetime
import json


# Sentinel value for safe_json_loads default parameter
_SENTINEL = object()


def format_timestamp(dt: Optional[datetime] = None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format a datetime object as a string.
    
    Args:
        dt: Datetime object to format. If None, uses current time.
        fmt: Format string for the output.
    
    Returns:
        Formatted datetime string.
    
    Example:
        >>> format_timestamp()
        '2024-01-15 10:30:00'
        >>> format_timestamp(datetime(2024, 1, 1), "%Y-%m-%d")
        '2024-01-01'
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime(fmt)


def truncate_string(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Truncate a string to a maximum length.
    
    Args:
        text: The string to truncate.
        max_length: Maximum length of the output string.
        suffix: Suffix to append when truncation occurs.
    
    Returns:
        Truncated string with suffix if truncation occurred.
    
    Example:
        >>> truncate_string("Hello World", 8)
        'Hello...'
        >>> truncate_string("Hi", 10)
        'Hi'
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def safe_json_loads(data: str, default: Any = _SENTINEL) -> Any:
    """
    Safely parse JSON string.
    
    Args:
        data: JSON string to parse.
        default: Default value to return if parsing fails. 
                 If not provided, defaults to empty dict {}.
    
    Returns:
        Parsed JSON data or default value on error.
    
    Example:
        >>> safe_json_loads('{"key": "value"}')
        {'key': 'value'}
        >>> safe_json_loads('invalid json', {})
        {}
        >>> safe_json_loads('invalid json', None)
        None
        >>> safe_json_loads('invalid json', [])
        []
    """
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return {} if default is _SENTINEL else default


def merge_dicts(base: Dict, updates: Dict) -> Dict:
    """
    Recursively merge two dictionaries.
    
    Args:
        base: Base dictionary to merge into.
        updates: Dictionary with updates to apply.
    
    Returns:
        New merged dictionary.
    
    Example:
        >>> merge_dicts({'a': 1, 'b': {'c': 2}}, {'b': {'d': 3}})
        {'a': 1, 'b': {'c': 2, 'd': 3}}
    """
    result = base.copy()
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def chunk_list(items: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Split a list into chunks of specified size.
    
    Args:
        items: List to split.
        chunk_size: Maximum size of each chunk.
    
    Returns:
        List of chunked lists.
    
    Example:
        >>> chunk_list([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def flatten_list(nested_list: List[List[Any]]) -> List[Any]:
    """
    Flatten a nested list by one level.
    
    Args:
        nested_list: List of lists to flatten.
    
    Returns:
        Flattened list.
    
    Example:
        >>> flatten_list([[1, 2], [3, 4], [5]])
        [1, 2, 3, 4, 5]
    """
    return [item for sublist in nested_list for item in sublist]


# Module metadata
__author__ = "OpenAgent Team"
__version__ = "1.0.0"