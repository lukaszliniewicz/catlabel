import React, { useEffect, useRef } from 'react';
import { Ellipse, Group, Image as KonvaImage, Line, Rect, Text } from 'react-konva';
import { applyVars, useCodeGenerator } from '../utils/rendering';
import { useStore } from '../store';
import { LABEL_TEMPLATE_STYLES, buildLabelTemplateMarkup } from './templateStyles';

const useImageLoader = (url) => {
  const [img, setImg] = React.useState(null);

  React.useEffect(() => {
    if (!url) {
      setImg(null);
      return undefined;
    }

    let cancelled = false;
    const image = new window.Image();
    image.src = url;
    image.onload = () => {
      if (!cancelled) {
        setImg(image);
      }
    };

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

const getVisualMetrics = (item, substitutedText) => {
  const textValue = substitutedText || '';
  const lineCount = textValue ? String(textValue).split('\n').length : 1;
  const pad = item.padding !== undefined ? Number(item.padding) : ((item.invert || item.bg_white) ? 4 : 0);
  const approxHeight = item.height || (
    item.type === 'text'
      ? (item.size * 1.15 * lineCount) + (pad * 2)
      : 50
  );

  return {
    visualW: item.width || 100,
    approxHeight,
    pad,
    lineCount
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

  const { visualW, approxHeight, pad, lineCount } = getVisualMetrics(item, substitutedText);
  const groupRef = useRef(null);

  useEffect(() => {
    if (isSelected && interactive && groupRef.current) {
      const tr = groupRef.current.getStage()?.findOne('Transformer');
      if (tr) {
        tr.nodes([groupRef.current]);
        tr.getLayer()?.batchDraw();
      }
    }
  }, [interactive, isSelected]);

  const commonProps = interactive
    ? {
        ref: groupRef,
        x: item.x,
        y: item.y,
        rotation: item.rotation || 0,
        draggable: item.type !== 'cut_line_indicator' && item.type !== 'label_template',
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

          useStore.getState().updateItem(item.id, {
            x: node.x(),
            y: node.y(),
            rotation: node.rotation(),
            width: Math.max(5, (item.width || 100) * scaleX),
            height: Math.max(5, approxHeight * scaleY)
          });
        }
      }
    : {
        x: item.x,
        y: item.y,
        rotation: item.rotation || 0
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
        {renderItemBorder(item, visualW, approxHeight)}
      </Group>
    );
  }

  let element = null;

  if (item.type === 'text') {
    const fontFamily = item.font ? item.font.split('.')[0] : 'Arial';
    const fontStyleAttr = [
      item.italic ? 'italic' : '',
      item.weight || 700
    ].filter(Boolean).join(' ') || 'normal';
    const actualColor = item.color || (item.invert ? 'white' : 'black');
    const actualBg = item.bgColor || (item.invert ? 'black' : (item.bg_white ? 'white' : 'transparent'));
    const capHeight = item.size * 0.71;
    const lineHeightPx = item.size * 1.15;
    const availWidth = Math.max(0, visualW - (pad * 2));
    const availHeight = Math.max(0, approxHeight - (pad * 2));
    const boxCenterY = pad + (availHeight / 2);
    const firstBaselineY = boxCenterY + (capHeight / 2) - ((lineCount - 1) * lineHeightPx / 2);
    const konvaY = firstBaselineY - (item.size * 0.76);

    element = (
      <Group>
        {actualBg !== 'transparent' && <Rect width={visualW} height={approxHeight} fill={actualBg} cornerRadius={2} listening={false} />}
        <Text
          text={substitutedText}
          x={pad}
          y={konvaY}
          width={availWidth}
          align={item.align || 'left'}
          fontFamily={fontFamily}
          fontStyle={fontStyleAttr}
          textDecoration={item.underline ? 'underline' : ''}
          wrap={item.no_wrap ? 'none' : 'word'}
          fontSize={item.size}
          fill={isSelected ? '#2563eb' : actualColor}
          lineHeight={1.15}
        />
      </Group>
    );
  } else if (item.type === 'icon_text') {
    const fontFamily = item.font ? item.font.split('.')[0] : 'Arial';
    const capHeight = item.size * 0.71;
    const konvaY = item.text_y + capHeight - (item.size * 0.76);

    element = (
      <Group>
        <Group x={item.icon_x} y={item.icon_y}>
          <URLImage src={item.icon_src} width={item.icon_size} height={item.icon_size} />
        </Group>
        <Text
          text={substitutedText}
          x={item.text_x}
          y={konvaY}
          fontSize={item.size}
          fontFamily={fontFamily}
          fontStyle={(item.weight || 700).toString()}
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
    const svgPayload = `<svg xmlns="http://www.w3.org/2000/svg" width="${visualW}" height="${approxHeight}"><foreignObject width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml" style="margin:0;padding:0;width:100%;height:100%;box-sizing:border-box;"><style>${LABEL_TEMPLATE_STYLES}</style>${templateMarkup}</div></foreignObject></svg>`;
    const src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgPayload)}`;
    element = <URLImage src={src} width={item.width} height={approxHeight} />;
  } else if (item.type === 'html') {
    const svgPayload = `<svg xmlns="http://www.w3.org/2000/svg" width="${visualW}" height="${approxHeight}"><foreignObject width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml" style="margin:0;padding:0;width:100%;height:100%;box-sizing:border-box;">${substitutedHtml || ''}</div></foreignObject></svg>`;
    const src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgPayload)}`;
    element = <URLImage src={src} width={item.width} height={approxHeight} />;
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
      {isSelected && item.type !== 'cut_line_indicator' && (
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
      {renderItemBorder(item, visualW, approxHeight)}
    </Group>
  );
}
