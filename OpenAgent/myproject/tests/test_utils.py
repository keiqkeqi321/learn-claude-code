"""Tests for MyProject utilities."""

import pytest
from myproject.utils import greet, add_numbers


class TestGreet:
    """Tests for the greet function."""

    def test_greet_with_name(self) -> None:
        """Test greeting with a specific name."""
        assert greet("Alice") == "Hello, Alice!"

    def test_greet_with_empty_name(self) -> None:
        """Test greeting with an empty name."""
        assert greet("") == "Hello, !"

    def test_greet_with_spaces(self) -> None:
        """Test greeting with names containing spaces."""
        assert greet("John Doe") == "Hello, John Doe!"


class TestAddNumbers:
    """Tests for the add_numbers function."""

    def test_add_integers(self) -> None:
        """Test adding two integers."""
        assert add_numbers(2, 3) == 5

    def test_add_floats(self) -> None:
        """Test adding two floats."""
        assert add_numbers(1.5, 2.5) == 4.0

    def test_add_mixed(self) -> None:
        """Test adding integer and float."""
        assert add_numbers(1, 2.5) == 3.5

    def test_add_negative(self) -> None:
        """Test adding negative numbers."""
        assert add_numbers(-1, -2) == -3

    def test_add_zero(self) -> None:
        """Test adding with zero."""
        assert add_numbers(0, 5) == 5
