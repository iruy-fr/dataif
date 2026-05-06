from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from dataif_pipelines.connectors.base.types import RunContext
from dataif_pipelines.connectors.nilo_pecanha.config import load_config
from dataif_pipelines.connectors.nilo_pecanha.connector import NiloPecanhaConnector
from dataif_pipelines.repositories import pnp_raw_repository
from dataif_pipelines.services import (
    pnp_curated_service,
    pnp_quality_service,
    pnp_raw_ingestion_service,
    pnp_staging_service,
    powerbi_catalog_service,
)


def _warehouse_dsn() -> str:
    dsn = os.getenv("WAREHOUSE_DSN")
    if not dsn:
        raise RuntimeError("WAREHOUSE_DSN is required")
    return dsn


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _step_details(
    *,
    dag_id: str,
    dag_run_id: str,
    task_id: str,
    logical_date: str | None,
    map_index: int | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details = {
        "airflow_dag_id": dag_id,
        "airflow_dag_run_id": dag_run_id,
        "airflow_task_id": task_id,
        "logical_date": logical_date,
    }
    if map_index is not None and map_index >= 0:
        details["map_index"] = map_index
    if extra:
        details.update(extra)
    return details


def _start_step(
    *,
    run_id: str,
    instance_key: str | None,
    dag_id: str,
    dag_run_id: str,
    task_id: str,
    logical_date: str | None,
    map_index: int | None,
    extra: dict[str, Any] | None = None,
) -> None:
    pnp_raw_repository.register_run_step_start(
        _warehouse_dsn(),
        run_id=run_id,
        instance_key=instance_key,
        airflow_task_id=task_id,
        map_index=map_index,
        status="running",
        details=_step_details(
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            extra=extra,
        ),
        started_at=_utcnow(),
    )


def _finish_step(
    *,
    run_id: str,
    instance_key: str | None,
    dag_id: str,
    dag_run_id: str,
    task_id: str,
    logical_date: str | None,
    map_index: int | None,
    status: str,
    records_affected: int | None,
    error_message: str | None,
    extra: dict[str, Any] | None = None,
) -> None:
    details = _step_details(
        dag_id=dag_id,
        dag_run_id=dag_run_id,
        task_id=task_id,
        logical_date=logical_date,
        map_index=map_index,
        extra=extra,
    )
    pnp_raw_repository.finish_run_step(
        _warehouse_dsn(),
        run_id=run_id,
        airflow_task_id=task_id,
        map_index=map_index,
        status=status,
        finished_at=_utcnow(),
        records_affected=records_affected,
        error_message=error_message,
        details=details,
    )
    pnp_raw_repository.append_run_package(
        _warehouse_dsn(),
        run_id=run_id,
        instance_key=instance_key,
        airflow_dag_id=dag_id,
        airflow_dag_run_id=dag_run_id,
        airflow_task_id=task_id,
        package_type="step_result",
        package_name=task_id,
        package_status=status,
        records_affected=records_affected,
        payload={
            **details,
            "status": status,
            "records_affected": records_affected,
            "error_message": error_message,
        },
    )


def resolve_pipeline_targets(
    *,
    dag_id: str,
    dag_run_id: str,
    logical_date: str | None,
    requested_instance_key: str | None,
    requested_operation: str | None,
    requested_by: str,
) -> list[dict[str, Any]]:
    operation = str(requested_operation or "sync").strip().lower() or "sync"
    if operation not in {"sync", "validate"}:
        raise RuntimeError(f"Unsupported operation for pnp_pipeline: {operation}")

    if requested_instance_key:
        instance_key = requested_instance_key.strip()
        if not instance_key:
            raise RuntimeError("instance_key cannot be blank")
        return [
            {
                "instance_key": instance_key,
                "operation": operation,
                "trigger_mode": f"airflow_manual_{operation}",
                "requested_by": requested_by,
                "dag_id": dag_id,
                "dag_run_id": dag_run_id,
                "logical_date": logical_date,
            }
        ]

    if operation == "validate":
        raise RuntimeError("Manual validation requires an explicit instance_key")

    from croniter import croniter

    now = datetime.fromisoformat(logical_date) if logical_date else _utcnow()
    rows = pnp_raw_repository.list_active_instance_schedules(_warehouse_dsn())
    targets: list[dict[str, Any]] = []
    for row in rows:
        schedule = str(row.get("schedule") or "").strip()
        if not schedule or bool(row.get("has_running_run")):
            continue
        last_started_at = row.get("last_started_at")
        if last_started_at is None:
            due = True
        else:
            due = croniter(schedule, last_started_at).get_next(datetime) <= now
        if not due:
            continue
        targets.append(
            {
                "instance_key": str(row["instance_key"]),
                "operation": "sync",
                "trigger_mode": "airflow_scheduled_sync",
                "requested_by": requested_by,
                "dag_id": dag_id,
                "dag_run_id": dag_run_id,
                "logical_date": logical_date,
            }
        )
    return targets


def register_pipeline_run(
    target: dict[str, Any],
    *,
    task_id: str,
    map_index: int | None,
) -> dict[str, Any]:
    instance_key = str(target["instance_key"])
    pipeline_id = str(target.get("pipeline_id") or "")
    dag_id = str(target["dag_id"])
    dag_run_id = str(target["dag_run_id"])
    logical_date = target.get("logical_date")
    operation = str(target.get("operation") or "sync")
    trigger_mode = str(target.get("trigger_mode") or f"airflow_manual_{operation}")
    requested_by = str(target.get("requested_by") or f"airflow.{dag_id}")
    run_id = str(uuid.uuid4())
    started_at = _utcnow()

    pnp_raw_repository.register_run_start(
        _warehouse_dsn(),
        run_id=run_id,
        instance_key=instance_key,
        airflow_dag_id=dag_id,
        airflow_dag_run_id=dag_run_id,
        status="running",
        trigger_mode=trigger_mode,
        requested_by=requested_by,
        logical_date=datetime.fromisoformat(logical_date) if logical_date else started_at,
        started_at=started_at,
    )
    _start_step(
        run_id=run_id,
        instance_key=instance_key,
        dag_id=dag_id,
        dag_run_id=dag_run_id,
        task_id=task_id,
        logical_date=logical_date,
        map_index=map_index,
        extra={"operation": operation, "trigger_mode": trigger_mode},
    )
    result = {
        "run_id": run_id,
        "instance_key": instance_key,
        "pipeline_id": pipeline_id,
        "operation": operation,
        "dag_id": dag_id,
        "dag_run_id": dag_run_id,
        "logical_date": logical_date,
        "requested_by": requested_by,
        "trigger_mode": trigger_mode,
        "started_at": started_at.isoformat(),
    }
    _finish_step(
        run_id=run_id,
        instance_key=instance_key,
        dag_id=dag_id,
        dag_run_id=dag_run_id,
        task_id=task_id,
        logical_date=logical_date,
        map_index=map_index,
        status="success",
        records_affected=1,
        error_message=None,
        extra=result,
    )
    return result


def load_instance_config(
    run_ref: dict[str, Any],
    *,
    task_id: str,
    map_index: int | None,
) -> dict[str, Any]:
    run_id = str(run_ref["run_id"])
    instance_key = str(run_ref["instance_key"])
    dag_id = str(run_ref["dag_id"])
    dag_run_id = str(run_ref["dag_run_id"])
    logical_date = run_ref.get("logical_date")
    _start_step(
        run_id=run_id,
        instance_key=instance_key,
        dag_id=dag_id,
        dag_run_id=dag_run_id,
        task_id=task_id,
        logical_date=logical_date,
        map_index=map_index,
        extra={"operation": run_ref.get("operation")},
    )
    try:
        config = pnp_raw_repository.load_instance_runtime_config(_warehouse_dsn(), instance_key=instance_key)
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="success",
            records_affected=len(config.get("selection_rows") or []),
            error_message=None,
            extra={
                "operation": run_ref.get("operation"),
                "page_url": config.get("page_url"),
                "selection_count": len(config.get("selection_rows") or []),
                "connection_key": config.get("connection_key"),
            },
        )
        return config
    except Exception as exc:
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="failed",
            records_affected=0,
            error_message=str(exc),
            extra={"operation": run_ref.get("operation")},
        )
        raise


