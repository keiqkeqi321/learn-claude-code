"""mypackage 的单元测试."""

import unittest

from mypackage.utils import calculate_average, greet_user, is_positive


class TestGreetUser(unittest.TestCase):
    """测试 greet_user 函数."""

    def test_default_greeting(self) -> None:
        """测试默认问候."""
        result = greet_user("Alice")
        self.assertEqual(result, "Hello, Alice!")

    def test_custom_greeting(self) -> None:
        """测试自定义问候."""
        result = greet_user("Bob", "Hi")
        self.assertEqual(result, "Hi, Bob!")

    def test_empty_name_raises_error(self) -> None:
        """测试空名字抛出异常."""
        with self.assertRaises(ValueError):
            greet_user("")


class TestCalculateAverage(unittest.TestCase):
    """测试 calculate_average 函数."""

    def test_normal_list(self) -> None:
        """测试正常列表."""
        result = calculate_average([1, 2, 3, 4, 5])
        self.assertEqual(result, 3.0)

    def test_empty_list(self) -> None:
        """测试空列表."""
        result = calculate_average([])
        self.assertIsNone(result)

    def test_single_element(self) -> None:
        """测试单个元素."""
        result = calculate_average([42.0])
        self.assertEqual(result, 42.0)

    def test_floats(self) -> None:
        """测试浮点数."""
        result = calculate_average([1.5, 2.5, 3.0])
        self.assertAlmostEqual(result, 2.333333, places=5)


class TestIsPositive(unittest.TestCase):
    """测试 is_positive 函数."""

    def test_positive_number(self) -> None:
        """测试正数."""
        self.assertTrue(is_positive(5))

    def test_negative_number(self) -> None:
        """测试负数."""
        self.assertFalse(is_positive(-3))

    def test_zero(self) -> None:
        """测试零."""
        self.assertFalse(is_positive(0))


if __name__ == "__main__":
    unittest.main()