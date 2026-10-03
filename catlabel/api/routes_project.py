import json
from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from ..core.database import engine
from ..core.resource_limits import MAX_UPLOAD_BYTES
from ..services import projects as project_service
from ..services.projects import (
    MAX_TREE_DEPTH,
    MAX_TREE_NODES,
    CategoryCreate,
    CategoryUpdate,
    ProjectCreate,
    ProjectServiceError,
    ProjectUpdate,
    _delete_category_recursive,
    _export_tree,
    _import_tree,
    _project_detail,
    _require_category,
    _revision_error,
    _validate_import_tree,
    _validated_name,
)

router = APIRouter(tags=["Project"])
_project_write_lock = project_service._project_write_lock

__all__ = [
    "router",
    "ProjectCreate",
    "ProjectUpdate",
    "CategoryCreate",
    "CategoryUpdate",
    "MAX_TREE_NODES",
    "MAX_TREE_DEPTH",
    "_project_write_lock",
    "_validated_name",
    "_require_category",
    "_project_detail",
    "_revision_error",
    "_delete_category_recursive",
    "_export_tree",
    "_validate_import_tree",
    "_import_tree",
]

T = TypeVar("T")


def _service_result(operation: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    try:
        return operation(*args, **kwargs)
    except ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/projects")
def create_project(project: ProjectCreate):
    return _service_result(
        project_service.create_project,
        project,
        db_engine=engine,
        _write_lock=_project_write_lock,
    )


@router.get("/api/projects")
def list_projects():
    return project_service.list_projects(db_engine=engine)


@router.get("/api/projects/summaries")
def list_project_summaries(
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    after_id: Annotated[int, Query(ge=0)] = 0,
):
    return project_service.list_project_summaries(limit, after_id, db_engine=engine)


@router.get("/api/projects/{project_id}")
def get_project(project_id: int):
    project = _service_result(project_service.get_project, project_id, db_engine=engine)
    return _project_detail(project)


@router.put("/api/projects/{project_id}")
def update_project(project_id: int, project_update: ProjectUpdate):
    return _service_result(
        project_service.update_project,
        project_id,
        project_update,
        db_engine=engine,
        _write_lock=_project_write_lock,
    )


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    return _service_result(
        project_service.delete_project,
        project_id,
        db_engine=engine,
        _write_lock=_project_write_lock,
    )


@router.get("/api/categories")
def list_categories():
    return project_service.list_categories(db_engine=engine)


@router.post("/api/categories")
def create_category(cat: CategoryCreate):
    return _service_result(
        project_service.create_category,
        cat,
        db_engine=engine,
        _write_lock=_project_write_lock,
    )


@router.put("/api/categories/{cat_id}")
def update_category(cat_id: int, cat_update: CategoryUpdate):
    return _service_result(
        project_service.update_category,
        cat_id,
        cat_update,
        db_engine=engine,
        max_tree_nodes=MAX_TREE_NODES,
        _write_lock=_project_write_lock,
    )


@router.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int):
    return _service_result(
        project_service.delete_category,
        cat_id,
        db_engine=engine,
        max_tree_nodes=MAX_TREE_NODES,
        _write_lock=_project_write_lock,
    )


@router.get("/api/export")
def export_filesystem(category_id: int | None = None):
    return _service_result(
        project_service.export_filesystem,
        category_id,
        db_engine=engine,
        max_tree_nodes=MAX_TREE_NODES,
        max_tree_depth=MAX_TREE_DEPTH,
    )


@router.post("/api/import")
async def import_filesystem(
    file: Annotated[UploadFile, File()], target_category_id: int | None = None
):
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413, detail="Import file exceeds upload limit."
            )
        try:
            payload: object = json.loads(content)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise HTTPException(status_code=400, detail="Invalid export JSON.") from exc
        return _service_result(
            project_service.import_filesystem,
            payload,
            target_category_id,
            db_engine=engine,
            max_tree_nodes=MAX_TREE_NODES,
            max_tree_depth=MAX_TREE_DEPTH,
        )
    finally:
        await file.close()