def resolve_catalog(
    run_ref: dict[str, Any],
    instance_config: dict[str, Any],
    *,
    task_id: str,
    map_index: int | None,
) -> dict[str, Any]:
    run_id = str(run_ref["run_id"])
    instance_key = str(run_ref["instance_key"])
    dag_id = str(run_ref["dag_id"])
    dag_run_id = str(run_ref["dag_run_id"])
    logical_date = run_ref.get("logical_date")
    _start_step(
        run_id=run_id,
        instance_key=instance_key,
        dag_id=dag_id,
        dag_run_id=dag_run_id,
        task_id=task_id,
        logical_date=logical_date,
        map_index=map_index,
        extra={"operation": run_ref.get("operation")},
    )
    try:
        config = load_config()
        client = powerbi_catalog_service.create_powerbi_client(
            page_url=str(instance_config["page_url"]),
            timeout_seconds=config.timeout_seconds,
        )
        selection = powerbi_catalog_service.resolve_catalog_selection(
            client=client,
            request_params=dict(instance_config["request_params"]),
        )
        catalog_rows = powerbi_catalog_service.build_catalog_entry_rows(run_id=run_id, selection=selection)
        selection_rows = powerbi_catalog_service.build_run_selection_rows(run_id=run_id, selection=selection)
        pnp_raw_ingestion_service.upsert_raw_metadata(
            _warehouse_dsn(),
            pending_assets=[],
            pending_catalog_entries=catalog_rows,
            pending_run_selection=selection_rows,
            pending_downloads=[],
            write_legacy=False,
            include_download_columns=False,
        )
        result = {
            "operation": run_ref.get("operation"),
            "catalog_entry_count": len(catalog_rows),
            "selected_download_count": len(selection_rows),
            "selection_source": selection.selection_source,
            "visual_id": selection.context.visual_id,
            "visual_type": selection.context.visual_type,
            "section_display_name": selection.context.section_display_name,
        }
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="success",
            records_affected=len(selection_rows),
            error_message=None,
            extra=result,
        )
        return result
    except Exception as exc:
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="failed",
            records_affected=0,
            error_message=str(exc),
            extra={"operation": run_ref.get("operation")},
        )
        raise


