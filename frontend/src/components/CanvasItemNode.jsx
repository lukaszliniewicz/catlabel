import React, { useEffect, useRef, useState } from 'react';
import { Ellipse, Group, Image as KonvaImage, Line, Rect, Text } from 'react-konva';
import { toPng } from 'html-to-image';
import { applyVars, calculateAutoFitItem, computeOptimalTextSize, resolveDim, useCodeGenerator } from '../utils/rendering';
import { useStore } from '../store';
import { LABEL_TEMPLATE_STYLES, buildLabelTemplateMarkup } from './templateStyles';

const useHtmlRasterizer = (htmlString, width, height, isTemplate = false) => {
  const [img, setImg] = useState(null);

  useEffect(() => {
    if (!htmlString || width <= 0 || height <= 0) {
      setImg(null);
      return undefined;
    }

    let cancelled = false;
    const container = document.createElement('div');
    container.style.position = 'fixed';
    container.style.left = '-9999px';
    container.style.top = '0';
    container.style.width = `${width}px`;
    container.style.height = `${height}px`;
    container.style.overflow = 'hidden';
    container.style.boxSizing = 'border-box';
    container.style.pointerEvents = 'none';
    container.style.backgroundColor = 'transparent';
    container.innerHTML = isTemplate
      ? `<style>${LABEL_TEMPLATE_STYLES}</style>${htmlString}`
      : htmlString;

    document.body.appendChild(container);

    const rasterize = async () => {
      const autoTexts = container.querySelectorAll('.auto-text');

      autoTexts.forEach((el) => {
        let low = 4;
        let high = 500;
        let best = 4;

        const targetW = el.clientWidth || el.parentElement?.clientWidth || width;
        const targetH = el.clientHeight || el.parentElement?.clientHeight || height;

        while (high - low >= 0.5) {
          const mid = (low + high) / 2;
          el.style.fontSize = `${mid}px`;

          if (el.scrollWidth <= targetW && el.scrollHeight <= targetH) {
            best = mid;
            low = mid + 0.5;
          } else {
            high = mid - 0.5;
          }
        }

        el.style.fontSize = `${Math.floor(best)}px`;
      });

      try {
        if (document.fonts?.ready) {
          await document.fonts.ready;
        }
      } catch (error) {
        console.warn('Font readiness check failed', error);
      }

      requestAnimationFrame(() => {
        requestAnimationFrame(async () => {
          try {
            const dataUrl = await toPng(container, {
              pixelRatio: 1,
              useCORS: true
            });

            if (cancelled) {
              return;
            }

            const imageObj = new window.Image();
            imageObj.onload = () => {
              if (!cancelled) {
                setImg(imageObj);
              }
            };
            imageObj.onerror = () => {
              if (!cancelled) {
                setImg(null);
              }
            };
            imageObj.src = dataUrl;
          } catch (error) {
            console.error('Rasterization failed', error);
            if (!cancelled) {
              setImg(null);
            }
          } finally {
            if (document.body.contains(container)) {
              document.body.removeChild(container);
            }
          }
        });
      });
    };

    rasterize();

    return () => {
      cancelled = true;
      if (document.body.contains(container)) {
        document.body.removeChild(container);
      }
    };
  }, [htmlString, width, height, isTemplate]);

  return img;
};

const RasterizedHtml = ({ html, width, height, isTemplate = false }) => {
  const image = useHtmlRasterizer(html, width, height, isTemplate);

  if (!image) {
    return null;
  }

  return <KonvaImage image={image} width={width} height={height} />;
};

const useImageLoader = (url) => {
  const [img, setImg] = React.useState(null);

  React.useEffect(() => {
    if (!url) {
      setImg(null);
      return undefined;
    }

    let cancelled = false;
    const image = new window.Image();

    image.onload = () => {
      if (!cancelled) {
        setImg(image);
      }
    };

    image.onerror = () => {
      console.warn('Failed to load image or SVG on canvas:', `${String(url).substring(0, 50)}...`);
      if (!cancelled) {
        setImg(null);
      }
    };

    image.src = url;

    return () => {
      cancelled = true;
    };
  }, [url]);

  return img;
};

const URLImage = ({ src, width, height }) => {
  const image = useImageLoader(src);
  return <KonvaImage image={image} width={width} height={height} />;
};

const CodeImage = ({ type, data, barcodeType, width, height }) => {
  const src = useCodeGenerator(type, data, barcodeType);

  if (!src) {
    return <Rect width={width} height={height} fill="#e5e7eb" />;
  }

  return <URLImage src={src} width={width} height={height} />;
};

