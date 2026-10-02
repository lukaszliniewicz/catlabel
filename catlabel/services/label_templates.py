import re
from html import escape

TEMPLATE_MAP = {
    "default": {"container": "layout-default", "text": "text-standard", "sub": None},
    "center": {"container": "layout-center", "text": "text-standard", "sub": None},
    "maximize": {"container": "layout-center", "text": "text-maximized", "sub": None},
    "title_subtitle": {
        "container": "layout-flex-col",
        "text": "text-title",
        "sub": "text-subtitle",
    },
    "warning_banner": {
        "container": "layout-banner",
        "text": "text-bold-inverted",
        "sub": None,
    },
    "price_tag": {
        "container": "layout-price",
        "text": "text-huge-price",
        "sub": "text-product-name",
    },
    "address": {"container": "layout-address", "text": "text-address", "sub": None},
    "jar_apothecary": {"container": None, "text": None, "sub": None},
    "jar_farmhouse": {"container": None, "text": None, "sub": None},
    "custom": {"container": "layout-default", "text": None, "sub": None},
}

LABEL_TEMPLATE_STYLES = """
html, body {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
  background: white;
}
body {
  overflow: hidden;
}
.label-canvas-container {
  container-type: size;
  container-name: label;
  width: 100%;
  height: 100%;
  background-color: white;
  box-sizing: border-box;
  overflow: hidden;
  padding: 4cqmin;
  display: flex;
}
.label-canvas-container * {
  box-sizing: border-box;
}
.label-copy {
  max-width: 100%;
  max-height: 100%;
  overflow-wrap: anywhere;
}
.layout-default {
  justify-content: flex-start;
  align-items: flex-start;
}
.layout-center {
  justify-content: center;
  align-items: center;
  text-align: center;
}
.layout-flex-col {
  flex-direction: column;
  justify-content: center;
  align-items: center;
  text-align: center;
  gap: 4cqh;
}
.layout-banner {
  justify-content: center;
  align-items: center;
  text-align: center;
  padding: 0 6cqw;
  background: #111827;
  color: white;
}
.layout-price {
  flex-direction: column;
  justify-content: space-between;
  align-items: center;
  text-align: center;
  padding: 10cqh 5cqw;
}
.layout-address {
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  text-align: left;
  padding: 8cqh 10cqw;
}
.text-standard {
  width: 100%;
  font-size: 22cqh;
  font-weight: 700;
  line-height: 1.05;
}
.text-maximized {
  width: 100%;
  font-size: 72cqh;
  font-weight: 900;
  line-height: 0.85;
  text-align: center;
}
.text-title {
  width: 100%;
  font-size: 32cqh;
  font-weight: 900;
  line-height: 0.95;
}
.text-subtitle {
  width: 100%;
  font-size: 16cqh;
  font-weight: 600;
  line-height: 1.1;
}
.text-bold-inverted {
  width: 100%;
  font-size: 30cqh;
  font-weight: 900;
  line-height: 0.95;
  text-transform: uppercase;
}
.text-huge-price {
  font-size: 45cqh;
  font-weight: 900;
  line-height: 1;
}
.text-product-name {
  font-size: 15cqh;
  font-weight: 700;
  line-height: 1.1;
  text-transform: uppercase;
  color: #333333;
}
.text-address {
  width: 100%;
  font-size: 18cqh;
  font-weight: 700;
  line-height: 1.4;
  white-space: pre-wrap;
}
.auto-text-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Apothecary Style */
.apothecary {
  padding: 4cqmin;
}
.apothecary .inner {
  border: 4px solid black;
  height: 100%;
  width: 100%;
  outline: 2px solid black;
  outline-offset: -8px;
  display: flex;
  flex-direction: column;
  padding: 8cqmin;
  text-align: center;
}

/* Farmhouse Style */
.farmhouse {
  display: flex;
  flex-direction: column;
  border: 6px solid black;
  padding: 0 !important;
}
.farmhouse .stripes {
  height: 15cqh;
  background: repeating-linear-gradient(45deg, transparent, transparent 4px, black 4px, black 8px);
  border-bottom: 4px solid black;
}
.farmhouse .stripes.bottom {
  border-bottom: none;
  border-top: 4px solid black;
}
"""

_SCRIPT_RE = re.compile(r"<script[\s\S]*?>[\s\S]*?</script>", re.IGNORECASE)
_IFRAME_RE = re.compile(r"<iframe[\s\S]*?>[\s\S]*?</iframe>", re.IGNORECASE)
_EMBEDDED_RE = re.compile(r"<(object|embed|form)[\s\S]*?>[\s\S]*?</\1>", re.IGNORECASE)
_VOID_RE = re.compile(
    r"<(input|button|textarea|select|link|meta)[^>]*?/?>", re.IGNORECASE
)
_EVENT_HANDLER_RE = re.compile(r"\son\w+\s*=\s*(\".*?\"|'.*?'|[^\s>]+)", re.IGNORECASE)
_JS_PROTOCOL_RE = re.compile(r"javascript\s*:", re.IGNORECASE)


