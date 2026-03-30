#!/usr/bin/env python3
"""Hello World 示例模块.

这个模块演示了 Python 代码的最佳实践，包括：
- 类型提示 (type hints)
- 文档字符串 (docstrings)
- main guard
"""

from typing import Optional


def greet(name: Optional[str] = None) -> str:
    """生成问候语.

    Args:
        name: 要问候的人名。如果为 None，则使用默认问候语。

    Returns:
        生成的问候字符串。

    Examples:
        >>> greet("World")
        'Hello, World!'
        >>> greet()
        'Hello, stranger!'
    """
    if name is None:
        return "Hello, stranger!"
    return f"Hello, {name}!"


def main() -> None:
    """程序入口函数."""
    message = greet("World")
    print(message)


if __name__ == "__main__":
    main()