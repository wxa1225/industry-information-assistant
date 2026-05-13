# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有

"""
Tushare 数据服务 - 结构化金融数据源

提供实时行情、财务数据、行业分类等结构化数据。
Scout 发现涉及上市公司时自动调用此服务，而不是盲目搜索。

优化 #4: 多数据源扩展（Tushare 接入）
"""

import os
import json
import time
import hashlib
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Tushare 免费 token 注册地址: https://tushare.pro/register
_TUSHARE_TOKEN = os.getenv("TUSHARE_API_TOKEN", "")
_TUSHARE_BASE_URL = "https://api.tushare.pro"

# 缓存 Tushare 返回结果，避免重复调用
_CACHE: Dict[str, Dict] = {}
_CACHE_TTL_SEC = 300  # 5 分钟


def _cache_key(func_name: str, **kwargs) -> str:
    """生成缓存 key"""
    raw = f"{func_name}:{json.dumps(kwargs, sort_keys=True)}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _get_cache(key: str) -> Optional[Dict]:
    """获取缓存"""
    if key in _CACHE:
        entry = _CACHE[key]
        if time.time() - entry.get("_time", 0) < _CACHE_TTL_SEC:
            return entry.get("data")
        del _CACHE[key]
    return None


def _set_cache(key: str, data: Dict):
    """设置缓存"""
    _CACHE[key] = {"data": data, "_time": time.time()}


