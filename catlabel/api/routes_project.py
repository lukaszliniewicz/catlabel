import json
from threading import RLock
from typing import Annotated, Any, cast

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlmodel import Session, col, select

from ..core.database import engine
from ..core.models import Category, Project
from ..core.resource_limits import MAX_UPLOAD_BYTES

router = APIRouter(tags=["Project"])
MAX_TREE_NODES = 10_000
MAX_TREE_DEPTH = 64
_project_write_lock = RLock()


class ProjectCreate(BaseModel):
    name: str | None
    canvas_state: dict[str, Any] | None
    category_id: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    canvas_state: dict[str, Any] | None = None
    category_id: int | None = None
    expected_revision: Annotated[int, Field(strict=True, gt=0)] | None = None


class CategoryCreate(BaseModel):
    name: str | None
    parent_id: int | None = None


class CategoryUpdate(BaseModel):
    name: str | None = None
    parent_id: int | None = None


def _validated_name(name: object) -> str:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
        raise HTTPException(
            status_code=400, detail="Name must contain 1 to 200 characters."
        )
    return name.strip()


def _require_category(category_id: int | None, session: Session) -> None:
    if category_id is not None and session.get(Category, category_id) is None:
        raise HTTPException(status_code=400, detail="Category does not exist.")


def _project_detail(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "category_id": project.category_id,
        "canvas_state": json.loads(project.canvas_state_json),
        "revision": project.revision,
    }


@router.post("/api/projects")
def create_project(project: ProjectCreate):
    name = _validated_name(project.name)
    if project.canvas_state is None:
        raise HTTPException(status_code=400, detail="canvas_state must be an object.")
    with _project_write_lock, Session(engine) as session:
        _require_category(project.category_id, session)
        db_project = Project(
            name=name,
            category_id=project.category_id,
            canvas_state_json=json.dumps(project.canvas_state),
        )
        session.add(db_project)
        session.commit()
        session.refresh(db_project)
        return db_project


@router.get("/api/projects")
def list_projects():
    with Session(engine) as session:
        return [_project_detail(p) for p in session.exec(select(Project)).all()]


@router.get("/api/projects/summaries")
def list_project_summaries(
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    after_id: Annotated[int, Query(ge=0)] = 0,
):
    with Session(engine) as session:
        rows = session.exec(
            select(Project.id, Project.name, Project.category_id, Project.revision)
            .where(col(Project.id) > after_id)
            .order_by(col(Project.id))
            .limit(limit + 1)
        ).all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    projects: list[dict[str, int | str | None]] = []
    for project_id, name, category_id, revision in page_rows:
        assert project_id is not None
        projects.append(
            {
                "id": project_id,
                "name": name,
                "category_id": category_id,
                "revision": revision,
            }
        )

    next_after_id: int | None = None
    if has_more:
        next_after_id = page_rows[-1][0]
        assert next_after_id is not None
    return {"projects": projects, "next_after_id": next_after_id}


@router.get("/api/projects/{project_id}")
def get_project(project_id: int):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return _project_detail(project)


def _revision_error(status_code: int, current_revision: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "message": (
                "expected_revision is required."
                if status_code == 428
                else "Project changed. Reload it before saving."
            ),
            "current_revision": current_revision,
        },
    )


