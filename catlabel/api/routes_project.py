import json
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlmodel import Session, select

from ..core.database import engine
from ..core.models import Category, Project

router = APIRouter(tags=["Project"])

class ProjectCreate(BaseModel):
    name: str
    canvas_state: Dict[str, Any]
    category_id: Optional[int] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    canvas_state: Optional[Dict[str, Any]] = None
    category_id: Optional[int] = None

class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None

def _provided_model_fields(model):
    if hasattr(model, "model_fields_set"):
        return set(model.model_fields_set)
    return set(getattr(model, "__fields_set__", set()))

@router.post("/api/projects")
def create_project(project: ProjectCreate):
    with Session(engine) as session:
        db_project = Project(
            name=project.name,
            category_id=project.category_id,
            canvas_state_json=json.dumps(project.canvas_state)
        )
        session.add(db_project)
        session.commit()
        session.refresh(db_project)
        return db_project

@router.get("/api/projects")
def list_projects():
    with Session(engine) as session:
        projects = session.exec(select(Project)).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "category_id": p.category_id,
                "canvas_state": json.loads(p.canvas_state_json)
            }
            for p in projects
        ]

@router.put("/api/projects/{project_id}")
def update_project(project_id: int, project_update: ProjectUpdate):
    with Session(engine) as session:
        db_project = session.get(Project, project_id)
        if not db_project:
            raise HTTPException(status_code=404, detail="Project not found")

        provided_fields = _provided_model_fields(project_update)

        if "name" in provided_fields and project_update.name is not None:
            db_project.name = project_update.name
        if "category_id" in provided_fields:
            db_project.category_id = project_update.category_id
        if "canvas_state" in provided_fields and project_update.canvas_state is not None:
            db_project.canvas_state_json = json.dumps(project_update.canvas_state)

        session.add(db_project)
        session.commit()
        session.refresh(db_project)
        return db_project

@router.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    with Session(engine) as session:
        db_project = session.get(Project, project_id)
        if not db_project:
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
    with Session(engine) as session:
        if cat.parent_id is not None:
            parent = session.get(Category, cat.parent_id)
            if not parent:
                raise HTTPException(status_code=400, detail="Parent category does not exist.")
        db_cat = Category(name=cat.name, parent_id=cat.parent_id)
        session.add(db_cat)
        session.commit()
        session.refresh(db_cat)
        return db_cat

@router.put("/api/categories/{cat_id}")
def update_category(cat_id: int, cat_update: CategoryUpdate):
    with Session(engine) as session:
        db_cat = session.get(Category, cat_id)
        if not db_cat:
            raise HTTPException(status_code=404, detail="Category not found")

        provided_fields = _provided_model_fields(cat_update)

        if "name" in provided_fields and cat_update.name is not None:
            db_cat.name = cat_update.name
        if "parent_id" in provided_fields:
            new_parent_id = cat_update.parent_id
            if new_parent_id == cat_id:
                raise HTTPException(status_code=400, detail="Category cannot be its own parent")

            current_check_id = new_parent_id
            while current_check_id is not None:
                if current_check_id == cat_id:
                    raise HTTPException(status_code=400, detail="Circular reference detected. Cannot move a folder into its own subfolder.")
                check_cat = session.get(Category, current_check_id)
                current_check_id = check_cat.parent_id if check_cat else None

            db_cat.parent_id = new_parent_id

        session.add(db_cat)
        session.commit()
        session.refresh(db_cat)
        return db_cat

def _delete_category_recursive(cat_id: int, session: Session):
    children = session.exec(select(Category).where(Category.parent_id == cat_id)).all()
    for child in children:
        _delete_category_recursive(child.id, session)

    projects = session.exec(select(Project).where(Project.category_id == cat_id)).all()
    for proj in projects:
        session.delete(proj)

    cat = session.get(Category, cat_id)
    if cat:
        session.delete(cat)

@router.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int):
    with Session(engine) as session:
        _delete_category_recursive(cat_id, session)
        session.commit()
        return {"status": "deleted"}

def _export_tree(category_id: Optional[int], session: Session, visited: set = None) -> dict:
    if visited is None:
        visited = set()

    if category_id is not None:
        if category_id in visited:
            return {}
        visited.add(category_id)

    cat_node = {"type": "category", "name": "Root", "children": []}
    if category_id:
        cat = session.get(Category, category_id)
        if not cat:
            return {}
        cat_node["name"] = cat.name

    children_cats = session.exec(select(Category).where(Category.parent_id == category_id)).all()
    for c in children_cats:
        child_export = _export_tree(c.id, session, visited)
        if child_export:
            cat_node["children"].append(child_export)

    projects = session.exec(select(Project).where(Project.category_id == category_id)).all()
    for p in projects:
        cat_node["children"].append({
            "type": "project",
            "name": p.name,
            "canvas_state": json.loads(p.canvas_state_json)
        })

    return cat_node

@router.get("/api/export")
def export_filesystem(category_id: Optional[int] = None):
    with Session(engine) as session:
        data = _export_tree(category_id, session)
        return {"catlabel_export_version": "1.0", "data": data}

def _import_tree(node: dict, parent_id: Optional[int], session: Session):
    if node.get("type") == "category":
        new_parent_id = parent_id
        if node.get("name") != "Root" or parent_id is not None:
            new_cat = Category(name=node["name"], parent_id=parent_id)
            session.add(new_cat)
            session.commit()
            session.refresh(new_cat)
            new_parent_id = new_cat.id

        for child in node.get("children", []):
            _import_tree(child, new_parent_id, session)

    elif node.get("type") == "project":
        new_proj = Project(
            name=node["name"],
            category_id=parent_id,
            canvas_state_json=json.dumps(node["canvas_state"])
        )
        session.add(new_proj)
        session.commit()

@router.post("/api/import")
async def import_filesystem(file: UploadFile = File(...), target_category_id: Optional[int] = None):
    try:
        content = await file.read()
        payload = json.loads(content)
        if payload.get("catlabel_export_version") != "1.0":
            raise ValueError("Invalid export file format.")

        with Session(engine) as session:
            _import_tree(payload["data"], target_category_id, session)

        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
