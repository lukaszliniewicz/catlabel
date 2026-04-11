import React, { useState, useMemo, useRef, useEffect } from 'react';
import { useStore } from '../store';
import {
  Folder, FolderOpen, FileText, Layers, MoreVertical,
  Download, Upload, Plus, Trash, Edit2, Save, Play
} from 'lucide-react';

// --- Recursive Tree Node Component ---
const TreeNode = ({ node, level, onImport }) => {
  const {
    currentProjectId, loadProject, updateProject, deleteProject,
    createCategory, updateCategory, deleteCategory, saveProject
  } = useStore();

  const [isOpen, setIsOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
    };
    if (menuOpen) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [menuOpen]);

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

      const res = await fetch(url);
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

  return (
    <div className="w-full">
      <div
        className={`flex items-center justify-between py-1.5 px-2 group cursor-pointer border border-transparent transition-colors
          ${isLoaded ? 'bg-blue-50 dark:bg-blue-900/30 border-blue-200 dark:border-blue-800' : 'hover:bg-neutral-100 dark:hover:bg-neutral-800'}
        `}
        style={{ paddingLeft: `${level * 12 + 8}px` }}
        onClick={() => {
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
          <span className={`text-xs truncate ${isLoaded ? 'font-bold text-blue-700 dark:text-blue-400' : 'text-neutral-700 dark:text-neutral-300'}`}>
            {node.name}
          </span>
        </div>

        <div className="relative" ref={menuRef} onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className={`p-1 rounded transition-colors ${menuOpen ? 'bg-neutral-200 dark:bg-neutral-700 text-neutral-900 dark:text-white' : 'opacity-0 group-hover:opacity-100 text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-700'}`}
          >
            <MoreVertical size={14} />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 w-48 bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 shadow-xl rounded-md z-50 py-1 flex flex-col">
              {isFolder && (
                <>
                  <button className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); setIsOpen(true); const n = prompt("New Folder Name:"); if (n) createCategory(n, node.id); }}>
                    <Folder size={12} /> New Subfolder
                  </button>
                  <button className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); setIsOpen(true); const n = prompt("Save current canvas as:"); if (n) saveProject(n, node.id); }}>
                    <Save size={12} /> Save Current Here
                  </button>
                  <label className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left cursor-pointer dark:text-white">
                    <Upload size={12} /> Import Package Here
                    <input type="file" accept=".json" className="hidden" onChange={(e) => { setMenuOpen(false); setIsOpen(true); onImport(e, node.id); }} />
                  </label>
                  <div className="h-px bg-neutral-100 dark:bg-neutral-800 my-1"></div>
                </>
              )}

              {!isFolder && (
                <>
                  <button className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); loadProject(node); }}>
                    <Play size={12} /> Load to Canvas
                  </button>
                  <button className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); updateProject(node.id); }}>
                    <Save size={12} /> Overwrite with Current
                  </button>
                  <div className="h-px bg-neutral-100 dark:bg-neutral-800 my-1"></div>
                </>
              )}

              <button className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-neutral-100 dark:hover:bg-neutral-800 text-left dark:text-white" onClick={() => { setMenuOpen(false); const n = prompt("Rename to:", node.name); if (n) isFolder ? updateCategory(node.id, n) : updateProject(node.id, n); }}>
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
          )}
        </div>
      </div>

      {isFolder && isOpen && node.children && (
        <div className="flex flex-col border-l border-neutral-100 dark:border-neutral-800 ml-3">
          {node.children.map(child => (
            <TreeNode key={`${child.type}-${child.id}`} node={child} level={level + 1} onImport={onImport} />
          ))}
        </div>
      )}
    </div>
  );
};

export default function ProjectTree() {
  const { projects, categories, createCategory, saveProject } = useStore();

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
      const res = await fetch(url, { method: 'POST', body: formData });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Import failed");
      }
      useStore.getState().fetchProjects();
    } catch (err) {
      console.error(err);
      alert(err.message);
    }
    e.target.value = null;
  };

  return (
    <div className="flex flex-col gap-2 mt-2 w-full select-none">
      <div className="flex gap-1 mb-1">
        <button
          onClick={() => { const n = prompt("New Root Folder Name:"); if (n) createCategory(n); }}
          className="flex-1 flex items-center justify-center gap-1 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 text-neutral-600 dark:text-neutral-400 py-1.5 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors text-[10px] uppercase font-bold tracking-wider"
        >
          <Plus size={12} /> Folder
        </button>
        <button
          onClick={() => { const n = prompt("Save current canvas as:"); if (n) saveProject(n); }}
          className="flex-1 flex items-center justify-center gap-1 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 text-neutral-600 dark:text-neutral-400 py-1.5 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors text-[10px] uppercase font-bold tracking-wider"
        >
          <Save size={12} /> Save
        </button>
        <label className="flex-1 flex items-center justify-center gap-1 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 text-neutral-600 dark:text-neutral-400 py-1.5 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors text-[10px] uppercase font-bold tracking-wider cursor-pointer">
          <Upload size={12} /> Import
          <input type="file" accept=".json" className="hidden" onChange={(e) => handleImport(e, null)} />
        </label>
      </div>

      <div className="flex flex-col max-h-64 overflow-y-auto border border-neutral-100 dark:border-neutral-800 rounded bg-white dark:bg-neutral-950">
        {treeNodes.length === 0 ? (
          <div className="text-xs text-neutral-400 text-center py-4">No projects saved yet.</div>
        ) : (
          treeNodes.map(node => (
            <TreeNode key={`${node.type}-${node.id}`} node={node} level={0} onImport={handleImport} />
          ))
        )}
      </div>
    </div>
  );
}
