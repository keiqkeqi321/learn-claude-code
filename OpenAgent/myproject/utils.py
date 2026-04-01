"""Utility functions for MyProject."""

from typing import Union


def greet(name: str) -> str:
    """Return a greeting message for the given name.

    Args:
        name: The name to greet.

    Returns:
        A greeting string.

    Example:
        >>> greet("Alice")
        'Hello, Alice!'
    """
    return f"Hello, {name}!"


def add_numbers(a: Union[int, float], b: Union[int, float]) -> Union[int, float]:
    """Add two numbers together.

    Args:
        a: First number.
        b: Second number.

    Returns:
        The sum of a and b.

    Example:
        >>> add_numbers(2, 3)
        5
        >>> add_numbers(1.5, 2.5)
        4.0
    """
    return a + b
