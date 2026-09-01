from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from swim_coach.domain.activities.contextual import (
    AlignmentStatus,
    QualityLevel,
    TrendDirection,
    align_planned_steps,
    analyze_continuity,
    assess_data_quality,
    build_speed_endurance_profile,
    detect_interval_outliers,
    expand_planned_steps,
    format_seconds_mmss,
    freestyle_work_intervals,
    group_equivalent_sets,
    pace_for,
)


def interval(
    index: int,
    *,
    distance_m: int,
    pace: str | None = None,
    interval_type: str = "SWIM",
    planned_role: str = "WORK",
    stroke: str = "FREESTYLE",
    timer_duration_s: str | None = None,
    rest_duration_s: str | None = None,
    **extra: object,
) -> dict[str, object]:
    result: dict[str, object] = {
        "interval_index": index,
        "distance_m": distance_m,
        "interval_type": interval_type,
        "planned_role": planned_role,
        "detected_stroke": stroke,
        **extra,
    }
    if pace is not None:
        result["moving_pace_s_per_100m"] = Decimal(pace)
    if timer_duration_s is not None:
        result["timer_duration_s"] = Decimal(timer_duration_s)
    if rest_duration_s is not None:
        result["rest_duration_s"] = Decimal(rest_duration_s)
    return result


def test_pace_basis_is_explicit_and_objects_and_mappings_are_supported() -> None:
    legacy = {"pace_seconds_per_100m": Decimal("197.7")}
    normalized = SimpleNamespace(
        moving_pace_s_per_100m=Decimal("169"),
        timer_pace_s_per_100m=Decimal("197.7"),
        pace_from_garmin_reported_speed_s_per_100m=Decimal("169"),
    )

    assert pace_for(legacy, basis="moving") is None
    assert pace_for(legacy, basis="timer") == Decimal("197.7")
    assert pace_for(normalized, basis="moving") == Decimal("169")
    assert pace_for(normalized, basis="timer") == Decimal("197.7")
    assert pace_for(normalized, basis="garmin") == Decimal("169")

    entity_v2_shape = SimpleNamespace(
        moving_pace_seconds_per_100m=Decimal("171"),
        timer_pace_seconds_per_100m=Decimal("199"),
    )
    assert pace_for(entity_v2_shape, basis="moving") == Decimal("171")
    assert pace_for(entity_v2_shape, basis="timer") == Decimal("199")


def test_duration_helpers_accept_v2_storage_names_and_nullable_properties() -> None:
    activity = SimpleNamespace(
        moving_duration_s=None,
        moving_seconds=Decimal("1699.541"),
        timer_duration_s=None,
        timer_seconds=Decimal("2075.559"),
        elapsed_duration_s=None,
        elapsed_seconds=Decimal("2089.629"),
        pool_length_m=20,
        distance_m=860,
        active_length_count=43,
    )
    length = SimpleNamespace(
        length_index=0,
        length_type="ACTIVE",
        distance_m=20,
        swim_duration_s=None,
        swim_seconds=Decimal("35"),
        detected_stroke="FREESTYLE",
        planned_role="WORK",
    )

    quality = assess_data_quality(
        activity,
        intervals=(
            interval(0, distance_m=80, pace="180"),
            interval(1, distance_m=80, pace="181"),
        ),
        lengths=(length,),
    )
    continuity = analyze_continuity((length,), window_distances_m=(20,))

    assert "MISSING_MOVING_DURATION" not in quality.reasons
    assert continuity.longest_continuous_swim is not None
    assert continuity.longest_continuous_swim.duration_s == Decimal("35.000")


def test_formatter_rounds_half_up_and_keeps_minutes_unbounded() -> None:
    assert format_seconds_mmss(Decimal("168.5")) == "2:49"
    assert format_seconds_mmss(Decimal("197.621")) == "3:18"
    assert format_seconds_mmss(Decimal("3661.4")) == "61:01"


def test_freestyle_work_excludes_drill_cooldown_rest_and_outliers() -> None:
    records = (
        interval(0, distance_m=80, pace="180"),
        interval(1, distance_m=40, pace="170", planned_role="DRILL"),
        interval(2, distance_m=80, pace="190", planned_role="COOLDOWN"),
        interval(3, distance_m=0, interval_type="REST", planned_role="REST"),
        interval(4, distance_m=80, pace="160", stroke="BREASTSTROKE"),
        interval(5, distance_m=80, pace="181", is_outlier=True),
        interval(6, distance_m=80, pace="182", interval_type="UNKNOWN"),
    )

    selected = freestyle_work_intervals(records)

    assert tuple(item["interval_index"] for item in selected if isinstance(item, dict)) == (0,)


