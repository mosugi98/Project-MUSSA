from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from cagsyntax.contract.models import (SCHEMA_VERSION, CaseAnalysis, CaseForm, Evidence, Finding, LesionForm,
                                       LesionProposal, ModelRef, Review, ScoreSummary, SeriesInfo)

NOW = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)


def ev(**kw):
    base = dict(series_uid="2.25.1", frame=2, primary_angle=30.0, secondary_angle=-20.0, box=(5, 6, 20, 30))
    base.update(kw)
    return Evidence(**base)


def finding(**kw):
    base = dict(evidence=ev(), segment="6", score=0.9, pixels=120, overlap=0.8,
                models=[ModelRef(name="segments", identity="2026-11-21 ab12cd34")])
    base.update(kw)
    return Finding(**base)


def series(uid="2.25.1", frames=5):
    return SeriesInfo(series_uid=uid, kind="cine", frame_count=frames, fps=15.0, primary_angle=30.0, secondary_angle=-20.0)


def analysis(**kw):
    base = dict(study_uid="2.25.9", series=[series()], findings=[finding()], created_at=NOW)
    base.update(kw)
    return CaseAnalysis(**base)


def test_the_schema_version_is_one_point_zero_and_stamped_on_every_analysis():
    assert SCHEMA_VERSION == "1.0" and analysis().schema_version == "1.0"


# ---- evidence ----
def test_evidence_needs_a_series_a_frame_and_a_sane_box():
    assert ev().box == (5, 6, 20, 30)
    for bad in (dict(series_uid=""), dict(frame=-1), dict(box=(10, 10, 5, 20)), dict(box=(0, 0, 5, 0)),
                dict(box=(-1, 0, 5, 5)), dict(primary_angle=200.0), dict(secondary_angle=-181.0)):
        with pytest.raises(ValidationError):
            ev(**bad)


def test_angles_and_box_may_be_unknown():
    e = ev(primary_angle=None, secondary_angle=None, box=None)
    assert e.box is None and e.primary_angle is None


def test_unknown_fields_are_refused():
    with pytest.raises(ValidationError):
        ev(patient_name="DOE")


# ---- findings ----
def test_a_finding_checks_segment_score_and_overlap():
    assert finding(segment=None, overlap=0.0).segment is None                # unplaced is allowed
    for bad in (dict(segment="LAD"), dict(segment="17"), dict(score=1.2), dict(score=-0.1), dict(overlap=1.5),
                dict(pixels=-1)):
        with pytest.raises(ValidationError):
            finding(**bad)


def test_all_25_segment_names_are_accepted():
    from cagsyntax.ai.segment_names import SEGMENT_NAMES
    for name in SEGMENT_NAMES:
        assert finding(segment=name).segment == name


# ---- forms ----
def test_an_unanswered_draft_lesion_is_valid():
    form = LesionForm(segments=[])
    assert form.occlusion is None and form.thrombus is None


def test_lesion_answers_are_checked_against_the_engines_vocabulary():
    assert LesionForm(segments=["6"], bifurcation="A", side_branch="large", age_over_3_months="unknown",
                      trifurcation=3, beyond_first_visualized="none").bifurcation == "A"
    for bad in (dict(bifurcation="H"), dict(side_branch="huge"), dict(age_over_3_months="maybe"),
                dict(trifurcation=5), dict(trifurcation=-1), dict(beyond_first_visualized="99"),
                dict(first_segment="LAD"), dict(segments=["6", "6"]), dict(segments=["6", "nope"])):
        with pytest.raises(ValidationError):
            LesionForm(**{"segments": ["6"], **bad})


def test_a_case_form_checks_dominance_and_diffuse_segments():
    form = CaseForm(dominance="co-dominant", scoring_dominance="right", lesions=[LesionForm(segments=["6"])],
                    diffuse_segments=["7", "8"])
    assert form.scoring_dominance == "right"
    for bad in (dict(dominance="both"), dict(scoring_dominance="co-dominant"), dict(diffuse_segments=["7", "7"]),
                dict(diffuse_segments=["x"])):
        with pytest.raises(ValidationError):
            CaseForm(**{"dominance": "right", "scoring_dominance": None, "lesions": [], **bad})


