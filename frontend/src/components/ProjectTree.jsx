import React, { useState, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useStore } from '../store';
import { useShallow } from 'zustand/react/shallow';
import { apiFetch } from '../utils/apiClient';
import {
  Folder, FolderOpen, FileText, Layers, MoreVertical,
  Download, Upload, Plus, Trash, Edit2, Save, Play
} from 'lucide-react';

// --- Inline Edit Component ---
const InlineEdit = ({ initialValue, onSave, onCancel }) => {
  const [val, setVal] = useState(initialValue || '');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const inputRef = React.useRef(null);

  React.useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, []);

  const submit = (finalVal) => {
    if (isSubmitting) return;
    setIsSubmitting(true);
    if (finalVal) onSave(finalVal);
    else onCancel();
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      submit(val.trim());
    } else if (e.key === 'Escape') {
      submit('');
    }
  };

  return (
    <input
      ref={inputRef}
      value={val}
      onChange={(e) => setVal(e.target.value)}
      onKeyDown={handleKeyDown}
      onBlur={() => submit(val.trim() && val !== initialValue ? val.trim() : '')}
      className="flex-1 bg-white dark:bg-neutral-900 border border-blue-500 px-1 py-0.5 text-xs outline-hidden text-neutral-900 dark:text-white rounded-xs w-full"
      onClick={e => e.stopPropagation()}
      onDragStart={e => e.preventDefault()}
    />
  );
};

