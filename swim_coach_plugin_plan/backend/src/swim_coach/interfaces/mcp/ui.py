"""Portable, optional MCP Apps resources and card projections for P09."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any, Final
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP

from swim_coach.application.services.mcp_read import McpResult

MCP_APP_MIME_TYPE: Final = "text/html;profile=mcp-app"
MCP_UI_RESOURCE_URIS: Final = {
    "workout": "ui://swim-coach/workout-card/v1.html",
    "activity": "ui://swim-coach/activity-comparison-card/v1.html",
    "goal": "ui://swim-coach/goal-progress-card/v1.html",
    "proposal": "ui://swim-coach/proposal-confirmation-card/v1.html",
    "sync": "ui://swim-coach/sync-status-card/v1.html",
}
MCP_UI_TOOLS: Final = (
    "render_workout_card",
    "render_activity_comparison_card",
    "render_goal_progress_card",
    "render_proposal_confirmation_card",
    "render_sync_status_card",
)


def register_ui_resources(server: FastMCP, *, pwa_base_url: str) -> None:
    """Register self-contained resources with a closed CSP and one trusted PWA link origin."""

    template = (
        files("swim_coach.interfaces.mcp")
        .joinpath("assets/swim-coach-card-v1.html")
        .read_text(encoding="utf-8")
    )
    origin = _origin(pwa_base_url)
    standard_csp: dict[str, list[str]] = {
        "connectDomains": [],
        "resourceDomains": [],
        "frameDomains": [],
    }
    resource_meta: dict[str, Any] = {
        "ui": {
            "prefersBorder": True,
            "csp": standard_csp,
        },
        "openai/widgetDescription": (
            "Interactive Swim Coach review card. All displayed business data remains "
            "authoritative on the MCP server."
        ),
        "openai/widgetPrefersBorder": True,
        "openai/widgetCSP": {
            "connect_domains": [],
            "resource_domains": [],
            "frame_domains": [],
            "redirect_domains": [origin],
        },
    }

    def resource_factory() -> Callable[[], str]:
        def resource() -> str:
            return template

        return resource

    for kind, uri in MCP_UI_RESOURCE_URIS.items():
        resource = resource_factory()
        resource.__name__ = f"swim_coach_{kind}_card_v1"
        server.resource(
            uri,
            name=f"swim-coach-{kind}-card-v1",
            title=f"Swim Coach {kind.title()} Card",
            description=(
                "Versioned optional MCP Apps inline card with a complete headless fallback."
            ),
            mime_type=MCP_APP_MIME_TYPE,
            meta=resource_meta,
        )(resource)


def ui_tool_meta(kind: str) -> dict[str, Any]:
    """Return standards-first tool metadata plus the supported ChatGPT alias."""

    uri = MCP_UI_RESOURCE_URIS[kind]
    return {
        "ui": {"resourceUri": uri},
        "openai/outputTemplate": uri,
        "openai/toolInvocation/invoking": "Preparing swim card…",
        "openai/toolInvocation/invoked": "Swim card ready.",
    }


def workout_card(result: McpResult, *, pwa_base_url: str, view: str) -> McpResult:
    projected = result.model_copy(deep=True)
    if view == "week":
        sessions = projected.data.get("sessions", [])
        projected.data["card"] = {
            "kind": "workout",
            "view": "week",
            "title": "Semana de natação",
            "subtitle": f"{projected.data.get('week_start')} a {projected.data.get('week_end')}",
            "status": projected.status,
            "metrics": [
                {"label": "Sessões", "value": projected.data.get("session_count", 0)},
                {
                    "label": "Volume",
                    "value": f"{projected.data.get('total_distance_m', 0)} m",
                },
            ],
            "items": [_workout_item(item) for item in sessions if isinstance(item, dict)],
            "links": [{"label": "Abrir calendário", "href": _pwa_link(pwa_base_url, "/calendar")}],
            "warnings": _warnings(projected),
        }
        return projected

    workout = projected.data.get("workout")
    if not isinstance(workout, dict):
        projected.data["card"] = {
            "kind": "workout",
            "view": "today",
            "title": "Treino do dia",
            "subtitle": projected.data.get("date"),
            "status": projected.status,
            "empty": True,
            "metrics": [],
            "items": [],
            "links": [{"label": "Abrir treinos", "href": _pwa_link(pwa_base_url, "/workouts")}],
            "warnings": _warnings(projected),
        }
        return projected

    totals = workout.get("totals", {}) if isinstance(workout.get("totals"), dict) else {}
    steps = workout.get("steps", []) if isinstance(workout.get("steps"), list) else []
    projected.data["card"] = {
        "kind": "workout",
        "view": "today",
        "title": workout.get("title", "Treino do dia"),
        "subtitle": workout.get("scheduled_date") or projected.data.get("date"),
        "status": workout.get("status", projected.status),
        "hash": workout.get("content_hash"),
        "metrics": [
            {"label": "Distância", "value": f"{totals.get('distance_m', 0)} m"},
            {
                "label": "Duração estimada",
                "value": _duration(totals.get("estimated_total_seconds")),
            },
            {"label": "Piscina", "value": f"{workout.get('pool_length_m', 20)} m"},
            {
                "label": "Garmin",
                "value": (workout.get("garmin") or {}).get("publish_status", "—")
                if isinstance(workout.get("garmin"), dict)
                else "—",
            },
        ],
        "items": [_step_item(item) for item in steps if isinstance(item, dict)][:30],
        "links": [{"label": "Abrir treino", "href": _pwa_link(pwa_base_url, "/workouts")}],
        "warnings": _warnings(projected),
    }
    return projected


def activity_card(result: McpResult, *, pwa_base_url: str) -> McpResult:
    projected = result.model_copy(deep=True)
    analysis = projected.data.get("analysis")
    analysis = analysis if isinstance(analysis, dict) else {}
    feedback = projected.data.get("feedback")
    match = projected.data.get("match")
    intervals = projected.data.get("intervals", [])
    projected.data["card"] = {
        "kind": "activity",
        "title": "Natação realizada",
        "subtitle": projected.data.get("started_local"),
        "status": projected.status,
        "quality": projected.data.get("quality"),
        "metrics": [
            {"label": "Distância", "value": f"{projected.data.get('distance_m', 0)} m"},
            {
                "label": "Tempo em movimento",
                "value": _duration(projected.data.get("moving_seconds")),
            },
            {
                "label": "Ritmo / 100 m",
                "value": _duration(projected.data.get("pace_seconds_per_100m")),
            },
            {"label": "SWOLF", "value": analysis.get("average_swolf", "—")},
            {"label": "Fade", "value": _percent(analysis.get("fade_percent"))},
            {
                "label": "Feedback",
                "value": "Registrado" if isinstance(feedback, dict) else "Pendente",
            },
        ],
        "comparison": {
            "matched": isinstance(match, dict),
            "confidence": match.get("confidence") if isinstance(match, dict) else None,
        },
        "items": [_interval_item(item) for item in intervals if isinstance(item, dict)][:30],
        "links": [{"label": "Abrir atividades", "href": _pwa_link(pwa_base_url, "/activities")}],
        "warnings": _warnings(projected),
    }
    return projected


def goal_card(result: McpResult, *, pwa_base_url: str) -> McpResult:
    projected = result.model_copy(deep=True)
    goal = projected.data.get("goal")
    goal = goal if isinstance(goal, dict) else {}
    projected.data["card"] = {
        "kind": "goal",
        "title": "Progresso da meta",
        "subtitle": f"Amostra: {projected.data.get('sample_quality', '—')}",
        "status": projected.status,
        "metrics": [
            {"label": "Meta", "value": f"{goal.get('target_distance_m', '—')} m"},
            {
                "label": "Melhor distância recente",
                "value": f"{projected.data.get('best_recent_distance_m', 0)} m",
            },
            {
                "label": "Melhor ritmo / 100 m",
                "value": _duration(projected.data.get("best_recent_pace_seconds_per_100m")),
            },
            {"label": "Amostras", "value": projected.data.get("sample_size", 0)},
        ],
        "items": [],
        "links": [{"label": "Abrir meta", "href": _pwa_link(pwa_base_url, "/goal")}],
        "warnings": _warnings(projected),
    }
    return projected


def proposal_card(result: McpResult) -> McpResult:
    projected = result.model_copy(deep=True)
    raw_expiry = projected.data.get("expires_at")
    expired = _expired(raw_expiry)
    status = str(projected.data.get("status", "UNKNOWN"))
    proposal_id = str(projected.data.get("proposal_id", ""))
    action_hash = str(projected.data.get("action_hash", ""))
    can_decide = status == "READY_FOR_REVIEW" and not expired
    projected.data["card"] = {
        "kind": "proposal",
        "title": "Confirmar ação",
        "subtitle": projected.data.get("action_type"),
        "status": status,
        "hash": action_hash,
        "expires_at": raw_expiry,
        "expired": expired,
        "metrics": [
            {"label": "Ação", "value": projected.data.get("action_type", "—")},
            {"label": "Escopo", "value": projected.data.get("required_action_scope", "—")},
            {"label": "Expira", "value": raw_expiry or "—"},
        ],
        "items": _impact_items(projected.data.get("impact")),
        "warnings": _warnings(projected),
        "decision": (
            {
                "tool": "approve_action_proposal",
                "proposal_id": proposal_id,
                "expected_action_hash": action_hash,
            }
            if can_decide
            else None
        ),
    }
    return projected


def sync_card(
    result: McpResult,
    *,
    job: McpResult | None,
) -> McpResult:
    projected = result.model_copy(deep=True)
    recent_runs = projected.data.get("recent_runs", [])
    job_data = job.data if job else None
    projected.data["card"] = {
        "kind": "sync",
        "title": "Sincronização Garmin",
        "subtitle": "Dados locais desatualizados"
        if projected.data.get("stale")
        else "Dados locais atuais",
        "status": projected.status,
        "metrics": [
            {"label": "Conexão", "value": projected.data.get("connection_status", "—")},
            {"label": "Último sucesso", "value": projected.data.get("last_success_at") or "—"},
            {"label": "Stale", "value": "Sim" if projected.data.get("stale") else "Não"},
        ],
        "items": [_sync_run_item(item) for item in recent_runs if isinstance(item, dict)][:5],
        "job": job_data,
        "retry": (
            {
                "tool": "retry_failed_job",
                "job_id": job_data.get("job_id"),
                "idempotency_key": f"ui-retry-{job_data.get('job_id')}",
            }
            if job_data and job_data.get("retryable") is True
            else None
        ),
        "warnings": [*_warnings(projected), *(_warnings(job) if job else [])],
    }
    return projected


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("PWA base URL must be an absolute HTTP(S) URL")
    return f"{parsed.scheme}://{parsed.netloc}"


def _pwa_link(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _warnings(result: McpResult | None) -> list[dict[str, str]]:
    if result is None:
        return []
    return [item.model_dump(mode="json") for item in result.warnings]


def _duration(value: Any) -> str:
    if value is None:
        return "—"
    try:
        seconds = max(0, round(float(value)))
    except (TypeError, ValueError):
        return "—"
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}:{remainder:02d}"


def _percent(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value}%"


def _workout_item(item: dict[str, Any]) -> dict[str, Any]:
    totals = item.get("totals", {}) if isinstance(item.get("totals"), dict) else {}
    return {
        "title": item.get("title", "Treino"),
        "detail": f"{item.get('scheduled_date', '—')} · {totals.get('distance_m', 0)} m",
        "status": item.get("status"),
    }


def _step_item(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("type") == "repeat":
        return {
            "title": item.get("label") or "Bloco repetido",
            "detail": f"{item.get('repetitions', 0)} repetições",
            "status": "repeat",
        }
    end_condition = item.get("end_condition", {})
    detail = "Etapa"
    if isinstance(end_condition, dict):
        value = end_condition.get("value")
        unit = end_condition.get("unit") or end_condition.get("type")
        detail = f"{value} {unit}" if value is not None else str(unit or detail)
    return {
        "title": item.get("label") or item.get("role") or "Etapa",
        "detail": detail,
        "status": item.get("intensity"),
    }


def _interval_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": f"Série {int(item.get('index', 0)) + 1}",
        "detail": (
            f"{item.get('distance_m', 0)} m · {_duration(item.get('duration_seconds'))} · "
            f"{item.get('stroke_type') or 'nado'}"
        ),
        "status": f"SWOLF {item.get('swolf')}" if item.get("swolf") is not None else None,
    }


def _impact_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    items: list[dict[str, Any]] = []
    for key, raw in sorted(value.items())[:20]:
        if isinstance(raw, list):
            detail = ", ".join(str(item) for item in raw[:10])
        elif isinstance(raw, dict):
            detail = ", ".join(f"{name}: {item}" for name, item in sorted(raw.items())[:10])
        else:
            detail = str(raw)
        items.append({"title": key.replace("_", " ").title(), "detail": detail, "status": None})
    return items


def _sync_run_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(item.get("status", "run")),
        "detail": (
            f"criados {item.get('created', 0)} · atualizados {item.get('updated', 0)} · "
            f"ignorados {item.get('skipped', 0)} · falhas {item.get('failed', 0)}"
        ),
        "status": item.get("started_at"),
    }


def _expired(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        return True
    return parsed.astimezone(UTC) <= datetime.now(UTC)