def test_an_incomplete_case_form_is_valid():
    assert CaseForm(dominance=None, scoring_dominance=None, lesions=[LesionForm(segments=[])]).dominance is None


# ---- review ----
def test_the_ai_prediction_and_the_physician_answer_live_side_by_side():
    raw = CaseForm(dominance=None, scoring_dominance=None, lesions=[LesionForm(segments=["6"])])
    final = CaseForm(dominance="right", scoring_dominance=None, lesions=[LesionForm(segments=["6", "7"])])
    r = Review(ai_raw_prediction=raw, physician_final_approved=final, reviewer_id=3, reviewer_level="cardiologist",
               reviewed_at=NOW)
    assert r.ai_raw_prediction.lesions[0].segments == ["6"] and r.physician_final_approved.dominance == "right"


def test_a_final_answer_needs_a_reviewer_and_a_time():
    final = CaseForm(dominance="right", scoring_dominance=None, lesions=[])
    with pytest.raises(ValidationError):
        Review(physician_final_approved=final)
    with pytest.raises(ValidationError):
        Review(physician_final_approved=final, reviewer_id=1, reviewer_level="resident")
    assert Review(ai_raw_prediction=final).physician_final_approved is None           # AI-only review is fine


def test_review_timestamps_must_have_a_timezone():
    final = CaseForm(dominance="right", scoring_dominance=None, lesions=[])
    with pytest.raises(ValidationError):
        Review(physician_final_approved=final, reviewer_id=1, reviewer_level="resident", reviewed_at=datetime(2026, 1, 1))


# ---- the whole analysis ----
def test_evidence_must_point_at_a_listed_series_and_a_frame_inside_it():
    analysis()                                                                       # fine
    with pytest.raises(ValidationError) as exc:
        analysis(findings=[finding(evidence=ev(series_uid="2.25.404"))])
    assert "2.25.404" in str(exc.value)
    with pytest.raises(ValidationError) as exc:
        analysis(findings=[finding(evidence=ev(frame=5))])                           # the series has frames 0..4
    assert "frame 5" in str(exc.value)


def test_proposals_are_traceable_too():
    form = LesionForm(segments=["6"])
    ok = LesionProposal(form=form, findings=[finding()], source="ai")
    assert analysis(proposals=[ok]).proposals[0].source == "ai"
    bad = LesionProposal(form=form, findings=[finding(evidence=ev(series_uid="2.25.404"))], source="ai")
    with pytest.raises(ValidationError):
        analysis(proposals=[bad])


def test_a_physician_proposal_may_have_no_findings_but_an_ai_proposal_may_not():
    LesionProposal(form=LesionForm(segments=["6"]), findings=[], source="physician")
    with pytest.raises(ValidationError):
        LesionProposal(form=LesionForm(segments=["6"]), findings=[], source="ai")


def test_created_at_needs_a_timezone_and_duplicate_series_are_refused():
    with pytest.raises(ValidationError):
        analysis(created_at=datetime(2026, 11, 22))
    with pytest.raises(ValidationError):
        analysis(series=[series(), series()])


def test_a_score_summary_is_read_only_data_with_the_engine_version():
    s = ScoreSummary(status="complete", total=7.0, group="low", engine_version="official calculator 2.28",
                     issues=[], lesion_totals=[7.0], diffuse_points=0.0)
    assert analysis(score=s).score.total == 7.0
    for bad in (dict(status="done"), dict(total=-1.0)):
        with pytest.raises(ValidationError):
            ScoreSummary(**{"status": "complete", "total": 1.0, "group": "low", "engine_version": "x", "issues": [],
                            "lesion_totals": [], "diffuse_points": 0.0, **bad})
