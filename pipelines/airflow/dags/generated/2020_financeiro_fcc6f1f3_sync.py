from dataif_pipelines.airflow.pnp_pipeline_factory import build_pipeline_dag


dag = build_pipeline_dag(
    dag_id='2020_financeiro_fcc6f1f3_sync',
    pipeline_id='fcc6f1f3-ca8f-480e-bc7a-d48dcc8516ee',
    instance_key='pnp_pipe_pnp_2020_financeiro',
    schedule=None,
)