def test_specific_planned_stroke_contextualizes_mixed_but_excludes_explicit_mismatch() -> None:
    records = tuple(
        interval(
            index,
            distance_m=40,
            pace=pace,
            stroke=detected,
            planned_stroke="FREESTYLE",
            set_id="planned-freestyle",
        )
        for index, (pace, detected) in enumerate(
            (
                ("160", "FREESTYLE"),
                ("170", "MIXED"),
                ("210", "BREASTSTROKE"),
                ("180", "UNKNOWN"),
            )
        )
    )

    selected = freestyle_work_intervals(records)
    analyzed = group_equivalent_sets(records)[0]

    assert tuple(item["interval_index"] for item in selected if isinstance(item, dict)) == (
        0,
        1,
        3,
    )
    assert analyzed.key.stroke == "FREESTYLE"
    assert analyzed.interval_indices == (0, 1, 3)
    assert analyzed.excluded_outlier_indices == ()
    assert analyzed.excluded_stroke_mismatch_indices == (2,)
    assert analyzed.paces_s_per_100m == (
        Decimal("160.000"),
        Decimal("170.000"),
        Decimal("180.000"),
    )
    assert "DETECTED_STROKE_MISMATCH_EXCLUDED" in analyzed.quality_reasons
    assert "PLANNED_STROKE_CONTEXT_USED" in analyzed.quality_reasons


def test_equivalent_sets_do_not_mix_planned_intensity_or_target_range() -> None:
    records = (
        interval(
            0,
            distance_m=80,
            pace="180",
            set_id="main",
            planned_intensity="MODERATE",
            target_min_pace_s_per_100m=Decimal("170"),
            target_max_pace_s_per_100m=Decimal("190"),
        ),
        interval(
            1,
            distance_m=80,
            pace="181",
            set_id="main",
            planned_intensity="MODERATE",
            target_min_pace_s_per_100m=Decimal("170"),
            target_max_pace_s_per_100m=Decimal("190"),
        ),
        interval(
            2,
            distance_m=80,
            pace="165",
            set_id="main",
            planned_intensity="FAST",
            target_min_pace_s_per_100m=Decimal("155"),
            target_max_pace_s_per_100m=Decimal("170"),
        ),
        interval(
            3,
            distance_m=80,
            pace="164",
            set_id="main",
            planned_intensity="FAST",
            target_min_pace_s_per_100m=Decimal("155"),
            target_max_pace_s_per_100m=Decimal("170"),
        ),
    )

    sets = group_equivalent_sets(records)

    assert len(sets) == 2
    assert [item.key.planned_intensity for item in sets] == ["MODERATE", "FAST"]
    assert [item.key.target_min_pace_s_per_100m for item in sets] == [
        Decimal("170"),
        Decimal("155"),
    ]
    assert [item.paces_s_per_100m for item in sets] == [
        (Decimal("180.000"), Decimal("181.000")),
        (Decimal("165.000"), Decimal("164.000")),
    ]


