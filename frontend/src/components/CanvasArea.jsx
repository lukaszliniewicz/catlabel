import React from 'react';
import { Layer, Line, Rect, Stage, Transformer } from 'react-konva';
import { useStore } from '../store';
import CanvasItemNode from './CanvasItemNode';
import FloatingToolbar from './FloatingToolbar';

export default function CanvasArea() {
  const {
    items,
    selectedId,
    selectedIds,
    selectItem,
    updateItem,
    canvasWidth,
    canvasHeight,
    zoomScale,
    canvasBorder,
    canvasBorderThickness,
    snapLines,
    setSnapLines,
    settings,
    isRotated,
    currentPage,
    setCurrentPage,
    addPage,
    deletePage,
    togglePageForPrint,
    selectedPagesForPrint,
    printPages,
    selectedPrinterInfo,
    currentDpi
  } = useStore();

  const { splitMode } = useStore();
  const [selectionBox, setSelectionBox] = React.useState(null);
  const trRef = React.useRef(null);
  const cvThick = canvasBorderThickness || 4;
  const dotsPerMm = (currentDpi || settings.default_dpi || 203) / 25.4;
  const printPx = selectedPrinterInfo?.width_px || Math.round((settings.print_width_mm || 48) * dotsPerMm);
  const batchRecords = useStore((state) => state.batchRecords) || [{}];
  const visibleRecords = batchRecords.slice(0, 10);
  const maxPage = items.reduce((max, item) => Math.max(max, Number(item.pageIndex ?? 0)), 0);
  const maxDisplayedPage = Math.max(maxPage, currentPage);
  const pages = Array.from({ length: maxDisplayedPage + 1 }, (_, index) => index);
  const selectedItem = items.find((item) => item.id === selectedId);

  React.useEffect(() => {
    if (!trRef.current) return;
    const stage = trRef.current.getStage();
    if (!stage) return;

    const selectedNodes = selectedIds.map((id) => stage.findOne(`#node-${id}`)).filter(Boolean);
    trRef.current.nodes(selectedNodes);
    trRef.current.getLayer()?.batchDraw();
  }, [selectedIds, currentPage, items]);

  React.useEffect(() => {
    const handleKeyDown = (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

      const { selectedIds, deleteSelectedItems, moveSelectedItems } = useStore.getState();
      if (selectedIds.length === 0) return;

      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        deleteSelectedItems();
      }

      const step = e.shiftKey ? 10 : 1;
      if (e.key === 'ArrowUp') { e.preventDefault(); moveSelectedItems(0, -step); }
      if (e.key === 'ArrowDown') { e.preventDefault(); moveSelectedItems(0, step); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); moveSelectedItems(-step, 0); }
      if (e.key === 'ArrowRight') { e.preventDefault(); moveSelectedItems(step, 0); }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleDragMove = (e, item) => {
    const node = e.target;
    const x = node.x();
    const y = node.y();
    const w = node.getClientRect().width || item.width || 100;
    const h = node.getClientRect().height || item.height || (item.type === 'text' ? item.size : 50);

    const SNAP_T = 10;
    let newX = x;
    let newY = y;
    const lines = [];

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

    node.position({ x: newX, y: newY });
    setSnapLines(lines);
  };

  const handleDragEnd = (e, item) => {
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
  };

  return (
    <div className="flex-1 flex flex-col items-center overflow-auto p-8 bg-neutral-100 dark:bg-neutral-900 transition-colors duration-300 gap-8">
      <div className="text-neutral-400 dark:text-neutral-500 text-[10px] uppercase tracking-widest font-bold">
        Canvas Feed Engine: {isRotated ? 'Landscape' : 'Portrait'}
      </div>

      <div className="flex flex-col gap-10">
        {visibleRecords.map((record, rIdx) => (
          <div key={rIdx} className="flex flex-col items-center gap-4">
            {batchRecords.length > 1 && (
              <div className="text-[10px] uppercase tracking-widest font-bold text-neutral-400">
                Record {rIdx + 1} {rIdx === 9 && batchRecords.length > 10 ? `(Showing 10 of ${batchRecords.length} records)` : ''}
              </div>
            )}

            {pages.map((pageIndex, pageIdx) => {
              const pageItems = items.filter((item) => Number(item.pageIndex ?? 0) === pageIndex);
              const isActive = currentPage === pageIndex;

              return (
                <div key={`${rIdx}-${pageIndex}`} className="flex flex-col items-center gap-2 relative">
                  <div className="flex items-center justify-between w-full px-2 mb-2">
                    <div className="flex items-center gap-2">
                      {pages.length > 1 && (
                        <input
                          type="checkbox"
                          checked={selectedPagesForPrint.includes(pageIndex)}
                          onChange={() => togglePageForPrint(pageIndex)}
                          className="w-3.5 h-3.5 cursor-pointer accent-blue-600"
                          title="Select for batch printing"
                        />
                      )}
                      <span className="text-neutral-400 dark:text-neutral-500 text-[10px] uppercase tracking-widest font-bold">
                        Label {pageIdx + 1} {isActive && '(Active)'}
                      </span>
                    </div>
                    {rIdx === 0 && (
                      <div className="flex gap-3">
                        <button
                          onClick={() => printPages([pageIndex])}
                          className="text-[10px] text-emerald-600 dark:text-emerald-500 hover:text-emerald-700 dark:hover:text-emerald-400 uppercase font-bold tracking-widest transition-colors"
                          title="Print only this label"
                        >
                          Print
                        </button>
                        <button
                          onClick={() => useStore.getState().duplicatePage(pageIndex)}
                          className="text-[10px] text-blue-500 hover:text-blue-600 uppercase font-bold tracking-widest transition-colors"
                        >
                          Duplicate
                        </button>
                        {pages.length > 1 && (
                          <button
                            onClick={() => deletePage(pageIndex)}
                            className="text-[10px] text-red-500 hover:text-red-600 uppercase font-bold tracking-widest transition-colors"
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  <div
                    className={`bg-white shadow-2xl relative transition-all duration-300 ${isActive ? 'ring-2 ring-blue-500' : 'opacity-70 hover:opacity-100 cursor-pointer'}`}
                    style={{ width: canvasWidth * zoomScale, height: canvasHeight * zoomScale, transformOrigin: 'top left' }}
                    onClick={() => {
                      if (!isActive) {
                        setCurrentPage(pageIndex);
                      }
                    }}
                  >
                    <Stage
                      ref={(node) => {
                        if (node && isActive && rIdx === 0) {
                          useStore.getState().setStageRef(node);
                        }
                      }}
                      width={canvasWidth * zoomScale}
                      height={canvasHeight * zoomScale}
                      scale={{ x: zoomScale, y: zoomScale }}
                      onMouseDown={(e) => {
                        const clickedOnEmpty = e.target === e.target.getStage() || e.target.hasName('bg-rect');
                        if (!clickedOnEmpty) return;

                        setCurrentPage(pageIndex);

                        const pos = e.target.getStage().getPointerPosition();
                        const stageX = pos.x / zoomScale;
                        const stageY = pos.y / zoomScale;

                        setSelectionBox({
                          pageIndex,
                          startX: stageX,
                          startY: stageY,
                          x: stageX,
                          y: stageY,
                          width: 0,
                          height: 0,
                          active: true
                        });

                        if (!e.evt.shiftKey && !e.evt.ctrlKey && !e.evt.metaKey) {
                          selectItem(null);
                        }
                      }}
                      onMouseMove={(e) => {
                        if (!selectionBox || !selectionBox.active || selectionBox.pageIndex !== pageIndex) return;

                        const pos = e.target.getStage().getPointerPosition();
                        const currentX = pos.x / zoomScale;
                        const currentY = pos.y / zoomScale;

                        setSelectionBox((prev) => ({
                          ...prev,
                          x: Math.min(prev.startX, currentX),
                          y: Math.min(prev.startY, currentY),
                          width: Math.abs(currentX - prev.startX),
                          height: Math.abs(currentY - prev.startY)
                        }));
                      }}
                      onMouseUp={(e) => {
                        if (!selectionBox || !selectionBox.active || selectionBox.pageIndex !== pageIndex) return;

                        if (selectionBox.width > 2 && selectionBox.height > 2) {
                          const isMulti = e.evt.shiftKey || e.evt.ctrlKey || e.evt.metaKey;

                          const intersectingIds = pageItems.filter((item) => {
                            const itemX = item.x;
                            const itemY = item.y;
                            const pad = item.padding !== undefined ? Number(item.padding) : ((item.invert || item.bg_white) ? 4 : 0);
                            const numLines = item.text ? String(item.text).split('\n').length : 1;
                            const itemW = item.width || 100;
                            const itemH = item.height || (item.type === 'text' ? (item.size * 1.15 * numLines) + (pad * 2) : 50);

                            return !(
                              itemX > selectionBox.x + selectionBox.width ||
                              itemX + itemW < selectionBox.x ||
                              itemY > selectionBox.y + selectionBox.height ||
                              itemY + itemH < selectionBox.y
                            );
                          }).map((item) => item.id);

                          if (intersectingIds.length > 0) {
                            useStore.getState().selectItems(intersectingIds, isMulti);
                          }
                        }

                        setSelectionBox(null);
                      }}
                    >
                      <Layer>
                        <Rect x={0} y={0} width={canvasWidth} height={canvasHeight} fill="transparent" name="bg-rect" />

                        {canvasBorder === 'box' && <Rect x={0} y={0} width={canvasWidth} height={canvasHeight} stroke="black" strokeWidth={cvThick} listening={false} />}
                        {canvasBorder === 'top' && <Line points={[0, 0, canvasWidth, 0]} stroke="black" strokeWidth={cvThick} listening={false} />}
                        {canvasBorder === 'bottom' && <Line points={[0, canvasHeight, canvasWidth, canvasHeight]} stroke="black" strokeWidth={cvThick} listening={false} />}
                        {canvasBorder === 'cut_line' && <Line points={[0, canvasHeight, canvasWidth, canvasHeight]} stroke="black" strokeWidth={cvThick} dash={[10, 10]} listening={false} />}

                        {splitMode && (
                          <>
                            {!isRotated ? (
                              Array.from({ length: Math.ceil(canvasWidth / printPx) - 1 }).map((_, index) => (
                                <Line
                                  key={`split-v-${index}`}
                                  points={[(index + 1) * printPx, 0, (index + 1) * printPx, canvasHeight]}
                                  stroke="#ef4444"
                                  strokeWidth={2}
                                  dash={[10, 10]}
                                  listening={false}
                                />
                              ))
                            ) : (
                              Array.from({ length: Math.ceil(canvasHeight / printPx) - 1 }).map((_, index) => (
                                <Line
                                  key={`split-h-${index}`}
                                  points={[0, (index + 1) * printPx, canvasWidth, (index + 1) * printPx]}
                                  stroke="#ef4444"
                                  strokeWidth={2}
                                  dash={[10, 10]}
                                  listening={false}
                                />
                              ))
                            )}
                          </>
                        )}

                        {pageItems.map((item) => (
                          <CanvasItemNode
                            key={item.id}
                            item={item}
                            record={record}
                            canvasWidth={canvasWidth}
                            canvasHeight={canvasHeight}
                            isSelected={selectedIds.includes(item.id)}
                            interactive
                            onMouseDown={(e) => {
                              e.cancelBubble = true;
                              setCurrentPage(pageIndex);
                              const isMulti = e.evt.shiftKey || e.evt.ctrlKey || e.evt.metaKey;
                              selectItem(item.id, isMulti);
                            }}
                            onTouchStart={(e) => {
                              e.cancelBubble = true;
                              setCurrentPage(pageIndex);
                              const isMulti = e.evt.shiftKey || e.evt.ctrlKey || e.evt.metaKey;
                              selectItem(item.id, isMulti);
                            }}
                            onDragMove={(e) => handleDragMove(e, item)}
                            onDragEnd={(e) => handleDragEnd(e, item)}
                          />
                        ))}

                        {isActive && snapLines.map((line, index) => (
                          <Line key={index} points={line.points} stroke={line.stroke} strokeWidth={1} dash={[4, 4]} />
                        ))}

                        {selectionBox && selectionBox.active && selectionBox.pageIndex === pageIndex && (
                          <Rect
                            x={selectionBox.x}
                            y={selectionBox.y}
                            width={selectionBox.width}
                            height={selectionBox.height}
                            fill="rgba(59, 130, 246, 0.3)"
                            stroke="#3b82f6"
                            strokeWidth={1 / zoomScale}
                            listening={false}
                          />
                        )}

                        {isActive && (
                          <Transformer
                            ref={trRef}
                            borderStroke="#2563eb"
                            borderDash={[4, 4]}
                            borderStrokeWidth={2 / zoomScale}
                            anchorSize={8 / zoomScale}
                            anchorStroke="#2563eb"
                            anchorFill="#ffffff"
                            anchorStrokeWidth={2 / zoomScale}
                            resizeEnabled={selectedItem?.type !== 'icon_text'}
                            boundBoxFunc={(oldBox, newBox) => {
                              if (newBox.width < 5 || newBox.height < 5) return oldBox;
                              return newBox;
                            }}
                          />
                        )}
                      </Layer>
                    </Stage>

                    {isActive && selectedItem && selectedIds.length === 1 && (
                      <FloatingToolbar
                        item={selectedItem}
                        zoomScale={zoomScale}
                        canvasWidth={canvasWidth}
                        canvasHeight={canvasHeight}
                      />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <button
        onClick={addPage}
        className="py-3 px-8 border-2 border-dashed border-neutral-300 dark:border-neutral-700 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors rounded text-xs uppercase tracking-widest font-bold"
      >
        + Add New Label
      </button>

      <div className="text-neutral-400 dark:text-neutral-600 text-[10px] uppercase tracking-widest">
        Drag items to move. Click empty space to deselect.
      </div>
    </div>
  );
}
