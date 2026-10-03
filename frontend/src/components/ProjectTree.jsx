import React, { useState, useMemo, useId, useRef } from 'react';
import { useStore } from '../store';
import { useShallow } from 'zustand/react/shallow';
import { apiFetch, apiJson, isObjectPayload } from '../utils/apiClient';
import ConfirmActionDialog from './ConfirmActionDialog';
import ProjectActionsDialog from './ProjectActionsDialog';
import FileUploadButton from './FileUploadButton';
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
      aria-label="Project or folder name"
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
const TreeNode = ({ node, level, onImport, onMove, focusedKey, onFocusNode }) => {
  const nodeId = useId();
  const nodeKey = `${node.type}-${node.id}`;
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
  const [confirmation, setConfirmation] = useState(null);
  const [actionError, setActionError] = useState('');
  const actionTrigger = useRef(null);

  const isFolder = node.type === 'category';
  const isLoaded = !isFolder && currentProjectId === node.id;
  const isBatch = !isFolder && (
    (node.canvas_state?.batchRecords?.length > 1) ||
    (node.canvas_state?.items?.some(i => i.pageIndex > 0))
  );

  const handleExport = async () => {
    setMenuOpen(false);
    setActionError('');
    try {
      let data;
      let name;
      if (isFolder) {
        data = await apiJson(`/api/export?category_id=${node.id}`, {}, { validate: isObjectPayload });
        name = `${node.name}_export`;
      } else {
        const project = await apiJson(`/api/projects/${node.id}`, {}, { validate: isObjectPayload });
        if (project.id !== node.id || !isObjectPayload(project.canvas_state)) throw new Error('The saved project document is missing or malformed.');
        data = { catlabel_export_version: '1.0', data: { type: 'project', name: project.name, canvas_state: project.canvas_state } };
        name = project.name;
      }
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      try {
        const link = document.createElement('a');
        link.href = url;
        link.download = `${name}.json`;
        link.click();
      } finally { setTimeout(() => URL.revokeObjectURL(url), 0); }
    } catch (error) { setActionError(`Export failed: ${error.message || 'The saved project could not be retrieved.'}`); }
  };

  const requestConfirmation = type => {
    const state = useStore.getState();
    setMenuOpen(false);
    setConfirmation({ type, session: state.documentSessionId, revision: state.documentRevision,
      targetRevision: state.currentProjectId === node.id ? state.currentProjectRevision : node.revision,
      busy: false, error: '' });
  };
  const confirmAction = async () => {
    if (!confirmation || confirmation.busy) return;
    const state = useStore.getState();
    if (confirmation.type === 'overwrite' && (state.documentSessionId !== confirmation.session || state.documentRevision !== confirmation.revision)) {
      setConfirmation({ ...confirmation, error: 'The current design changed while confirmation was open. Cancel and reopen the action to review it again.' });
      return;
    }
    setConfirmation({ ...confirmation, busy: true, error: '' });
    try {
      const result = confirmation.type === 'overwrite'
        ? await updateProject(node.id, null, undefined, confirmation.targetRevision)
        : await (isFolder ? deleteCategory(node.id) : deleteProject(node.id));
      if (result === true) setConfirmation(null);
      else setConfirmation({ ...confirmation, busy: false, error: useStore.getState().apiError || 'The action failed. Your current design is still here.' });
    } catch (error) { setConfirmation({ ...confirmation, busy: false, error: error.message || 'The action failed.' }); }
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
        id={nodeId}
        aria-label={node.name}
        aria-level={level + 1}
        aria-owns={isFolder && isOpen ? `${nodeId}-children` : undefined}
        tabIndex={focusedKey === nodeKey ? 0 : -1}
        onFocus={event => { if (event.target === event.currentTarget) onFocusNode(nodeKey); }}
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
          onFocusNode(nodeKey);
          if (isFolder) setIsOpen(!isOpen);
          else loadProject(node);
        }}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return;
          const row = event.currentTarget;
          const rows = [...row.closest('[role=tree]').querySelectorAll('[role=treeitem]')];
          const index = rows.indexOf(row);
          if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
            event.preventDefault();
            const target = event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1 : Math.max(0, Math.min(rows.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
            rows[target]?.focus();
            return;
          }
          if (event.key === 'ArrowRight') {
            event.preventDefault();
            if (isFolder && !isOpen) setIsOpen(true);
            else if (isFolder) document.getElementById(`${nodeId}-children`)?.querySelector('[role=treeitem]')?.focus();
            return;
          }
          if (event.key === 'ArrowLeft') {
            event.preventDefault();
            if (isFolder && isOpen) setIsOpen(false);
            else document.getElementById(row.closest('[role=group]')?.getAttribute('aria-labelledby'))?.focus();
            return;
          }
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
            ref={actionTrigger}
            aria-haspopup="dialog"
            aria-expanded={menuOpen}
            onClick={(e) => {
              if (menuOpen) {
                setMenuOpen(false);
                return;
              }

              const rect = e.currentTarget.getBoundingClientRect();
              const menuWidth = 192;
              const viewportPadding = 8;
              const estimatedMenuHeight = isFolder ? 390 : 325;
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
            className={`min-h-8 min-w-8 p-1 rounded-sm transition-colors ${menuOpen ? 'bg-neutral-200 dark:bg-neutral-700 text-neutral-900 dark:text-white' : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus:opacity-100 text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700'}`}
          >
            <MoreVertical size={14} />
          </button>

          {menuOpen && <ProjectActionsDialog name={node.name} coordinates={menuCoords} onClose={() => setMenuOpen(false)} returnFocusRef={actionTrigger}>
                {isFolder && (
                  <>
                    <button className="min-h-11 flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); setIsOpen(true); setCreating({ type: 'category' }); }}>
                      <Folder size={12} /> New Subfolder
                    </button>
                    <button className="min-h-11 flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); setIsOpen(true); setCreating({ type: 'project' }); }}>
                      <Save size={12} /> Save Current Here
                    </button>
                    <FileUploadButton label="Import package here" accept=".json" className="min-h-11 flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onChange={event => { setMenuOpen(false); setIsOpen(true); onImport(event, node.id); }}><Upload size={12} /> Import Package Here</FileUploadButton>
                    <div className="h-px bg-neutral-100 dark:bg-neutral-800 my-1"></div>
                  </>
                )}

                {!isFolder && (
                  <>
                    <button className="min-h-11 flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); loadProject(node); }}>
                      <Play size={12} /> Load to Canvas
                    </button>
                    <button className="min-h-11 flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => requestConfirmation('overwrite')}>
                      <Save size={12} /> Overwrite with Current
                    </button>
                    <div className="h-px bg-neutral-100 dark:bg-neutral-800 my-1"></div>
                  </>
                )}

                <button className="min-h-11 flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); setIsEditing(true); }}>
                  <Edit2 size={12} /> Rename
                </button>

                <button className="min-h-11 flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={handleExport}>
                  <Download size={12} /> Export JSON
                </button>

                <div className="h-px bg-neutral-100 dark:bg-neutral-800 my-1"></div>

                <button className="min-h-11 flex items-center gap-2 px-3 py-2 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 text-left" onClick={() => requestConfirmation('delete')}>
                  <Trash size={12} /> Delete
                </button>
          </ProjectActionsDialog>}
        </div>
      </div>

      {actionError && <p role="alert" className="px-2 py-2 text-xs text-red-800 dark:text-red-300">{actionError}</p>}
      {confirmation && <ConfirmActionDialog title={confirmation.type === 'overwrite' ? `Overwrite ${node.name}?` : `Delete ${node.name}?`}
        message={confirmation.type === 'overwrite' ? 'Replace this saved project with the current canvas. Its previous document will be lost.' : isFolder ? 'Delete this folder and all its saved projects and subfolders. This cannot be undone. Your current canvas stays in the editor.' : 'Delete this saved project. This cannot be undone. Your current canvas stays in the editor.'}
        actionLabel={confirmation.type === 'overwrite' ? 'Overwrite saved project' : isFolder ? 'Delete folder and contents' : 'Delete saved project'}
        busy={confirmation.busy} error={confirmation.error} onConfirm={confirmAction}
        onClose={() => { if (!confirmation.busy) setConfirmation(null); }} returnFocusRef={actionTrigger} />}

      {isFolder && isOpen && node.children && (
        <div role="group" id={`${nodeId}-children`} aria-labelledby={nodeId} className="flex flex-col border-l border-neutral-100 dark:border-neutral-800 ml-3">
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
            <TreeNode key={`${child.type}-${child.id}`} node={child} level={level + 1} onImport={onImport} onMove={onMove} focusedKey={focusedKey} onFocusNode={onFocusNode} />
          ))}
        </div>
      )}
    </div>
  );
};