def test_equivalent_set_metrics_compare_only_same_distance_stroke_and_role() -> None:
    records = (
        interval(
            0,
            distance_m=80,
            pace="198",
            swim_pace_s_per_100m=Decimal("198"),
            set_id="main",
            target_min_pace_s_per_100m=Decimal("170"),
            target_max_pace_s_per_100m=Decimal("200"),
        ),
        interval(
            1,
            distance_m=0,
            interval_type="REST",
            planned_role="REST",
            timer_duration_s="24",
            rest_duration_s="24",
            planned_duration_s=Decimal("25"),
        ),
        interval(
            2,
            distance_m=80,
            pace="194",
            swim_pace_s_per_100m=Decimal("194"),
            set_id="main",
            target_min_pace_s_per_100m=Decimal("170"),
            target_max_pace_s_per_100m=Decimal("200"),
        ),
        interval(
            3,
            distance_m=0,
            interval_type="REST",
            planned_role="REST",
            timer_duration_s="24",
            rest_duration_s="24",
            planned_duration_s=Decimal("25"),
        ),
        interval(
            4,
            distance_m=80,
            pace="179",
            swim_pace_s_per_100m=Decimal("179"),
            set_id="main",
            target_min_pace_s_per_100m=Decimal("170"),
            target_max_pace_s_per_100m=Decimal("200"),
        ),
        interval(
            5,
            distance_m=0,
            interval_type="REST",
            planned_role="REST",
            timer_duration_s="24",
            rest_duration_s="24",
            planned_duration_s=Decimal("25"),
        ),
        interval(
            6,
            distance_m=80,
            pace="175",
            swim_pace_s_per_100m=Decimal("175"),
            set_id="main",
            target_min_pace_s_per_100m=Decimal("170"),
            target_max_pace_s_per_100m=Decimal("200"),
        ),
        interval(7, distance_m=40, pace="130", planned_role="DRILL"),
        interval(8, distance_m=80, pace="220", planned_role="COOLDOWN"),
    )

    sets = group_equivalent_sets(records)

    assert len(sets) == 1
    result = sets[0]
    assert result.key.distance_m == 80
    assert result.key.stroke == "FREESTYLE"
    assert result.key.planned_role == "WORK"
    assert result.paces_s_per_100m == (
        Decimal("198.000"),
        Decimal("194.000"),
        Decimal("179.000"),
        Decimal("175.000"),
    )
    assert result.mean_pace_s_per_100m == Decimal("186.500")
    assert result.best_pace_s_per_100m == Decimal("175.000")
    assert result.worst_pace_s_per_100m == Decimal("198.000")
    assert result.amplitude_s_per_100m == Decimal("23.000")
    assert result.coefficient_of_variation == Decimal("0.0521")
    assert result.trend is TrendDirection.FASTER
    assert result.negative_split is True
    assert result.fade_percent == Decimal("-9.69")
    assert result.target_compliance_ratio == Decimal("1.0000")
    assert result.target_compliance_pace_basis == "swim"
    assert result.planned_rest_duration_s == Decimal("75.000")
    assert result.actual_rest_duration_s == Decimal("72.000")
    assert result.quality is QualityLevel.MEDIUM
    assert result.quality_reasons == ("PLANNED_PACE_BASIS_INFERRED_SWIM",)


def test_robust_outlier_detection_is_scoped_to_equivalent_repetitions() -> None:
    records = tuple(
        interval(index, distance_m=20, pace=pace, set_id="twenties")
        for index, pace in enumerate(("180", "181", "179", "360", "180"))
    )

    flags = detect_interval_outliers(records)
    sets = group_equivalent_sets(records)

    assert len(flags) == 1
    assert flags[0].interval_index == 3
    assert flags[0].reason == "ROBUST_MAD_OUTLIER"
    # A statistical flag asks for inspection; it is not proof that the swim is
    # invalid and therefore must not erase a real fade from the set metrics.
    assert sets[0].excluded_outlier_indices == ()
    assert sets[0].mean_pace_s_per_100m == Decimal("216.000")


def test_equivalent_set_excludes_only_explicit_low_quality_measurements() -> None:
    records = tuple(
        interval(
            index,
            distance_m=100,
            pace=pace,
            set_id="hundreds",
            is_outlier=index == 3,
        )
        for index, pace in enumerate(("150", "151", "152", "200"))
    )

    result = group_equivalent_sets(records)[0]

    assert result.excluded_outlier_indices == (3,)
    assert result.paces_s_per_100m == (
        Decimal("150.000"),
        Decimal("151.000"),
        Decimal("152.000"),
    )


def test_persisted_quality_warning_excludes_measurement_from_fitness_and_fade() -> None:
    records = tuple(
        interval(
            index,
            distance_m=100,
            pace=pace,
            set_id="hundreds",
            quality_warnings=("EXCLUDE_FROM_FITNESS",) if index == 3 else (),
        )
        for index, pace in enumerate(("150", "151", "152", "240"))
    )

    result = group_equivalent_sets(records)[0]

    assert result.excluded_outlier_indices == (3,)
    assert result.paces_s_per_100m == (
        Decimal("150.000"),
        Decimal("151.000"),
        Decimal("152.000"),
    )
    assert tuple(
        item["interval_index"]
        for item in freestyle_work_intervals(records)
        if isinstance(item, dict)
    ) == (0, 1, 2)


def test_unknown_interval_set_never_claims_high_quality_or_fade() -> None:
    records = tuple(
        interval(
            index,
            distance_m=80,
            pace=pace,
            interval_type="UNKNOWN",
            set_id="unknown-main",
        )
        for index, pace in enumerate(("200", "195", "190", "185"))
    )

    result = group_equivalent_sets(records)[0]

    assert result.quality is QualityLevel.MEDIUM
    assert "UNKNOWN_INTERVAL_TYPE_IN_SET" in result.quality_reasons
    assert result.fade_percent is None


