from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context
from airflow.utils.trigger_rule import TriggerRule

from dataif_pipelines.orchestration import pnp_workflow


def _context_metadata() -> dict[str, object]:
    context = get_current_context()
    dag_run = context["dag_run"]
    task_instance = context["ti"]
    logical_date = context.get("logical_date")
    return {
        "dag_id": dag_run.dag_id,
        "dag_run_id": dag_run.run_id,
        "logical_date": logical_date.isoformat() if logical_date else None,
        "task_id": task_instance.task_id,
        "map_index": getattr(task_instance, "map_index", -1),
    }


def _task_states() -> tuple[str, dict[str, str]]:
    context = get_current_context()
    dag_run = context["dag_run"]
    current_task_id = context["ti"].task_id
    task_states: dict[str, str] = {}
    for task_instance in dag_run.get_task_instances():
        if task_instance.task_id == current_task_id:
            continue
        task_states[task_instance.task_id] = str(task_instance.state)
    failed = any(state in {"failed", "upstream_failed"} for state in task_states.values())
    return ("failed" if failed else "success", task_states)


def build_pipeline_dag(*, dag_id: str, pipeline_id: str | None = None, instance_key: str, schedule: str | None):
    @dag(
        dag_id=dag_id,
        start_date=datetime(2025, 1, 1),
        schedule=schedule,
        catchup=False,
        max_active_runs=1,
        default_args={
            "owner": "dataif",
            "depends_on_past": False,
            "retries": 1,
            "retry_delay": timedelta(minutes=5),
        },
        tags=["dataif", "governo", "nilo_pecanha", "pnp", "pipeline", instance_key, *( [pipeline_id] if pipeline_id else [] )],
    )
    def _build():
        @task
        def register_run() -> dict[str, object]:
            context = get_current_context()
            dag_run = context["dag_run"]
            conf = getattr(dag_run, "conf", None) or {}
            metadata = _context_metadata()
            operation = str(conf.get("operation") or "sync").strip().lower() or "sync"
            trigger_origin = "manual" if conf else "scheduled"
            return pnp_workflow.register_pipeline_run(
                {
                    "instance_key": instance_key,
                    "pipeline_id": pipeline_id,
                    "operation": operation,
                    "trigger_mode": f"airflow_{trigger_origin}_{operation}",
                    "requested_by": str(conf.get("requested_by") or f"airflow.{metadata['dag_id']}"),
                    "dag_id": str(metadata["dag_id"]),
                    "dag_run_id": str(metadata["dag_run_id"]),
                    "logical_date": metadata["logical_date"],
                },
                task_id=str(metadata["task_id"]),
                map_index=int(metadata["map_index"]),
            )

        @task
        def load_instance_config(run_ref: dict[str, object]) -> dict[str, object]:
            metadata = _context_metadata()
            return pnp_workflow.load_instance_config(
                run_ref,
                task_id=str(metadata["task_id"]),
                map_index=int(metadata["map_index"]),
            )

        @task
        def resolve_powerbi_catalog(run_ref: dict[str, object], instance_config: dict[str, object]) -> dict[str, object]:
            metadata = _context_metadata()
            return pnp_workflow.resolve_catalog(
                run_ref,
                instance_config,
                task_id=str(metadata["task_id"]),
                map_index=int(metadata["map_index"]),
            )

        @task.branch
        def select_execution_path(run_ref: dict[str, object]) -> str:
            operation = str(run_ref.get("operation") or "sync").strip().lower()
            if operation == "validate":
                return "finalize_run"
            return "extract_raw"

        @task
        def extract_raw(run_ref: dict[str, object], instance_config: dict[str, object]) -> dict[str, object]:
            metadata = _context_metadata()
            return pnp_workflow.sync_raw(
                run_ref,
                instance_config,
                task_id=str(metadata["task_id"]),
                map_index=int(metadata["map_index"]),
            )

        @task
        def materialize_staging(run_ref: dict[str, object]) -> dict[str, object]:
            metadata = _context_metadata()
            return pnp_workflow.materialize_staging(
                run_ref,
                task_id=str(metadata["task_id"]),
                map_index=int(metadata["map_index"]),
            )

        @task
        def build_curated_views(run_ref: dict[str, object]) -> dict[str, object]:
            metadata = _context_metadata()
            return pnp_workflow.materialize_curated(
                run_ref,
                task_id=str(metadata["task_id"]),
                map_index=int(metadata["map_index"]),
            )

        @task
        def run_quality_checks(run_ref: dict[str, object]) -> dict[str, object]:
            metadata = _context_metadata()
            return pnp_workflow.run_quality_checks(
                run_ref,
                task_id=str(metadata["task_id"]),
                map_index=int(metadata["map_index"]),
            )

        @task(trigger_rule=TriggerRule.ALL_DONE)
        def finalize_run(run_ref: dict[str, object]) -> dict[str, object]:
            metadata = _context_metadata()
            dag_status, task_states = _task_states()
            return pnp_workflow.finalize_run(
                run_ref,
                dag_status=dag_status,
                task_states=task_states,
                task_id=str(metadata["task_id"]),
                map_index=int(metadata["map_index"]),
            )

        run_ref = register_run()
        instance_config = load_instance_config(run_ref)
        catalog = resolve_powerbi_catalog(run_ref, instance_config)
        execution_path = select_execution_path(run_ref)
        raw = extract_raw(run_ref, instance_config)
        staging = materialize_staging(run_ref)
        curated = build_curated_views(run_ref)
        quality = run_quality_checks(run_ref)
        final = finalize_run(run_ref)

        run_ref >> instance_config >> catalog >> execution_path
        execution_path >> raw >> staging >> curated >> quality >> final
        execution_path >> final

    return _build()
