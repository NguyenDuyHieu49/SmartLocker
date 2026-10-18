STORAGE_DAY_MINUTES = 24 * 60

BOX_DAILY_RATES_VND: dict[int, int] = {
    0: 5_000,
    1: 5_000,
    2: 7_000,
    3: 10_000,
}


def daily_rate_for_box(box: int) -> int:
    try:
        return BOX_DAILY_RATES_VND[box]
    except KeyError as exc:
        raise ValueError("box_not_rentable") from exc


def pricing_snapshot_for_box(box: int) -> tuple[int, int, int, int]:
    daily_rate = daily_rate_for_box(box)
    return (
        daily_rate,
        STORAGE_DAY_MINUTES,
        STORAGE_DAY_MINUTES,
        daily_rate,
    )