def test_each_equivalent_set_selects_its_own_explicit_pace_basis() -> None:
    records = (
        interval(0, distance_m=100, pace="190", planned_role="WARMUP", set_id="warmup"),
        interval(1, distance_m=100, pace="191", planned_role="WARMUP", set_id="warmup"),
        *(
            interval(
                index,
                distance_m=80,
                planned_role="WORK",
                set_id="main",
                timer_pace_s_per_100m=Decimal(pace),
            )
            for index, pace in enumerate(("198", "194", "179", "175"), start=2)
        ),
    )

    sets = group_equivalent_sets(records, pace_basis="best_available")
    main = next(item for item in sets if item.key.set_id == "main")

    assert main.pace_basis == "timer"
    assert main.paces_s_per_100m == (
        Decimal("198.000"),
        Decimal("194.000"),
        Decimal("179.000"),
        Decimal("175.000"),
    )


def test_best_available_set_basis_maximizes_coverage_and_discloses_missing_repetitions() -> None:
    complete_swim = tuple(
        interval(
            index,
            distance_m=80,
            pace="180" if index < 2 else None,
            swim_pace_s_per_100m=Decimal(170 + index),
            timer_pace_s_per_100m=Decimal(190 + index) if index < 3 else None,
        )
        for index in range(4)
    )
    moving_wins_tie = tuple(
        interval(
            index,
            distance_m=100,
            pace=str(180 + index) if index < 4 else None,
            swim_pace_s_per_100m=Decimal(170 + index) if index < 3 else None,
            timer_pace_s_per_100m=Decimal(190 + index) if index < 4 else None,
        )
        for index in range(5)
    )

    swim_set = group_equivalent_sets(complete_swim, pace_basis="best_available")[0]
    moving_set = group_equivalent_sets(moving_wins_tie, pace_basis="best_available")[0]

    assert swim_set.pace_basis == "swim"
    assert swim_set.interval_indices == (0, 1, 2, 3)
    assert swim_set.missing_pace_indices == ()
    assert moving_set.pace_basis == "moving"
    assert moving_set.interval_indices == (0, 1, 2, 3)
    assert moving_set.missing_pace_indices == (4,)
    assert moving_set.quality is QualityLevel.MEDIUM
    assert "MISSING_MOVING_PACE_FOR_REPETITIONS" in moving_set.quality_reasons


def test_long_rest_splits_unplanned_sets_but_normal_repetition_rest_does_not() -> None:
    records = (
        interval(0, distance_m=80, pace="180"),
        interval(1, distance_m=0, interval_type="REST", planned_role="REST", rest_duration_s="25"),
        interval(2, distance_m=80, pace="181"),
        interval(3, distance_m=0, interval_type="REST", planned_role="REST", rest_duration_s="25"),
        interval(4, distance_m=80, pace="182"),
        interval(5, distance_m=0, interval_type="REST", planned_role="REST", rest_duration_s="25"),
        interval(6, distance_m=80, pace="183"),
        interval(7, distance_m=0, interval_type="REST", planned_role="REST", rest_duration_s="90"),
        interval(8, distance_m=80, pace="184"),
        interval(9, distance_m=0, interval_type="REST", planned_role="REST", rest_duration_s="25"),
        interval(10, distance_m=80, pace="185"),
    )

    sets = group_equivalent_sets(records)

    assert [item.interval_indices for item in sets] == [(0, 2, 4, 6), (8, 10)]
    assert sets[0].actual_rest_duration_s == Decimal("75.000")
    assert sets[1].actual_rest_duration_s == Decimal("25.000")
    assert all("UNPLANNED_LONG_REST_SET_BOUNDARY_INFERRED" in item.quality_reasons for item in sets)