const getVisualMetrics = (item, substitutedText, canvasWidth, canvasHeight) => {
  const textValue = substitutedText || '';
  const lineCount = textValue ? String(textValue).split('\n').length : 1;
  const pad = item.padding !== undefined ? Number(item.padding) : 0;
  const actualLineHeight = item.lineHeight ?? (lineCount > 1 ? 1.15 : 1);

  const visualW = resolveDim(item.width || 100, canvasWidth);
  const approxHeight = resolveDim(item.height, canvasHeight) || (
    item.type === 'text'
      ? (item.size * actualLineHeight * lineCount) + (pad * 2)
      : 50
  );

  return {
    visualW,
    approxHeight,
    pad,
    lineCount,
    actualLineHeight
  };
};

const renderItemBorder = (item, visualW, approxHeight) => {
  const thickness = item.border_thickness || 4;

  if (item.border_style === 'box') {
    return <Rect width={visualW} height={approxHeight} stroke="black" strokeWidth={thickness} listening={false} />;
  }

  if (item.border_style === 'top') {
    return <Line points={[0, 0, visualW, 0]} stroke="black" strokeWidth={thickness} listening={false} />;
  }

  if (item.border_style === 'bottom') {
    return <Line points={[0, approxHeight, visualW, approxHeight]} stroke="black" strokeWidth={thickness} listening={false} />;
  }

  if (item.border_style === 'cut_line') {
    return <Line points={[0, approxHeight + 2, visualW, approxHeight + 2]} stroke="black" strokeWidth={thickness} dash={[10, 10]} listening={false} />;
  }

  return null;
};

