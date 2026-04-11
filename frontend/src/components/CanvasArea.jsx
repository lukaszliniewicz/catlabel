import React from 'react';
import { Stage, Layer, Text, Rect, Line, Group, Image as KonvaImage } from 'react-konva';
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
  const { items, selectedId, selectItem, updateItem, canvasWidth, canvasHeight, canvasBorder, canvasBorderThickness, snapLines, setSnapLines, settings, isRotated, currentPage, setCurrentPage, addPage, deletePage, togglePageForPrint, selectedPagesForPrint, printPages } = useStore();
  
  const { splitMode } = useStore();
  const cvThick = canvasBorderThickness || 4;
  const dotsPerMm = settings.default_dpi / 25.4;
  const printPx = Math.round(settings.print_width_mm * dotsPerMm);
  const batchRecords = useStore(state => state.batchRecords) || [{}];
  const visibleRecords = batchRecords.slice(0, 10);
  const maxPage = items.reduce((max, item) => Math.max(max, Number(item.pageIndex ?? 0)), 0);
  const maxDisplayedPage = Math.max(maxPage, currentPage);
  const pages = Array.from({ length: maxDisplayedPage + 1 }, (_, i) => i);

  const applyVars = (str, record) => {
    if (!str || !record) return str;
    let res = String(str);
    Object.keys(record).forEach((key) => {
      const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`{{\\s*${escapedKey}\\s*}}`, 'g');
      res = res.replace(regex, String(record[key] ?? ''));
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
    updateItem(item.id, { x: e.target.x(), y: e.target.y() });
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
                    style={{ width: canvasWidth, height: canvasHeight }}
                    onClick={() => {
                      if (!isActive) {
                        setCurrentPage(pageIndex);
                      }
                    }}
                  >
                    <Stage
                      width={canvasWidth}
                      height={canvasHeight}
                      onMouseDown={(e) => {
                        setCurrentPage(pageIndex);
                        if (e.target === e.target.getStage()) selectItem(null);
                      }}
                    >
                      <Layer>
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
                          const isSelected = item.id === selectedId;
                          const substitutedText = applyVars(item.text, record);
                          const substitutedHtml = applyVars(item.html, record);
                          
                          const numLines = substitutedText ? String(substitutedText).split('\n').length : 1;
                          const pad = item.padding !== undefined ? Number(item.padding) : ((item.invert || item.bg_white) ? 4 : 0);
                          const approxHeight = item.height || (item.type === 'text' ? (item.size * 1.15 * numLines) + (pad * 2) : 50);
                          const yOffset = item.y;
                            
                          const visualW = item.width || 100;
                            
                          const commonProps = {
                            key: item.id, x: item.x, y: yOffset, width: item.width, height: item.height,
                            draggable: item.type !== 'cut_line_indicator', 
                            onClick: () => { setCurrentPage(pageIndex); selectItem(item.id); }, 
                            onTap: () => { setCurrentPage(pageIndex); selectItem(item.id); },
                            onDragMove: (e) => handleDragMove(e, item), 
                            onDragEnd: (e) => handleDragEnd(e, item)
                          };

                          let element = null;

                          if (item.type === 'text') {
                            const fontFamily = item.font ? item.font.split('.')[0] : 'Arial';
                            const fill = item.invert ? 'white' : (isSelected ? '#2563eb' : 'black');
                            const bgFill = item.invert ? 'black' : (item.bg_white ? 'white' : null);
                            const capHeight = item.size * 0.71;
                            const lineHeightPx = item.size * 1.15;
                            const availWidth = Math.max(0, visualW - (pad * 2));
                            const availHeight = Math.max(0, approxHeight - (pad * 2));
                            const boxCenterY = pad + (availHeight / 2);
                            const firstBaselineY = boxCenterY + (capHeight / 2) - ((numLines - 1) * lineHeightPx / 2);
                            const konvaY = firstBaselineY - (item.size * 0.76);
                            
                            element = (
                              <Group {...commonProps}>
                                {bgFill && <Rect width={visualW} height={approxHeight} fill={bgFill} cornerRadius={2} listening={false} />}
                                <Text 
                                  text={substitutedText} 
                                  x={pad}
                                  y={konvaY}
                                  width={availWidth}
                                  align={item.align || 'left'} 
                                  fontFamily={fontFamily} 
                                  fontStyle={(item.weight || 700).toString()}
                                  wrap={item.no_wrap ? "none" : "word"} 
                                  fontSize={item.size} 
                                  fill={fill} 
                                  lineHeight={1.15}
                                />
                              </Group>
                            );
                          } else if (item.type === 'icon_text') {
                            const fontFamily = item.font ? item.font.split('.')[0] : 'Arial';
                            const capHeight = item.size * 0.71;
                            const baselineY = item.text_y + capHeight;
                            const konvaY = baselineY - (item.size * 0.76);

                            element = (
                              <Group {...commonProps}>
                                <URLImage item={{icon_src: item.icon_src}} commonProps={{x: item.icon_x, y: item.icon_y, width: item.icon_size, height: item.icon_size}} isSelected={false} />
                                <Text text={substitutedText} x={item.text_x} y={konvaY} fontSize={item.size} fontFamily={fontFamily} fontStyle={(item.weight || 700).toString()} fill={isSelected ? '#2563eb' : 'black'} padding={0} />
                              </Group>
                            )
                          } else if (item.type === 'barcode') {
                            element = (
                              <Group {...commonProps}>
                                <Rect width={visualW} height={approxHeight} fill="#e5e7eb" />
                                <Text text="BARCODE" width={visualW} height={approxHeight} align="center" verticalAlign="middle" fill="#9ca3af" fontSize={14} fontStyle="bold" />
                              </Group>
                            );
                          } else if (item.type === 'qrcode') {
                            element = (
                              <Group {...commonProps}>
                                <Rect width={visualW} height={approxHeight} fill="#e5e7eb" />
                                <Text text="QR" width={visualW} height={approxHeight} align="center" verticalAlign="middle" fill="#9ca3af" fontSize={Math.min(visualW, approxHeight) * 0.3} fontStyle="bold" />
                              </Group>
                            );
                          } else if (item.type === 'image') {
                            element = <URLImage item={item} commonProps={commonProps} isSelected={false} />;
                          } else if (item.type === 'html') {
                            // Dynamically build SVG data string to natively render the HTML payload.
                            const svgPayload = `<svg xmlns="http://www.w3.org/2000/svg" width="${visualW}" height="${approxHeight}"><foreignObject width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml" style="margin:0;padding:0;width:100%;height:100%;box-sizing:border-box;">${substitutedHtml || ''}</div></foreignObject></svg>`;
                            const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svgPayload);
                            element = <URLImage item={{...item, src: url}} commonProps={{...commonProps, height: approxHeight}} isSelected={false} />;
                          } else if (item.type === 'cut_line_indicator') {
                            element = <Line points={item.isVertical ? [item.x, item.y, item.x, canvasHeight] : [item.x, item.y, canvasWidth, item.y]} stroke="gray" strokeWidth={1} dash={[10, 10]} listening={false} />;
                          }

                          const bThick = item.border_thickness || 4;
                          return (
                            <Group key={`${item.id}-wrap`}>
                              {element}
                              {isSelected && item.type !== 'cut_line_indicator' && <Rect x={item.x} y={item.y} width={visualW} height={approxHeight} stroke="#2563eb" strokeWidth={2} dash={[4,4]} fillEnabled={false} listening={false} />}
                              
                              {item.border_style === 'box' && <Rect x={item.x} y={yOffset} width={visualW} height={approxHeight} stroke="black" strokeWidth={bThick} listening={false} />}
                              {item.border_style === 'top' && <Line points={[item.x, yOffset, item.x + visualW, yOffset]} stroke="black" strokeWidth={bThick} listening={false} />}
                              {item.border_style === 'bottom' && <Line points={[item.x, yOffset + approxHeight, item.x + visualW, yOffset + approxHeight]} stroke="black" strokeWidth={bThick} listening={false} />}
                              {item.border_style === 'cut_line' && <Line points={[item.x, yOffset + approxHeight + 2, item.x + visualW, yOffset + approxHeight + 2]} stroke="black" strokeWidth={bThick} dash={[10, 10]} listening={false} />}
                            </Group>
                          );
                        })}
                        
                        {isActive && snapLines.map((line, i) => (
                          <Line key={i} points={line.points} stroke={line.stroke} strokeWidth={1} dash={[4, 4]} />
                        ))}
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