def test_continuity_uses_real_active_sequences_and_exact_freestyle_windows() -> None:
    lengths: list[dict[str, object]] = []
    for index, duration in enumerate((40, 40, 40, 40, 40, 30, 30, 30, 30, 30)):
        lengths.append(
            {
                "length_index": index,
                "length_type": "ACTIVE",
                "distance_m": 20,
                "duration_seconds": duration,
                "detected_stroke": "FREESTYLE",
                "planned_role": "WORK",
            }
        )
    lengths.append({"length_index": 10, "length_type": "IDLE", "distance_m": 0})
    for index in range(11, 16):
        lengths.append(
            {
                "length_index": index,
                "length_type": "ACTIVE",
                "distance_m": 20,
                "duration_seconds": 25,
                "detected_stroke": "DRILL",
                "planned_role": "DRILL",
            }
        )

    result = analyze_continuity(lengths)

    assert result.longest_continuous_swim is not None
    assert result.longest_continuous_swim.distance_m == 200
    assert result.longest_continuous_freestyle is not None
    assert result.longest_continuous_freestyle.distance_m == 200
    assert result.best_windows[100] is not None
    assert result.best_windows[100].duration_s == Decimal("150.000")
    assert result.best_windows[100].pace_s_per_100m == Decimal("150.000")
    assert result.best_windows[200] is not None
    assert result.best_windows[200].pace_s_per_100m == Decimal("175.000")
    assert result.best_windows[400] is None
    assert result.quality is QualityLevel.MEDIUM
    assert "NO_CONTIGUOUS_400M_WINDOW" in result.quality_reasons


def test_continuity_never_crosses_a_positive_stationary_length_fact() -> None:
    lengths = tuple(
        {
            "length_index": index,
            "length_type": "ACTIVE",
            "distance_m": 20,
            "swim_duration_s": Decimal("30"),
            "stationary_duration_s": Decimal("0.001") if index == 1 else Decimal(0),
            "detected_stroke": "FREESTYLE",
            "planned_role": "WORK",
        }
        for index in range(4)
    )

    result = analyze_continuity(lengths, window_distances_m=(40, 80))

    assert result.longest_continuous_swim is not None
    assert result.longest_continuous_swim.distance_m == 40
    assert result.best_windows[40] is not None
    assert result.best_windows[80] is None


def test_quality_reasons_warn_instead_of_rejecting_garmin_invariants() -> None:
    activity = {
        "moving_duration_s": Decimal("2100"),
        "timer_duration_s": Decimal("2075"),
        "elapsed_duration_s": Decimal("2089"),
        "pool_length_m": 20,
        "distance_m": 860,
        "active_length_count": 40,
    }
    records = (
        interval(0, distance_m=80, pace="180"),
        interval(1, distance_m=80, pace="182"),
    )

    result = assess_data_quality(
        activity,
        intervals=records,
        lengths=({"length_type": "ACTIVE", "distance_m": 20},),
        pool_length_inferred=True,
    )

    assert result.level is QualityLevel.LOW
    assert "MOVING_EXCEEDS_TIMER" in result.reasons
    assert "ACTIVE_LENGTH_DISTANCE_MISMATCH" in result.reasons
    assert "POOL_LENGTH_INFERRED" in result.reasons


def test_one_pool_length_distance_difference_is_still_a_quality_warning() -> None:
    result = assess_data_quality(
        {
            "moving_duration_s": Decimal("100"),
            "timer_duration_s": Decimal("100"),
            "elapsed_duration_s": Decimal("100"),
            "pool_length_m": 20,
            "distance_m": 860,
            "active_length_count": 42,
        },
        intervals=(
            interval(0, distance_m=80, pace="180"),
            interval(1, distance_m=80, pace="181"),
        ),
        lengths=({"length_type": "ACTIVE", "distance_m": 20},),
    )

    assert "ACTIVE_LENGTH_DISTANCE_MISMATCH" in result.reasons


def test_analysis_quality_never_overrides_poor_normalization_quality() -> None:
    result = assess_data_quality(
        {
            "moving_duration_s": Decimal("100"),
            "timer_duration_s": Decimal("100"),
            "elapsed_duration_s": Decimal("100"),
            "pool_length_m": 20,
            "distance_m": 40,
            "active_length_count": 2,
            "quality": "poor",
            "completeness": Decimal("0.10"),
        },
        intervals=(
            interval(0, distance_m=20, pace="150"),
            interval(1, distance_m=20, pace="151"),
        ),
        lengths=({"length_type": "ACTIVE", "distance_m": 20},),
    )

    assert result.level is QualityLevel.LOW
    assert "NORMALIZATION_QUALITY_POOR" in result.reasons