export default function CanvasItemNode({
  item,
  record,
  canvasWidth,
  canvasHeight,
  isSelected = false,
  interactive = false,
  onMouseDown,
  onTouchStart,
  onDragMove,
  onDragEnd
}) {
  const substitutedText = applyVars(item.text, record);
  const substitutedTitle = applyVars(item.title, record);
  const substitutedSubtitle = applyVars(item.subtitle, record);
  const substitutedHtml = applyVars(item.html, record);
  const substitutedCustomHtml = applyVars(item.custom_html, record);
  const substitutedData = applyVars(item.data, record);

  const { visualW, approxHeight, actualLineHeight, pad: activePad } = getVisualMetrics(item, substitutedText, canvasWidth, canvasHeight);
  const groupRef = useRef(null);

  let activeItem = item;
  if (item.type === 'text' && item.fit_to_width && item.batch_scale_mode === 'individual') {
    const targetWidth = Math.max(10, visualW - (activePad * 2));
    const targetHeight = Math.max(10, approxHeight - (activePad * 2));
    const dynamicSize = computeOptimalTextSize(item, substitutedText, targetWidth, targetHeight);
    activeItem = { ...item, size: dynamicSize };
  }

  const resolvedX = resolveDim(activeItem.x, canvasWidth);
  const resolvedY = resolveDim(activeItem.y, canvasHeight);

  const commonProps = interactive
    ? {
        ref: groupRef,
        id: `node-${item.id}`,
        x: resolvedX,
        y: resolvedY,
        rotation: activeItem.rotation || 0,
        draggable: activeItem.type !== 'cut_line_indicator' && activeItem.type !== 'label_template',
        onMouseDown,
        onTouchStart,
        onDragMove,
        onDragEnd,
        onTransformEnd: () => {
          const node = groupRef.current;
          if (!node) return;

          const scaleX = node.scaleX();
          const scaleY = node.scaleY();

          node.scaleX(1);
          node.scaleY(1);

          let updatedItem = {
            ...item,
            x: node.x(),
            y: node.y(),
            rotation: node.rotation(),
            width: Math.max(5, (item.width || 100) * scaleX),
            height: Math.max(5, approxHeight * scaleY)
          };

          if (item.type === 'text' && item.fit_to_width) {
            updatedItem = calculateAutoFitItem(updatedItem, useStore.getState().batchRecords);
          }

          useStore.getState().updateItem(item.id, updatedItem);
        }
      }
    : {
        x: resolvedX,
        y: resolvedY,
        rotation: activeItem.rotation || 0
      };

  if (item.type === 'group') {
    return (
      <Group {...commonProps}>
        {(item.children || []).map((child) => (
          <CanvasItemNode
            key={child.id}
            item={child}
            record={record}
            canvasWidth={canvasWidth}
            canvasHeight={canvasHeight}
          />
        ))}
        {renderItemBorder(item, visualW, approxHeight)}
      </Group>
    );
  }

  let element = null;

  if (item.type === 'text') {
    const fontFamily = activeItem.font ? activeItem.font.split('.')[0] : 'Arial';
    const fontStyleAttr = [
      activeItem.italic ? 'italic' : '',
      activeItem.weight || 700
    ].filter(Boolean).join(' ') || 'normal';
    const actualColor = activeItem.color || (activeItem.invert ? 'white' : 'black');
    const actualBg = activeItem.bgColor || (activeItem.invert ? 'black' : (activeItem.bg_white ? 'white' : 'transparent'));
    const availWidth = Math.max(0, visualW - (activePad * 2));
    const availHeight = Math.max(0, approxHeight - (activePad * 2));

    element = (
      <Group>
        {actualBg !== 'transparent' && <Rect width={visualW} height={approxHeight} fill={actualBg} cornerRadius={2} listening={false} />}
        <Text
          text={substitutedText}
          x={activePad}
          y={activePad}
          width={availWidth}
          height={availHeight}
          align={activeItem.align || 'center'}
          verticalAlign={activeItem.verticalAlign || 'middle'}
          fontFamily={fontFamily}
          fontStyle={fontStyleAttr}
          textDecoration={activeItem.underline ? 'underline' : ''}
          wrap={activeItem.no_wrap ? 'none' : 'word'}
          fontSize={activeItem.size}
          fill={isSelected ? '#2563eb' : actualColor}
          lineHeight={actualLineHeight}
        />
      </Group>
    );
  } else if (item.type === 'icon_text') {
    const fontFamily = activeItem.font ? activeItem.font.split('.')[0] : 'Arial';
    const capHeight = activeItem.size * 0.71;
    const konvaY = activeItem.text_y + capHeight - (activeItem.size * 0.76);

    element = (
      <Group>
        <Group x={activeItem.icon_x} y={activeItem.icon_y}>
          <URLImage src={activeItem.icon_src} width={activeItem.icon_size} height={activeItem.icon_size} />
        </Group>
        <Text
          text={substitutedText}
          x={activeItem.text_x}
          y={konvaY}
          width={activeItem.width ? Math.max(0, visualW - activeItem.text_x) : undefined}
          align={activeItem.align || 'left'}
          fontSize={activeItem.size}
          fontFamily={fontFamily}
          fontStyle={(activeItem.weight || 700).toString()}
          fill={isSelected ? '#2563eb' : 'black'}
          padding={0}
        />
      </Group>
    );
  } else if (item.type === 'shape') {
    if (item.shapeType === 'rect') {
      element = (
        <Rect
          width={visualW}
          height={approxHeight}
          fill={item.fill === 'transparent' ? undefined : item.fill}
          stroke={item.stroke !== 'transparent' ? item.stroke : undefined}
          strokeWidth={item.strokeWidth}
        />
      );
    } else if (item.shapeType === 'circle' || item.shapeType === 'ellipse') {
      element = (
        <Ellipse
          x={visualW / 2}
          y={approxHeight / 2}
          radiusX={visualW / 2}
          radiusY={approxHeight / 2}
          fill={item.fill === 'transparent' ? undefined : item.fill}
          stroke={item.stroke !== 'transparent' ? item.stroke : undefined}
          strokeWidth={item.strokeWidth}
        />
      );
    } else if (item.shapeType === 'line') {
      element = (
        <Line
          points={[0, 0, visualW, 0]}
          stroke={item.fill}
          strokeWidth={item.height}
          listening={false}
        />
      );
    }
  } else if (item.type === 'barcode' || item.type === 'qrcode') {
    element = (
      <CodeImage
        type={item.type}
        data={substitutedData || substitutedText || ''}
        barcodeType={item.barcode_type}
        width={visualW}
        height={approxHeight}
      />
    );
  } else if (item.type === 'image') {
    element = <URLImage src={item.src} width={item.width} height={item.height} />;
  } else if (item.type === 'label_template') {
    const templateMarkup = buildLabelTemplateMarkup({
      ...item,
      text: substitutedText,
      title: substitutedTitle,
      subtitle: substitutedSubtitle,
      custom_html: substitutedCustomHtml
    });
    element = (
      <RasterizedHtml
        html={templateMarkup}
        width={visualW}
        height={approxHeight}
        isTemplate
      />
    );
  } else if (item.type === 'html') {
    element = (
      <RasterizedHtml
        html={substitutedHtml || ''}
        width={visualW}
        height={approxHeight}
      />
    );
  } else if (item.type === 'cut_line_indicator') {
    element = (
      <Line
        points={item.isVertical ? [0, 0, 0, canvasHeight] : [0, 0, canvasWidth, 0]}
        stroke="gray"
        strokeWidth={1}
        dash={[10, 10]}
        listening={false}
      />
    );
  }

  return (
    <Group {...commonProps}>
      {element}
      {renderItemBorder(item, visualW, approxHeight)}
    </Group>
  );
}
