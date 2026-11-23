from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional
from typing_extensions import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.scoring.syntax_engine import (
    BifurcationDetails,
    Dominance,
    InvolvedSegment,
    LesionInput,
    SegmentID,
    StudySyntaxInput,
    StudySyntaxOutput,
    TotalOcclusionDetails,
    TrifurcationDetails,
    ViewEvidence,
    calculate_syntax_score,
)


# =====================================================================
# 1. RAW COMPUTER VISION OUTPUT SCHEMAS (PER DICOM RUN / SERIES)
# =====================================================================

class RawCVLesionCandidate(BaseModel):
    """Single lesion detection produced by the local CV model on a specific key-frame."""
    candidate_id: str
    predicted_segment: SegmentID
    segment_confidence: float = Field(..., ge=0.0, le=1.0)
    series_instance_uid: str
    sop_instance_uid: str
    frame_index: int
    primary_angle_deg: float = Field(..., description="LAO (+) / RAO (-) C-arm angle")
    secondary_angle_deg: float = Field(..., description="Cranial (+) / Caudal (-) C-arm angle")
    bbox_xyxy: List[float]
    qca_stenosis_percent: float
    reference_vessel_diameter_mm: float
    lesion_length_mm: float
    is_total_occlusion: bool = False
    is_bifurcation_candidate: bool = False
    has_calcification_hint: bool = False
    has_thrombus_hint: bool = False
    image_snr_score: float = Field(default=1.0, ge=0.0, le=1.0)


class RunPerceptionSummary(BaseModel):
    """Aggregated CV output for one angiographic run (series)."""
    series_instance_uid: str
    view_label: str = Field(..., description="e.g., 'RAO 30 / Cranial 30', 'LAO 45 / Caudal 25'")
    visible_segments: List[SegmentID]
    pda_origin_detected: Optional[Dominance] = Field(
        default=None,
        description="'right' if PDA arises from RCA, 'left' if PDA arises from LCx, None if not visible in this run."
    )
    candidates: List[RawCVLesionCandidate] = Field(default_factory=list)


# =====================================================================
# 2. LLM STRUCTURED RECONCILIATION SCHEMA
# =====================================================================

class ReconciledStudyDraft(BaseModel):
    """
    Structured output enforced on the Local LLM.
    Notice: NO score fields exist here—the LLM only outputs clinical structure.
    """
    dominance: Dominance = Field(
        ...,
        description="Determined from which artery (RCA vs LCx) supplies the PDA/PLV across all runs."
    )
    reconciled_lesions: List[LesionInput] = Field(
        default_factory=list,
        description="Deduplicated anatomical lesions reconciled across all angiographic projections."
    )
    diffuse_disease_segments: List[SegmentID] = Field(
        default_factory=list,
        description="Segments distal to a lesion with >=75% length having diameter < 2.0 mm."
    )
    overall_clinical_summary: str = Field(
        ...,
        description="Concise Indonesian clinical summary of coronary dominance, multivessel involvement, and key findings."
    )


# =====================================================================
# 3. LANGGRAPH AGENT STATE
# =====================================================================

class CAGAgentState(TypedDict):
    study_instance_uid: str
    dicom_series_paths: List[str]
    run_perceptions: List[RunPerceptionSummary]
    reconciled_draft: Optional[ReconciledStudyDraft]
    syntax_input: Optional[StudySyntaxInput]
    syntax_output: Optional[StudySyntaxOutput]
    audit_warnings: List[str]


# =====================================================================
# 4. CLINICAL SYSTEM PROMPT FOR MULTI-VIEW RECONCILIATION
# =====================================================================