def test_speed_endurance_profile_does_not_extrapolate_800m_to_2km() -> None:
    records = (
        interval(0, distance_m=40, pace="125", stroke_count=20),
        interval(1, distance_m=40, pace="127", stroke_count=20),
        interval(2, distance_m=40, pace="126", stroke_count=20),
        interval(3, distance_m=200, pace="145"),
        interval(4, distance_m=200, pace="147"),
        interval(5, distance_m=400, pace="150"),
        interval(6, distance_m=400, pace="152"),
        interval(7, distance_m=800, pace="155"),
        interval(8, distance_m=80, pace="220", planned_role="DRILL"),
    )

    profile = build_speed_endurance_profile(records)

    assert profile.speed.interval_count == 3
    assert profile.speed.gap_to_goal_pace_s_per_100m is None
    assert profile.short_endurance.interval_count == 2
    assert profile.short_endurance.gap_to_goal_pace_s_per_100m is None
    assert profile.aerobic_endurance.interval_count == 3
    assert profile.aerobic_endurance.gap_to_goal_pace_s_per_100m is not None
    assert profile.goal_readiness.longest_evidence_distance_m == 800
    assert profile.goal_readiness.ready is None
    assert profile.goal_readiness.confidence is QualityLevel.MEDIUM
    assert "GOAL_DISTANCE_NOT_YET_OBSERVED" in profile.goal_readiness.reasons
    assert profile.technique.gap_to_goal_pace_s_per_100m is None
    assert profile.technique.quality is QualityLevel.LOW
    assert next(
        band for band in profile.bands if band.name == "1000m_plus_long_endurance"
    ).reasons == ("NO_COMPARABLE_EVIDENCE",)
    assert all(band.name != "CSS" for band in profile.bands)


def test_goal_readiness_uses_real_unplanned_length_continuity() -> None:
    lengths = tuple(
        {
            "length_index": index,
            "length_type": "ACTIVE",
            "distance_m": 20,
            "duration_seconds": Decimal("27"),
            "swim_pace_s_per_100m": Decimal("135"),
            "detected_stroke": "FREESTYLE",
            "stroke_count": 10,
        }
        for index in range(100)
    )

    profile = build_speed_endurance_profile((), lengths=lengths)

    assert profile.goal_readiness.longest_evidence_distance_m == 2_000
    assert profile.goal_readiness.evidence_pace_s_per_100m == Decimal("135.000")
    assert profile.goal_readiness.evidence_pace_basis == "swim_length"
    assert profile.goal_readiness.ready is True
    assert profile.goal_readiness.confidence is QualityLevel.HIGH
    assert profile.technique.interval_count == 100
    assert profile.technique.gap_to_goal_pace_s_per_100m is None


def test_goal_readiness_is_capped_by_low_canonical_data_quality() -> None:
    lengths = tuple(
        {
            "length_index": index,
            "length_type": "ACTIVE",
            "distance_m": 20,
            "duration_seconds": Decimal("27"),
            "swim_pace_s_per_100m": Decimal("135"),
            "detected_stroke": "FREESTYLE",
        }
        for index in range(100)
    )
    activity = {
        "moving_duration_s": Decimal("2700"),
        "timer_duration_s": Decimal("2700"),
        "elapsed_duration_s": Decimal("2700"),
        "pool_length_m": 20,
        "distance_m": 2_000,
        "active_length_count": 100,
        "quality": "poor",
        "completeness": Decimal("0.10"),
    }

    profile = build_speed_endurance_profile((), lengths=lengths, activity=activity)

    assert profile.goal_readiness.longest_evidence_distance_m == 2_000
    assert profile.goal_readiness.ready is None
    assert profile.goal_readiness.confidence is QualityLevel.LOW
    assert "CANONICAL_DATA_QUALITY_LOW" in profile.goal_readiness.reasons


def test_short_speed_evidence_is_not_compared_to_long_distance_goal_pace() -> None:
    profile = build_speed_endurance_profile(
        (
            interval(0, distance_m=40, pace="125"),
            interval(1, distance_m=40, pace="126"),
            interval(2, distance_m=40, pace="127"),
        )
    )

    assert profile.speed.best_pace_s_per_100m == Decimal("125.000")
    assert profile.goal_readiness.longest_evidence_distance_m == 40
    assert profile.goal_readiness.pace_gap_s_per_100m is None
    assert profile.goal_readiness.ready is None
    assert profile.goal_readiness.confidence is QualityLevel.LOW


def test_incompatible_distance_and_stroke_do_not_align() -> None:
    planned = [
        {
            "type": "step",
            "step_role": "WORK",
            "distance_m": 400,
            "stroke": "breaststroke",
        }
    ]
    actual = [interval(0, distance_m=20, pace="150", stroke="FREESTYLE")]

    adherence = align_planned_steps(planned, actual)

    assert adherence.matched_step_ratio == Decimal("0.0000")
    assert adherence.alignments[0].status is AlignmentStatus.UNMATCHED
    assert adherence.unmatched_actual_indices == (0,)


