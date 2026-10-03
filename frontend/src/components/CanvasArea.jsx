import React, { useRef, useState, useEffect } from 'react';
import { Group, Layer, Line, Path, Rect, Stage, Transformer } from 'react-konva';
import { useStore } from '../store';
import { useShallow } from 'zustand/react/shallow';
import CanvasItemNode from './CanvasItemNode';
import FloatingToolbar from './FloatingToolbar';
import HtmlLabel from './HtmlLabel';
import CanvasCapture from './CanvasCapture';
import useCanvasKeyboard from './useCanvasKeyboard';
import useCanvasInteractions from './useCanvasInteractions';
import { getPageIndices, getPageItems, getPageLayout } from '../utils/canvasPages';

const WORKSPACE_PAD = 40;

export default function CanvasArea() {
  const {
    items,
    selectedId,
    selectedIds,
    selectItem,
    updateItem,
    canvasWidth,
    canvasHeight,
    zoomScale: userZoomScale,
    isNarrowLayout,
    canvasBorder,
    canvasBorderThickness,
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
    currentDpi,
    splitMode,
    pageLayouts,
    batchRecords
  } = useStore(useShallow((state) => ({
    items: state.items,
    selectedId: state.selectedId,
    selectedIds: state.selectedIds,
    selectItem: state.selectItem,
    updateItem: state.updateItem,
    canvasWidth: state.canvasWidth,
    canvasHeight: state.canvasHeight,
    zoomScale: state.zoomScale,
    isNarrowLayout: state.isNarrowLayout,
    canvasBorder: state.canvasBorder,
    canvasBorderThickness: state.canvasBorderThickness,
    settings: state.settings,
    isRotated: state.isRotated,
    currentPage: state.currentPage,
    setCurrentPage: state.setCurrentPage,
    addPage: state.addPage,
    deletePage: state.deletePage,
    togglePageForPrint: state.togglePageForPrint,
    selectedPagesForPrint: state.selectedPagesForPrint,
    printPages: state.printPages,
    selectedPrinterInfo: state.selectedPrinterInfo,
    currentDpi: state.currentDpi,
    splitMode: state.splitMode,
    pageLayouts: state.pageLayouts,
    batchRecords: state.batchRecords
  })));

  const [selectionBox, setSelectionBox] = useState(null);
  const isPanning = useCanvasKeyboard();
  const [stagePos, setStagePos] = useState({ x: 0, y: 0 });
  const containerRef = useRef(null);
  const [availableWidth, setAvailableWidth] = useState(0);
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const measure = () => {
      const style = getComputedStyle(container);
      setAvailableWidth(container.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);
  const fitScale = isNarrowLayout && availableWidth > 0 ? Math.min(1, availableWidth / (canvasWidth + WORKSPACE_PAD * 2)) : 1;
  const zoomScale = userZoomScale * fitScale;
  const cvThick = canvasBorderThickness || 4;

  const dotsPerMm = (currentDpi || settings.default_dpi || 203) / 25.4;
  const printPx = selectedPrinterInfo?.width_px || Math.round((settings.print_width_mm || 48) * dotsPerMm);
  const visibleRecords = (batchRecords || [{}]).slice(0, 10);
  
  const pages = getPageIndices({ items, pageLayouts, currentPage });
  
  const selectedItem = items.find((item) => item.id === selectedId);

  const { trRef, snapLines, handleDragMove, handleDragEnd, handleItemPointerDown } = useCanvasInteractions({
    items, selectedIds, currentPage, canvasWidth, canvasHeight, isPanning, updateItem, setCurrentPage, selectItem
  });

  return (
    <div 
      ref={containerRef}
      className={`flex-1 flex flex-col items-center p-2 sm:p-8 bg-neutral-100 dark:bg-neutral-900 transition-colors duration-300 gap-8 ${isPanning ? 'cursor-grab active:cursor-grabbing overflow-hidden' : 'overflow-auto'}`}
    >
      <div className="text-neutral-600 dark:text-neutral-300 text-[10px] uppercase tracking-widest font-bold sticky top-0 bg-neutral-100 dark:bg-neutral-900/90 z-10 py-1">
        Canvas Feed Engine: {isRotated ? 'Landscape' : 'Portrait'}
      </div>

      <div className="flex flex-col self-start mx-auto gap-10 min-h-max min-w-max pb-16">
        {visibleRecords.map((record, rIdx) => (
          <div key={rIdx} className="flex flex-col items-center gap-4">
            {batchRecords.length > 1 && (
              <div className="text-[10px] uppercase tracking-widest font-bold text-neutral-600 dark:text-neutral-300">
                Record {rIdx + 1} {rIdx === 9 && batchRecords.length > 10 ? `(Showing 10 of ${batchRecords.length} records)` : ''}
              </div>
            )}

            {pages.map((pageIndex, pageIdx) => {
              const pageItems = getPageItems(items, pageIndex);
              const layout = getPageLayout({ pageLayouts }, pageIndex);

              const isActive = currentPage === pageIndex;
              const showControls = (rIdx === 0);
              const isSelectedForPrint = selectedPagesForPrint.includes(pageIndex);

              return (
                <div key={`${rIdx}-${pageIndex}`} className="flex flex-col items-center gap-2 relative">
                  <div className="flex items-center justify-between w-full px-2 mb-2">
                    <div className="flex items-center gap-2">
                      {(pages.length > 1) && (
                        <input
                          type="checkbox"
                          checked={isSelectedForPrint}
                          onChange={() => togglePageForPrint(pageIndex)}
                          className="w-3.5 h-3.5 cursor-pointer accent-blue-600"
                          title="Select for batch printing"
                        />
                      )}
                      <span className="text-neutral-600 dark:text-neutral-300 text-[10px] uppercase tracking-widest font-bold">
                        Label {pageIdx + 1} {isActive && '(Active)'}
                      </span>
                    </div>
                    {showControls && (
                      <div className="flex gap-3">
                        <button
                          onClick={() => printPages([pageIndex])}
                          className="text-[10px] text-emerald-700 dark:text-emerald-400 hover:text-emerald-700 dark:hover:text-emerald-400 uppercase font-bold tracking-widest transition-colors"
                          title="Print only this label"
                        >
                          Print
                        </button>
                        <button
                          onClick={() => useStore.getState().duplicatePage(pageIndex)}
                          className="text-[10px] text-blue-700 dark:text-blue-300 hover:text-blue-600 uppercase font-bold tracking-widest transition-colors"
                        >
                          Duplicate
                        </button>
                        {(pages.length > 1) && (
                          <button
                            onClick={() => deletePage(pageIndex)}
                            className="text-[10px] text-red-700 dark:text-red-300 hover:text-red-600 uppercase font-bold tracking-widest transition-colors"
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  <div
                    className={`relative transition-[box-shadow,opacity] duration-300 bg-white shadow-md ${isActive ? 'ring-1 ring-blue-400' : 'opacity-60 hover:opacity-100 cursor-pointer'}`}
                    style={{
                      width: (canvasWidth + WORKSPACE_PAD * 2) * zoomScale,
                      height: (canvasHeight + WORKSPACE_PAD * 2) * zoomScale,
                      transformOrigin: 'top left'
                    }}
                    onClick={() => {
                      if (!isActive) {
                        setCurrentPage(pageIndex);
                      }
                    }}
                  >
                    <div
                      style={{
                        position: 'relative',
                        width: (canvasWidth + WORKSPACE_PAD * 2) * zoomScale,
                        height: (canvasHeight + WORKSPACE_PAD * 2) * zoomScale
                      }}
                    >
                      {/* BASE HTML LAYER */}
                      <div
                        style={{
                          position: 'absolute',
                          top: WORKSPACE_PAD * zoomScale,
                          left: WORKSPACE_PAD * zoomScale,
                          width: canvasWidth * zoomScale,
                          height: canvasHeight * zoomScale,
                          overflow: 'hidden'
                        }}
                      >
                        <div style={{
                          transform: `scale(${zoomScale})`,
                          transformOrigin: 'top left',
                          width: canvasWidth,
                          height: canvasHeight
                        }}>
                          <HtmlLabel
                            html={layout?.htmlContent || ''}
                            record={record}
                            width={canvasWidth}
                            height={canvasHeight}
                            canvasBorder="none"
                          />
                        </div>
                      </div>

                      {/* KONVA OVERLAY LAYER */}
                      <div style={{ position: 'absolute', inset: 0, zIndex: 2 }}>
                      <Stage
                        draggable={isPanning}
                        x={stagePos.x}
                        y={stagePos.y}
                        onDragEnd={(e) => {
                          if (isPanning && e.target === e.target.getStage()) {
                            setStagePos({ x: e.target.x(), y: e.target.y() });
                          }
                        }}
                        width={(canvasWidth + WORKSPACE_PAD * 2) * zoomScale}
                        height={(canvasHeight + WORKSPACE_PAD * 2) * zoomScale}
                        scale={{ x: zoomScale, y: zoomScale }}
                        onMouseDown={(e) => {
                          if (isPanning) return;
                          const clickedOnEmpty = e.target === e.target.getStage() || e.target.hasName('bg-rect');
                          if (!clickedOnEmpty) return;

                          setCurrentPage(pageIndex);

                          const pos = e.target.getStage().getPointerPosition();
                          const stageX = (pos.x - stagePos.x) / zoomScale - WORKSPACE_PAD;
                          const stageY = (pos.y - stagePos.y) / zoomScale - WORKSPACE_PAD;

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
                          if (isPanning) return;
                          if (!selectionBox || !selectionBox.active || selectionBox.pageIndex !== pageIndex) return;

                          const pos = e.target.getStage().getPointerPosition();
                          const currentX = (pos.x - stagePos.x) / zoomScale - WORKSPACE_PAD;
                          const currentY = (pos.y - stagePos.y) / zoomScale - WORKSPACE_PAD;

                          setSelectionBox((prev) => ({
                            ...prev,
                            x: Math.min(prev.startX, currentX),
                            y: Math.min(prev.startY, currentY),
                            width: Math.abs(currentX - prev.startX),
                            height: Math.abs(currentY - prev.startY)
                          }));
                        }}
                        onMouseUp={(e) => {
                          if (isPanning) return;
                          if (!selectionBox || !selectionBox.active || selectionBox.pageIndex !== pageIndex) return;

                          if (selectionBox.width > 2 && selectionBox.height > 2) {
                            const isMulti = e.evt.shiftKey || e.evt.ctrlKey || e.evt.metaKey;

                            const intersectingIds = pageItems.filter((item) => {
                              const itemX = item.x;
                              const itemY = item.y;
                              const pad = item.padding !== undefined ? Number(item.padding) : ((item.invert || item.bg_white) ? 4 : 0);
                              const numLines = item.text ? String(item.text).split('\n').length : 1;
                              const actualLineHeight = item.lineHeight ?? (numLines > 1 ? 1.15 : 1);
                              const itemW = item.width || 100;
                              const itemH = item.height || (item.type === 'text' ? (item.size * actualLineHeight * numLines) + (pad * 2) : 50);

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
                          <Rect
                            x={0}
                            y={0}
                            width={canvasWidth + WORKSPACE_PAD * 2}
                            height={canvasHeight + WORKSPACE_PAD * 2}
                            fill="transparent"
                            name="bg-rect"
                          />

                          <Group x={WORKSPACE_PAD} y={WORKSPACE_PAD}>
                            <Rect
                              x={0}
                              y={0}
                              width={canvasWidth}
                              height={canvasHeight}
                              stroke="#e5e5e5"
                              strokeWidth={1}
                              dash={[4, 4]}
                              listening={false}
                            />

                            <Path
                              stroke="#a3a3a3"
                              strokeWidth={1}
                              listening={false}
                              data={`
                                M -${WORKSPACE_PAD} 0 L -5 0 M 0 -${WORKSPACE_PAD} L 0 -5
                                M ${canvasWidth + 5} 0 L ${canvasWidth + WORKSPACE_PAD} 0 M ${canvasWidth} -${WORKSPACE_PAD} L ${canvasWidth} -5
                                M -${WORKSPACE_PAD} ${canvasHeight} L -5 ${canvasHeight} M 0 ${canvasHeight + 5} L 0 ${canvasHeight + WORKSPACE_PAD}
                                M ${canvasWidth + 5} ${canvasHeight} L ${canvasWidth + WORKSPACE_PAD} ${canvasHeight} M ${canvasWidth} ${canvasHeight + 5} L ${canvasWidth} ${canvasHeight + WORKSPACE_PAD}
                              `}
                            />

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
                                interactive={!isPanning}
                                onMouseDown={handleItemPointerDown}
                                onTouchStart={handleItemPointerDown}
                                onDragMove={handleDragMove}
                                onDragEnd={handleDragEnd}
                              />
                            ))}

                            <Rect
                              x={0}
                              y={0}
                              width={canvasWidth}
                              height={canvasHeight}
                              stroke="#ef4444"
                              strokeWidth={1.5 / zoomScale}
                              dash={[4, 4]}
                              opacity={0.6}
                              listening={false}
                            />

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

                            {isActive && !isPanning && (
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
                          </Group>
                        </Layer>
                      </Stage>
                      </div>
                    </div>
                    {isActive && selectedItem && selectedIds.length === 1 && !isPanning && (
                      <FloatingToolbar
                        item={selectedItem}
                        zoomScale={zoomScale}
                        canvasWidth={canvasWidth}
                        canvasHeight={canvasHeight}
                        workspacePad={WORKSPACE_PAD}
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
        className="py-3 px-8 border-2 border-dashed border-neutral-300 dark:border-neutral-700 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-800 transition-colors rounded-sm text-xs uppercase tracking-widest font-bold"
      >
        + Add New Label Page
      </button>

      <div className="text-neutral-400 dark:text-neutral-600 text-[10px] uppercase tracking-widest sticky bottom-0 bg-neutral-100 dark:bg-neutral-900/90 py-1 z-10">
        Drag items to move. Click empty space to deselect. Hold Space to Pan.
      </div>

      <CanvasCapture />
    </div>
  );
}