RECONCILIATION_SYSTEM_PROMPT = """Anda adalah AI Interventional Cardiology Orchestrator yang bertugas merekonsiliasi temuan Computer Vision dari beberapa proyeksi DICOM Coronary Angiography (CAG) menjadi satu representasi anatomi koroner yang terpadu untuk kalkulasi SYNTAX Score I.

ATURAN KLINIS WAJIB:
1. **Deduplikasi Lintas Proyeksi (Cross-View Matching):**
   - Lesi fisik yang sama sering muncul pada beberapa proyeksi (misalnya Mid-LAD terlihat di RAO Cranial dan LAO Cranial). Gabungkan deteksi tersebut menjadi SATU `LesionInput`.
   - Pilih proyeksi dengan sudut terbaik (paling sedikit *foreshortening* dan derajat stenosis QCA tertinggi) sebagai `primary_evidence`. Masukkan proyeksi lain yang memperlihatkan lesi yang sama ke dalam `supporting_views`.

2. **Kriteria Signifikansi SYNTAX Score I:**
   - Hanya masukkan lesi dengan diameter stenosis **minimal 50%** pada pembuluh darah dengan diameter referensi **minimal 1,5 mm**. Abaikan stenosis di bawah 50% atau cabang kecil di bawah 1,5 mm.
   - Jika satu lesi memanjang kontinu melintasi dua segmen berurutan (misal Segmen 6 ke Segmen 7), masukkan keduanya ke dalam `involved_segments` pada satu `LesionInput`.
   - Dua penyempitan terpisah dalam satu segmen dianggap **satu lesi** jika jaraknya kurang dari 3 kali diameter pembuluh referensi, dan dianggap **dua lesi terpisah** jika jaraknya minimal 3 kali diameter pembuluh.

3. **Penentuan Dominansi Koroner:**
   - Tentukan `right` jika PDA (Segmen 4) berasal dari RCA, atau `left` jika PDA (Segmen 15) berasal dari LCx.

4. **Flagging Ketidakpastian (`needs_attention = True`):**
   - Set `needs_attention = True` pada `primary_evidence` jika:
     a) Perbedaan derajat stenosis antar proyeksi untuk lesi yang sama sangat lebar (misal 45% di satu view vs 75% di view lain),
     b) Confidence segmentasi di bawah 0.80 atau `image_snr_score` di bawah 0.65,
     c) Lesi berada di area percabangan kompleks (LM / bifurcasi proksimal) yang rawan *vessel overlap*.

5. **Penjelasan Klinis (`agent_reasoning`):**
   - Tulis alasan singkat dan objektif dalam Bahasa Indonesia untuk setiap lesi (sebutkan proyeksi rujukan, persentase QCA, panjang lesi, dan alasan klasifikasi bifurkasi/CTO jika ada).
   - JANGAN menghitung angka SYNTAX Score di dalam teks; perhitungan skor dilakukan sepenuhnya oleh engine deterministik.
"""


# =====================================================================
# 5. LANGGRAPH WORKFLOW BUILDER
# =====================================================================