def test_step_alignment_discloses_timer_pace_fallback_when_moving_is_missing() -> None:
    planned = [
        {
            "type": "step",
            "step_role": "WORK",
            "distance_m": 80,
            "stroke": "freestyle",
        }
    ]
    actual = [
        interval(
            0,
            distance_m=80,
            timer_duration_s="158.2",
            timer_pace_s_per_100m=Decimal("197.75"),
        )
    ]

    alignment = align_planned_steps(planned, actual, pace_basis="best_available").alignments[0]

    assert alignment.actual_pace_s_per_100m == Decimal("197.75")
    assert alignment.actual_pace_basis == "timer"


def test_adherence_quality_uses_only_alignment_evidence() -> None:
    adherence = align_planned_steps(
        [
            {
                "type": "step",
                "step_role": "WORK",
                "distance_m": 80,
                "stroke": "freestyle",
            }
        ],
        [interval(0, distance_m=80, pace="180", timer_duration_s="144")],
    )

    assert adherence.quality.level is QualityLevel.HIGH
    assert adherence.quality.reasons == ()
    assert "NO_LENGTH_DATA" not in adherence.quality.reasons
    assert "INSUFFICIENT_INTERVALS" not in adherence.quality.reasons


def test_planned_drill_aligns_to_same_distance_mixed_swim_but_not_arbitrary_swims() -> None:
    planned = [
        {
            "type": "step",
            "step_role": "DRILL",
            "distance_m": 160,
            "stroke": "drill",
        }
    ]

    contextual = align_planned_steps(
        planned,
        [interval(0, distance_m=160, interval_type="SWIM", stroke="MIXED", pace="210")],
    )
    unrelated = align_planned_steps(
        planned,
        [interval(0, distance_m=20, interval_type="SWIM", stroke="MIXED", pace="210")],
    )

    alignment = contextual.alignments[0]
    assert alignment.status is AlignmentStatus.PARTIAL
    assert alignment.confidence == Decimal("0.8125")
    assert alignment.actual_interval_type == "SWIM"
    assert "INTERVAL_TYPE_MISMATCH" in alignment.reasons
    assert "STROKE_DETECTION_INDETERMINATE" in alignment.reasons
    assert "STROKE_MISMATCH" not in alignment.reasons
    assert unrelated.alignments[0].status is AlignmentStatus.UNMATCHED


def planned_workout_880m() -> dict[str, object]:
    return {
        "nodes": [
            {
                "type": "step",
                "id": "warmup",
                "step_role": "WARMUP",
                "end_condition": {"type": "distance", "meters": 160},
                "stroke": {"type": "freestyle"},
            },
            {
                "type": "repeat",
                "id": "main",
                "repetitions": 4,
                "children": [
                    {
                        "type": "step",
                        "id": "work-80",
                        "step_role": "WORK",
                        "end_condition": {"type": "distance", "meters": 80},
                        "stroke": {"type": "freestyle"},
                        "target": {
                            "type": "pace_range",
                            "min_seconds_per_100m": 170,
                            "max_seconds_per_100m": 190,
                        },
                        "intensity": "MODERATE",
                    },
                    {
                        "type": "step",
                        "id": "rest-25",
                        "step_role": "REST",
                        "end_condition": {"type": "time", "seconds": 25},
                        "stroke": {"type": "choice"},
                    },
                ],
            },
            {
                "type": "step",
                "id": "drill",
                "step_role": "DRILL",
                "end_condition": {"type": "distance", "meters": 160},
                "stroke": {"type": "drill", "drill": "catch-up"},
            },
            {
                "type": "step",
                "id": "cooldown",
                "step_role": "COOLDOWN",
                "end_condition": {"type": "distance", "meters": 240},
                "stroke": {"type": "freestyle"},
            },
        ]
    }


def actual_activity_860m() -> tuple[dict[str, object], ...]:
    records = [
        interval(
            0,
            distance_m=160,
            pace="190",
            planned_role="WARMUP",
            timer_duration_s="304",
        )
    ]
    next_index = 1
    for pace in ("198", "194", "179", "175"):
        records.append(
            interval(
                next_index,
                distance_m=80,
                pace=pace,
                timer_duration_s=str(Decimal(pace) * Decimal("0.8")),
                swim_duration_s=Decimal(pace) * Decimal("0.8"),
                swim_pace_s_per_100m=Decimal(pace),
            )
        )
        next_index += 1
        records.append(
            interval(
                next_index,
                distance_m=0,
                interval_type="REST",
                planned_role="REST",
                stroke="UNKNOWN",
                timer_duration_s="25",
                rest_duration_s="25",
            )
        )
        next_index += 1
    records.extend(
        (
            interval(
                next_index,
                distance_m=160,
                pace="210",
                interval_type="DRILL",
                planned_role="DRILL",
                stroke="DRILL",
                timer_duration_s="336",
            ),
            interval(
                next_index + 1,
                distance_m=220,
                pace="200",
                planned_role="COOLDOWN",
                timer_duration_s="440",
            ),
        )
    )
    return tuple(records)


