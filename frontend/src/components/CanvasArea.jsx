import React, { useRef } from 'react';
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
  const { items, selectedId, selectItem, updateItem, canvasWidth, canvasHeight, snapLines, setSnapLines, settings, isRotated } = useStore();
  
  // Calculate Paper Visuals (assuming 8 dots per mm for 203 DPI)
  const dotsPerMm = settings.default_dpi / 25.4;
  const paperPx = Math.round(settings.paper_width_mm * dotsPerMm); 
  const printPx = Math.round(settings.print_width_mm * dotsPerMm); // usually 384
  
  const sideMarginX = isRotated ? 0 : (paperPx - printPx) / 2;
  const sideMarginY = isRotated ? (paperPx - printPx) / 2 : 0;

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
    <div className="flex-1 flex flex-col items-center justify-center overflow-auto p-8 bg-neutral-100 dark:bg-neutral-900 transition-colors duration-300">
      <div className="mb-6 text-neutral-400 dark:text-neutral-500 text-[10px] uppercase tracking-widest font-bold">
        Paper Width: {settings.paper_width_mm}mm | Print Area: {settings.print_width_mm}mm
      </div>
      
      {/* Paper Visual Wrapper */}
      <div 
        className="bg-white shadow-2xl relative transition-all duration-300"
        style={{ width: isRotated ? canvasWidth : paperPx, height: isRotated ? paperPx : canvasHeight }}
      >
        {/* Red dashed lines denoting printable area boundaries */}
        {isRotated ? (
           <div style={{ position: 'absolute', left: 0, right: 0, top: sideMarginY, height: printPx, borderTop: '1px dashed #ef4444', borderBottom: '1px dashed #ef4444', pointerEvents: 'none' }} />
        ) : (
           <div style={{ position: 'absolute', left: sideMarginX, width: printPx, top: 0, bottom: 0, borderLeft: '1px dashed #ef4444', borderRight: '1px dashed #ef4444', pointerEvents: 'none' }} />
        )}
        
        {/* Actual Canvas offset to match the printable area */}
        <div style={{ marginLeft: isRotated ? 0 : sideMarginX, marginTop: isRotated ? sideMarginY : 0 }}>
          <Stage
            width={canvasWidth}
            height={isRotated ? printPx : canvasHeight}
            onMouseDown={(e) => { if (e.target === e.target.getStage()) selectItem(null); }}
          >
            <Layer>
              {items.map((item) => {
                const isSelected = item.id === selectedId;
                const commonProps = {
                  key: item.id, x: item.x, y: item.y, width: item.width, height: item.height,
                  draggable: true, onClick: () => selectItem(item.id), onTap: () => selectItem(item.id),
                  onDragMove: (e) => handleDragMove(e, item), onDragEnd: (e) => handleDragEnd(e, item)
                };

                if (item.type === 'text') {
                  // REMOVED PADDING entirely and mapped word wrapping
                  const fontFamily = item.font ? item.font.split('.')[0] : 'Arial';
                  return <Text {...commonProps} text={item.text} align={item.align || 'left'} fontFamily={fontFamily} wrap={item.no_wrap ? "none" : "word"} fontSize={item.size} fill={isSelected ? '#2563eb' : 'black'} padding={0} />;
                }

                if (item.type === 'icon_text') {
                  const fontFamily = item.font ? item.font.split('.')[0] : 'Arial';
                  return (
                    <Group {...commonProps}>
                      <URLImage item={{icon_src: item.icon_src}} commonProps={{x: item.icon_x, y: item.icon_y, width: item.icon_size, height: item.icon_size}} isSelected={false} />
                      <Text text={item.text} x={item.text_x} y={item.text_y} fontSize={item.size} fontFamily={fontFamily} fill={isSelected ? '#2563eb' : 'black'} padding={0} />
                      {isSelected && <Rect x={0} y={0} width={item.width || 100} height={item.height || 100} stroke="#2563eb" strokeWidth={2} dash={[4,4]} fillEnabled={false} listening={false} />}
                    </Group>
                  )
                }
                
                if (item.type === 'barcode') {
                  return <Rect {...commonProps} fill="#e5e7eb" stroke={isSelected ? '#2563eb' : '#9ca3af'} strokeWidth={isSelected ? 2 : 1} dash={isSelected ? [4, 4] : []} />;
                }

                if (item.type === 'image') {
                  // USE THE NEW ISOLATED COMPONENT
                  return <URLImage key={item.id} item={item} commonProps={commonProps} isSelected={isSelected} />;
                }
                return null;
              })}
              
              {/* Snapping Guides */}
              {snapLines.map((line, i) => (
                <Line key={i} points={line.points} stroke={line.stroke} strokeWidth={1} dash={[4, 4]} />
              ))}
            </Layer>
          </Stage>
        </div>
      </div>
      
      <div className="mt-8 text-neutral-400 dark:text-neutral-600 text-[10px] uppercase tracking-widest">
        Drag items to move. Click empty space to deselect.
      </div>
    </div>
  );
}
