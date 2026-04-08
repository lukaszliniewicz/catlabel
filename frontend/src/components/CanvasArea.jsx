import React from 'react';
import { Stage, Layer, Text, Rect } from 'react-konva';
import { useStore } from '../store';

export default function CanvasArea() {
  const { items, selectedId, selectItem, updateItem, canvasWidth, canvasHeight } = useStore();

  return (
    <div className="flex-1 flex flex-col items-center justify-center overflow-auto p-8 bg-gray-100">
      <div className="mb-4 text-gray-500 text-sm font-medium">
        Canvas Size: {canvasWidth} x {canvasHeight} px
      </div>
      
      <div 
        className="bg-white shadow-md border border-gray-300" 
        style={{ width: canvasWidth, height: canvasHeight }}
      >
        <Stage
          width={canvasWidth}
          height={canvasHeight}
          onMouseDown={(e) => {
            // Deselect when clicking on empty area
            const clickedOnEmpty = e.target === e.target.getStage();
            if (clickedOnEmpty) {
              selectItem(null);
            }
          }}
        >
          <Layer>
            {items.map((item) => {
              const isSelected = item.id === selectedId;
              
              if (item.type === 'text') {
                return (
                  <Text
                    key={item.id}
                    text={item.text}
                    x={item.x}
                    y={item.y}
                    fontSize={item.size}
                    draggable
                    onClick={() => selectItem(item.id)}
                    onTap={() => selectItem(item.id)}
                    onDragEnd={(e) => {
                      updateItem(item.id, {
                        x: e.target.x(),
                        y: e.target.y(),
                      });
                    }}
                    fill={isSelected ? '#2563eb' : 'black'}
                    padding={4}
                  />
                );
              }
              
              if (item.type === 'barcode') {
                return (
                  <Rect
                    key={item.id}
                    x={item.x}
                    y={item.y}
                    width={item.width}
                    height={item.height}
                    fill="#e5e7eb" // Placeholder for barcode visual
                    draggable
                    onClick={() => selectItem(item.id)}
                    onTap={() => selectItem(item.id)}
                    onDragEnd={(e) => {
                      updateItem(item.id, {
                        x: e.target.x(),
                        y: e.target.y(),
                      });
                    }}
                    stroke={isSelected ? '#2563eb' : '#9ca3af'}
                    strokeWidth={isSelected ? 2 : 1}
                    dash={isSelected ? [4, 4] : []}
                  />
                );
              }
              
              return null;
            })}
          </Layer>
        </Stage>
      </div>
      
      <div className="mt-4 text-gray-400 text-xs">
        Drag items to move them. Click empty space to deselect.
      </div>
    </div>
  );
}