def test_planned_steps_expand_repeat_identity_and_align_880m_to_860m() -> None:
    workout = planned_workout_880m()
    expanded = expand_planned_steps(workout)

    assert len(expanded) == 11
    assert [step.repetition_index for step in expanded if step.step_id == "work-80"] == [
        0,
        1,
        2,
        3,
    ]
    assert {step.set_id for step in expanded if step.step_id == "work-80"} == {"main"}

    adherence = align_planned_steps(workout, actual_activity_860m())

    assert adherence.planned_distance_m == 880
    assert adherence.actual_distance_m == 860
    assert adherence.distance_difference_m == -20
    assert adherence.distance_adherence_ratio == Decimal("0.9773")
    assert adherence.matched_step_ratio == Decimal("1.0000")
    assert not adherence.unmatched_actual_indices
    assert all(
        alignment.status is not AlignmentStatus.UNMATCHED for alignment in adherence.alignments
    )
    rests = [
        alignment for alignment in adherence.alignments if alignment.planned_interval_type == "REST"
    ]
    assert len(rests) == 4
    assert all(rest.actual_duration_s == Decimal("25") for rest in rests)
    work = [alignment for alignment in adherence.alignments if alignment.planned_role == "WORK"]
    assert all(alignment.planned_intensity == "MODERATE" for alignment in work)
    assert [alignment.target_pace_met for alignment in work] == [False, False, True, True]
    assert [alignment.duration_target_met for alignment in work] == [False, False, True, True]
    assert all(alignment.planned_duration_s is None for alignment in work)
    assert all(alignment.planned_duration_min_s == Decimal("136.000") for alignment in work)
    assert all(alignment.planned_duration_max_s == Decimal("152.000") for alignment in work)
    assert all(alignment.actual_duration_basis == "swim_duration_s" for alignment in work)
    assert all(alignment.planned_pace_basis == "swim" for alignment in work)
    assert work[0].pace_difference_s_per_100m == Decimal("18.000")
    assert work[0].planned_pace_min_s_per_100m == Decimal("170")
    assert work[0].planned_pace_max_s_per_100m == Decimal("190")
    assert "PACE_TARGET_MISSED" in work[0].reasons
    assert "DURATION_MISMATCH" not in work[0].reasons
    assert "PLANNED_PACE_BASIS_INFERRED_SWIM" in work[0].reasons
    cooldown = adherence.alignments[-1]
    assert cooldown.distance_difference_m == -20
    assert "DISTANCE_MISMATCH" in cooldown.reasons
    assert adherence.quality.level is QualityLevel.MEDIUM
    assert "NO_LENGTH_DATA" not in adherence.quality.reasons
    assert "INSUFFICIENT_INTERVALS" not in adherence.quality.reasons


@given(
    seconds=st.decimals(
        min_value=0,
        max_value=100_000,
        places=3,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_format_seconds_property_round_trips_to_nearest_second(seconds: Decimal) -> None:
    rendered = format_seconds_mmss(seconds)
    minutes_text, seconds_text = rendered.split(":")
    reconstructed = int(minutes_text) * 60 + int(seconds_text)
    expected = int(seconds.to_integral_value(rounding=ROUND_HALF_UP))

    assert reconstructed == expected
    assert 0 <= int(seconds_text) < 60


@given(
    planned_distance=st.integers(min_value=20, max_value=2_000),
    actual_distance=st.integers(min_value=0, max_value=2_000),
)
def test_adherence_distance_difference_is_an_exact_invariant(
    planned_distance: int, actual_distance: int
) -> None:
    planned = [
        {
            "type": "step",
            "step_role": "WORK",
            "distance_m": planned_distance,
            "stroke": "freestyle",
        }
    ]
    actual = [
        interval(
            0,
            distance_m=actual_distance,
            pace="180" if actual_distance else None,
            timer_duration_s="60",
        )
    ]

    result = align_planned_steps(planned, actual)

    assert result.distance_difference_m == actual_distance - planned_distance
    assert result.planned_distance_m == planned_distance
    assert result.actual_distance_m == actual_distance
