import React, { useState, useRef, useEffect } from 'react';
import { useStore } from '../store';
import {
  Type, Calendar, Smile, ImagePlus, Image as ImageIcon,
  Barcode, QrCode, Code, FileText, Wand2, ChevronDown, Package, Trash2
} from 'lucide-react';

import IconPicker from './IconPicker';
import HtmlPickerModal from './HtmlPickerModal';
import ShippingLabelModal from './ShippingLabelModal';
import DateToolModal from './DateToolModal';

const ToolButton = ({ icon: Icon, label, onClick, component: Component = 'button', active = false, children }) => (
  <Component
    onClick={onClick}
    className={`relative group p-2.5 rounded transition-colors cursor-pointer flex items-center justify-center ${
      active
        ? 'bg-neutral-100 dark:bg-neutral-800 text-neutral-900 dark:text-white'
        : 'text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:text-neutral-900 dark:hover:text-white'
    }`}
  >
    <Icon size={18} strokeWidth={2} />
    {children}
    <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 text-[10px] uppercase font-bold tracking-widest px-2.5 py-1.5 rounded opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-[60] shadow-md">
      {label}
    </div>
  </Component>
);

export default function Toolbar() {
  const { addItem, clearCanvas, canvasWidth, canvasHeight } = useStore();

  const [showIconPicker, setShowIconPicker] = useState(false);
  const [iconPickerMode, setIconPickerMode] = useState('icon');
  const [showHtmlPicker, setShowHtmlPicker] = useState(false);
  const [showShippingModal, setShowShippingModal] = useState(false);
  const [showDateModal, setShowDateModal] = useState(false);
  const [showGenDropdown, setShowGenDropdown] = useState(false);

  const dropdownRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setShowGenDropdown(false);
      }
    };

    if (showGenDropdown) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showGenDropdown]);

  const handleAddText = () => {
    const defaultFont = useStore.getState().settings.default_font || 'Roboto.ttf';
    addItem({
      id: Date.now().toString(),
      type: 'text',
      text: 'Text',
      x: 0,
      y: 50,
      size: 24,
      weight: 700,
      font: defaultFont,
      width: canvasWidth,
      height: 24,
      align: 'center'
    });
  };

  const handleAddHtml = (htmlContent) => {
    addItem({
      id: Date.now().toString(),
      type: 'html',
      html: htmlContent,
      x: 0,
      y: 0,
      width: canvasWidth,
      height: canvasHeight
    });
    setShowHtmlPicker(false);
  };

  const handleAddIconText = (base64Png) => {
    const defaultFont = useStore.getState().settings.default_font || 'Roboto.ttf';
    addItem({
      id: Date.now().toString(),
      type: 'icon_text',
      x: 10,
      y: 10,
      icon_src: base64Png,
      icon_x: 0,
      icon_y: 0,
      icon_size: 40,
      text: 'Icon + Text',
      text_x: 46,
      text_y: 10,
      size: 24,
      weight: 700,
      font: defaultFont,
      text_width: 150,
      align: 'left',
      width: 196,
      height: 40
    });
    setShowIconPicker(false);
  };

  const handleAddIcon = (base64Png) => {
    if (iconPickerMode === 'icon_text') {
      handleAddIconText(base64Png);
    } else {
      addItem({
        id: Date.now().toString(),
        type: 'image',
        src: base64Png,
        x: 0,
        y: 0,
        width: 100,
        height: 100
      });
      setShowIconPicker(false);
    }
  };

  const handleAddBarcode = () => {
    addItem({
      id: Date.now().toString(),
      type: 'barcode',
      data: '123456789',
      barcode_type: 'code128',
      x: 50,
      y: 100,
      width: 200,
      height: 50
    });
  };

  const handleAddImage = (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (ev) => {
      const img = new window.Image();
      img.src = ev.target.result;
      img.onload = () => {
        const ratio = img.width / img.height;
        const targetWidth = Math.min(img.width, canvasWidth);
        const targetHeight = targetWidth / ratio;
        addItem({
          id: Date.now().toString(),
          type: 'image',
          src: ev.target.result,
          x: 0,
          y: 0,
          width: targetWidth,
          height: targetHeight
        });
      };
    };
    reader.readAsDataURL(file);
    e.target.value = null;
  };

  const handleAddPdf = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/pdf/convert', {
        method: 'POST',
        body: formData
      });
      if (!res.ok) throw new Error('PDF processing failed');
      const data = await res.json();

      let currentY = 0;
      for (let i = 0; i < data.images.length; i++) {
        const b64 = data.images[i];
        await new Promise((resolve) => {
          const img = new window.Image();
          img.src = b64;
          img.onload = () => {
            const ratio = img.width / img.height;
            const targetWidth = Math.min(img.width, useStore.getState().canvasWidth);
            const targetHeight = targetWidth / ratio;
            useStore.getState().addItem({
              id: Date.now().toString() + '-' + i,
              type: 'image',
              src: b64,
              x: 0,
              y: currentY,
              width: targetWidth,
              height: targetHeight
            });
            currentY += targetHeight + 10;
            resolve();
          };
        });
      }
    } catch (err) {
      console.error(err);
      alert('Failed to process PDF file.');
    }

    e.target.value = null;
  };

  return (
    <div className="h-14 bg-white dark:bg-neutral-950 border-b border-neutral-200 dark:border-neutral-800 flex items-center px-4 justify-between shrink-0 z-20">
      <div className="flex items-center gap-1">
        <ToolButton icon={Type} label="Add Text" onClick={handleAddText} />
        <ToolButton icon={Calendar} label="Add Date" onClick={() => setShowDateModal(true)} />

        <div className="w-px h-6 bg-neutral-200 dark:bg-neutral-800 mx-2" />

        <ToolButton icon={Smile} label="Icon Only" onClick={() => { setIconPickerMode('icon'); setShowIconPicker(true); }} />
        <ToolButton icon={ImagePlus} label="Icon + Text" onClick={() => { setIconPickerMode('icon_text'); setShowIconPicker(true); }} />
        <ToolButton component="label" icon={ImageIcon} label="Upload Image">
          <input type="file" accept="image/*" className="hidden" onChange={handleAddImage} />
        </ToolButton>

        <div className="w-px h-6 bg-neutral-200 dark:bg-neutral-800 mx-2" />

        <ToolButton icon={Barcode} label="Barcode" onClick={handleAddBarcode} />
        <ToolButton
          icon={QrCode}
          label="QR Code"
          onClick={() => addItem({
            id: Date.now().toString(),
            type: 'qrcode',
            data: 'https://example.com',
            x: 50,
            y: 100,
            width: 120,
            height: 120
          })}
        />

        <div className="w-px h-6 bg-neutral-200 dark:bg-neutral-800 mx-2" />

        <ToolButton icon={Code} label="Custom HTML" onClick={() => setShowHtmlPicker(true)} />
        <ToolButton component="label" icon={FileText} label="Import PDF">
          <input type="file" accept="application/pdf" className="hidden" onChange={handleAddPdf} />
        </ToolButton>
        <ToolButton icon={Trash2} label="Clear Canvas" onClick={clearCanvas} />
      </div>

      <div className="flex items-center relative" ref={dropdownRef}>
        <ToolButton
          icon={Wand2}
          label="Generate"
          onClick={() => setShowGenDropdown(!showGenDropdown)}
          active={showGenDropdown}
        >
          <ChevronDown
            size={12}
            className={`absolute right-1 bottom-1 pointer-events-none transition-transform ${showGenDropdown ? 'rotate-180' : ''}`}
          />
        </ToolButton>

        {showGenDropdown && (
          <div className="absolute top-full right-0 mt-2 w-56 bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 rounded-md shadow-xl py-2 z-50">
            <div className="px-4 pb-2 mb-2 border-b border-neutral-100 dark:border-neutral-800 text-[10px] uppercase tracking-widest font-bold text-neutral-400">
              Smart Wizards
            </div>
            <button
              onClick={() => { setShowShippingModal(true); setShowGenDropdown(false); }}
              className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors text-left"
            >
              <Package size={16} className="text-blue-500" />
              Shipping Label
            </button>
          </div>
        )}
      </div>

      {showIconPicker && <IconPicker onClose={() => setShowIconPicker(false)} onSelect={handleAddIcon} />}
      {showHtmlPicker && <HtmlPickerModal onClose={() => setShowHtmlPicker(false)} onSelect={handleAddHtml} />}
      {showShippingModal && <ShippingLabelModal onClose={() => setShowShippingModal(false)} />}
      {showDateModal && <DateToolModal onClose={() => setShowDateModal(false)} />}
    </div>
  );
}
