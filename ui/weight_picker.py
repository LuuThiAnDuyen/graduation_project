"""
ui/weight_picker.py
-------------------
Streamlit component cho phép user tuỳ chỉnh trọng số 6 chiều đánh giá.

Usage
-----
    from ui.weight_picker import render_weight_picker
    from core.tc_evaluator import DimensionWeightConfig

    weights: DimensionWeightConfig = render_weight_picker(key="lab")
    # Truyền `weights` vào evaluate(..., weights=weights)

API
---
    render_weight_picker(key: str = "default") -> DimensionWeightConfig

    Trả về DimensionWeightConfig đã được normalize (tổng = 1.0).
    Giá trị được lưu trong st.session_state[f"weights_{key}"].
"""

from __future__ import annotations
import streamlit as st
from core.tc_evaluator import (
    DimensionWeightConfig,
    DIMENSION_KEYS,
    DIMENSION_LABELS,
    DIMENSION_DESCRIPTIONS,
    WEIGHT_PRESETS,
    DEFAULT_WEIGHTS,
)

# Icon mapping cho 6 chiều
_DIM_ICONS = {
    "coverage_breadth": "🗂️",
    "clarity": "🔍",
    "test_data_quality": "📦",
    "security_coverage": "🔒",
    "boundary_edge_coverage": "🔢",
    "requirement_traceability": "🔗",
}

# Màu accent cho từng chiều (dùng cho progress bar)
_DIM_COLORS = {
    "coverage_breadth": "#378ADD",
    "clarity": "#34d399",
    "test_data_quality": "#f59e0b",
    "security_coverage": "#ef4444",
    "boundary_edge_coverage": "#8b5cf6",
    "requirement_traceability": "#ec4899",
}

# Nhãn hiển thị ngắn cho slider
_DIM_SHORT = {
    "coverage_breadth": "Coverage",
    "clarity": "Clarity",
    "test_data_quality": "Test Data",
    "security_coverage": "Security",
    "boundary_edge_coverage": "Boundary",
    "requirement_traceability": "Traceability",
}


def _config_to_sliders(cfg: DimensionWeightConfig) -> dict[str, int]:
    """Convert DimensionWeightConfig → dict of int (0–100) cho slider."""
    norm = cfg.normalize()
    return {k: round(getattr(norm, k) * 100) for k in DIMENSION_KEYS}


def _sliders_to_config(values: dict[str, int]) -> DimensionWeightConfig:
    """Convert slider dict (0–100) → DimensionWeightConfig (normalize tự động)."""
    return DimensionWeightConfig(
        **{k: values[k] / 100.0 for k in DIMENSION_KEYS}
    ).normalize()


