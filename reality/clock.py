"""时间源模块：向虚拟世界提供真实时间，并判断日期是否为节假日。

约定：
- now() / today() 返回本机真实时间（模拟"现实在走、虚拟人在过"）。
- is_holiday(d)：周末 + 中国法定节假日。节日表为 2026-2027 硬编码
  （国务院每年 11 月前后公布次年安排，届时手动更新 HOLIDAY_RANGES 即可），
  不做农历推算、不做调休上班日判断（调休补班日仍按周末放假处理）。

本模块无网络调用、无第三方依赖。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

# 各年度法定节假日（放假日，含调休连休），按年度列出起止日期区间。
# 格式：(年份, [(起始日 月, 日), (结束日 月, 日)])；区间为闭区间。
HOLIDAY_RANGES: dict[int, list[tuple[tuple[int, int], tuple[int, int]]]] = {
    2026: [
        ((1, 1), (1, 3)),      # 元旦
        ((2, 15), (2, 21)),    # 春节（2/17 除夕？以官方公布为准，此处取 2/15-2/21）
        ((4, 4), (4, 6)),      # 清明
        ((5, 1), (5, 5)),      # 劳动节
        ((6, 19), (6, 21)),    # 端午
        ((9, 25), (9, 27)),    # 中秋
        ((10, 1), (10, 7)),    # 国庆
    ],
    2027: [
        ((1, 1), (1, 3)),      # 元旦
        ((2, 5), (2, 11)),     # 春节（2027 年春节为 2/6）
        ((4, 3), (4, 5)),      # 清明
        ((5, 1), (5, 5)),      # 劳动节
        ((6, 9), (6, 11)),     # 端午
        ((9, 13), (9, 15)),    # 中秋
        ((10, 1), (10, 7)),    # 国庆
    ],
}


def _build_holiday_set() -> frozenset[date]:
    """把区间表展开成具体日期集合（模块加载时算一次）。"""
    days: set[date] = set()
    for year, ranges in HOLIDAY_RANGES.items():
        for (sm, sd), (em, ed) in ranges:
            start = date(year, sm, sd)
            end = date(year, em, ed)
            cur = start
            while cur <= end:
                days.add(cur)
                cur += timedelta(days=1)
    return frozenset(days)


_HOLIDAYS = _build_holiday_set()


def now() -> datetime:
    """真实当前时间。"""
    return datetime.now()


def today() -> date:
    """真实当前日期。"""
    return date.today()


def is_holiday(d: date) -> bool:
    """判断某天是否放假：周末或命中法定节假日表。

    表未覆盖的年份只按周末判断，并记一条 warning 提醒更新表。
    """
    if d.weekday() >= 5:  # 5=周六 6=周日
        return True
    if d.year not in HOLIDAY_RANGES:
        log.warning("clock: %s 年不在节假日表内，仅按周末判断", d.year)
    return d in _HOLIDAYS
