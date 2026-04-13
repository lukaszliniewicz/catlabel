import React from 'react';
import { useStore } from '../store';
import { calculateAutoFitItem } from '../utils/rendering';
import {
  AlignLeft, AlignCenter, AlignRight,
  Bold, Italic, Maximize, BoxSelect, WrapText, ArrowRightToLine
} from 'lucide-react';

const ToolbarButton = ({ icon: Icon, onClick, active, title }) => (
  <button
    onClick={(e) => {
      e.stopPropagation();
      onClick();
    }}
    title={title}
    className={`p-1.5 rounded transition-colors ${
      active
        ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-400'
        : 'text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-700 hover:text-neutral-900 dark:hover:text-white'
    }`}
  >
    <Icon size={16} strokeWidth={2.5} />
  </button>
);

export default function FloatingToolbar({ item, zoomScale, canvasWidth, canvasHeight }) {
  const updateItem = useStore((state) => state.updateItem);

  if (!item || item.type !== 'text') return null;

  const handleFillCanvas = () => {
    let updated = {
      ...item,
      x: 0,
      y: 0,
      width: canvasWidth,
      height: canvasHeight,
      align: 'center',
      fit_to_width: true,
    };
    updated = calculateAutoFitItem(updated);
    updateItem(item.id, updated);
  };

  const handleFitBox = () => {
    let updated = { ...item, fit_to_width: !item.fit_to_width };
    if (updated.fit_to_width) {
      updated = calculateAutoFitItem(updated);
    }
    updateItem(item.id, updated);
  };

  const topPos = (item.y * zoomScale) - 48;
  const leftPos = item.x * zoomScale;

  return (
    <div
      className="absolute z-50 flex items-center gap-1 p-1 bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-lg shadow-xl"
      style={{
        top: topPos < -10 ? -10 : topPos,
        left: leftPos < 0 ? 0 : leftPos,
        transform: 'translateY(-10px)',
      }}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <ToolbarButton icon={AlignLeft} active={item.align === 'left'} onClick={() => updateItem(item.id, { align: 'left' })} title="Align Left" />
      <ToolbarButton icon={AlignCenter} active={item.align === 'center'} onClick={() => updateItem(item.id, { align: 'center' })} title="Align Center" />
      <ToolbarButton icon={AlignRight} active={item.align === 'right'} onClick={() => updateItem(item.id, { align: 'right' })} title="Align Right" />

      <div className="w-px h-5 bg-neutral-200 dark:bg-neutral-700 mx-1" />

      <ToolbarButton icon={Bold} active={item.weight >= 700} onClick={() => updateItem(item.id, { weight: item.weight >= 700 ? 400 : 700 })} title="Bold" />
      <ToolbarButton icon={Italic} active={item.italic} onClick={() => updateItem(item.id, { italic: !item.italic })} title="Italic" />
      <ToolbarButton
        icon={item.no_wrap ? ArrowRightToLine : WrapText}
        active={item.no_wrap}
        onClick={() => updateItem(item.id, { no_wrap: !item.no_wrap })}
        title={item.no_wrap ? 'Enable Wrapping' : 'Force Single Line'}
      />

      <div className="w-px h-5 bg-neutral-200 dark:bg-neutral-700 mx-1" />

      <ToolbarButton icon={BoxSelect} active={item.fit_to_width} onClick={handleFitBox} title="Maximize inside Bounding Box" />
      <ToolbarButton icon={Maximize} active={false} onClick={handleFillCanvas} title="Maximize to Fill Entire Canvas" />
    </div>
  );
}
