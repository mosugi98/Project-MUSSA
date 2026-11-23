"""One AI pass over a whole study: pick its series, run the models, reconcile, and keep the raw result.

The viewer calls `study_paths` + `run_study`, shows the proposals, and hands the ticked ones to `lesions_for_form`.
`StudyRun.payload_json()` is what the store keeps as the AI's raw proposal, beside (never instead of) the scorer's own
answer. The AI proposes segments only; no score is computed here."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..dicom_import.models import ImportRejected
from ..dicom_import.reader import read_header
from ..library import Library
from ..scoring import Lesion
from .adapters import lesion_input_to_lesion
from .perception import perceive_study
from .reconcile import Reconciliation, reconcile
from .schema import Dominance, RunPerceptionSummary


@dataclass
class StudyRun:
    runs: list[RunPerceptionSummary]
    skipped: list[tuple[str, str]]
    reconciliation: Reconciliation
    _models: dict[str, str] = field(default_factory=dict)

    def proposed_ids(self) -> list[str]:
        return [les.lesion_id for les in self.reconciliation.study.lesions]

    def evidence_of(self, lesion_id: str) -> tuple[str, int]:
        """(series uid, frame index) of the best view of a proposed lesion; KeyError when there is no such lesion."""
        for les in self.reconciliation.study.lesions:
            if les.lesion_id == lesion_id:
                if les.primary_evidence is None:
                    raise KeyError(lesion_id)
                return les.primary_evidence.series_instance_uid, les.primary_evidence.frame_index
        raise KeyError(lesion_id)

    def model_ids(self) -> tuple[str, str]:
        """(segment model, stenosis model) as the models identify themselves."""
        return self._models.get("segments", ""), self._models.get("stenosis", "")

    def payload_json(self) -> str:
        """The AI's raw output for the study: every run and the reconciliation."""
        runs = ",".join(r.model_dump_json() for r in self.runs)
        return '{"runs":[' + runs + '],"reconciliation":' + self.reconciliation.model_dump_json() + "}"


def study_paths(library: Library, study_uid: str, mrn_hash: str | None = None) -> list[Path]:
    """The stored series that belong to one case, in a stable order. Unreadable files are left out. A case is its
    study uid and, when given, the patient's hash too, so a mislabelled series of another patient is never pulled in."""
    found = []
    for entry in library.entries():
        try:
            header = read_header(entry.path)
            if header.study_uid == study_uid and (mrn_hash is None or header.mrn_hash == mrn_hash):
                found.append(entry.path)
        except ImportRejected:
            continue
    return sorted(found, key=lambda p: p.name)


def run_study(paths: list[Path], segmenter, stenosis, study_uid: str,
              dominance: Dominance | None = None) -> StudyRun:
    """Analyse the series of one study and reconcile them into proposed draft lesions. Raises PerceptionError when
    nothing can be analysed and ReconcileError when the files do not belong to `study_uid`."""
    perception = perceive_study(paths, segmenter, stenosis)
    reconciliation = reconcile(perception.runs, study_instance_uid=study_uid, dominance=dominance)
    models = {m.name: m.identity for m in perception.runs[0].models}
    return StudyRun(perception.runs, perception.skipped, reconciliation,
                    {name: f"{name} {identity}" for name, identity in models.items()})


def lesions_for_form(run: StudyRun, chosen_ids: list[str]) -> list[Lesion]:
    """The ticked proposals as segment-only form lesions, in the order they were proposed. KeyError for an id that
    was never proposed."""
    by_id = {les.lesion_id: les for les in run.reconciliation.study.lesions}
    for lesion_id in chosen_ids:
        if lesion_id not in by_id:
            raise KeyError(lesion_id)
    wanted = set(chosen_ids)
    return [lesion_input_to_lesion(les, None) for les in run.reconciliation.study.lesions if les.lesion_id in wanted]
