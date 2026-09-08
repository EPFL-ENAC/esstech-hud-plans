import time
from uuid import UUID

from prefect import flow, get_run_logger
from prefect.deployments import arun_deployment

COUNTER_DEPLOYMENT = "counter/default"


@flow(name="counter")
def counter_flow(owner_id: UUID) -> None:
    run_logger = get_run_logger()
    for count in range(1, 61):
        time.sleep(1)
        run_logger.info("Counter: %d", count)


async def schedule_counter(owner_id: UUID) -> UUID:
    flow_run = await arun_deployment(
        name=COUNTER_DEPLOYMENT,
        parameters={"owner_id": str(owner_id)},
        timeout=0,
        as_subflow=False,
    )
    return flow_run.id
