import React, { useMemo } from 'react';
import parse, { attributesToProps, domToReact } from 'html-react-parser';
import { AutoTextSize } from 'auto-text-size';
import { applyVars } from '../utils/rendering';

const overlayBaseStyle = {
  position: 'absolute',
  pointerEvents: 'none',
  boxSizing: 'border-box'
};

export default function HtmlLabel({
  html,
  record,
  width,
  height,
  canvasBorder = 'none',
  canvasBorderThickness = 4
}) {
  const processedHtml = useMemo(() => applyVars(html || '', record), [html, record]);
  const borderThickness = Math.max(1, Number(canvasBorderThickness) || 4);

  const parsedContent = useMemo(() => {
    const options = {
      replace: (domNode) => {
        if (domNode?.name !== 'div' || !domNode.attribs) {
          return undefined;
        }

        const className = String(domNode.attribs.class || '');
        if (!className.split(/\s+/).includes('auto-text')) {
          return undefined;
        }

        const parsedProps = attributesToProps(domNode.attribs || {});
        const finalStyle = {
          width: '100%',
          height: '100%',
          minWidth: 0,
          minHeight: 0,
          ...(parsedProps.style || {})
        };

        return (
          <div {...parsedProps} style={finalStyle}>
            <AutoTextSize mode="box" maxFontSizePx={300}>
              {domToReact(domNode.children || [], options)}
            </AutoTextSize>
          </div>
        );
      }
    };

    return parse(processedHtml || '', options);
  }, [processedHtml]);

  return (
    <div
      style={{
        width,
        height,
        overflow: 'hidden',
        position: 'relative',
        backgroundColor: 'white'
      }}
    >
      <div style={{ width: '100%', height: '100%' }}>
        {parsedContent}
      </div>
      {canvasBorder === 'box' && (
        <div
          style={{
            ...overlayBaseStyle,
            inset: 0,
            border: `${borderThickness}px solid black`
          }}
        />
      )}
      {canvasBorder === 'top' && (
        <div
          style={{
            ...overlayBaseStyle,
            top: 0,
            left: 0,
            right: 0,
            height: borderThickness,
            backgroundColor: 'black'
          }}
        />
      )}
      {canvasBorder === 'bottom' && (
        <div
          style={{
            ...overlayBaseStyle,
            bottom: 0,
            left: 0,
            right: 0,
            height: borderThickness,
            backgroundColor: 'black'
          }}
        />
      )}
      {canvasBorder === 'cut_line' && (
        <div
          style={{
            ...overlayBaseStyle,
            bottom: 0,
            left: 0,
            right: 0,
            borderBottom: `${borderThickness}px dashed black`
          }}
        />
      )}
    </div>
  );
}