def sync_raw(
    run_ref: dict[str, Any],
    instance_config: dict[str, Any],
    *,
    task_id: str,
    map_index: int | None,
) -> dict[str, Any]:
    run_id = str(run_ref["run_id"])
    instance_key = str(run_ref["instance_key"])
    dag_id = str(run_ref["dag_id"])
    dag_run_id = str(run_ref["dag_run_id"])
    logical_date = run_ref.get("logical_date")
    operation = str(run_ref.get("operation") or "sync")
    _start_step(
        run_id=run_id,
        instance_key=instance_key,
        dag_id=dag_id,
        dag_run_id=dag_run_id,
        task_id=task_id,
        logical_date=logical_date,
        map_index=map_index,
        extra={"operation": operation},
    )
    if operation != "sync":
        result = {"operation": operation, "skipped": True, "reason": "validate_only"}
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="success",
            records_affected=0,
            error_message=None,
            extra=result,
        )
        return result
    try:
        config = load_config()
        connector = NiloPecanhaConnector(dsn=_warehouse_dsn(), config=config)
        run_context = RunContext(
            run_id=run_id,
            started_at=_utcnow(),
            source_url=str(instance_config["page_url"]),
        )
        loaded_count = connector.extract_and_load_raw(run_context, instance_key=instance_key)
        result = {
            "operation": operation,
            "loaded_count": loaded_count,
            "runtime": connector.runtime_stats(),
        }
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="success",
            records_affected=loaded_count,
            error_message=None,
            extra=result,
        )
        return result
    except Exception as exc:
        pnp_raw_repository.mark_run_downloads_failed(
            _warehouse_dsn(),
            run_id=run_id,
            error_message=str(exc),
        )
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="failed",
            records_affected=0,
            error_message=str(exc),
            extra={"operation": operation},
        )
        raise


def materialize_staging(
    run_ref: dict[str, Any],
    *,
    task_id: str,
    map_index: int | None,
) -> dict[str, Any]:
    run_id = str(run_ref["run_id"])
    instance_key = str(run_ref["instance_key"])
    dag_id = str(run_ref["dag_id"])
    dag_run_id = str(run_ref["dag_run_id"])
    logical_date = run_ref.get("logical_date")
    operation = str(run_ref.get("operation") or "sync")
    _start_step(
        run_id=run_id,
        instance_key=instance_key,
        dag_id=dag_id,
        dag_run_id=dag_run_id,
        task_id=task_id,
        logical_date=logical_date,
        map_index=map_index,
        extra={"operation": operation},
    )
    if operation != "sync":
        result = {"operation": operation, "skipped": True, "reason": "validate_only"}
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="success",
            records_affected=0,
            error_message=None,
            extra=result,
        )
        return result
    try:
        result = pnp_staging_service.materialize_instance_staging(
            _warehouse_dsn(),
            run_id=run_id,
            instance_key=instance_key,
        )
        result["operation"] = operation
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="success",
            records_affected=int(result.get("deduplicated_record_count") or 0),
            error_message=None,
            extra=result,
        )
        return result
    except Exception as exc:
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="failed",
            records_affected=0,
            error_message=str(exc),
            extra={"operation": operation},
        )
        raise


