from dataif_pipelines.airflow.pnp_pipeline_factory import build_pipeline_dag


dag = build_pipeline_dag(
    dag_id='matriculas_20_24_47e010f9_sync',
    pipeline_id='47e010f9-de3f-421a-983f-f44964a1085f',
    instance_key='pnp_pipe_matriculas_20_24',
    schedule=None,
)
