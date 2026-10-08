"""Hand check of 20 random buyback-start titles (seed in b1_events.HAND_CHECK_SEED): message id -> (is it the
start of a new buyback programme?, note). Judged by reading each title and the start of its body."""

VERDICTS: dict[int, tuple[bool, str]] = {}