def sanitize_custom_html(html: str) -> str:
    if not html:
        return ""

    result = str(html)
    result = _SCRIPT_RE.sub("", result)
    result = _IFRAME_RE.sub("", result)
    result = _EMBEDDED_RE.sub("", result)
    result = _VOID_RE.sub("", result)
    result = _EVENT_HANDLER_RE.sub("", result)
    result = _JS_PROTOCOL_RE.sub("", result)
    return result.strip()


def _format_text(value: str) -> str:
    return escape(str(value or "")).replace("\n", "<br />")


def build_label_template_markup(
    *,
    template_id: str,
    text: str = "",
    title: str = "",
    subtitle: str = "",
    custom_html: str = "",
) -> str:
    active_template = TEMPLATE_MAP.get(template_id, TEMPLATE_MAP["default"])

    if template_id == "custom":
        safe_html = sanitize_custom_html(custom_html)
        return (
            '<div class="label-canvas-container">'
            f'<div style="width:100%;height:100%;">{safe_html}</div>'
            "</div>"
        )

    if template_id == "jar_apothecary":
        return (
            '<div class="label-canvas-container apothecary">'
            '<div class="inner">'
            f'<div style="font-size: 16cqh; letter-spacing: 4px; font-weight: 700; margin-bottom: auto;">{_format_text(text or "PREMIUM")}</div>'
            '<div class="auto-text-wrapper" style="flex: 2; margin: 8cqmin 0;">'
            f'<div class="auto-text" style="font-weight: 900; text-transform: uppercase; font-family: serif;">{_format_text(title)}</div>'
            "</div>"
            '<div style="display: flex; align-items: center; justify-content: center; gap: 8px; margin: 8cqmin 0;">'
            '<div style="height: 2px; background: black; width: 40px;"></div>'
            '<span style="font-size: 16cqh;">✧</span>'
            '<div style="height: 2px; background: black; width: 40px;"></div>'
            "</div>"
            '<div class="auto-text-wrapper" style="flex: 1;">'
            f'<div class="auto-text" style="font-style: italic; font-weight: bold; font-family: serif;">{_format_text(subtitle)}</div>'
            "</div>"
            "</div>"
            "</div>"
        )

    if template_id == "jar_farmhouse":
        return (
            '<div class="label-canvas-container farmhouse">'
            '<div class="stripes"></div>'
            '<div style="flex: 1; display: flex; flex-direction: column; align-items: center; padding: 6cqmin; text-align: center;">'
            '<div class="auto-text-wrapper" style="flex: 2; width: 100%;">'
            f'<div class="auto-text" style="font-weight: 900; text-transform: uppercase; font-style: italic; font-family: serif;">{_format_text(title)}</div>'
            "</div>"
            '<div style="width: 100%; height: 4px; background: black; margin: 12cqmin 0;"></div>'
            '<div class="auto-text-wrapper" style="width: 100%; flex: 1;">'
            f'<div class="auto-text" style="font-weight: bold; letter-spacing: 4px; text-transform: uppercase;">{_format_text(subtitle)}</div>'
            "</div>"
            "</div>"
            '<div class="stripes bottom"></div>'
            "</div>"
        )

    if template_id in {"title_subtitle", "price_tag"}:
        return (
            f'<div class="label-canvas-container {active_template["container"]}">'
            f'<div class="label-copy {active_template["text"]}">{_format_text(title)}</div>'
            f'<div class="label-copy {active_template["sub"]}">{_format_text(subtitle)}</div>'
            "</div>"
        )

    return (
        f'<div class="label-canvas-container {active_template["container"]}">'
        f'<div class="label-copy {active_template["text"]}">{_format_text(text)}</div>'
        "</div>"
    )


def build_label_template_document(
    *,
    template_id: str,
    text: str = "",
    title: str = "",
    subtitle: str = "",
    custom_html: str = "",
) -> str:
    markup = build_label_template_markup(
        template_id=template_id,
        text=text,
        title=title,
        subtitle=subtitle,
        custom_html=custom_html,
    )
    return (
        "<!DOCTYPE html>"
        "<html>"
        "<head>"
        '<meta charset="utf-8" />'
        f"<style>{LABEL_TEMPLATE_STYLES}</style>"
        "</head>"
        f"<body>{markup}</body>"
        "</html>"
    )