def build_cag_orchestrator(
    cv_perception_runner: Callable[[str], RunPerceptionSummary],
    llm_base_url: str = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"),
    llm_model_name: str = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:32b-instruct"),
):
    """
    Builds a compiled LangGraph agent that:
    1. Runs local DICOM + CV perception per angiographic series.
    2. Uses a Local LLM (Ollama/vLLM) with strict Pydantic schema enforcement to reconcile views.
    3. Runs deterministic sanity checks against raw CV detections.
    4. Executes the deterministic Python SYNTAX Score I calculator.
    """

    # Local LLM client (zero external network calls)
    local_llm = ChatOpenAI(
        base_url=llm_base_url,
        api_key="local-no-key-required",
        model=llm_model_name,
        temperature=0.0,  # Deterministic clinical reasoning
    )
    structured_reconciler = local_llm.with_structured_output(ReconciledStudyDraft)

    # --- NODE 1: Perception across all DICOM runs ---
    def perceive_all_runs(state: CAGAgentState) -> Dict[str, Any]:
        perceptions: List[RunPerceptionSummary] = []
        for series_path in state["dicom_series_paths"]:
            run_summary = cv_perception_runner(series_path)
            perceptions.append(run_summary)
        return {"run_perceptions": perceptions}

    # --- NODE 2: Agentic Multi-View Reconciliation ---
    def reconcile_views(state: CAGAgentState) -> Dict[str, Any]:
        serialized_runs = [r.model_dump() for r in state["run_perceptions"]]
        user_payload = (
            f"Study Instance UID: {state['study_instance_uid']}\n"
            f"Total Angiographic Runs: {len(serialized_runs)}\n\n"
            f"Data Deteksi Computer Vision per Run:\n"
            f"{json.dumps(serialized_runs, indent=2)}"
        )

        draft: ReconciledStudyDraft = structured_reconciler.invoke(
            [
                SystemMessage(content=RECONCILIATION_SYSTEM_PROMPT),
                HumanMessage(content=user_payload),
            ]
        )
        return {"reconciled_draft": draft}

    # --- NODE 3: Symbolic Guardrail & Cross-Check ---
    def verify_reconciliation_guardrails(state: CAGAgentState) -> Dict[str, Any]:
        """
        Deterministic verification ensuring the LLM did not silently drop
        high-confidence severe CV detections (>=70% stenosis, conf >=0.85).
        """
        draft = state["reconciled_draft"]
        assert draft is not None

        warnings: List[str] = []
        reconciled_segments = {
            seg.segment_id
            for lesion in draft.reconciled_lesions
            for seg in lesion.involved_segments
        }

        for run in state["run_perceptions"]:
            for cand in run.candidates:
                if (
                    cand.qca_stenosis_percent >= 70.0
                    and cand.reference_vessel_diameter_mm >= 1.5
                    and cand.segment_confidence >= 0.85
                    and cand.predicted_segment not in reconciled_segments
                ):
                    warnings.append(
                        f"High-confidence CV candidate '{cand.candidate_id}' at Segment "
                        f"{cand.predicted_segment.value} ({cand.qca_stenosis_percent:.1f}% QCA) "
                        f"was omitted during reconciliation; automatically injected for physician review."
                    )
                    draft.reconciled_lesions.append(
                        LesionInput(
                            lesion_id=f"AUTO_RECOVERED_{cand.candidate_id}",
                            involved_segments=[
                                InvolvedSegment(
                                    segment_id=cand.predicted_segment,
                                    is_total_occlusion=cand.is_total_occlusion,
                                )
                            ],
                            length_gt_20mm=cand.lesion_length_mm > 20.0,
                            has_heavy_calcification=cand.has_calcification_hint,
                            has_thrombus=cand.has_thrombus_hint,
                            primary_evidence=ViewEvidence(
                                series_instance_uid=cand.series_instance_uid,
                                sop_instance_uid=cand.sop_instance_uid,
                                frame_index=cand.frame_index,
                                primary_angle_deg=cand.primary_angle_deg,
                                secondary_angle_deg=cand.secondary_angle_deg,
                                bbox_xyxy=cand.bbox_xyxy,
                                qca_stenosis_percent=cand.qca_stenosis_percent,
                                reference_vessel_diameter_mm=cand.reference_vessel_diameter_mm,
                                confidence_score=cand.segment_confidence,
                                needs_attention=True,
                            ),
                            agent_reasoning=(
                                "Dipulihkan otomatis oleh Symbolic Guardrail karena deteksi CV "
                                "menunjukkan stenosis signifikan dengan confidence tinggi yang belum "
                                "tercakup dalam penggabungan multi-proyeksi. Mohon verifikasi dokter."
                            ),
                        )
                    )
                    reconciled_segments.add(cand.predicted_segment)

        syntax_input = StudySyntaxInput(
            study_instance_uid=state["study_instance_uid"],
            dominance=draft.dominance,
            lesions=draft.reconciled_lesions,
            diffuse_disease_segments=draft.diffuse_disease_segments,
        )
        return {"syntax_input": syntax_input, "audit_warnings": warnings}

    # --- NODE 4: Deterministic SYNTAX Score I Calculation ---
    def compute_deterministic_score(state: CAGAgentState) -> Dict[str, Any]:
        syntax_input = state["syntax_input"]
        assert syntax_input is not None
        syntax_output = calculate_syntax_score(syntax_input)
        return {"syntax_output": syntax_output}

    # Assemble StateGraph
    graph = StateGraph(CAGAgentState)
    graph.add_node("perceive_all_runs", perceive_all_runs)
    graph.add_node("reconcile_views", reconcile_views)
    graph.add_node("verify_guardrails", verify_reconciliation_guardrails)
    graph.add_node("compute_score", compute_deterministic_score)

    graph.set_entry_point("perceive_all_runs")
    graph.add_edge("perceive_all_runs", "reconcile_views")
    graph.add_edge("reconcile_views", "verify_guardrails")
    graph.add_edge("verify_guardrails", "compute_score")
    graph.add_edge("compute_score", END)

    return graph.compile()