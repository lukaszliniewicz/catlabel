import React, { useRef, useState, useEffect } from 'react';
import { useStore } from '../store';
import { useShallow } from 'zustand/react/shallow';
import CanvasPagePreview from './CanvasPagePreview';
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
                <CanvasPagePreview key={`${rIdx}-${pageIndex}`} pageIndex={pageIndex} pageNumber={pageIdx + 1} pageCount={pages.length}
                  pageItems={pageItems} layout={layout} record={record} isActive={isActive} showControls={showControls}
                  isSelectedForPrint={isSelectedForPrint} rootRef={containerRef}
                  view={{ canvasWidth, canvasHeight, zoomScale, canvasBorder, cvThick, splitMode, isRotated, printPx, selectedIds, selectedItem, stagePos }}
                  interactions={{ isPanning, trRef, snapLines, selectionBox, setSelectionBox, setStagePos, handleDragMove, handleDragEnd, handleItemPointerDown }}
                  actions={{ setCurrentPage, togglePageForPrint, printPages, deletePage, selectItem }} />
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
