from __future__ import annotations

from dataclasses import dataclass

from .store import LEVELS, CaseStore


@dataclass
class LevelStats:
    level: str
    compared: int
    same_total: int
    same_group: int
    mean_abs_diff: float
    max_abs_diff: float


def disagreement_report(store: CaseStore) -> list[LevelStats]:
    """How often scorers' complete entries differ from each case's confirmed snapshot, per scorer
    level. The confirmed entry itself, incomplete entries and cases without a confirmation are not
    counted. Totals and groups only: two scorers reaching the same total by different lesions agree."""
    diffs: dict[str, list[tuple[float, bool]]] = {level: [] for level in LEVELS}
    for study_uid, _count, confirmed in store.case_summaries():
        if not confirmed:
            continue
        ref = store.confirmation(study_uid)
        for entry in store.entries(study_uid):
            if entry.id == ref.entry_id or entry.status != "complete" or entry.total is None:
                continue
            diffs[entry.user.level].append((abs(entry.total - ref.total), entry.group == ref.group))
    rows = []
    for level in LEVELS:
        items = diffs[level]
        if not items:
            continue
        gaps = [d for d, _ in items]
        rows.append(LevelStats(level=level, compared=len(items),
                               same_total=sum(1 for d in gaps if d == 0),
                               same_group=sum(1 for _, g in items if g),
                               mean_abs_diff=sum(gaps) / len(gaps), max_abs_diff=max(gaps)))
    return rows
