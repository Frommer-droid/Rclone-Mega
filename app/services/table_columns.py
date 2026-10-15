"""Allocate a complete viewport with bounded, integer column widths."""


def distribute_width(total: int, weights: list[float], minimum: int) -> list[int]:
    if not weights:
        return []
    total = max(len(weights), total)
    floor = min(minimum, total // len(weights))
    widths = [floor] * len(weights)
    remaining = total - sum(widths)
    flexible = [max(1.0, w - floor) for w in weights]
    shares = [remaining * w / sum(flexible) for w in flexible]
    for i, share in enumerate(shares):
        widths[i] += int(share)
    for i in sorted(range(len(weights)), key=lambda i: shares[i] % 1, reverse=True)[
        : total - sum(widths)
    ]:
        widths[i] += 1
    return widths


def resize_within_width(
    widths: list[int], index: int, requested: int, minimum: int
) -> list[int]:
    result = list(widths)
    others = list(range(index + 1, len(widths))) + list(range(index - 1, -1, -1))
    if not others:
        return result
    difference = max(minimum, requested) - widths[index]
    if difference > 0:
        difference = min(difference, sum(max(0, widths[i] - minimum) for i in others))
        remaining = difference
        for i in others:
            take = min(remaining, max(0, result[i] - minimum))
            result[i] -= take
            remaining -= take
    else:
        result[others[0]] -= difference
    result[index] += difference
    return result