export default function ProjectTree() {
  const [importError, setImportError] = useState('');
  const [isImporting, setIsImporting] = useState(false);
  const { projects, categories, createCategory, saveProject } = useStore(useShallow((state) => ({
    projects: state.projects, categories: state.categories,
    createCategory: state.createCategory, saveProject: state.saveProject
  })));
  const [creatingRoot, setCreatingRoot] = useState(null);
  const [isRootDragOver, setIsRootDragOver] = useState(false);
  const [focusedKey, setFocusedKey] = useState(null);

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

  const hasFocusedNode = nodes => nodes.some(node => `${node.type}-${node.id}` === focusedKey || hasFocusedNode(node.children || []));
  const effectiveFocusedKey = hasFocusedNode(treeNodes) ? focusedKey : treeNodes[0] && `${treeNodes[0].type}-${treeNodes[0].id}`;

  const handleImport = async (e, targetCategoryId = null) => {
    const file = e.target.files[0];
    if (!file) return;

    if (isImporting) return;
    setImportError(''); setIsImporting(true);
    const formData = new FormData();
    formData.append("file", file);

    let url = '/api/import';
    if (targetCategoryId) url += `?target_category_id=${targetCategoryId}`;

    try {
      await apiFetch(url, { method: 'POST', body: formData });
      await useStore.getState().fetchProjects();
    } catch (err) {
      console.error(err);
      setImportError(err.message || 'The project package could not be imported.');
    } finally { setIsImporting(false); }
    e.target.value = '';
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
        <FileUploadButton label="Import project package" accept=".json" disabled={isImporting} className="min-h-8 flex-1 flex items-center justify-center gap-1 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 text-neutral-600 dark:text-neutral-400 py-1.5 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors text-[10px] uppercase font-bold tracking-wider" onChange={event => handleImport(event, null)}><Upload size={12} /> Import</FileUploadButton>
      </div>

      {isImporting && <p role="status" className="text-xs">Importing project package…</p>}
      {importError && <p role="alert" className="text-xs text-red-800 dark:text-red-300">{importError}</p>}
      <div 
        role="tree" aria-label="Saved projects and folders"
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
            <TreeNode key={`${node.type}-${node.id}`} node={node} level={0} onImport={handleImport} onMove={handleMove} focusedKey={effectiveFocusedKey} onFocusNode={setFocusedKey} />
          ))
        )}
      </div>
    </div>
  );
}
