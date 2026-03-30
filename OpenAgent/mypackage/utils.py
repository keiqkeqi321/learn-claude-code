"""实用工具模块.

提供常用的工具函数。
"""

from typing import List, Optional


def greet_user(name: str, greeting: str = "Hello") -> str:
    """生成个性化的问候语.

    Args:
        name: 用户名。
        greeting: 问候词，默认为 "Hello"。

    Returns:
        格式化的问候字符串。

    Raises:
        ValueError: 如果 name 为空字符串。

    Examples:
        >>> greet_user("Alice")
        'Hello, Alice!'
        >>> greet_user("Bob", "Hi")
        'Hi, Bob!'
    """
    if not name:
        raise ValueError("Name cannot be empty")
    return f"{greeting}, {name}!"


def calculate_average(numbers: List[float]) -> Optional[float]:
    """计算数字列表的平均值.

    Args:
        numbers: 数字列表。

    Returns:
        平均值。如果列表为空则返回 None。

    Examples:
        >>> calculate_average([1, 2, 3, 4, 5])
        3.0
        >>> calculate_average([])
        None
    """
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def is_positive(number: float) -> bool:
    """检查数字是否为正数.

    Args:
        number: 要检查的数字。

    Returns:
        如果数字为正数返回 True，否则返回 False。

    Examples:
        >>> is_positive(5)
        True
        >>> is_positive(-3)
        False
        >>> is_positive(0)
        False
    """
    return number > 0