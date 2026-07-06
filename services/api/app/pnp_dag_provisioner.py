from __future__ import annotations

from pathlib import Path

from croniter import croniter


def _pipeline_slug(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in value.strip())
    collapsed = "_".join(part for part in normalized.split("_") if part)
    for prefix in ("pnp_pipe_", "pipe_", "pnp_"):
        if collapsed.startswith(prefix):
            collapsed = collapsed[len(prefix):]
            break
    if collapsed.startswith("pnp_"):
        collapsed = collapsed[len("pnp_"):]
    return collapsed or "pipeline"


def build_pipeline_dag_id(instance_key: str, pipeline_id: str | None = None) -> str:
    token = ""
    if pipeline_id:
        token = pipeline_id.replace("-", "").lower()[:8]
    slug = _pipeline_slug(instance_key)
    return f"{slug}_{token}_sync" if token else f"{slug}_sync"


def _legacy_pipeline_dag_id(instance_key: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in instance_key.strip())
    collapsed = "_".join(part for part in normalized.split("_") if part)
    return f"pnp_pipeline__{collapsed or 'instance'}"


def _resolve_generated_dags_dir() -> Path:
    resolved = Path(__file__).resolve()
    repo_root_candidate = next(
        (parent for parent in resolved.parents if (parent / "pipelines" / "airflow" / "dags").exists()),
        None,
    )
    candidates = [Path("/app/pipelines/airflow/dags/generated")]
    if repo_root_candidate is not None:
        candidates.append(repo_root_candidate / "pipelines" / "airflow" / "dags" / "generated")
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue
    raise RuntimeError("PNP generated DAG directory is not writable")


def _dag_file_path(instance_key: str, pipeline_id: str | None = None) -> Path:
    return _resolve_generated_dags_dir() / f"{build_pipeline_dag_id(instance_key, pipeline_id)}.py"


def _legacy_dag_file_path(instance_key: str) -> Path:
    return _resolve_generated_dags_dir() / f"{_legacy_pipeline_dag_id(instance_key)}.py"


def _normalize_airflow_schedule(schedule: str | None, *, is_active: bool) -> str | None:
    if not is_active or not schedule or not schedule.strip():
        return None
    normalized = schedule.strip()
    if not croniter.is_valid(normalized):
        return None
    return normalized


def render_pipeline_dag_file(*, dag_id: str, instance_key: str, pipeline_id: str, schedule: str | None, is_active: bool) -> str:
    normalized_schedule = _normalize_airflow_schedule(schedule, is_active=is_active)
    schedule_literal = repr(normalized_schedule) if normalized_schedule else "None"
    return f"""from dataif_pipelines.airflow.pnp_pipeline_factory import build_pipeline_dag


dag = build_pipeline_dag(
    dag_id={dag_id!r},
    pipeline_id={pipeline_id!r},
    instance_key={instance_key!r},
    schedule={schedule_literal},
)
"""


def provision_pipeline_dag(*, pipeline_id: str, instance_key: str, schedule: str | None, is_active: bool) -> str:
    dag_id = build_pipeline_dag_id(instance_key, pipeline_id)
    legacy_target = _legacy_dag_file_path(instance_key)
    if legacy_target.exists():
        legacy_target.unlink()
    target = _dag_file_path(instance_key, pipeline_id)
    target.write_text(
        render_pipeline_dag_file(
            dag_id=dag_id,
            pipeline_id=pipeline_id,
            instance_key=instance_key,
            schedule=schedule,
            is_active=is_active,
        ),
        encoding="utf-8",
    )
    if not target.exists():
        raise RuntimeError(f"Failed to provision DAG file for pipeline {instance_key}")
    return dag_id


def generated_pipeline_dag_path(*, instance_key: str, pipeline_id: str | None = None) -> Path:
    return _dag_file_path(instance_key, pipeline_id)


def remove_pipeline_dag(*, instance_key: str, pipeline_id: str | None = None) -> str:
    dag_id = build_pipeline_dag_id(instance_key, pipeline_id)
    target = _dag_file_path(instance_key, pipeline_id)
    if target.exists():
        target.unlink()
    legacy_target = _legacy_dag_file_path(instance_key)
    if legacy_target.exists():
        legacy_target.unlink()
    return dag_id