def materialize_curated(
    run_ref: dict[str, Any],
    *,
    task_id: str,
    map_index: int | None,
) -> dict[str, Any]:
    run_id = str(run_ref["run_id"])
    instance_key = str(run_ref["instance_key"])
    dag_id = str(run_ref["dag_id"])
    dag_run_id = str(run_ref["dag_run_id"])
    logical_date = run_ref.get("logical_date")
    operation = str(run_ref.get("operation") or "sync")
    _start_step(
        run_id=run_id,
        instance_key=instance_key,
        dag_id=dag_id,
        dag_run_id=dag_run_id,
        task_id=task_id,
        logical_date=logical_date,
        map_index=map_index,
        extra={"operation": operation},
    )
    if operation != "sync":
        result = {"operation": operation, "skipped": True, "reason": "validate_only"}
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="success",
            records_affected=0,
            error_message=None,
            extra=result,
        )
        return result
    try:
        result = pnp_curated_service.materialize_instance_curated(
            _warehouse_dsn(),
            run_id=run_id,
            instance_key=instance_key,
        )
        result["operation"] = operation
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="success",
            records_affected=int(result.get("vanna_resumo_count") or 0),
            error_message=None,
            extra=result,
        )
        return result
    except Exception as exc:
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="failed",
            records_affected=0,
            error_message=str(exc),
            extra={"operation": operation},
        )
        raise


def run_quality_checks(
    run_ref: dict[str, Any],
    *,
    task_id: str,
    map_index: int | None,
) -> dict[str, Any]:
    run_id = str(run_ref["run_id"])
    instance_key = str(run_ref["instance_key"])
    dag_id = str(run_ref["dag_id"])
    dag_run_id = str(run_ref["dag_run_id"])
    logical_date = run_ref.get("logical_date")
    operation = str(run_ref.get("operation") or "sync")
    _start_step(
        run_id=run_id,
        instance_key=instance_key,
        dag_id=dag_id,
        dag_run_id=dag_run_id,
        task_id=task_id,
        logical_date=logical_date,
        map_index=map_index,
        extra={"operation": operation},
    )
    try:
        checks = pnp_quality_service.collect_run_checks(_warehouse_dsn(), run_id)
        checks["operation"] = operation
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="success",
            records_affected=int(checks.get("raw_count") or 0),
            error_message=None,
            extra=checks,
        )
        return checks
    except Exception as exc:
        _finish_step(
            run_id=run_id,
            instance_key=instance_key,
            dag_id=dag_id,
            dag_run_id=dag_run_id,
            task_id=task_id,
            logical_date=logical_date,
            map_index=map_index,
            status="failed",
            records_affected=0,
            error_message=str(exc),
            extra={"operation": operation},
        )
        raise


def finalize_run(
    run_ref: dict[str, Any],
    *,
    dag_status: str,
    task_states: dict[str, str],
    task_id: str,
    map_index: int | None,
    checks: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    run_id = str(run_ref["run_id"])
    instance_key = str(run_ref["instance_key"])
    dag_id = str(run_ref["dag_id"])
    dag_run_id = str(run_ref["dag_run_id"])
    logical_date = run_ref.get("logical_date")
    operation = str(run_ref.get("operation") or "sync")
    _start_step(
        run_id=run_id,
        instance_key=instance_key,
        dag_id=dag_id,
        dag_run_id=dag_run_id,
        task_id=task_id,
        logical_date=logical_date,
        map_index=map_index,
        extra={"dag_status": dag_status, "operation": operation},
    )
    resolved_checks = checks or pnp_quality_service.collect_run_checks(_warehouse_dsn(), run_id)
    failed_tasks = sorted(task_name for task_name, state in task_states.items() if state in {"failed", "upstream_failed"})
    final_status = "success" if dag_status == "success" and not failed_tasks else "failed"
    resolved_error = error_message
    if not resolved_error and failed_tasks:
        resolved_error = f"Airflow tasks failed: {', '.join(failed_tasks)}"

    pnp_raw_repository.finish_run(
        _warehouse_dsn(),
        run_id=run_id,
        status=final_status,
        catalog_entry_count=int(resolved_checks.get("catalog_entry_count") or 0),
        selected_download_count=int(resolved_checks.get("run_selection_count") or 0),
        downloaded_file_count=int(resolved_checks.get("download_count") or 0),
        raw_record_count=int(resolved_checks.get("raw_count") or 0),
        error_message=resolved_error,
        run_summary={
            "operation": operation,
            "checks": resolved_checks,
            "task_states": task_states,
            "dag_status": final_status,
        },
        finished_at=_utcnow(),
    )
    if final_status != "success":
        pnp_raw_repository.mark_run_downloads_failed(
            _warehouse_dsn(),
            run_id=run_id,
            error_message=resolved_error or "Run finished with failed Airflow tasks",
        )

    result = {
        "run_id": run_id,
        "operation": operation,
        "status": final_status,
        "error_message": resolved_error,
        "checks": resolved_checks,
        "task_states": task_states,
    }
    _finish_step(
        run_id=run_id,
        instance_key=instance_key,
        dag_id=dag_id,
        dag_run_id=dag_run_id,
        task_id=task_id,
        logical_date=logical_date,
        map_index=map_index,
        status="success",
        records_affected=int(resolved_checks.get("raw_count") or 0),
        error_message=None,
        extra=result,
    )
    return result