// --- Recursive Tree Node Component ---
const TreeNode = ({ node, level, onImport, onMove }) => {
  const {
    currentProjectId, loadProject, updateProject, deleteProject,
    createCategory, updateCategory, deleteCategory, saveProject
  } = useStore(useShallow((state) => ({
    currentProjectId: state.currentProjectId, loadProject: state.loadProject,
    updateProject: state.updateProject, deleteProject: state.deleteProject,
    createCategory: state.createCategory, updateCategory: state.updateCategory,
    deleteCategory: state.deleteCategory, saveProject: state.saveProject
  })));

  const [isOpen, setIsOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuCoords, setMenuCoords] = useState({ top: null, bottom: null, left: 0, maxHeight: 320 });
  const [isEditing, setIsEditing] = useState(false);
  const [creating, setCreating] = useState(null); // { type: 'category'|'project' }
  const [isDragOver, setIsDragOver] = useState(false);

  const isFolder = node.type === 'category';
  const isLoaded = !isFolder && currentProjectId === node.id;
  const isBatch = !isFolder && (
    (node.canvas_state?.batchRecords?.length > 1) ||
    (node.canvas_state?.items?.some(i => i.pageIndex > 0))
  );

  const handleExport = async () => {
    setMenuOpen(false);
    try {
      const url = isFolder
        ? `/api/export?category_id=${node.id}`
        : `/api/export`;

      if (!isFolder) {
        const payload = { catlabel_export_version: "1.0", data: { type: "project", name: node.name, canvas_state: node.canvas_state } };
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `${node.name}.json`;
        link.click();
        return;
      }

      const res = await apiFetch(url);
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `${node.name}_export.json`;
      link.click();
    } catch (e) {
      console.error(e);
      alert("Failed to export.");
    }
  };

  const handleDragStart = (e) => {
    e.stopPropagation();
    e.dataTransfer.setData('application/catlabel-node', JSON.stringify({ id: node.id, type: node.type, parent_id: node.parent_id || node.category_id || null }));
  };

  const handleDragOver = (e) => {
    if (isFolder) {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(true);
    }
  };

  const handleDragLeave = (e) => {
    e.stopPropagation();
    setIsDragOver(false);
  };

  const handleDrop = (e) => {
    if (isFolder) {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);
      try {
        const dragged = JSON.parse(e.dataTransfer.getData('application/catlabel-node'));
        if (dragged.id === node.id && dragged.type === node.type) return;
        if (dragged.parent_id === node.id) return;
        onMove(dragged, node.id);
      } catch (_error) {}
    }
  };

  return (
    <div className="w-full">
      <div
        role="treeitem"
        tabIndex={0}
        aria-expanded={isFolder ? isOpen : undefined}
        aria-current={isLoaded ? 'page' : undefined}
        className={`flex items-center justify-between py-1.5 px-2 group cursor-pointer border border-transparent transition-colors
          ${isLoaded ? 'bg-blue-50 dark:bg-blue-900/30 border-blue-200 dark:border-blue-800' : isDragOver ? 'bg-blue-100 dark:bg-blue-900/50 border-blue-300 dark:border-blue-600' : 'hover:bg-neutral-100 dark:hover:bg-neutral-800'}
        `}
        style={{ paddingLeft: `${level * 12 + 8}px` }}
        draggable={!isEditing}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => {
          if (isFolder) setIsOpen(!isOpen);
          else loadProject(node);
        }}
        onKeyDown={(event) => {
          if (event.key !== 'Enter' && event.key !== ' ') return;
          event.preventDefault();
          if (isFolder) setIsOpen(!isOpen);
          else loadProject(node);
        }}
      >
        <div className="flex items-center gap-2 overflow-hidden">
          {isFolder ? (
            isOpen ? <FolderOpen size={14} className="text-blue-500 shrink-0" /> : <Folder size={14} className="text-blue-500 shrink-0" />
          ) : (
            isBatch ? <Layers size={14} className="text-purple-500 shrink-0" /> : <FileText size={14} className="text-neutral-500 shrink-0" />
          )}
          {isEditing ? (
            <InlineEdit
              initialValue={node.name}
              onSave={(val) => {
                isFolder ? updateCategory(node.id, val) : updateProject(node.id, val);
                setIsEditing(false);
              }}
              onCancel={() => setIsEditing(false)}
            />
          ) : (
            <span className={`text-xs truncate ${isLoaded ? 'font-bold text-blue-700 dark:text-blue-400' : 'text-neutral-700 dark:text-neutral-300'}`}>
              {node.name}
            </span>
          )}
        </div>

        <div onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            aria-label={`Actions for ${node.name}`}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={(e) => {
              if (menuOpen) {
                setMenuOpen(false);
                return;
              }

              const rect = e.currentTarget.getBoundingClientRect();
              const menuWidth = 192;
              const viewportPadding = 8;
              const estimatedMenuHeight = isFolder ? 300 : 220;
              const availableBelow = window.innerHeight - rect.bottom - viewportPadding;
              const availableAbove = rect.top - viewportPadding;
              const renderAbove = availableBelow < estimatedMenuHeight && availableAbove > availableBelow;
              const leftPos = Math.max(
                viewportPadding,
                Math.min(rect.left, window.innerWidth - menuWidth - viewportPadding)
              );

              setMenuCoords({
                left: leftPos,
                top: renderAbove ? null : rect.bottom + 4,
                bottom: renderAbove ? window.innerHeight - rect.top + 4 : null,
                maxHeight: Math.max(140, renderAbove ? availableAbove : availableBelow)
              });
              setMenuOpen(true);
            }}
            className={`p-1 rounded-sm transition-colors ${menuOpen ? 'bg-neutral-200 dark:bg-neutral-700 text-neutral-900 dark:text-white' : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus:opacity-100 text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700'}`}
          >
            <MoreVertical size={14} />
          </button>

          {menuOpen && createPortal(
            <>
              <button type="button" aria-label="Close project actions" className="fixed inset-0 z-9998 cursor-default" onClick={() => setMenuOpen(false)} />
              
              <div
                role="menu"
                className="fixed w-48 bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 shadow-xl rounded-md z-9999 py-1 flex flex-col overflow-y-auto"
                style={{
                  top: menuCoords.top ?? undefined,
                  bottom: menuCoords.bottom ?? undefined,
                  left: menuCoords.left,
                  maxHeight: menuCoords.maxHeight
                }}
                onClick={(e) => e.stopPropagation()}
              >
                {isFolder && (
                  <>
                    <button className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); setIsOpen(true); setCreating({ type: 'category' }); }}>
                      <Folder size={12} /> New Subfolder
                    </button>
                    <button className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); setIsOpen(true); setCreating({ type: 'project' }); }}>
                      <Save size={12} /> Save Current Here
                    </button>
                    <label className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left cursor-pointer dark:text-white">
                      <Upload size={12} /> Import Package Here
                      <input type="file" accept=".json" className="hidden" onClick={(e) => e.target.value = null} onChange={(e) => { setMenuOpen(false); setIsOpen(true); onImport(e, node.id); }} />
                    </label>
                    <div className="h-px bg-neutral-100 dark:bg-neutral-800 my-1"></div>
                  </>
                )}

                {!isFolder && (
                  <>
                    <button className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); loadProject(node); }}>
                      <Play size={12} /> Load to Canvas
                    </button>
                    <button className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); if(window.confirm("WARNING: This will permanently overwrite this saved file with whatever is currently on your canvas. Proceed?")) updateProject(node.id); }}>
                      <Save size={12} /> Overwrite with Current
                    </button>
                    <div className="h-px bg-neutral-100 dark:bg-neutral-800 my-1"></div>
                  </>
                )}

                <button className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); setIsEditing(true); }}>
                  <Edit2 size={12} /> Rename
                </button>

                <button className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={handleExport}>
                  <Download size={12} /> Export JSON
                </button>

                <div className="h-px bg-neutral-100 dark:bg-neutral-800 my-1"></div>

                <button className="flex items-center gap-2 px-3 py-2 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 text-left" onClick={() => { setMenuOpen(false); isFolder ? deleteCategory(node.id) : deleteProject(node.id); }}>
                  <Trash size={12} /> Delete
                </button>
              </div>
            </>,
            document.body
          )}
        </div>
      </div>

      {isFolder && isOpen && node.children && (
        <div className="flex flex-col border-l border-neutral-100 dark:border-neutral-800 ml-3">
          {creating && (
            <div className="flex items-center gap-2 py-1.5 px-2" style={{ paddingLeft: `${(level + 1) * 12 + 8}px` }}>
              {creating.type === 'category' ? <Folder size={14} className="text-blue-500 shrink-0" /> : <FileText size={14} className="text-neutral-500 shrink-0" />}
              <InlineEdit
                initialValue=""
                onSave={(val) => {
                  creating.type === 'category' ? createCategory(val, node.id) : saveProject(val, node.id);
                  setCreating(null);
                }}
                onCancel={() => setCreating(null)}
              />
            </div>
          )}
          {node.children.map(child => (
            <TreeNode key={`${child.type}-${child.id}`} node={child} level={level + 1} onImport={onImport} onMove={onMove} />
          ))}
        </div>
      )}
    </div>
  );
};