@router.put("/api/projects/{project_id}")
def update_project(project_id: int, project_update: ProjectUpdate):
    with _project_write_lock, Session(engine) as session:
        db_project = session.get(Project, project_id)
        if db_project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        expected_revision = project_update.expected_revision
        if expected_revision is None:
            raise _revision_error(428, db_project.revision)
        if expected_revision != db_project.revision:
            raise _revision_error(409, db_project.revision)

        provided_fields = project_update.model_fields_set
        values: dict[str, Any] = {}
        if "name" in provided_fields:
            values["name"] = _validated_name(project_update.name)
        if "category_id" in provided_fields:
            _require_category(project_update.category_id, session)
            values["category_id"] = project_update.category_id
        if "canvas_state" in provided_fields:
            if project_update.canvas_state is None:
                raise HTTPException(
                    status_code=400, detail="canvas_state must be an object."
                )
            values["canvas_state_json"] = json.dumps(project_update.canvas_state)
        if not values:
            return db_project
        values["revision"] = expected_revision + 1
        result = cast(
            CursorResult[Any],
            session.execute(
                update(Project)
                .where(
                    col(Project.id) == project_id,
                    col(Project.revision) == expected_revision,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            ),
        )
        if result.rowcount != 1:
            session.rollback()
            current_project = session.get(Project, project_id, populate_existing=True)
            if current_project is None:
                raise HTTPException(status_code=404, detail="Project not found")
            raise _revision_error(409, current_project.revision)
        session.commit()
        session.refresh(db_project)
        return db_project


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    with _project_write_lock, Session(engine) as session:
        db_project = session.get(Project, project_id)
        if db_project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        session.delete(db_project)
        session.commit()
        return {"status": "deleted"}


@router.get("/api/categories")
def list_categories():
    with Session(engine) as session:
        return session.exec(select(Category)).all()


@router.post("/api/categories")
def create_category(cat: CategoryCreate):
    name = _validated_name(cat.name)
    with _project_write_lock, Session(engine) as session:
        _require_category(cat.parent_id, session)
        db_cat = Category(name=name, parent_id=cat.parent_id)
        session.add(db_cat)
        session.commit()
        session.refresh(db_cat)
        return db_cat


@router.put("/api/categories/{cat_id}")
def update_category(cat_id: int, cat_update: CategoryUpdate):
    with _project_write_lock, Session(engine) as session:
        db_cat = session.get(Category, cat_id)
        if db_cat is None:
            raise HTTPException(status_code=404, detail="Category not found")
        provided_fields = cat_update.model_fields_set
        name = (
            _validated_name(cat_update.name)
            if "name" in provided_fields
            else db_cat.name
        )
        if "parent_id" in provided_fields:
            _require_category(cat_update.parent_id, session)
            current_check_id = cat_update.parent_id
            visited: set[int] = set()
            while current_check_id is not None:
                if current_check_id == cat_id or current_check_id in visited:
                    raise HTTPException(
                        status_code=400, detail="Circular category reference detected."
                    )
                if len(visited) >= MAX_TREE_NODES:
                    raise HTTPException(
                        status_code=400, detail="Category tree exceeds node limit."
                    )
                visited.add(current_check_id)
                check_cat = session.get(Category, current_check_id)
                if check_cat is None:
                    raise HTTPException(
                        status_code=400, detail="Category ancestor does not exist."
                    )
                current_check_id = check_cat.parent_id
            db_cat.parent_id = cat_update.parent_id
        db_cat.name = name
        session.add(db_cat)
        session.commit()
        session.refresh(db_cat)
        return db_cat


def _delete_category_recursive(cat_id: int, session: Session) -> None:
    """Collect and validate the complete subtree before scheduling any deletions."""
    root = session.get(Category, cat_id)
    if root is None:
        raise HTTPException(status_code=404, detail="Category not found")
    categories: list[Category] = []
    visited: set[int] = set()
    pending = [root]
    while pending:
        category = pending.pop()
        assert category.id is not None
        if category.id in visited:
            raise HTTPException(
                status_code=400, detail="Circular category reference detected."
            )
        if len(visited) >= MAX_TREE_NODES:
            raise HTTPException(
                status_code=400, detail="Category tree exceeds node limit."
            )
        visited.add(category.id)
        categories.append(category)
        pending.extend(
            session.exec(
                select(Category).where(Category.parent_id == category.id)
            ).all()
        )
    for category in reversed(categories):
        for project in session.exec(
            select(Project).where(Project.category_id == category.id)
        ).all():
            session.delete(project)
        session.delete(category)


@router.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int):
    with _project_write_lock, Session(engine) as session:
        _delete_category_recursive(cat_id, session)
        session.commit()
        return {"status": "deleted"}


