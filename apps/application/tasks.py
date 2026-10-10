# coding=utf-8
from ops.celery import app


@app.task(name='application.run_evaluation', acks_late=False)
def run_evaluation(run_id: str):
    from application.evaluation.service import execute_run
    execute_run(run_id)
