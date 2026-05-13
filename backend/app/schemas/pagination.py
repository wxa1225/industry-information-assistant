# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有

"""
分页工具

为所有列表端点提供统一的分页参数解析和响应格式。
"""

from typing import Generic, TypeVar, List, Optional
from pydantic import BaseModel, Field


T = TypeVar("T")


class PageRequest:
    """分页请求参数解析"""

    @staticmethod
    def validate_page(page: int, page_size: int) -> tuple[int, int]:
        """
        校验分页参数。

        Args:
            page: 页码（从 1 开始）
            page_size: 每页数量

        Returns:
            (offset, limit) 元组

        Raises:
            ValueError: 如果参数无效
        """
        if page < 1:
            raise ValueError("page 必须 >= 1")
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size 必须在 1-100 之间")
        return (page - 1) * page_size, page_size


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应格式"""
    items: List[T] = Field(description="当前页数据")
    total: int = Field(description="总记录数")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页数量")
    has_next: bool = Field(description="是否有下一页")

    @classmethod
    def create(cls, items: List[T], total: int, page: int, page_size: int) -> "PaginatedResponse[T]":
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_next=page * page_size < total,
        )
