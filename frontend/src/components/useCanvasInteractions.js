import { useRef, useState, useEffect, useCallback } from 'react';
import { useStore } from '../store';
import { normalizePageIndex } from '../utils/canvasPages';
const SNAP_T = 10;

export default function useCanvasInteractions({ items, selectedIds, currentPage, canvasWidth, canvasHeight, isPanning, updateItem, setCurrentPage, selectItem }) {
  const [snapLines, setSnapLines] = useState([]);
  const trRef = useRef(null);
  useEffect(() => {
    if (!trRef.current) return;
    const stage = trRef.current.getStage();
    if (!stage) return;

    const selectedNodes = selectedIds.map((id) => stage.findOne(`#node-${id}`)).filter(Boolean);
    trRef.current.nodes(selectedNodes);
    trRef.current.getLayer()?.batchDraw();
  }, [selectedIds, currentPage, items, isPanning]);

  const getBoundingBox = useCallback((item) => {
    const w = item.width || 100;
    const lineCount = item.text ? String(item.text).split('\n').length : 1;
    const pad = item.padding !== undefined ? Number(item.padding) : 0;
    const actualLineHeight = item.lineHeight ?? (lineCount > 1 ? 1.15 : 1);
    const h = item.height || (item.type === 'text' ? (item.size * actualLineHeight * lineCount) + (pad * 2) : 50);
    return { x: item.x, y: item.y, width: w, height: h };
  }, []);

  const handleDragMove = useCallback((e, draggedItem) => {
    const node = e.target;
    const x = node.x();
    const y = node.y();
    const { width: w, height: h } = getBoundingBox(draggedItem);

    let newX = x;
    let newY = y;
    const lines = [];

    // Canvas Edge Snapping
    const centerX = canvasWidth / 2;
    if (Math.abs(x + w / 2 - centerX) < SNAP_T) {
      newX = centerX - w / 2;
      lines.push({ points: [centerX, -9999, centerX, 9999], stroke: '#06b6d4' });
    }
    if (Math.abs(x) < SNAP_T) {
      newX = 0;
      lines.push({ points: [0, -9999, 0, 9999], stroke: '#06b6d4' });
    }
    if (Math.abs(x + w - canvasWidth) < SNAP_T) {
      newX = canvasWidth - w;
      lines.push({ points: [canvasWidth, -9999, canvasWidth, 9999], stroke: '#06b6d4' });
    }

    const centerY = canvasHeight / 2;
    if (Math.abs(y + h / 2 - centerY) < SNAP_T) {
      newY = centerY - h / 2;
      lines.push({ points: [-9999, centerY, 9999, centerY], stroke: '#ec4899' });
    }
    if (Math.abs(y) < SNAP_T) {
      newY = 0;
      lines.push({ points: [-9999, 0, 9999, 0], stroke: '#ec4899' });
    }
    if (Math.abs(y + h - canvasHeight) < SNAP_T) {
      newY = canvasHeight - h;
      lines.push({ points: [-9999, canvasHeight, 9999, canvasHeight], stroke: '#ec4899' });
    }

    // Element-to-Element Snapping
    const otherItems = items.filter(i => i.id !== draggedItem.id && normalizePageIndex(i.pageIndex) === currentPage);
    for (const item of otherItems) {
      const box = getBoundingBox(item);

      // Snap Left to Left
      if (Math.abs(x - box.x) < SNAP_T) { newX = box.x; lines.push({ points: [box.x, -9999, box.x, 9999], stroke: '#f59e0b' }); }
      // Snap Left to Right
      if (Math.abs(x - (box.x + box.width)) < SNAP_T) { newX = box.x + box.width; lines.push({ points: [box.x + box.width, -9999, box.x + box.width, 9999], stroke: '#f59e0b' }); }
      // Snap Right to Right
      if (Math.abs((x + w) - (box.x + box.width)) < SNAP_T) { newX = box.x + box.width - w; lines.push({ points: [box.x + box.width, -9999, box.x + box.width, 9999], stroke: '#f59e0b' }); }
      // Snap Right to Left
      if (Math.abs((x + w) - box.x) < SNAP_T) { newX = box.x - w; lines.push({ points: [box.x, -9999, box.x, 9999], stroke: '#f59e0b' }); }
      // Snap Top to Top
      if (Math.abs(y - box.y) < SNAP_T) { newY = box.y; lines.push({ points: [-9999, box.y, 9999, box.y], stroke: '#f59e0b' }); }
      // Snap Top to Bottom
      if (Math.abs(y - (box.y + box.height)) < SNAP_T) { newY = box.y + box.height; lines.push({ points: [-9999, box.y + box.height, 9999, box.y + box.height], stroke: '#f59e0b' }); }
      // Snap Bottom to Bottom
      if (Math.abs((y + h) - (box.y + box.height)) < SNAP_T) { newY = box.y + box.height - h; lines.push({ points: [-9999, box.y + box.height, 9999, box.y + box.height], stroke: '#f59e0b' }); }
      // Snap Bottom to Top
      if (Math.abs((y + h) - box.y) < SNAP_T) { newY = box.y - h; lines.push({ points: [-9999, box.y, 9999, box.y], stroke: '#f59e0b' }); }
    }

    node.position({ x: newX, y: newY });
    setSnapLines(lines);
  }, [canvasHeight, canvasWidth, currentPage, getBoundingBox, items]);

  const handleDragEnd = useCallback((e, item) => {
    setSnapLines([]);
    const newX = e.target.x();
    const newY = e.target.y();
    const dx = newX - item.x;
    const dy = newY - item.y;

    const { selectedIds, moveSelectedItems } = useStore.getState();

    if (selectedIds.includes(item.id) && selectedIds.length > 1) {
      moveSelectedItems(dx, dy);
    } else {
      updateItem(item.id, { x: newX, y: newY });
    }
  }, [updateItem]);

  const handleItemPointerDown = useCallback((e, item) => {
    if (isPanning) return;
    e.cancelBubble = true;
    setCurrentPage(normalizePageIndex(item.pageIndex));
    const isMulti = e.evt.shiftKey || e.evt.ctrlKey || e.evt.metaKey;
    selectItem(item.id, isMulti);
  }, [isPanning, selectItem, setCurrentPage]);

  return { trRef, snapLines, handleDragMove, handleDragEnd, handleItemPointerDown };
}
