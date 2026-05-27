"""
core/prompt_lab.py
------------------
Chạy nhiều prompt variants và so sánh kết quả.

Thay đổi so với v1:
  • Parallel execution với ThreadPoolExecutor (tùy chọn, default=False để an toàn)
  • Statistical analysis: win-rate matrix, dimension comparison
  • LLM Judge tích hợp (tùy chọn)
  • LabResult bổ sung win_matrix, dimension_winner_map
  • Hỗ trợ DimensionWeightConfig để user tuỳ chỉnh trọng số đánh giá
"""

from __future__ import annotations
import logging
import time
import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from core.prompt_variants import VARIANTS, PromptVariant, build_prompt
from core.llm_client import call_llm
from core.tc_evaluator import evaluate, EvaluationResult, DimensionWeightConfig

logger = logging.getLogger(__name__)


# ── Result dataclasses ────────────────────────────────────────────────────────


@dataclass
class VariantRunResult:
    variant_id: str
    variant_name: str
    variant_description: str
    variant_tags: list[str]
    success: bool
    error_message: str = ""
    duration_seconds: float = 0.0
    evaluation: EvaluationResult | None = None
    raw_result: dict = field(default_factory=dict)

    @property
    def display_score(self) -> float:
        """Trả về hybrid_score nếu có, ngược lại overall_score."""
        if self.evaluation is None:
            return 0.0
        if self.evaluation.hybrid_score is not None:
            return self.evaluation.hybrid_score
        return self.evaluation.overall_score


@dataclass
class LabResult:
    requirement: str
    input_type: str
    language: str
    variants_run: list[VariantRunResult]
    best_variant_id: str = ""
    worst_variant_id: str = ""
    run_timestamp: str = ""
    used_llm_judge: bool = False
    used_parallel: bool = False

    # Statistical extras
    win_matrix: dict = field(default_factory=dict)
    dimension_winner_map: dict = field(default_factory=dict)

    @property
    def successful_runs(self) -> list[VariantRunResult]:
        return [r for r in self.variants_run if r.success and r.evaluation]

    @property
    def leaderboard(self) -> list[VariantRunResult]:
        """Sort by display_score (hybrid nếu có, ngược lại rule-based)."""
        return sorted(
            self.successful_runs,
            key=lambda r: r.display_score,
            reverse=True,
        )

    def get_dimension_stats(self) -> dict[str, dict]:
        stats: dict[str, dict] = {}
        for run in self.successful_runs:
            for d in run.evaluation.dimensions:
                stats.setdefault(d.name, {})[run.variant_name] = d.percentage
        return stats

    def get_score_delta(self) -> float:
        lb = self.leaderboard
        if len(lb) < 2:
            return 0.0
        return lb[0].display_score - lb[-1].display_score


# ── Helpers ───────────────────────────────────────────────────────────────────


def _sanitise(raw_llm: dict, requirement: str) -> dict:
    from core.testcase_generator import _sanitise_tc, _sanitise_td

    if isinstance(raw_llm, list):
        raw_llm = {
            "status": "SUCCESS",
            "reason": "",
            "feature_name": "",
            "test_cases": raw_llm,
            "test_data_set": [],
        }
    raw_tc = raw_llm.get("test_cases", [])
    raw_td = raw_llm.get("test_data_set", [])
    if not isinstance(raw_tc, list):
        raw_tc = []
    if not isinstance(raw_td, list):
        raw_td = []
    return {
        "status": raw_llm.get("status", "SUCCESS"),
        "reason": raw_llm.get("reason", ""),
        "feature_name": raw_llm.get("feature_name", ""),
        "test_cases": [_sanitise_tc(tc, i + 1) for i, tc in enumerate(raw_tc)],
        "test_data_set": [_sanitise_td(td, i + 1) for i, td in enumerate(raw_td)],
    }


def _run_single(
    variant: PromptVariant,
    requirement: str,
    input_type: str,
    language: str,
    use_llm_judge: bool = False,
    weights: Optional[DimensionWeightConfig] = None,
    use_error_analysis: bool = False,
) -> VariantRunResult:
    start = time.time()
    try:
        prompt = build_prompt(variant.id, requirement, input_type, language)
        raw_llm = call_llm(prompt)
        if raw_llm is None:
            return VariantRunResult(
                variant.id,
                variant.name,
                variant.description,
                variant.tags,
                False,
                "LLM returned None — API error or parse failure",
                time.time() - start,
            )
        result = _sanitise(raw_llm, requirement)
        duration = time.time() - start

        eval_r = evaluate(
            variant.id,
            variant.name,
            result,
            requirement,
            use_llm_judge=use_llm_judge,
            weights=weights,
            use_error_analysis=use_error_analysis,
        )

        score_label = (
            f"hybrid={eval_r.hybrid_score:.1f}"
            if eval_r.hybrid_score is not None
            else f"rule={eval_r.overall_score:.1f}"
        )
        logger.info(
            f"Variant {variant.id}: {eval_r.total_tc} TCs, "
            f"score={score_label}, {duration:.1f}s"
        )
        return VariantRunResult(
            variant.id,
            variant.name,
            variant.description,
            variant.tags,
            True,
            "",
            duration,
            eval_r,
            result,
        )
    except Exception as exc:
        logger.error(f"Variant {variant.id} failed: {exc}", exc_info=True)
        return VariantRunResult(
            variant.id,
            variant.name,
            variant.description,
            variant.tags,
            False,
            str(exc),
            time.time() - start,
        )


