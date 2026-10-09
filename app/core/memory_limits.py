"""Общие пределы журнала и диагностических примеров; счетчики не ограничены."""

from itertools import islice


MAX_LOG_BLOCKS = 2000
MAX_LOG_MESSAGE_CHARS = 2048
MAX_CHANGE_DETAILS = 100
MAX_CHANGE_DETAIL_CHARS = 2048
MAX_OUTPUT_LINE_CHARS = 65536
MAX_DIAGNOSTIC_CHARS = 1024 * 1024


def bounded_change_details(items: object) -> list[str]:
    if not isinstance(items, (list, tuple)):
        return []
    return [
        text[:MAX_CHANGE_DETAIL_CHARS]
        for item in islice(items, MAX_CHANGE_DETAILS)
        if (text := str(item or "").strip())
    ]