def _export_tree(category_id: int | None, session: Session) -> dict[str, Any]:
    visited: set[int] = set()
    node_count = 0

    def export_node(current_id: int | None, depth: int) -> dict[str, Any]:
        nonlocal node_count
        node_count += 1
        if depth > MAX_TREE_DEPTH or node_count > MAX_TREE_NODES:
            raise HTTPException(
                status_code=400, detail="Category tree exceeds export limits."
            )
        name = "Root"
        if current_id is not None:
            if current_id in visited:
                raise HTTPException(
                    status_code=400, detail="Circular category reference detected."
                )
            visited.add(current_id)
            category = session.get(Category, current_id)
            if category is None:
                raise HTTPException(status_code=404, detail="Category not found")
            name = category.name
        children: list[dict[str, Any]] = []
        for category in session.exec(
            select(Category).where(Category.parent_id == current_id)
        ).all():
            children.append(export_node(category.id, depth + 1))
        for project in session.exec(
            select(Project).where(Project.category_id == current_id)
        ).all():
            node_count += 1
            if depth + 1 > MAX_TREE_DEPTH or node_count > MAX_TREE_NODES:
                raise HTTPException(
                    status_code=400, detail="Category tree exceeds export limits."
                )
            children.append(
                {
                    "type": "project",
                    "name": project.name,
                    "canvas_state": json.loads(project.canvas_state_json),
                }
            )
        return {"type": "category", "name": name, "children": children}

    result = export_node(category_id, 0)
    if category_id is None:
        persisted_category_ids = set(session.exec(select(Category.id)).all())
        project_category_ids = session.exec(select(Project.category_id)).all()
        if persisted_category_ids != visited or any(
            parent_id is not None and parent_id not in visited
            for parent_id in project_category_ids
        ):
            raise HTTPException(
                status_code=400, detail="Stored category tree is corrupt."
            )
    return result


@router.get("/api/export")
def export_filesystem(category_id: int | None = None):
    with Session(engine) as session:
        return {
            "catlabel_export_version": "1.0",
            "data": _export_tree(category_id, session),
        }


def _validate_import_tree(data: object) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400, detail="Export data must be a tree object."
        )
    root = cast(dict[str, Any], data)
    pending: list[tuple[object, int]] = [(root, 0)]
    node_count = 0
    while pending:
        node, depth = pending.pop()
        node_count += 1
        if depth > MAX_TREE_DEPTH or node_count > MAX_TREE_NODES:
            raise HTTPException(status_code=400, detail="Import tree exceeds limits.")
        if not isinstance(node, dict):
            raise HTTPException(status_code=400, detail="Import nodes must be objects.")
        _validated_name(node.get("name"))
        if node.get("type") == "category":
            children = node.get("children")
            if not isinstance(children, list):
                raise HTTPException(
                    status_code=400, detail="Category children must be a list."
                )
            if len(children) > MAX_TREE_NODES - node_count:
                raise HTTPException(
                    status_code=400, detail="Import tree exceeds limits."
                )
            pending.extend((child, depth + 1) for child in children)
        elif node.get("type") == "project":
            if not isinstance(node.get("canvas_state"), dict):
                raise HTTPException(
                    status_code=400, detail="Project canvas_state must be an object."
                )
        else:
            raise HTTPException(status_code=400, detail="Unknown import node type.")
    return root


def _import_tree(node: dict[str, Any], parent_id: int | None, session: Session) -> None:
    name = _validated_name(node["name"])
    if node["type"] == "category":
        new_parent_id = parent_id
        if name != "Root" or parent_id is not None:
            new_cat = Category(name=name, parent_id=parent_id)
            session.add(new_cat)
            session.flush()
            new_parent_id = new_cat.id
        for child in node["children"]:
            _import_tree(child, new_parent_id, session)
    else:
        session.add(
            Project(
                name=name,
                category_id=parent_id,
                canvas_state_json=json.dumps(node["canvas_state"]),
            )
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
        if (
            not isinstance(payload, dict)
            or payload.get("catlabel_export_version") != "1.0"
        ):
            raise HTTPException(status_code=400, detail="Invalid export file format.")
        data = _validate_import_tree(payload.get("data"))
        try:
            with _project_write_lock, Session(engine) as session, session.begin():
                _require_category(target_category_id, session)
                _import_tree(data, target_category_id, session)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail="Unable to save imported projects."
            ) from exc
        return {"status": "success"}
    finally:
        await file.close()
