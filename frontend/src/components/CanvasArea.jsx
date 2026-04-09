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
  const { items, selectedId, selectItem, updateItem, canvasWidth, canvasHeight, canvasBorder, snapLines, setSnapLines, settings, isRotated } = useStore();
  
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
    <div className="flex-1 flex flex-col items-center overflow-auto p-8 bg-neutral-100 dark:bg-neutral-900 transition-colors duration-300">
      <div className="mb-6 text-neutral-400 dark:text-neutral-500 text-[10px] uppercase tracking-widest font-bold">
        Canvas Feed Engine: {isRotated ? "Landscape" : "Portrait"}
      </div>
      
      <div 
        className="bg-white shadow-2xl relative transition-all duration-300"
        style={{ width: canvasWidth, height: canvasHeight }}
      >
        <Stage
          width={canvasWidth}
          height={canvasHeight}
          onMouseDown={(e) => { if (e.target === e.target.getStage()) selectItem(null); }}
        >
          <Layer>
            {/* Canvas Border Background Renders */}
            {canvasBorder === 'box' && <Rect x={0} y={0} width={canvasWidth} height={canvasHeight} stroke="black" strokeWidth={2} listening={false} />}
            {canvasBorder === 'top' && <Line points={[0, 0, canvasWidth, 0]} stroke="black" strokeWidth={2} listening={false} />}
            {canvasBorder === 'bottom' && <Line points={[0, canvasHeight, canvasWidth, canvasHeight]} stroke="black" strokeWidth={2} listening={false} />}
            {canvasBorder === 'cut_line' && <Line points={[0, canvasHeight, canvasWidth, canvasHeight]} stroke="black" strokeWidth={2} dash={[10, 10]} listening={false} />}

            {items.map((item) => {
              const isSelected = item.id === selectedId;
              
              const numLines = item.text ? String(item.text).split('\n').length : 1;
              const approxHeight = item.height || (item.type === 'text' ? item.size * 1.2 * numLines : 50);
              const yOffset = item.y;
                
              const visualW = item.width || 100;
                
              const commonProps = {
                key: item.id, x: item.x, y: yOffset, width: item.width, height: item.height,
                draggable: item.type !== 'cut_line_indicator', 
                onClick: () => selectItem(item.id), 
                onTap: () => selectItem(item.id),
                onDragMove: (e) => handleDragMove(e, item), 
                onDragEnd: (e) => handleDragEnd(e, item)
              };

              let element = null;

              if (item.type === 'text') {
                const fontFamily = item.font ? item.font.split('.')[0] : 'Arial';
                const fill = item.invert ? 'white' : (isSelected ? '#2563eb' : 'black');
                const bgFill = item.invert ? 'black' : (item.bg_white ? 'white' : null);
                element = (
                  <Group {...commonProps}>
                    {bgFill && <Rect width={item.width || canvasWidth} height={approxHeight} fill={bgFill} />}
                    <Text text={item.text} width={item.width} align={item.align || 'left'} fontFamily={fontFamily} wrap={item.no_wrap ? "none" : "word"} fontSize={item.size} fill={fill} padding={0} />
                  </Group>
                );
              } else if (item.type === 'icon_text') {
                const fontFamily = item.font ? item.font.split('.')[0] : 'Arial';
                element = (
                  <Group {...commonProps}>
                    <URLImage item={{icon_src: item.icon_src}} commonProps={{x: item.icon_x, y: item.icon_y, width: item.icon_size, height: item.icon_size}} isSelected={false} />
                    <Text text={item.text} x={item.text_x} y={item.text_y} fontSize={item.size} fontFamily={fontFamily} fill={isSelected ? '#2563eb' : 'black'} padding={0} />
                  </Group>
                )
              } else if (item.type === 'barcode') {
                element = <Rect {...commonProps} fill="#e5e7eb" />;
              } else if (item.type === 'image') {
                element = <URLImage item={item} commonProps={commonProps} isSelected={false} />;
              } else if (item.type === 'html') {
                // Dynamically build SVG data string to natively render the HTML payload.
                const svgPayload = `<svg xmlns="http://www.w3.org/2000/svg" width="${visualW}" height="${approxHeight}"><foreignObject width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml" style="margin:0;padding:0;width:100%;height:100%;box-sizing:border-box;">${item.html || ''}</div></foreignObject></svg>`;
                const url = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svgPayload);
                element = <URLImage item={{...item, src: url}} commonProps={{...commonProps, height: approxHeight}} isSelected={false} />;
              } else if (item.type === 'cut_line_indicator') {
                element = <Line points={item.isVertical ? [item.x, item.y, item.x, canvasHeight] : [item.x, item.y, canvasWidth, item.y]} stroke="gray" strokeWidth={1} dash={[10, 10]} listening={false} />;
              }

              return (
                <Group key={`${item.id}-wrap`}>
                  {element}
                  {isSelected && item.type !== 'cut_line_indicator' && <Rect x={item.x} y={item.y} width={visualW} height={approxHeight} stroke="#2563eb" strokeWidth={2} dash={[4,4]} fillEnabled={false} listening={false} />}
                  
                  {item.border_style === 'box' && <Rect x={item.x} y={yOffset} width={visualW} height={approxHeight} stroke="black" strokeWidth={2} listening={false} />}
                  {item.border_style === 'top' && <Line points={[item.x, yOffset, item.x + visualW, yOffset]} stroke="black" strokeWidth={2} listening={false} />}
                  {item.border_style === 'bottom' && <Line points={[item.x, yOffset + approxHeight, item.x + visualW, yOffset + approxHeight]} stroke="black" strokeWidth={2} listening={false} />}
                  {item.border_style === 'cut_line' && <Line points={[item.x, yOffset + approxHeight + 2, item.x + visualW, yOffset + approxHeight + 2]} stroke="black" strokeWidth={2} dash={[10, 10]} listening={false} />}
                </Group>
              );
            })}
            
            {snapLines.map((line, i) => (
              <Line key={i} points={line.points} stroke={line.stroke} strokeWidth={1} dash={[4, 4]} />
            ))}
          </Layer>
        </Stage>
      </div>
      
      <div className="mt-8 text-neutral-400 dark:text-neutral-600 text-[10px] uppercase tracking-widest">
        Drag items to move. Click empty space to deselect.
      </div>
    </div>
  );
}
