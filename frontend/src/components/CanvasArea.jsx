import React from 'react';
import { Stage, Layer, Text, Rect, Line, Group, Image as KonvaImage, Ellipse } from 'react-konva';
import { useStore } from '../store';

// Custom hook to load base64/url images into Konva
const useImageLoader = (url) => {
  const [img, setImg] = React.useState(null);
  React.useEffect(() => {
    if (!url) return;
    const image = new window.Image();
    image.src = url;
    image.onload = () => setImg(image);
  }, [url]);
  return img;
};

// NEW: Component isolated to safely use the hook
const URLImage = ({ item, commonProps, isSelected }) => {
  const imgElement = useImageLoader(item.src || item.icon_src);
  return (
    <React.Fragment>
      <KonvaImage image={imgElement} {...commonProps} />
      {isSelected && <Rect {...commonProps} stroke="#2563eb" strokeWidth={2} dash={[4,4]} fillEnabled={false} listening={false} />}
    </React.Fragment>
  );
};

export default function CanvasArea() {
  const { items, selectedId, selectedIds, selectItem, updateItem, canvasWidth, canvasHeight, zoomScale, canvasBorder, canvasBorderThickness, snapLines, setSnapLines, settings, isRotated, currentPage, setCurrentPage, addPage, deletePage, togglePageForPrint, selectedPagesForPrint, printPages, selectedPrinterInfo, currentDpi } = useStore();
  
  const { splitMode } = useStore();
  const [selectionBox, setSelectionBox] = React.useState(null);
  const cvThick = canvasBorderThickness || 4;
  const dotsPerMm = (currentDpi || settings.default_dpi || 203) / 25.4;
  const printPx = selectedPrinterInfo?.width_px || Math.round((settings.print_width_mm || 48) * dotsPerMm);
  const batchRecords = useStore(state => state.batchRecords) || [{}];
  const visibleRecords = batchRecords.slice(0, 10);
  const maxPage = items.reduce((max, item) => Math.max(max, Number(item.pageIndex ?? 0)), 0);
  const maxDisplayedPage = Math.max(maxPage, currentPage);
  const pages = Array.from({ length: maxDisplayedPage + 1 }, (_, i) => i);

  // Global Keyboard Shortcuts
  React.useEffect(() => {
    const handleKeyDown = (e) => {
      // Don't trigger if the user is typing in an input field (like the Properties Panel)
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

      const { selectedIds, deleteSelectedItems, moveSelectedItems } = useStore.getState();
      if (selectedIds.length === 0) return;

      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        deleteSelectedItems();
      }

      // Holding shift moves by 10px instead of 1px
      const step = e.shiftKey ? 10 : 1;
      if (e.key === 'ArrowUp') { e.preventDefault(); moveSelectedItems(0, -step); }
      if (e.key === 'ArrowDown') { e.preventDefault(); moveSelectedItems(0, step); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); moveSelectedItems(-step, 0); }
      if (e.key === 'ArrowRight') { e.preventDefault(); moveSelectedItems(step, 0); }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const applyVars = (str, record) => {
    if (!str) return str;
    let res = String(str);

    // 1. Standard variables
    if (record) {
      Object.keys(record).forEach((key) => {
        const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`{{\\s*${escapedKey}\\s*}}`, 'g');
        res = res.replace(regex, String(record[key] ?? ''));
      });
    }

    // 2. Smart Date/Time
    const now = new Date();

    const formatYMD = (dateObj) => {
      const y = dateObj.getFullYear();
      const m = String(dateObj.getMonth() + 1).padStart(2, '0');
      const d = String(dateObj.getDate()).padStart(2, '0');
      return `${y}-${m}-${d}`;
    };

    res = res.replace(/{{\s*\$date\s*}}/g, formatYMD(now));
    res = res.replace(/{{\s*\$time\s*}}/g, now.toTimeString().substring(0, 5));

    // 3. Smart Date Math {{ $date+7 }}
    res = res.replace(/{{\s*\$date([+-])(\d+)\s*}}/g, (match, op, daysStr) => {
      const days = parseInt(daysStr, 10);
      const d = new Date(now);
      d.setDate(d.getDate() + (op === '+' ? days : -days));
      return formatYMD(d);
    });

    return res;
  };

  const handleDragMove = (e, item) => {
    const node = e.target;
    const x = node.x();
    const y = node.y();
    // Use getClientRect to account for the actual bounding box
    const w = node.getClientRect().width || item.width || 100;
    const h = node.getClientRect().height || item.height || (item.type === 'text' ? item.size : 50);

    const SNAP_T = 10;
    let newX = x;
    let newY = y;
    let lines = [];

    // --- Horizontal Snapping ---
    const centerX = canvasWidth / 2;
    if (Math.abs(x + w / 2 - centerX) < SNAP_T) {
      newX = centerX - w / 2;
      lines.push({ points: [centerX, -9999, centerX, 9999], stroke: '#06b6d4' });
    }
    // Snap exactly to Left edge
    if (Math.abs(x) < SNAP_T) {
      newX = 0;
      lines.push({ points: [0, -9999, 0, 9999], stroke: '#06b6d4' });
    }
    // Snap exactly to Right edge
    if (Math.abs(x + w - canvasWidth) < SNAP_T) {
      newX = canvasWidth - w;
      lines.push({ points: [canvasWidth, -9999, canvasWidth, 9999], stroke: '#06b6d4' });
    }

    // --- Vertical Snapping ---
    const centerY = canvasHeight / 2;
    if (Math.abs(y + h / 2 - centerY) < SNAP_T) {
      newY = centerY - h / 2;
      lines.push({ points: [-9999, centerY, 9999, centerY], stroke: '#ec4899' }); 
    }
    // Snap exactly to Top edge
    if (Math.abs(y) < SNAP_T) {
      newY = 0;
      lines.push({ points: [-9999, 0, 9999, 0], stroke: '#ec4899' });
    }
    // Snap exactly to Bottom edge
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
    
    // If we're dragging a member of a multi-selection, move all selected items
    if (selectedIds.includes(item.id) && selectedIds.length > 1) {
      moveSelectedItems(dx, dy);
    } else {
      updateItem(item.id, { x: newX, y: newY });
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center overflow-auto p-8 bg-neutral-100 dark:bg-neutral-900 transition-colors duration-300 gap-8">
      <div className="text-neutral-400 dark:text-neutral-500 text-[10px] uppercase tracking-widest font-bold">
        Canvas Feed Engine: {isRotated ? "Landscape" : "Portrait"}
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
                      width={canvasWidth * zoomScale}
                      height={canvasHeight * zoomScale}
                      scale={{ x: zoomScale, y: zoomScale }}
                      onMouseDown={(e) => {
                        const clickedOnEmpty = e.target === e.target.getStage() || e.target.hasName('bg-rect');
                        if (clickedOnEmpty) {
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
                        }
                      }}
                      onMouseMove={(e) => {
                        if (!selectionBox || !selectionBox.active || selectionBox.pageIndex !== pageIndex) return;
                        
                        const pos = e.target.getStage().getPointerPosition();
                        const currentX = pos.x / zoomScale;
                        const currentY = pos.y / zoomScale;
                        
                        setSelectionBox(prev => ({
                          ...prev,
                          x: Math.min(prev.startX, currentX),
                          y: Math.min(prev.startY, currentY),
                          width: Math.abs(currentX - prev.startX),
                          height: Math.abs(currentY - prev.startY)
                        }));
                      }}
                      onMouseUp={(e) => {
                        if (selectionBox && selectionBox.active && selectionBox.pageIndex === pageIndex) {
                          if (selectionBox.width > 2 && selectionBox.height > 2) {
                            const isMulti = e.evt.shiftKey || e.evt.ctrlKey || e.evt.metaKey;
                            
                            const intersectingIds = pageItems.filter(item => {
                              const itemX = item.x;
                              const itemY = item.y;
                              const pad = item.padding !== undefined ? Number(item.padding) : ((item.invert || item.bg_white) ? 4 : 0);
                              const numLines = item.text ? String(item.text).split('\n').length : 1;
                              const itemW = item.width || 100;
                              const itemH = item.height || (item.type === 'text' ? (item.size * 1.15 * numLines) + (pad * 2) : 50);

                              // Bounding Box overlap
                              return !(
                                itemX > selectionBox.x + selectionBox.width ||
                                itemX + itemW < selectionBox.x ||
                                itemY > selectionBox.y + selectionBox.height ||
                                itemY + itemH < selectionBox.y
                              );
                            }).map(i => i.id);

                            if (intersectingIds.length > 0) {
                              useStore.getState().selectItems(intersectingIds, isMulti);
                            }
                          }
                          setSelectionBox(null);
                        }
                      }}
                    >
                      <Layer>
                        {/* Base rect catches clicks seamlessly even if borders are removed */}
                        <Rect x={0} y={0} width={canvasWidth} height={canvasHeight} fill="transparent" name="bg-rect" />

                        {/* Canvas Border Background Renders */}
                        {canvasBorder === 'box' && <Rect x={0} y={0} width={canvasWidth} height={canvasHeight} stroke="black" strokeWidth={cvThick} listening={false} />}
                        {canvasBorder === 'top' && <Line points={[0, 0, canvasWidth, 0]} stroke="black" strokeWidth={cvThick} listening={false} />}
                        {canvasBorder === 'bottom' && <Line points={[0, canvasHeight, canvasWidth, canvasHeight]} stroke="black" strokeWidth={cvThick} listening={false} />}
                        {canvasBorder === 'cut_line' && <Line points={[0, canvasHeight, canvasWidth, canvasHeight]} stroke="black" strokeWidth={cvThick} dash={[10, 10]} listening={false} />}
                        
                        {/* Oversize Strip Split Indicators */}
                        {splitMode && (
                          <>
                            {!isRotated ? (
                              Array.from({ length: Math.ceil(canvasWidth / printPx) - 1 }).map((_, i) => (
                                <Line key={`split-v-${i}`} points={[(i + 1) * printPx, 0, (i + 1) * printPx, canvasHeight]} stroke="#ef4444" strokeWidth={2} dash={[10, 10]} listening={false} />
                              ))
                            ) : (
                              Array.from({ length: Math.ceil(canvasHeight / printPx) - 1 }).map((_, i) => (
                                <Line key={`split-h-${i}`} points={[0, (i + 1) * printPx, canvasWidth, (i + 1) * printPx]} stroke="#ef4444" strokeWidth={2} dash={[10, 10]} listening={false} />
                              ))
                            )}
                          </>
                        )}

                        {pageItems.map((item) => {
                          const renderElement = (currItem, isChild = false) => {
                            const isSelected = !isChild && selectedIds.includes(currItem.id);
                            const substitutedText = applyVars(currItem.text, record);
                            const substitutedHtml = applyVars(currItem.html, record);

                            const numLines = substitutedText ? String(substitutedText).split('\n').length : 1;
                            const pad = currItem.padding !== undefined ? Number(currItem.padding) : ((currItem.invert || currItem.bg_white) ? 4 : 0);
                            const approxHeight = currItem.height || (currItem.type === 'text' ? (currItem.size * 1.15 * numLines) + (pad * 2) : 50);
                            const visualW = currItem.width || 100;

                            const commonProps = {
                              key: currItem.id,
                              x: currItem.x,
                              y: currItem.y,
                              width: currItem.width,
                              height: currItem.height,
                              draggable: !isChild && currItem.type !== 'cut_line_indicator',
                              onMouseDown: (e) => {
                                if (isChild) return;
                                e.cancelBubble = true;
                                setCurrentPage(pageIndex);
                                const isMulti = e.evt.shiftKey || e.evt.ctrlKey || e.evt.metaKey;
                                selectItem(currItem.id, isMulti);
                              },
                              onTouchStart: (e) => {
                                if (isChild) return;
                                e.cancelBubble = true;
                                setCurrentPage(pageIndex);
                                const isMulti = e.evt.shiftKey || e.evt.ctrlKey || e.evt.metaKey;
                                selectItem(currItem.id, isMulti);
                              },
                              onDragMove: (e) => !isChild && handleDragMove(e, currItem),
                              onDragEnd: (e) => !isChild && handleDragEnd(e, currItem)
                            };

                            if (currItem.type === 'group') {
                              return (
                                <Group {...commonProps}>
                                  {currItem.children.map((child) => renderElement(child, true))}
                                  {isSelected && (
                                    <Rect
                                      width={visualW}
                                      height={approxHeight}
                                      stroke="#2563eb"
                                      strokeWidth={2}
                                      dash={[4, 4]}
                                      fillEnabled={false}
                                      listening={false}
                                    />
                                  )}
                                </Group>
                              );
                            }

                            let element = null;

                            if (currItem.type === 'text') {
                              const fontFamily = currItem.font ? currItem.font.split('.')[0] : 'Arial';
                              const fill = currItem.invert ? 'white' : (isSelected ? '#2563eb' : 'black');
                              const bgFill = currItem.invert ? 'black' : (currItem.bg_white ? 'white' : null);
                              const capHeight = currItem.size * 0.71;
                              const lineHeightPx = currItem.size * 1.15;
                              const availWidth = Math.max(0, visualW - (pad * 2));
                              const availHeight = Math.max(0, approxHeight - (pad * 2));
                              const boxCenterY = pad + (availHeight / 2);
                              const firstBaselineY = boxCenterY + (capHeight / 2) - ((numLines - 1) * lineHeightPx / 2);
                              const konvaY = firstBaselineY - (currItem.size * 0.76);

                              element = (
                                <Group>
                                  {bgFill && <Rect width={visualW} height={approxHeight} fill={bgFill} cornerRadius={2} listening={false} />}
                                  <Text
                                    text={substitutedText}
                                    x={pad}
                                    y={konvaY}
                                    width={availWidth}
                                    align={currItem.align || 'left'}
                                    fontFamily={fontFamily}
                                    fontStyle={(currItem.weight || 700).toString()}
                                    wrap={currItem.no_wrap ? "none" : "word"}
                                    fontSize={currItem.size}
                                    fill={fill}
                                    lineHeight={1.15}
                                  />
                                </Group>
                              );
                            } else if (currItem.type === 'icon_text') {
                              const fontFamily = currItem.font ? currItem.font.split('.')[0] : 'Arial';
                              const capHeight = currItem.size * 0.71;
                              const konvaY = currItem.text_y + capHeight - (currItem.size * 0.76);

                              element = (
                                <Group>
                                  <URLImage item={{ icon_src: currItem.icon_src }} commonProps={{ x: currItem.icon_x, y: currItem.icon_y, width: currItem.icon_size, height: currItem.icon_size }} isSelected={false} />
                                  <Text text={substitutedText} x={currItem.text_x} y={konvaY} fontSize={currItem.size} fontFamily={fontFamily} fontStyle={(currItem.weight || 700).toString()} fill={isSelected ? '#2563eb' : 'black'} padding={0} />
                                </Group>
                              );
                            } else if (currItem.type === 'shape') {
                              if (currItem.shapeType === 'rect') {
                                element = (
                                  <Rect
                                    width={visualW}
                                    height={approxHeight}
                                    fill={currItem.fill === 'transparent' ? undefined : currItem.fill}
                                    stroke={currItem.stroke !== 'transparent' ? currItem.stroke : undefined}
                                    strokeWidth={currItem.strokeWidth}
                                  />
                                );
                              } else if (currItem.shapeType === 'circle' || currItem.shapeType === 'ellipse') {
                                element = (
                                  <Ellipse
                                    x={visualW / 2}
                                    y={approxHeight / 2}
                                    radiusX={visualW / 2}
                                    radiusY={approxHeight / 2}
                                    fill={currItem.fill === 'transparent' ? undefined : currItem.fill}
                                    stroke={currItem.stroke !== 'transparent' ? currItem.stroke : undefined}
                                    strokeWidth={currItem.strokeWidth}
                                  />
                                );
                              } else if (currItem.shapeType === 'line') {
                                element = (
                                  <Line
                                    points={[0, 0, visualW, 0]}
                                    stroke={currItem.fill}
                                    strokeWidth={currItem.height}
                                    listening={false}
                                  />
                                );
                              }
                            } else if (currItem.type === 'barcode') {
                              element = (
                                <Group>
                                  <Rect width={visualW} height={approxHeight} fill="#e5e7eb" />
                                  <Text text="BARCODE" width={visualW} height={approxHeight} align="center" verticalAlign="middle" fill="#9ca3af" fontSize={14} fontStyle="bold" />
                                </Group>
                              );
                            } else if (currItem.type === 'qrcode') {
                              element = (
                                <Group>
                                  <Rect width={visualW} height={approxHeight} fill="#e5e7eb" />
                                  <Text text="QR" width={visualW} height={approxHeight} align="center" verticalAlign="middle" fill="#9ca3af" fontSize={Math.min(visualW, approxHeight) * 0.3} fontStyle="bold" />
                                </Group>
                              );
                            } else if (currItem.type === 'image') {
                              element = <URLImage item={currItem} commonProps={{ width: currItem.width, height: currItem.height }} isSelected={false} />;
                            } else if (currItem.type === 'html') {
                              const svgPayload = `<svg xmlns="http://www.w3.org/2000/svg" width="${visualW}" height="${approxHeight}"><foreignObject width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml" style="margin:0;padding:0;width:100%;height:100%;box-sizing:border-box;">${substitutedHtml || ''}</div></foreignObject></svg>`;
                              const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svgPayload);
                              element = <URLImage item={{ ...currItem, src: url }} commonProps={{ width: currItem.width, height: approxHeight }} isSelected={false} />;
                            } else if (currItem.type === 'cut_line_indicator') {
                              element = <Line points={currItem.isVertical ? [0, 0, 0, canvasHeight] : [0, 0, canvasWidth, 0]} stroke="gray" strokeWidth={1} dash={[10, 10]} listening={false} />;
                            }

                            const bThick = currItem.border_thickness || 4;
                            return (
                              <Group {...commonProps} key={`${currItem.id}-wrap`}>
                                {element}
                                {isSelected && currItem.type !== 'cut_line_indicator' && <Rect width={visualW} height={approxHeight} stroke="#2563eb" strokeWidth={2} dash={[4, 4]} fillEnabled={false} listening={false} />}
                                {currItem.border_style === 'box' && <Rect width={visualW} height={approxHeight} stroke="black" strokeWidth={bThick} listening={false} />}
                                {currItem.border_style === 'top' && <Line points={[0, 0, visualW, 0]} stroke="black" strokeWidth={bThick} listening={false} />}
                                {currItem.border_style === 'bottom' && <Line points={[0, approxHeight, visualW, approxHeight]} stroke="black" strokeWidth={bThick} listening={false} />}
                                {currItem.border_style === 'cut_line' && <Line points={[0, approxHeight + 2, visualW, approxHeight + 2]} stroke="black" strokeWidth={bThick} dash={[10, 10]} listening={false} />}
                              </Group>
                            );
                          };

                          return renderElement(item);
                        })}
                        
                        {isActive && snapLines.map((line, i) => (
                          <Line key={i} points={line.points} stroke={line.stroke} strokeWidth={1} dash={[4, 4]} />
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
                      </Layer>
                    </Stage>
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