def render_weight_picker(key: str = "default") -> DimensionWeightConfig:
    """
    Render UI tuỳ chỉnh trọng số 6 chiều.

    Parameters
    ----------
    key : str
        Unique key để isolate session state (dùng "gen" hoặc "lab").

    Returns
    -------
    DimensionWeightConfig
        Config đã normalize, sẵn sàng truyền vào evaluate().
    """
    ss_key = f"weights_{key}"
    ss_preset_key = f"weights_preset_{key}"

    # --- Init session state ---
    if ss_key not in st.session_state:
        st.session_state[ss_key] = _config_to_sliders(DEFAULT_WEIGHTS)
    if ss_preset_key not in st.session_state:
        st.session_state[ss_preset_key] = "balanced"

    # ── Header ──
    with st.expander("⚖️ Tuỳ chỉnh trọng số đánh giá", expanded=False):
        st.caption(
            "Điều chỉnh mức độ quan trọng của từng chiều. "
            "Tổng sẽ tự động được chuẩn hoá về 100%."
        )

        # ── Preset buttons ──
        st.markdown("**Chọn profile nhanh:**")
        preset_cols = st.columns(len(WEIGHT_PRESETS))
        for col, (pid, pinfo) in zip(preset_cols, WEIGHT_PRESETS.items()):
            with col:
                is_active = st.session_state[ss_preset_key] == pid
                btn_style = "primary" if is_active else "secondary"
                if st.button(
                    f"**{pinfo['label']}**",
                    key=f"preset_{key}_{pid}",
                    type=btn_style,
                    use_container_width=True,
                    help=pinfo["description"],
                ):
                    st.session_state[ss_preset_key] = pid
                    st.session_state[ss_key] = _config_to_sliders(pinfo["config"])
                    st.rerun()
                st.caption(pinfo["description"])

        st.divider()

        # ── Slider grid ──
        st.markdown("**Tuỳ chỉnh chi tiết:**")

        current_values: dict[str, int] = dict(st.session_state[ss_key])
        total_raw = sum(current_values.values())

        # Hiển thị 2 chiều mỗi hàng
        keys_list = DIMENSION_KEYS
        changed = False

        for i in range(0, len(keys_list), 2):
            pair = keys_list[i : i + 2]
            cols = st.columns(len(pair))
            for col, dim_key in zip(cols, pair):
                with col:
                    icon = _DIM_ICONS[dim_key]
                    short = _DIM_SHORT[dim_key]
                    desc = DIMENSION_DESCRIPTIONS[dim_key]
                    color = _DIM_COLORS[dim_key]

                    # Tính % đã normalize để hiển thị
                    norm_pct = (
                        round(current_values[dim_key] / total_raw * 100)
                        if total_raw > 0
                        else 0
                    )

                    st.markdown(
                        f"**{icon} {short}** "
                        f"<span style='color:{color};font-weight:600;'>"
                        f"→ {norm_pct}%</span>",
                        unsafe_allow_html=True,
                    )
                    st.caption(desc)

                    new_val = st.slider(
                        label=short,
                        min_value=0,
                        max_value=100,
                        value=current_values[dim_key],
                        step=5,
                        key=f"slider_{key}_{dim_key}",
                        label_visibility="collapsed",
                    )
                    if new_val != current_values[dim_key]:
                        current_values[dim_key] = new_val
                        changed = True

        if changed:
            st.session_state[ss_key] = current_values
            st.session_state[ss_preset_key] = "custom"
            st.rerun()

        # ── Summary bar ──
        st.divider()
        total_check = sum(current_values.values())

        if total_check == 0:
            st.error("⚠️ Tất cả trọng số = 0. Vui lòng điều chỉnh.")
            return DEFAULT_WEIGHTS

        # Visual weight bar
        bar_html = '<div style="display:flex;height:12px;border-radius:6px;overflow:hidden;margin:8px 0;">'
        for dim_key in DIMENSION_KEYS:
            pct = current_values[dim_key] / total_check * 100
            if pct > 0:
                color = _DIM_COLORS[dim_key]
                bar_html += (
                    f'<div style="width:{pct:.1f}%;background:{color};" '
                    f'title="{_DIM_SHORT[dim_key]}: {pct:.0f}%"></div>'
                )
        bar_html += "</div>"
        st.markdown(bar_html, unsafe_allow_html=True)

        # Summary table (compact)
        summary_parts = []
        for dim_key in DIMENSION_KEYS:
            norm_pct = round(current_values[dim_key] / total_check * 100)
            icon = _DIM_ICONS[dim_key]
            color = _DIM_COLORS[dim_key]
            summary_parts.append(
                f'<span style="margin-right:12px;">'
                f"{icon} <b>{_DIM_SHORT[dim_key]}</b>: "
                f'<span style="color:{color};font-weight:600;">{norm_pct}%</span>'
                f"</span>"
            )
        st.markdown(
            '<div style="font-size:0.85em;line-height:2;">'
            + "".join(summary_parts)
            + "</div>",
            unsafe_allow_html=True,
        )

        # Reset button
        st.markdown("")
        if st.button(
            "↩️ Reset về Balanced",
            key=f"reset_weights_{key}",
            use_container_width=False,
        ):
            st.session_state[ss_key] = _config_to_sliders(DEFAULT_WEIGHTS)
            st.session_state[ss_preset_key] = "balanced"
            st.rerun()

    # ── Return normalized config ──
    return _sliders_to_config(st.session_state[ss_key])
