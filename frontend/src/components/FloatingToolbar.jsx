import React from 'react';
import { useStore } from '../store';
import { calculateAutoFitItem } from '../utils/rendering';
import {
  AlignLeft, AlignCenter, AlignRight,
  AlignStartVertical, AlignCenterVertical, AlignEndVertical,
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

const HoverMenuGroup = ({ currentIcon: Icon, title, children }) => (
  <div className="relative group flex items-center" onMouseDown={(e) => e.stopPropagation()}>
    <div
      className="p-1.5 text-neutral-600 dark:text-neutral-400 cursor-default group-hover:text-neutral-900 dark:group-hover:text-white transition-colors"
      title={title}
    >
      <Icon size={16} strokeWidth={2.5} />
    </div>
    <div className="absolute bottom-full left-1/2 z-50 hidden -translate-x-1/2 group-hover:block pb-2">
      <div className="flex gap-1 rounded-lg border border-neutral-200 bg-white p-1 shadow-xl dark:border-neutral-700 dark:bg-neutral-800">
        {children}
      </div>
    </div>
  </div>
);

export default function FloatingToolbar({ item, zoomScale, canvasWidth, canvasHeight, workspacePad = 0 }) {
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
      verticalAlign: 'middle',
      fit_to_width: true
    };
    updated = calculateAutoFitItem(updated, useStore.getState().batchRecords, canvasWidth, canvasHeight);
    updateItem(item.id, updated);
  };

  const handleFitBox = () => {
    let updated = { ...item, fit_to_width: !item.fit_to_width };
    if (updated.fit_to_width) {
      updated = calculateAutoFitItem(updated, useStore.getState().batchRecords, canvasWidth, canvasHeight);
    }
    updateItem(item.id, updated);
  };

  const HAlignIcon = item.align === 'left' ? AlignLeft : item.align === 'right' ? AlignRight : AlignCenter;
  const VAlignIcon = item.verticalAlign === 'top' ? AlignStartVertical : item.verticalAlign === 'bottom' ? AlignEndVertical : AlignCenterVertical;

  const topPos = ((item.y + workspacePad) * zoomScale) - 48;
  const leftPos = (item.x + workspacePad) * zoomScale;

  return (
    <div
      className="absolute z-50 flex items-center gap-1 p-1 bg-white dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded-lg shadow-xl"
      style={{
        top: Math.max(-10, topPos),
        left: Math.max(0, leftPos),
        transform: 'translateY(-10px)'
      }}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <HoverMenuGroup currentIcon={HAlignIcon} title="Horizontal Alignment">
        <ToolbarButton icon={AlignLeft} active={item.align === 'left'} onClick={() => updateItem(item.id, { align: 'left' })} title="Align Left" />
        <ToolbarButton icon={AlignCenter} active={item.align === 'center' || !item.align} onClick={() => updateItem(item.id, { align: 'center' })} title="Align Center" />
        <ToolbarButton icon={AlignRight} active={item.align === 'right'} onClick={() => updateItem(item.id, { align: 'right' })} title="Align Right" />
      </HoverMenuGroup>

      <HoverMenuGroup currentIcon={VAlignIcon} title="Vertical Alignment">
        <ToolbarButton icon={AlignStartVertical} active={item.verticalAlign === 'top'} onClick={() => updateItem(item.id, { verticalAlign: 'top' })} title="Align Top" />
        <ToolbarButton icon={AlignCenterVertical} active={item.verticalAlign === 'middle' || !item.verticalAlign} onClick={() => updateItem(item.id, { verticalAlign: 'middle' })} title="Align Middle" />
        <ToolbarButton icon={AlignEndVertical} active={item.verticalAlign === 'bottom'} onClick={() => updateItem(item.id, { verticalAlign: 'bottom' })} title="Align Bottom" />
      </HoverMenuGroup>

      <div className="w-px h-5 bg-neutral-200 dark:bg-neutral-700 mx-1" />

      <ToolbarButton icon={Bold} active={item.weight >= 700} onClick={() => updateItem(item.id, { weight: item.weight >= 700 ? 400 : 700 })} title="Bold" />
      <ToolbarButton icon={Italic} active={item.italic} onClick={() => updateItem(item.id, { italic: !item.italic })} title="Italic" />
      <ToolbarButton
        icon={item.no_wrap ? ArrowRightToLine : WrapText}
        active={item.no_wrap}
        onClick={() => {
          const next = { ...item, no_wrap: !item.no_wrap };
          updateItem(
            item.id,
            next.fit_to_width
              ? calculateAutoFitItem(next, useStore.getState().batchRecords, canvasWidth, canvasHeight)
              : next
          );
        }}
        title={item.no_wrap ? 'Enable Word Wrap' : 'Force Single Line'}
      />

      <div className="w-px h-5 bg-neutral-200 dark:bg-neutral-700 mx-1" />

      <ToolbarButton icon={BoxSelect} active={item.fit_to_width} onClick={handleFitBox} title="Auto-Scale Font to Fit Box" />
      <ToolbarButton icon={Maximize} active={false} onClick={handleFillCanvas} title="Maximize to Fill Entire Canvas" />
    </div>
  );
}
