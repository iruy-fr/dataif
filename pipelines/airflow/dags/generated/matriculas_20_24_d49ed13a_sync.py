from dataif_pipelines.airflow.pnp_pipeline_factory import build_pipeline_dag


dag = build_pipeline_dag(
    dag_id='matriculas_20_24_d49ed13a_sync',
    pipeline_id='d49ed13a-e636-428b-aa9b-981652571ff2',
    instance_key='pnp_pipe_pnp_matriculas_20_24',
    schedule=None,
)