def _compute_win_matrix(runs: list[VariantRunResult]) -> dict:
    matrix: dict[str, dict[str, int]] = {}
    for r in runs:
        matrix[r.variant_id] = {}
    for r_a in runs:
        for r_b in runs:
            if r_a.variant_id == r_b.variant_id:
                continue
            matrix[r_a.variant_id][r_b.variant_id] = (
                1 if r_a.display_score > r_b.display_score else 0
            )
    return matrix


def _compute_dimension_winners(runs: list[VariantRunResult]) -> dict:
    dim_best: dict[str, tuple[str, float]] = {}
    for run in runs:
        if run.evaluation is None:
            continue
        for d in run.evaluation.dimensions:
            current_best = dim_best.get(d.name, ("", -1.0))
            if d.score > current_best[1]:
                dim_best[d.name] = (run.variant_name, d.score)
    return {dim: name for dim, (name, _) in dim_best.items()}


# ── Public API ─────────────────────────────────────────────────────────────────


def run_prompt_lab(
    requirement: str,
    input_type: str = "User Story",
    language: str = "English",
    variant_ids: list[str] | None = None,
    progress_callback: Callable | None = None,
    use_llm_judge: bool = False,
    parallel: bool = False,
    max_workers: int = 3,
    weights: Optional[DimensionWeightConfig] = None,
    use_error_analysis: bool = False,
) -> LabResult:
    """
    Chạy prompt lab với N variants.

    Parameters
    ----------
    weights : DimensionWeightConfig | None
        Trọng số tuỳ chỉnh cho 6 chiều đánh giá.
        None → dùng DEFAULT_WEIGHTS (Balanced).
    use_llm_judge : bool
        True → gọi thêm LLM Judge để đánh giá semantic (~+2s mỗi variant)
    parallel : bool
        True → dùng ThreadPoolExecutor để chạy song song
    max_workers : int
        Số threads khi parallel=True (recommend ≤ 3)
    use_error_analysis : bool
        True → chạy phân tích 7 loại lỗi sau khi evaluate mỗi variant
    """
    variants_to_run = (
        [v for v in VARIANTS if v.id in variant_ids] if variant_ids else list(VARIANTS)
    )
    if not variants_to_run:
        return LabResult(
            requirement,
            input_type,
            language,
            [],
            run_timestamp=datetime.now().isoformat(),
        )

    results: list[VariantRunResult] = []

    if parallel and len(variants_to_run) > 1:
        # ── Parallel mode ──────────────────────────────────────────────────
        logger.info(
            f"Running {len(variants_to_run)} variants in parallel "
            f"(max_workers={max_workers})"
        )
        completed = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_variant = {
                executor.submit(
                    _run_single,
                    v,
                    requirement,
                    input_type,
                    language,
                    use_llm_judge,
                    weights,
                    use_error_analysis,
                ): v
                for v in variants_to_run
            }

            for future in concurrent.futures.as_completed(future_to_variant):
                variant = future_to_variant[future]
                completed += 1
                try:
                    result = future.result()
                except Exception as exc:
                    result = VariantRunResult(
                        variant.id,
                        variant.name,
                        variant.description,
                        variant.tags,
                        False,
                        str(exc),
                        0.0,
                    )
                results.append(result)
                if progress_callback:
                    progress_callback(
                        variant.name,
                        "done" if result.success else "failed",
                        completed,
                        len(variants_to_run),
                    )

        order = {v.id: i for i, v in enumerate(variants_to_run)}
        results.sort(key=lambda r: order.get(r.variant_id, 999))

    else:
        # ── Sequential mode (default) ──────────────────────────────────────
        for i, variant in enumerate(variants_to_run):
            if progress_callback:
                progress_callback(variant.name, "running", i, len(variants_to_run))

            result = _run_single(
                variant,
                requirement,
                input_type,
                language,
                use_llm_judge,
                weights,
                use_error_analysis,
            )
            results.append(result)

            if progress_callback:
                progress_callback(
                    variant.name,
                    "done" if result.success else "failed",
                    i + 1,
                    len(variants_to_run),
                )

            if i < len(variants_to_run) - 1:
                time.sleep(2)

    # ── Post-processing ────────────────────────────────────────────────────
    successful = [r for r in results if r.success and r.evaluation]
    sorted_r = sorted(successful, key=lambda r: r.display_score, reverse=True)

    win_matrix = _compute_win_matrix(successful)
    dim_winner_map = _compute_dimension_winners(successful)

    return LabResult(
        requirement=requirement,
        input_type=input_type,
        language=language,
        variants_run=results,
        best_variant_id=sorted_r[0].variant_id if sorted_r else "",
        worst_variant_id=sorted_r[-1].variant_id if sorted_r else "",
        run_timestamp=datetime.now().isoformat(),
        used_llm_judge=use_llm_judge,
        used_parallel=parallel,
        win_matrix=win_matrix,
        dimension_winner_map=dim_winner_map,
    )
