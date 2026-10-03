"""Project and category persistence operations."""

from __future__ import annotations

import json
import time
from threading import RLock
from typing import Annotated, Any, cast
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, update
from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from ..core.models import Category, Project
from .artifacts import ArtifactPin, ArtifactRecord
from .documents import normalize_document

MAX_TREE_NODES = 10_000
MAX_TREE_DEPTH = 64
_project_write_lock = RLock()
_MANAGED_ASSET_PREFIX = "catlabel://artifacts/"


class ProjectServiceError(Exception):
    """An operation error that an API or tool adapter can translate."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


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
        raise ProjectServiceError(400, "Name must contain 1 to 200 characters.")
    return name.strip()


def _require_category(category_id: int | None, session: Session) -> None:
    if category_id is not None and session.get(Category, category_id) is None:
        raise ProjectServiceError(400, "Category does not exist.")


def _project_detail(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "category_id": project.category_id,
        "canvas_state": json.loads(project.canvas_state_json),
        "revision": project.revision,
    }


def _validated_canvas_state(canvas_state: dict[str, Any]) -> dict[str, Any]:
    if "document_version" not in canvas_state:
        return canvas_state
    version = canvas_state["document_version"]
    if type(version) is not int or version != 1:
        raise ProjectServiceError(400, "Unsupported document version.")
    try:
        return normalize_document(canvas_state)
    except (RecursionError, TypeError, ValueError, ValidationError) as exc:
        raise ProjectServiceError(400, "Invalid canonical document.") from exc


def _sync_managed_assets(
    project: Project, canvas_state: dict[str, Any], session: Session
) -> None:
    if project.id is None:
        raise ProjectServiceError(400, "Project must be saved before pinning assets.")

    pending: list[object] = [canvas_state.get("items", [])]
    artifact_ids: dict[str, None] = {}
    while pending:
        element = pending.pop()
        if isinstance(element, list):
            pending.extend(cast(list[object], element))
            continue
        if not isinstance(element, dict):
            continue

        typed_element = cast(dict[str, Any], element)
        src = typed_element.get("src")
        if isinstance(src, str) and src.startswith(_MANAGED_ASSET_PREFIX):
            raw_id = src[len(_MANAGED_ASSET_PREFIX) :]
            try:
                artifact_id = str(UUID(raw_id))
            except (AttributeError, TypeError, ValueError) as exc:
                raise ProjectServiceError(
                    400, "Managed asset reference is invalid."
                ) from exc
            if artifact_id != raw_id:
                raise ProjectServiceError(400, "Managed asset reference is invalid.")
            artifact_ids[artifact_id] = None

        children = typed_element.get("children")
        if isinstance(children, dict):
            pending.append(cast(dict[str, Any], children))
        elif isinstance(children, list):
            pending.append(cast(list[object], children))

    ids = list(artifact_ids)
    records: list[ArtifactRecord] = []
    if ids:
        records = list(
            session.exec(
                select(ArtifactRecord).where(col(ArtifactRecord.id).in_(ids))
            ).all()
        )
    records_by_id: dict[str, ArtifactRecord] = {record.id: record for record in records}
    now = time.time()
    active_pin_ids: set[str] = set()
    if ids:
        active_pin_ids = {
            pin.artifact_id
            for pin in session.exec(
                select(ArtifactPin).where(col(ArtifactPin.artifact_id).in_(ids))
            ).all()
            if pin.expires_at is None or pin.expires_at > now
        }
    for artifact_id in ids:
        record = records_by_id.get(artifact_id)
        if record is None or (
            record.expires_at < now and artifact_id not in active_pin_ids
        ):
            raise ProjectServiceError(400, "Managed image asset is missing or expired.")
        if record.mime_type != "image/png":
            raise ProjectServiceError(400, "Managed asset must be an image/png.")

    owner = f"design:{project.id}"
    session.exec(delete(ArtifactPin).where(col(ArtifactPin.owner) == owner))
    session.add_all(
        ArtifactPin(owner=owner, artifact_id=artifact_id, expires_at=None)
        for artifact_id in ids
    )


def create_project(
    project: ProjectCreate,
    *,
    db_engine: Engine,
    _write_lock: Any | None = None,
) -> Project:
    name = _validated_name(project.name)
    if project.canvas_state is None:
        raise ProjectServiceError(400, "canvas_state must be an object.")
    canvas_state = _validated_canvas_state(project.canvas_state)
    with _write_lock_for_call(_write_lock), Session(db_engine) as session:
        _require_category(project.category_id, session)
        db_project = Project(
            name=name,
            category_id=project.category_id,
            canvas_state_json=json.dumps(canvas_state),
        )
        session.add(db_project)
        session.flush()
        _sync_managed_assets(db_project, canvas_state, session)
        session.commit()
        session.refresh(db_project)
        return db_project


def list_projects(*, db_engine: Engine) -> list[dict[str, Any]]:
    with Session(db_engine) as session:
        return [
            _project_detail(project) for project in session.exec(select(Project)).all()
        ]


def list_project_summaries(
    limit: int, after_id: int, *, db_engine: Engine
) -> dict[str, Any]:
    if (
        type(limit) is not int
        or not 1 <= limit <= 200
        or type(after_id) is not int
        or after_id < 0
    ):
        raise ProjectServiceError(
            400, "Listing requires limit 1..200 and a nonnegative integer cursor."
        )
    with Session(db_engine) as session:
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


def get_project(project_id: int, *, db_engine: Engine) -> Project:
    with Session(db_engine) as session:
        project = session.get(Project, project_id)
        if project is None:
            raise ProjectServiceError(404, "Project not found")
        return project


def get_project_document(project_id: int, *, db_engine: Engine) -> dict[str, Any]:
    return _project_detail(get_project(project_id, db_engine=db_engine))


def _revision_error(status_code: int, current_revision: int) -> ProjectServiceError:
    return ProjectServiceError(
        status_code,
        {
            "message": (
                "expected_revision is required."
                if status_code == 428
                else "Project changed. Reload it before saving."
            ),
            "current_revision": current_revision,
        },
    )


def update_project(
    project_id: int,
    project_update: ProjectUpdate,
    *,
    db_engine: Engine,
    _write_lock: Any | None = None,
) -> Project:
    with _write_lock_for_call(_write_lock), Session(db_engine) as session:
        db_project = session.get(Project, project_id)
        if db_project is None:
            raise ProjectServiceError(404, "Project not found")
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
                raise ProjectServiceError(400, "canvas_state must be an object.")
            canvas_state = _validated_canvas_state(project_update.canvas_state)
            values["canvas_state_json"] = json.dumps(canvas_state)
        else:
            canvas_state = None
        if not values:
            return db_project
        values["revision"] = expected_revision + 1
        result = session.exec(
            update(Project)
            .where(
                col(Project.id) == project_id,
                col(Project.revision) == expected_revision,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            session.rollback()
            current_project = session.get(Project, project_id, populate_existing=True)
            if current_project is None:
                raise ProjectServiceError(404, "Project not found")
            raise _revision_error(409, current_project.revision)
        if canvas_state is not None:
            _sync_managed_assets(db_project, canvas_state, session)
        session.commit()
        session.refresh(db_project)
        return db_project


def delete_project(
    project_id: int, *, db_engine: Engine, _write_lock: Any | None = None
) -> dict[str, str]:
    with _write_lock_for_call(_write_lock), Session(db_engine) as session:
        db_project = session.get(Project, project_id)
        if db_project is None:
            raise ProjectServiceError(404, "Project not found")
        assert db_project.id is not None
        session.exec(
            delete(ArtifactPin).where(
                col(ArtifactPin.owner) == f"design:{db_project.id}"
            )
        )
        session.delete(db_project)
        session.commit()
        return {"status": "deleted"}


def list_categories(*, db_engine: Engine) -> list[Category]:
    with Session(db_engine) as session:
        return list(session.exec(select(Category)).all())


def list_directory(category_id: int | None, *, db_engine: Engine) -> dict[str, Any]:
    with Session(db_engine) as session:
        categories = session.exec(
            select(Category).where(Category.parent_id == category_id)
        ).all()
        projects = session.exec(
            select(Project).where(Project.category_id == category_id)
        ).all()
        return {
            "sub_folders": [{"id": item.id, "name": item.name} for item in categories],
            "projects": [{"id": item.id, "name": item.name} for item in projects],
        }


def get_category(category_id: int, *, db_engine: Engine) -> Category:
    with Session(db_engine) as session:
        category = session.get(Category, category_id)
        if category is None:
            raise ProjectServiceError(404, "Category not found")
        return category


def create_category(
    category: CategoryCreate,
    *,
    db_engine: Engine,
    _write_lock: Any | None = None,
) -> Category:
    name = _validated_name(category.name)
    with _write_lock_for_call(_write_lock), Session(db_engine) as session:
        _require_category(category.parent_id, session)
        db_category = Category(name=name, parent_id=category.parent_id)
        session.add(db_category)
        session.commit()
        session.refresh(db_category)
        return db_category


def update_category(
    category_id: int,
    category_update: CategoryUpdate,
    *,
    db_engine: Engine,
    max_tree_nodes: int = MAX_TREE_NODES,
    _write_lock: Any | None = None,
) -> Category:
    with _write_lock_for_call(_write_lock), Session(db_engine) as session:
        db_category = session.get(Category, category_id)
        if db_category is None:
            raise ProjectServiceError(404, "Category not found")
        provided_fields = category_update.model_fields_set
        name = (
            _validated_name(category_update.name)
            if "name" in provided_fields
            else db_category.name
        )
        if "parent_id" in provided_fields:
            _require_category(category_update.parent_id, session)
            current_check_id = category_update.parent_id
            visited: set[int] = set()
            while current_check_id is not None:
                if current_check_id == category_id or current_check_id in visited:
                    raise ProjectServiceError(
                        400, "Circular category reference detected."
                    )
                if len(visited) >= max_tree_nodes:
                    raise ProjectServiceError(400, "Category tree exceeds node limit.")
                visited.add(current_check_id)
                check_category = session.get(Category, current_check_id)
                if check_category is None:
                    raise ProjectServiceError(400, "Category ancestor does not exist.")
                current_check_id = check_category.parent_id
            db_category.parent_id = category_update.parent_id
        db_category.name = name
        session.add(db_category)
        session.commit()
        session.refresh(db_category)
        return db_category


def _delete_category_recursive(
    category_id: int, session: Session, *, max_tree_nodes: int = MAX_TREE_NODES
) -> None:
    """Collect and validate the complete subtree before scheduling deletions."""
    root = session.get(Category, category_id)
    if root is None:
        raise ProjectServiceError(404, "Category not found")
    categories: list[Category] = []
    visited: set[int] = set()
    pending = [root]
    while pending:
        category = pending.pop()
        assert category.id is not None
        if category.id in visited:
            raise ProjectServiceError(400, "Circular category reference detected.")
        if len(visited) >= max_tree_nodes:
            raise ProjectServiceError(400, "Category tree exceeds node limit.")
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
            assert project.id is not None
            session.exec(
                delete(ArtifactPin).where(
                    col(ArtifactPin.owner) == f"design:{project.id}"
                )
            )
            session.delete(project)
        session.delete(category)


def delete_category(
    category_id: int,
    *,
    db_engine: Engine,
    max_tree_nodes: int = MAX_TREE_NODES,
    _write_lock: Any | None = None,
) -> dict[str, str]:
    with _write_lock_for_call(_write_lock), Session(db_engine) as session:
        _delete_category_recursive(category_id, session, max_tree_nodes=max_tree_nodes)
        session.commit()
        return {"status": "deleted"}


def _export_tree(
    category_id: int | None,
    session: Session,
    *,
    max_tree_nodes: int = MAX_TREE_NODES,
    max_tree_depth: int = MAX_TREE_DEPTH,
) -> dict[str, Any]:
    visited: set[int] = set()
    node_count = 0

    def export_node(current_id: int | None, depth: int) -> dict[str, Any]:
        nonlocal node_count
        node_count += 1
        if depth > max_tree_depth or node_count > max_tree_nodes:
            raise ProjectServiceError(400, "Category tree exceeds export limits.")
        name = "Root"
        if current_id is not None:
            if current_id in visited:
                raise ProjectServiceError(400, "Circular category reference detected.")
            visited.add(current_id)
            category = session.get(Category, current_id)
            if category is None:
                raise ProjectServiceError(404, "Category not found")
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
            if depth + 1 > max_tree_depth or node_count > max_tree_nodes:
                raise ProjectServiceError(400, "Category tree exceeds export limits.")
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
            raise ProjectServiceError(400, "Stored category tree is corrupt.")
    return result


def export_filesystem(
    category_id: int | None = None,
    *,
    db_engine: Engine,
    max_tree_nodes: int = MAX_TREE_NODES,
    max_tree_depth: int = MAX_TREE_DEPTH,
) -> dict[str, Any]:
    with Session(db_engine) as session:
        return {
            "catlabel_export_version": "1.0",
            "data": _export_tree(
                category_id,
                session,
                max_tree_nodes=max_tree_nodes,
                max_tree_depth=max_tree_depth,
            ),
        }


def _validate_import_tree(
    data: object,
    *,
    max_tree_nodes: int = MAX_TREE_NODES,
    max_tree_depth: int = MAX_TREE_DEPTH,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ProjectServiceError(400, "Export data must be a tree object.")
    root = cast(dict[str, Any], data).copy()
    pending: list[tuple[object, int]] = [(root, 0)]
    node_count = 0
    while pending:
        node, depth = pending.pop()
        node_count += 1
        if depth > max_tree_depth or node_count > max_tree_nodes:
            raise ProjectServiceError(400, "Import tree exceeds limits.")
        if not isinstance(node, dict):
            raise ProjectServiceError(400, "Import nodes must be objects.")
        typed_node = cast(dict[str, Any], node)
        _validated_name(typed_node.get("name"))
        if typed_node.get("type") == "category":
            children = typed_node.get("children")
            if not isinstance(children, list):
                raise ProjectServiceError(400, "Category children must be a list.")
            typed_children = cast(list[object], children)
            if len(typed_children) > max_tree_nodes - node_count:
                raise ProjectServiceError(400, "Import tree exceeds limits.")
            copied_children: list[object] = []
            for child in typed_children:
                if isinstance(child, dict):
                    copied_child = cast(dict[str, Any], child).copy()
                    copied_children.append(copied_child)
                    pending.append((copied_child, depth + 1))
                else:
                    copied_children.append(child)
                    pending.append((child, depth + 1))
            typed_node["children"] = copied_children
        elif typed_node.get("type") == "project":
            canvas_state = typed_node.get("canvas_state")
            if not isinstance(canvas_state, dict):
                raise ProjectServiceError(
                    400, "Project canvas_state must be an object."
                )
            typed_node["canvas_state"] = _validated_canvas_state(
                cast(dict[str, Any], canvas_state)
            )
        else:
            raise ProjectServiceError(400, "Unknown import node type.")
    return root


def _import_tree(node: dict[str, Any], parent_id: int | None, session: Session) -> None:
    name = _validated_name(node["name"])
    if node["type"] == "category":
        new_parent_id = parent_id
        if name != "Root" or parent_id is not None:
            new_category = Category(name=name, parent_id=parent_id)
            session.add(new_category)
            session.flush()
            new_parent_id = new_category.id
        for child in node["children"]:
            _import_tree(child, new_parent_id, session)
    else:
        canvas_state = cast(dict[str, Any], node["canvas_state"])
        project = Project(
            name=name,
            category_id=parent_id,
            canvas_state_json=json.dumps(canvas_state),
        )
        session.add(project)
        session.flush()
        _sync_managed_assets(project, canvas_state, session)


def import_tree(
    data: object,
    target_category_id: int | None,
    *,
    db_engine: Engine,
    max_tree_nodes: int = MAX_TREE_NODES,
    max_tree_depth: int = MAX_TREE_DEPTH,
) -> dict[str, str]:
    validated_data = _validate_import_tree(
        data,
        max_tree_nodes=max_tree_nodes,
        max_tree_depth=max_tree_depth,
    )
    try:
        with _project_write_lock, Session(db_engine) as session, session.begin():
            _require_category(target_category_id, session)
            _import_tree(validated_data, target_category_id, session)
    except ProjectServiceError:
        raise
    except Exception as exc:
        raise ProjectServiceError(400, "Unable to save imported projects.") from exc
    return {"status": "success"}


def import_filesystem(
    payload: object,
    target_category_id: int | None,
    *,
    db_engine: Engine,
    max_tree_nodes: int = MAX_TREE_NODES,
    max_tree_depth: int = MAX_TREE_DEPTH,
) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ProjectServiceError(400, "Invalid export file format.")
    typed_payload = cast(dict[str, Any], payload)
    if typed_payload.get("catlabel_export_version") != "1.0":
        raise ProjectServiceError(400, "Invalid export file format.")
    return import_tree(
        typed_payload.get("data"),
        target_category_id,
        db_engine=db_engine,
        max_tree_nodes=max_tree_nodes,
        max_tree_depth=max_tree_depth,
    )


def _write_lock_for_call(write_lock: Any | None) -> Any:
    return _project_write_lock if write_lock is None else write_lock
