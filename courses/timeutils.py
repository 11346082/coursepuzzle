"""節次與時段的純 Python 工具（不依賴 Django，方便單獨測試）。"""

WEEKDAY_NAMES = {1: "週一", 2: "週二", 3: "週三", 4: "週四", 5: "週五"}
WEEKDAY_IDS = list(WEEKDAY_NAMES)

PERIOD_START = {
    1: "08:10", 2: "09:10", 3: "10:10", 4: "11:10", 5: "12:10",
    6: "13:10", 7: "14:10", 8: "15:10", 9: "16:10", 10: "17:10",
}
PERIODS = list(PERIOD_START)


def expand(weekday, start, end):
    """把「週二 第3到5節」展開成 {(2,3),(2,4),(2,5)}。"""
    return {(weekday, p) for p in range(start, end + 1)}


def describe_slots(slots):
    """{(2,4),(2,5)} -> '週二第4、5節'；跨天以空白分隔。"""
    by_day = {}
    for day, period in sorted(slots):
        by_day.setdefault(day, []).append(str(period))
    return " ".join(f"{WEEKDAY_NAMES[d]}第{'、'.join(ps)}節" for d, ps in by_day.items())


def label(weekday, start, end):
    name = WEEKDAY_NAMES[weekday]
    return f"{name} 第{start}節" if start == end else f"{name} 第{start}–{end}節"


def time_range(start, end):
    """第2到4節 -> '09:10–11:00'（每節 50 分鐘）。"""
    h, m = map(int, PERIOD_START[end].split(":"))
    total = h * 60 + m + 50
    return f"{PERIOD_START[start]}–{total // 60:02d}:{total % 60:02d}"
