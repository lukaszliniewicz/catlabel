import uuid


def _id():
    return str(uuid.uuid4())


def _text_item(
    x,
    y,
    w,
    h,
    text,
    size=40,
    weight=700,
    align="center",
    fit=True,
    invert=False,
    no_wrap=False,
):
    return {
        "id": _id(),
        "type": "text",
        "text": text,
        "x": int(x),
        "y": int(y),
        "width": int(w),
        "height": int(h),
        "size": int(size),
        "weight": weight,
        "align": align,
        "fit_to_width": fit,
        "no_wrap": no_wrap,
        "invert": invert,
        "font": "Roboto.ttf",
    }


def build_centered_text(width, height, params):
    return [
        _text_item(10, 10, width - 20, height - 20, params.get("text", "Text"), size=120)
    ]


def build_title_subtitle(width, height, params):
    return [
        _text_item(
            10,
            height * 0.1,
            width - 20,
            height * 0.4,
            params.get("title", "Title"),
            size=80,
            weight=900,
        ),
        _text_item(
            10,
            height * 0.5,
            width - 20,
            height * 0.4,
            params.get("subtitle", "Subtitle"),
            size=40,
            weight=400,
        ),
    ]


def build_price_tag(width, height, params):
    items = []
    has_barcode = bool(params.get("barcode", "").strip())

    price_h = height * 0.5 if has_barcode else height * 0.6
    name_h = height * 0.2 if has_barcode else height * 0.3

    items.append(
        _text_item(
            10,
            10,
            width - 20,
            price_h,
            params.get("price", "$0.00"),
            size=120,
            weight=900,
        )
    )
    items.append(
        _text_item(
            10,
            price_h + 10,
            width - 20,
            name_h,
            params.get("product_name", "Product Name"),
            size=40,
            weight=700,
        )
    )

    if has_barcode:
        bc_y = price_h + name_h + 10
        bc_h = height - bc_y - 10
        items.append(
            {
                "id": _id(),
                "type": "barcode",
                "barcode_type": "code128",
                "data": params.get("barcode", "123456"),
                "x": int(width * 0.1),
                "y": int(bc_y),
                "width": int(width * 0.8),
                "height": int(bc_h),
            }
        )
    return items


def build_inventory_tag(width, height, params):
    code_type = params.get("code_type", "qrcode").lower()
    data = params.get("code_data", "INV-001")
    title = params.get("title", "Item Name")

    code_size = min(width * 0.8, height * 0.5)
    code_x = (width - code_size) / 2

    return [
        {
            "id": _id(),
            "type": code_type if code_type in ["qrcode", "barcode"] else "qrcode",
            "data": data,
            "x": int(code_x),
            "y": int(height * 0.05),
            "width": int(code_size),
            "height": int(code_size),
        },
        _text_item(10, height * 0.6, width - 20, height * 0.15, data, size=30, weight=900),
        _text_item(10, height * 0.75, width - 20, height * 0.2, title, size=24, weight=400),
    ]


def build_cable_flag(width, height, params):
    mid_x = width / 2
    text = params.get("text", "CABLE-01")

    return [
        {
            "id": _id(),
            "type": "cut_line_indicator",
            "isVertical": True,
            "x": int(mid_x),
            "y": 0,
            "width": int(width),
            "height": int(height),
        },
        _text_item(10, 10, mid_x - 20, height - 20, text, size=60),
        _text_item(mid_x + 10, 10, mid_x - 20, height - 20, text, size=60),
    ]


def build_shipping_address(width, height, params):
    w = max(width, height)
    h = min(width, height)

    return [
        _text_item(
            16,
            16,
            w * 0.45,
            h * 0.22,
            f"FROM:\n{params.get('sender', 'Sender Address')}",
            size=24,
            align="left",
        ),
        {
            "id": _id(),
            "type": "shape",
            "shapeType": "line",
            "x": 0,
            "y": int(h * 0.3),
            "width": int(w),
            "height": 4,
            "fill": "black",
        },
        _text_item(16, h * 0.35, 120, h * 0.1, "SHIP TO:", size=24, invert=True, no_wrap=True),
        _text_item(
            16,
            h * 0.48,
            w - 32,
            h * 0.45,
            params.get("recipient", "Recipient Address"),
            size=48,
            align="left",
            weight=900,
        ),
    ]


def build_warning_banner(width, height, params):
    return [
        _text_item(
            10,
            10,
            width - 20,
            height - 20,
            params.get("text", "WARNING"),
            size=100,
            weight=900,
            invert=True,
        )
    ]


TEMPLATE_REGISTRY = {
    "centered_text": build_centered_text,
    "title_subtitle": build_title_subtitle,
    "price_tag": build_price_tag,
    "inventory_tag": build_inventory_tag,
    "cable_flag": build_cable_flag,
    "shipping_address": build_shipping_address,
    "warning_banner": build_warning_banner,
}


TEMPLATE_METADATA = [
    {
        "id": "centered_text",
        "name": "Centered Text",
        "description": "A single, auto-scaling text block.",
        "fields": [{"name": "text", "label": "Main Text", "type": "textarea"}],
    },
    {
        "id": "title_subtitle",
        "name": "Title & Subtitle",
        "description": "Stacked text with a large bold title.",
        "fields": [
            {"name": "title", "label": "Title", "type": "text"},
            {"name": "subtitle", "label": "Subtitle", "type": "text"},
        ],
    },
    {
        "id": "price_tag",
        "name": "Price Tag",
        "description": "Large price, product name, and optional barcode.",
        "fields": [
            {"name": "price", "label": "Price", "type": "text"},
            {"name": "product_name", "label": "Product Name", "type": "text"},
            {"name": "barcode", "label": "Barcode (Leave blank to omit)", "type": "text"},
        ],
    },
    {
        "id": "inventory_tag",
        "name": "Inventory / Asset Tag",
        "description": "QR/Barcode with identifying text below.",
        "fields": [
            {
                "name": "code_type",
                "label": "Code Type (qrcode or barcode)",
                "type": "text",
                "default": "qrcode",
            },
            {"name": "code_data", "label": "Code Data", "type": "text"},
            {"name": "title", "label": "Item Name", "type": "text"},
        ],
    },
    {
        "id": "cable_flag",
        "name": "Cable Flag",
        "description": "Fold-over tag with a dashed center line. Repeats text on both sides.",
        "fields": [{"name": "text", "label": "Cable ID / Text", "type": "text"}],
    },
    {
        "id": "shipping_address",
        "name": "Shipping Address",
        "description": "Standard landscape shipping layout.",
        "fields": [
            {"name": "sender", "label": "Sender Address", "type": "textarea"},
            {"name": "recipient", "label": "Recipient Address", "type": "textarea"},
        ],
    },
    {
        "id": "warning_banner",
        "name": "Warning Banner",
        "description": "Inverted black background with bold white text.",
        "fields": [
            {
                "name": "text",
                "label": "Warning Text",
                "type": "text",
                "default": "FRAGILE",
            }
        ],
    },
]


def generate_template_items(template_id: str, width: int, height: int, params: dict):
    """Executes the requested template and returns the list of layout items."""
    generator = TEMPLATE_REGISTRY.get(template_id)
    if not generator:
        return None
    return generator(width, height, params)