async def _tushare_request(api_name: str, params: Dict[str, Any]) -> Dict:
    """
    发送 Tushare API 请求

    Args:
        api_name: Tushare 接口名称（如 daily, daily_basic, income）
        params: 接口参数

    Returns:
        Tushare 返回的数据
    """
    if not _TUSHARE_TOKEN:
        return {"success": False, "error": "TUSHARE_API_TOKEN not configured"}

    cache_k = _cache_key(api_name, **params)
    cached = _get_cache(cache_k)
    if cached:
        logger.debug(f"[Tushare] Cache hit for {api_name}")
        return cached

    try:
        import httpx
        payload = {
            "api_name": api_name,
            "token": _TUSHARE_TOKEN,
            "params": params,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(_TUSHARE_BASE_URL, json=payload)
            resp.raise_for_status()
            result = resp.json()

        if result.get("code") != 0:
            return {
                "success": False,
                "error": result.get("msg", "Unknown error"),
            }

        data = {
            "success": True,
            "api_name": api_name,
            "fields": result.get("data", {}).get("fields", []),
            "items": result.get("data", {}).get("items", []),
        }

        _set_cache(cache_k, data)
        return data

    except Exception as e:
        logger.warning(f"[Tushare] API error ({api_name}): {e}")
        return {"success": False, "error": str(e)}


async def get_daily_quote(ts_code: str, trade_date: str = "") -> Dict[str, Any]:
    """
    获取个股日线行情

    Args:
        ts_code: 股票代码（如 600519.SH）
        trade_date: 交易日期（YYYYMMDD，默认今天）

    Returns:
        行情数据
    """
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    result = await _tushare_request("daily", {
        "ts_code": ts_code,
        "start_date": trade_date,
        "end_date": trade_date,
    })

    if not result.get("success"):
        return result

    fields = result.get("fields", [])
    items = result.get("items", [])
    if not items:
        return {"success": False, "error": f"No data for {ts_code} on {trade_date}"}

    row = dict(zip(fields, items[0]))
    return {
        "success": True,
        "type": "daily_quote",
        "data": row,
    }


async def get_daily_basic(ts_code: str, trade_date: str = "") -> Dict[str, Any]:
    """
    获取个股每日指标（PE、PB、总市值、流通市值、换手率等）

    Args:
        ts_code: 股票代码
        trade_date: 交易日期

    Returns:
        每日指标数据
    """
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    result = await _tushare_request("daily_basic", {
        "ts_code": ts_code,
        "start_date": trade_date,
        "end_date": trade_date,
        "fields": "ts_code,trade_date,pe,pe_ttm,pb,ps,total_mv,circ_mv,turnover_rate,volume_ratio",
    })

    if not result.get("success"):
        return result

    fields = result.get("fields", [])
    items = result.get("items", [])
    if not items:
        return {"success": False, "error": f"No daily_basic data for {ts_code} on {trade_date}"}

    row = dict(zip(fields, items[0]))
    return {
        "success": True,
        "type": "daily_basic",
        "data": row,
    }


async def get_financial_data(ts_code: str) -> Dict[str, Any]:
    """
    获取财务指标数据（营收、净利润、ROE 等）

    Args:
        ts_code: 股票代码

    Returns:
        最近一期财务数据
    """
    result = await _tushare_request("fina_indicator", {
        "ts_code": ts_code,
        "limit": 1,
    })

    if not result.get("success"):
        return result

    fields = result.get("fields", [])
    items = result.get("items", [])
    if not items:
        return {"success": False, "error": f"No financial data for {ts_code}"}

    row = dict(zip(fields, items[0]))
    return {
        "success": True,
        "type": "financial_data",
        "data": row,
    }


async def get_income(ts_code: str) -> Dict[str, Any]:
    """
    获取利润表数据

    Args:
        ts_code: 股票代码

    Returns:
        最近一期利润表
    """
    result = await _tushare_request("income", {
        "ts_code": ts_code,
        "limit": 1,
    })

    if not result.get("success"):
        return result

    fields = result.get("fields", [])
    items = result.get("items", [])
    if not items:
        return {"success": False, "error": f"No income data for {ts_code}"}

    row = dict(zip(fields, items[0]))
    return {
        "success": True,
        "type": "income_statement",
        "data": row,
    }


async def get_company_info(ts_code: str) -> Dict[str, Any]:
    """
    获取上市公司基本信息

    Args:
        ts_code: 股票代码

    Returns:
        公司基本信息
    """
    result = await _tushare_request("namechange", {
        "ts_code": ts_code,
        "limit": 1,
    })

    if not result.get("success"):
        return result

    fields = result.get("fields", [])
    items = result.get("items", [])
    if not items:
        return {"success": False, "error": f"No company info for {ts_code}"}

    row = dict(zip(fields, items[0]))
    return {
        "success": True,
        "type": "company_info",
        "data": row,
    }


async def query_company_comprehensive(ts_code: str) -> Dict[str, Any]:
    """
    综合查询：行情 + 指标 + 财务（一次调用获取完整数据）

    Args:
        ts_code: 股票代码（如 600519.SH）

    Returns:
        综合数据
    """
    import asyncio

    tasks = [
        get_daily_quote(ts_code),
        get_daily_basic(ts_code),
        get_company_info(ts_code),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    output = {"success": True, "ts_code": ts_code, "data": {}}

    for r in results:
        if isinstance(r, Exception):
            logger.warning(f"[Tushare] Sub-query failed: {r}")
            continue
        if r.get("success"):
            output["data"][r.get("type", "unknown")] = r.get("data", {})
        else:
            output.setdefault("warnings", []).append(r.get("error", "unknown"))

    return output


# ============================================================
# 股票代码转换工具
# ============================================================

def convert_to_ts_code(code: str) -> str:
    """
    将各种格式的股票代码转为 Tushare 格式（如 sh601009 → 601009.SH）

    Args:
        code: 股票代码（601009, sh601009, SZ000001 等）

    Returns:
        Tushare 格式代码
    """
    code = code.strip().upper()

    # 去除市场前缀
    if code.startswith(("SH", "SZ")):
        raw = code[2:]
        market = code[:2]
    else:
        raw = code
        # 根据代码判断市场：6开头=上海，0/3开头=深圳
        if raw.startswith("6"):
            market = "SH"
        else:
            market = "SZ"

    return f"{raw}.{market}"


def convert_from_ts_code(ts_code: str) -> str:
    """
    将 Tushare 格式转为传统格式（如 600519.SH → sh600519）

    Args:
        ts_code: Tushare 格式代码

    Returns:
        传统格式代码
    """
    parts = ts_code.split(".")
    if len(parts) == 2:
        raw, market = parts
        return f"{market.lower()}{raw}"
    return ts_code
