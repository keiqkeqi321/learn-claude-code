"""
Unit tests for hello.py module.

Tests cover the greet function with various inputs and edge cases.
"""

import unittest
from hello import greet, main


class TestGreet(unittest.TestCase):
    """Test greet function."""
    
    def test_greet_with_name(self) -> None:
        """Test greeting with a name."""
        result = greet("World")
        self.assertEqual(result, "Hello, World!")
        
    def test_greet_with_none(self) -> None:
        """Test greeting with None uses default."""
        result = greet(None)
        self.assertEqual(result, "Hello, stranger!")
        
    def test_greet_with_empty_string(self) -> None:
        """Test greeting with empty string."""
        result = greet("")
        self.assertEqual(result, "Hello, !")
        
    def test_greet_with_unicode(self) -> None:
        """Test greeting with unicode characters."""
        result = greet("世界")
        self.assertEqual(result, "Hello, 世界!")
        
    def test_greet_with_special_chars(self) -> None:
        """Test greeting with special characters."""
        result = greet("Alice & Bob")
        self.assertEqual(result, "Hello, Alice & Bob!")
        
    def test_greet_with_numbers_in_name(self) -> None:
        """Test greeting with numbers in name."""
        result = greet("User123")
        self.assertEqual(result, "Hello, User123!")
        
    def test_greet_with_whitespace(self) -> None:
        """Test greeting with whitespace in name."""
        result = greet("  John  ")
        self.assertEqual(result, "Hello,   John  !")
        
    def test_greet_return_type(self) -> None:
        """Test that greet returns a string."""
        result = greet("Test")
        self.assertIsInstance(result, str)
        
    def test_greet_docstring_examples(self) -> None:
        """Test examples from docstring."""
        self.assertEqual(greet("World"), "Hello, World!")
        self.assertEqual(greet(), "Hello, stranger!")


class TestMain(unittest.TestCase):
    """Test main function."""
    
    def test_main_prints_greeting(self) -> None:
        """Test that main function prints greeting."""
        import io
        import sys
        
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            main()
        finally:
            sys.stdout = sys.__stdout__
            
        output = captured_output.getvalue().strip()
        self.assertEqual(output, "Hello, World!")


if __name__ == "__main__":
    unittest.main()