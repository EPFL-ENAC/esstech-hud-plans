from api.models.auth import User
from api.services.auth import get_current_user
from fastapi import APIRouter, Depends

router = APIRouter()


@router.post("/submit")
def submit_workflow(
    current_user: User = Depends(get_current_user),
):
    pass


@router.get("/list")
def list_workflows(
    current_user: User = Depends(get_current_user),
):
    pass


@router.get("/status/{workflow_id}")
def get_workflow_status(
    workflow_id: str,
    current_user: User = Depends(get_current_user),
):
    pass


@router.get("/result/{workflow_id}")
def get_workflow_result(
    workflow_id: str,
    current_user: User = Depends(get_current_user),
):
    pass