export default function ProjectTree() {
  const { projects, categories, createCategory, saveProject } = useStore(useShallow((state) => ({
    projects: state.projects, categories: state.categories,
    createCategory: state.createCategory, saveProject: state.saveProject
  })));
  const [creatingRoot, setCreatingRoot] = useState(null);
  const [isRootDragOver, setIsRootDragOver] = useState(false);

  const treeNodes = useMemo(() => {
    const rootNodes = [];
    const catMap = {};

    categories.forEach(c => {
      catMap[c.id] = { ...c, type: 'category', children: [] };
    });

    categories.forEach(c => {
      if (c.parent_id) {
        if (catMap[c.parent_id]) catMap[c.parent_id].children.push(catMap[c.id]);
      } else {
        rootNodes.push(catMap[c.id]);
      }
    });

    projects.forEach(p => {
      const pNode = { ...p, type: 'project' };
      if (p.category_id && catMap[p.category_id]) {
        catMap[p.category_id].children.push(pNode);
      } else {
        rootNodes.push(pNode);
      }
    });

    const sortNodes = (nodes) => {
      nodes.sort((a, b) => {
        if (a.type !== b.type) return a.type === 'category' ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
      nodes.forEach(n => { if (n.children) sortNodes(n.children); });
    };
    sortNodes(rootNodes);

    return rootNodes;
  }, [projects, categories]);

  const handleImport = async (e, targetCategoryId = null) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    let url = '/api/import';
    if (targetCategoryId) url += `?target_category_id=${targetCategoryId}`;

    try {
      await apiFetch(url, { method: 'POST', body: formData });
      useStore.getState().fetchProjects();
    } catch (err) {
      console.error(err);
      alert(err.message);
    }
    e.target.value = null;
  };

  const handleMove = (dragged, targetCategoryId) => {
    if (dragged.type === 'category') {
      useStore.getState().updateCategory(dragged.id, undefined, targetCategoryId);
    } else {
      useStore.getState().updateProject(dragged.id, undefined, targetCategoryId);
    }
  };

  const handleRootDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsRootDragOver(false);
    try {
      const dragged = JSON.parse(e.dataTransfer.getData('application/catlabel-node'));
      if (dragged.parent_id === null) return;
      handleMove(dragged, null);
    } catch (_error) {}
  };

  return (
    <div className="flex flex-col gap-2 mt-2 w-full select-none">
      <div className="flex gap-1 mb-1">
        <button
          onClick={() => setCreatingRoot({ type: 'category' })}
          className="flex-1 flex items-center justify-center gap-1 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 text-neutral-600 dark:text-neutral-400 py-1.5 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors text-[10px] uppercase font-bold tracking-wider"
        >
          <Plus size={12} /> Folder
        </button>
        <button
          onClick={() => setCreatingRoot({ type: 'project' })}
          className="flex-1 flex items-center justify-center gap-1 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 text-neutral-600 dark:text-neutral-400 py-1.5 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors text-[10px] uppercase font-bold tracking-wider"
        >
          <Save size={12} /> Save
        </button>
        <label className="flex-1 flex items-center justify-center gap-1 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 text-neutral-600 dark:text-neutral-400 py-1.5 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors text-[10px] uppercase font-bold tracking-wider cursor-pointer">
          <Upload size={12} /> Import
          <input type="file" accept=".json" className="hidden" onClick={(e) => e.target.value = null} onChange={(e) => handleImport(e, null)} />
        </label>
      </div>

      <div 
        className={`flex flex-col flex-1 max-h-64 overflow-y-auto border border-neutral-100 dark:border-neutral-800 rounded-sm transition-colors ${isRootDragOver ? 'bg-blue-50/50 dark:bg-blue-900/10 border-blue-300 dark:border-blue-700' : 'bg-white dark:bg-neutral-950'}`}
        onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setIsRootDragOver(true); }}
        onDragLeave={(e) => { e.stopPropagation(); setIsRootDragOver(false); }}
        onDrop={handleRootDrop}
      >
        {creatingRoot && (
          <div className="flex items-center gap-2 py-1.5 px-2 pl-2">
            {creatingRoot.type === 'category' ? <Folder size={14} className="text-blue-500 shrink-0" /> : <FileText size={14} className="text-neutral-500 shrink-0" />}
            <InlineEdit
              initialValue=""
              onSave={(val) => {
                creatingRoot.type === 'category' ? createCategory(val, null) : saveProject(val, null);
                setCreatingRoot(null);
              }}
              onCancel={() => setCreatingRoot(null)}
            />
          </div>
        )}
        {treeNodes.length === 0 ? (
          <div className="text-xs text-neutral-400 text-center py-4 pointer-events-none">No projects saved yet. Drag items here to move them to the root.</div>
        ) : (
          treeNodes.map(node => (
            <TreeNode key={`${node.type}-${node.id}`} node={node} level={0} onImport={handleImport} onMove={handleMove} />
          ))
        )}
      </div>
    </div>
  );
}
