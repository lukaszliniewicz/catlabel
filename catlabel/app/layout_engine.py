import uuid


def _id():
    return str(uuid.uuid4())


def _shape_item(x, y, w, h, fill="black", shape_type="rect"):
    return {
        "id": _id(),
        "type": "shape",
        "shapeType": shape_type,
        "x": int(x),
        "y": int(y),
        "width": int(w),
        "height": int(h),
        "fill": fill,
        "stroke": "transparent",
        "strokeWidth": 0,
    }


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
    color="black",
    bg_color="transparent",
    italic=False,
    underline=False,
    rotation=0,
    no_wrap=False,
    invert=False,
):
    resolved_color = "white" if invert and color == "black" else color
    resolved_bg_color = "black" if invert and bg_color == "transparent" else bg_color

    item = {
        "id": _id(),
        "type": "text",
        "text": text,
        "x": int(x),
        "y": int(y),
        "width": int(w),
        "height": int(h),
        "size": float(size),
        "weight": weight,
        "align": align,
        "fit_to_width": fit,
        "no_wrap": no_wrap,
        "color": resolved_color,
        "bgColor": resolved_bg_color,
        "italic": italic,
        "underline": underline,
        "rotation": rotation,
        "font": "RobotoCondensed.ttf",
    }
    if invert:
        item["invert"] = True
    if resolved_bg_color == "white":
        item["bg_white"] = True
    return item


def build_centered_text(width, height, params):
    text = params.get("text", "Text")
    return [
        _text_item(
            10,
            10,
            width - 20,
            height - 20,
            text,
            size=int(min(width, height) * 0.4),
            align="center",
            fit=True,
        )
    ]


def build_title_subtitle(width, height, params):
    title = params.get("title", "Title")
    subtitle = params.get("subtitle", "Subtitle")

    items = []
    is_landscape = width > (height * 1.5)

    if is_landscape:
        title_w = width * 0.55
        items.append(
            _text_item(
                10,
                10,
                title_w - 20,
                height - 20,
                title,
                size=int(height * 0.5),
                weight=900,
                align="left",
                fit=True,
            )
        )
        items.append(_shape_item(title_w, height * 0.1, 4, height * 0.8, "black"))
        items.append(
            _text_item(
                title_w + 15,
                10,
                width - title_w - 25,
                height - 20,
                subtitle,
                size=int(height * 0.25),
                weight=400,
                align="left",
                fit=True,
            )
        )
    else:
        title_h = height * 0.5
        items.append(
            _text_item(
                10,
                10,
                width - 20,
                title_h,
                title,
                size=int(title_h * 0.5),
                weight=900,
                align="center",
                fit=True,
            )
        )
        items.append(_shape_item(width * 0.15, title_h + 5, width * 0.7, 4, "black"))
        items.append(
            _text_item(
                10,
                title_h + 15,
                width - 20,
                height - title_h - 25,
                subtitle,
                size=int(height * 0.15),
                weight=400,
                align="center",
                fit=True,
            )
        )

    return items


def build_price_tag(width, height, params):
    items = []
    has_barcode = bool(params.get("barcode", "").strip())
    currency = params.get("currency_symbol", "$")
    main = params.get("price_main", "19")
    cents = params.get("price_cents", "99")
    unit = params.get("unit", "")
    name = params.get("product_name", "Product Name")

    full_price = f"{currency}{main}.{cents} {unit}".strip()

    is_landscape = width > (height * 1.3)
    is_micro = height <= 150

    if is_landscape:
        if is_micro:
            price_w = width * 0.55
            items.append(
                _text_item(
                    10,
                    10,
                    price_w - 15,
                    height - 20,
                    full_price,
                    size=int(height * 0.6),
                    weight=900,
                    align="left",
                    fit=True,
                    no_wrap=True,
                )
            )
            items.append(
                _text_item(
                    price_w + 5,
                    10,
                    width - price_w - 15,
                    height - 20,
                    name,
                    size=int(height * 0.4),
                    weight=700,
                    align="right",
                    fit=True,
                )
            )
        else:
            left_w = width * 0.65 if has_barcode else width
            items.append(
                _text_item(
                    10,
                    10,
                    left_w - 20,
                    height * 0.45,
                    full_price,
                    size=int(height * 0.35),
                    weight=900,
                    align="left",
                    fit=True,
                    no_wrap=True,
                )
            )
            items.append(_shape_item(10, height * 0.5, left_w - 20, 4, "black"))
            items.append(
                _text_item(
                    10,
                    height * 0.55,
                    left_w - 20,
                    height * 0.35,
                    name,
                    size=int(height * 0.25),
                    weight=700,
                    align="left",
                    fit=True,
                )
            )

            if has_barcode:
                items.append(
                    {
                        "id": _id(),
                        "type": "barcode",
                        "barcode_type": "code128",
                        "data": params.get("barcode", "123456"),
                        "x": int(left_w),
                        "y": int(height * 0.1),
                        "width": int(width * 0.35 - 10),
                        "height": int(height * 0.8),
                    }
                )
    else:
        if width <= 150:
            items.append(
                _text_item(
                    10,
                    10,
                    width - 20,
                    height * 0.5 - 10,
                    full_price,
                    size=int(width * 0.4),
                    weight=900,
                    align="center",
                    fit=True,
                    no_wrap=True,
                )
            )
            items.append(
                _text_item(
                    10,
                    height * 0.5,
                    width - 20,
                    height * 0.5 - 10,
                    name,
                    size=int(width * 0.3),
                    weight=700,
                    align="center",
                    fit=True,
                )
            )
        else:
            price_h = height * 0.35 if has_barcode else height * 0.45
            name_h = height * 0.2 if has_barcode else height * 0.3

            items.append(
                _text_item(
                    10,
                    10,
                    width - 20,
                    price_h,
                    full_price,
                    size=int(price_h * 0.8),
                    weight=900,
                    align="center",
                    fit=True,
                    no_wrap=True,
                )
            )
            items.append(_shape_item(width * 0.1, price_h + 5, width * 0.8, 4, "black"))
            items.append(
                _text_item(
                    10,
                    price_h + 15,
                    width - 20,
                    name_h,
                    name,
                    size=int(name_h * 0.6),
                    weight=700,
                    align="center",
                    fit=True,
                )
            )

            if has_barcode:
                bc_y = price_h + name_h + 20
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
    dept = params.get("department", "WAREHOUSE")
    sku = params.get("sku", "SKU-123")

    items = []
    is_landscape = width > (height * 1.3)

    if is_landscape:
        qr_size = min(width * 0.35, height - 20)
        items.append(
            {
                "id": _id(),
                "type": code_type if code_type in ["qrcode", "barcode"] else "qrcode",
                "data": data,
                "x": 10,
                "y": int((height - qr_size) / 2),
                "width": int(qr_size),
                "height": int(qr_size),
            }
        )

        right_x = qr_size + 20
        right_w = width - right_x - 10

        dept_h = height * 0.25
        items.append(
            _text_item(
                right_x,
                10,
                right_w,
                dept_h,
                dept,
                size=int(dept_h * 0.7),
                weight=900,
                invert=True,
                align="center",
                fit=True,
            )
        )
        items.append(
            _text_item(
                right_x,
                10 + dept_h + 5,
                right_w,
                height * 0.35,
                title,
                size=int(height * 0.25),
                weight=900,
                align="left",
                fit=True,
            )
        )
        items.append(
            _text_item(
                right_x,
                height - (height * 0.25) - 10,
                right_w,
                height * 0.25,
                sku,
                size=int(height * 0.15),
                weight=700,
                align="left",
                fit=True,
            )
        )

    else:
        dept_h = height * 0.18
        items.append(
            _text_item(
                0,
                0,
                width,
                dept_h,
                dept,
                size=int(dept_h * 0.7),
                weight=900,
                invert=True,
                align="center",
                fit=True,
            )
        )

        code_size = min(width * 0.7, height * 0.45)
        code_x = (width - code_size) / 2
        code_y = dept_h + 10

        items.append(
            {
                "id": _id(),
                "type": code_type if code_type in ["qrcode", "barcode"] else "qrcode",
                "data": data,
                "x": int(code_x),
                "y": int(code_y),
                "width": int(code_size),
                "height": int(code_size),
            }
        )

        text_y = code_y + code_size + 10
        items.append(
            _text_item(
                10,
                text_y,
                width - 20,
                height * 0.15,
                title,
                size=int(height * 0.12),
                weight=900,
                align="center",
                fit=True,
            )
        )
        items.append(
            _text_item(
                10,
                text_y + (height * 0.15),
                width - 20,
                height * 0.1,
                sku,
                size=int(height * 0.08),
                weight=700,
                align="center",
                fit=True,
            )
        )

    return items


def build_cable_flag(width, height, params):
    text = params.get("text", "CABLE-01")
    is_landscape = width > height
    items = []

    if is_landscape:
        mid_x = width / 2
        items.append(
            {
                "id": _id(),
                "type": "cut_line_indicator",
                "isVertical": True,
                "x": int(mid_x),
                "y": 0,
                "width": int(width),
                "height": int(height),
            }
        )
        items.append(
            _text_item(
                10,
                10,
                mid_x - 20,
                height - 20,
                text,
                size=int(height * 0.4),
                align="center",
                fit=True,
                no_wrap=True,
            )
        )
        items.append(
            _text_item(
                mid_x + 10,
                10,
                mid_x - 20,
                height - 20,
                text,
                size=int(height * 0.4),
                align="center",
                fit=True,
                no_wrap=True,
            )
        )
    else:
        mid_y = height / 2
        items.append(
            {
                "id": _id(),
                "type": "cut_line_indicator",
                "isVertical": False,
                "x": 0,
                "y": int(mid_y),
                "width": int(width),
                "height": int(height),
            }
        )
        items.append(
            _text_item(
                10,
                10,
                width - 20,
                mid_y - 20,
                text,
                size=int(width * 0.25),
                align="center",
                fit=True,
                no_wrap=True,
            )
        )
        items.append(
            _text_item(
                10,
                mid_y + 10,
                width - 20,
                mid_y - 20,
                text,
                size=int(width * 0.25),
                align="center",
                fit=True,
                no_wrap=True,
            )
        )

    return items


def build_shipping_address(width, height, params):
    sender = params.get("sender", "Sender Address")
    recipient = params.get("recipient", "Recipient Address")
    service = params.get("service", "STANDARD")

    items = []
    is_landscape = width > height

    if is_landscape:
        banner_w = width * 0.15
        items.append(
            _text_item(
                0,
                0,
                banner_w,
                height,
                service,
                size=int(banner_w * 0.5),
                weight=900,
                align="center",
                invert=True,
                fit=True,
            )
        )

        content_x = banner_w + 10
        content_w = width - banner_w - 20

        sender_h = height * 0.25
        items.append(
            _text_item(
                content_x,
                10,
                content_w * 0.6,
                sender_h,
                f"FROM:\n{sender}",
                size=int(sender_h * 0.25),
                weight=700,
                align="left",
                fit=True,
            )
        )

        items.append(_shape_item(content_x, sender_h + 10, content_w, 4, "black"))

        recip_y = sender_h + 20
        items.append(
            _text_item(
                content_x,
                recip_y,
                100,
                height * 0.1,
                "SHIP TO:",
                size=int(height * 0.08),
                invert=True,
                align="center",
                no_wrap=True,
            )
        )
        items.append(
            _text_item(
                content_x,
                recip_y + (height * 0.1) + 10,
                content_w,
                height - recip_y - (height * 0.1) - 20,
                recipient,
                size=int(height * 0.15),
                weight=900,
                align="left",
                fit=True,
            )
        )
    else:
        banner_h = height * 0.12
        items.append(
            _text_item(
                0,
                0,
                width,
                banner_h,
                service,
                size=int(banner_h * 0.6),
                weight=900,
                align="center",
                invert=True,
                fit=True,
            )
        )

        sender_h = height * 0.2
        items.append(
            _text_item(
                10,
                banner_h + 10,
                width - 20,
                sender_h,
                f"FROM:\n{sender}",
                size=int(sender_h * 0.2),
                weight=700,
                align="left",
                fit=True,
            )
        )

        line_y = banner_h + sender_h + 10
        items.append(_shape_item(0, line_y, width, 4, "black"))

        items.append(
            _text_item(
                10,
                line_y + 10,
                120,
                height * 0.08,
                "SHIP TO:",
                size=int(height * 0.06),
                invert=True,
                align="center",
                no_wrap=True,
            )
        )

        recip_y = line_y + (height * 0.08) + 20
        recip_h = height - recip_y - 10
        items.append(
            _text_item(
                15,
                recip_y,
                width - 30,
                recip_h,
                recipient,
                size=int(recip_h * 0.15),
                weight=900,
                align="left",
                fit=True,
            )
        )

    return items


def build_warning_banner(width, height, params):
    text = params.get("text", "WARNING")
    items = []
    items.append(
        _text_item(
            0,
            0,
            width,
            height,
            text,
            size=int(min(width, height) * 0.6),
            weight=900,
            align="center",
            invert=True,
            fit=True,
        )
    )
    return items


def build_sale_tag(width, height, params):
    currency = params.get("currency", "$")
    old_price = f"{currency}{params.get('old_price', '29.99')}"
    new_price = f"{currency}{params.get('new_price', '19.99')}"
    product = params.get("product_name", "Sale Item")

    items = []
    is_landscape = width > height

    if is_landscape:
        items.append(_text_item(10, 10, width * 0.6, height * 0.3, product, size=24, align="left"))
        items.append(
            _text_item(
                10,
                height * 0.4,
                width * 0.4,
                height * 0.5,
                old_price,
                size=32,
                align="left",
                underline=True,
                color="#666666",
            )
        )
        items.append(
            _text_item(
                width * 0.5,
                height * 0.2,
                width * 0.45,
                height * 0.7,
                new_price,
                size=64,
                align="center",
                color="white",
                bg_color="black",
            )
        )
    else:
        items.append(_text_item(10, 10, width - 20, height * 0.2, product, size=24, align="center"))
        items.append(
            _text_item(
                10,
                height * 0.3,
                width - 20,
                height * 0.2,
                old_price,
                size=32,
                align="center",
                underline=True,
            )
        )
        items.append(
            _text_item(
                10,
                height * 0.55,
                width - 20,
                height * 0.4,
                new_price,
                size=50,
                align="center",
                color="white",
                bg_color="black",
            )
        )
    return items


def build_asset_tag(width, height, params):
    asset_id = params.get("asset_id", "AST-0001")
    dept = params.get("department", "IT DEPT")
    desc = params.get("description", "Laptop Computer")

    items = []
    header_h = height * 0.25
    items.append(
        _text_item(
            0,
            0,
            width,
            header_h,
            dept,
            size=20,
            align="center",
            color="white",
            bg_color="black",
        )
    )

    qr_size = min(width * 0.4, height - header_h - 10)
    items.append(
        {
            "id": _id(),
            "type": "qrcode",
            "data": asset_id,
            "x": 10,
            "y": int(header_h + 5),
            "width": int(qr_size),
            "height": int(qr_size),
        }
    )

    text_x = qr_size + 20
    text_w = width - text_x - 10
    items.append(
        _text_item(
            text_x,
            header_h + 10,
            text_w,
            height * 0.3,
            asset_id,
            size=30,
            weight=900,
            align="left",
        )
    )
    items.append(
        _text_item(
            text_x,
            header_h + (height * 0.3) + 10,
            text_w,
            height * 0.3,
            desc,
            size=18,
            weight=400,
            italic=True,
            align="left",
        )
    )
    return items


def build_spice_jar(width, height, params):
    title = params.get("title", "Basil")
    subtitle = params.get("subtitle", "Ocimum basilicum")

    items = []
    title_h = height * 0.6
    items.append(_text_item(10, 10, width - 20, title_h, title, size=40, weight=900, align="center"))
    items.append(
        _text_item(
            10,
            title_h + 10,
            width - 20,
            height * 0.3,
            subtitle,
            size=20,
            weight=400,
            italic=True,
            align="center",
        )
    )
    return items


def build_icon_text(width, height, params):
    text = params.get("text", "Label")
    direction = params.get("direction", "row")
    icon_src = params.get("icon_src")
    if not icon_src:
        icon_src = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJibGFjayIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwb2x5Z29uIHBvaW50cz0iMTIgMiAxNS4wOSA4LjI2IDIyIDkuMjcgMTcgMTQuMTQgMTguMTggMjEuMDIgMTIgMTcuNzcgNS44MiAyMS4wMiA3IDE0LjE0IDIgOS4yNyA4LjkxIDguMjYgMTIgMiI+PC9wb2x5Z29uPjwvc3ZnPg=="

    if direction == "col":
        icon_size = min(width * 0.4, height * 0.4)
        font_size = int(height * 0.2)
        gap = height * 0.05
        total_h = icon_size + gap + font_size
        start_y = (height - total_h) / 2

        return [
            {
                "id": _id(),
                "type": "icon_text",
                "x": 10,
                "y": 10,
                "icon_src": icon_src,
                "icon_x": (width - 20 - icon_size) / 2,
                "icon_y": start_y,
                "icon_size": int(icon_size),
                "text": text,
                "text_x": 0,
                "text_y": start_y + icon_size + gap,
                "size": font_size,
                "weight": 700,
                "font": "RobotoCondensed.ttf",
                "width": width - 20,
                "height": height - 20,
                "align": "center",
                "fit_to_width": True,
            }
        ]

    icon_size = min(width * 0.3, height - 20)
    font_size = int(icon_size * 0.6)
    gap = min(10, width * 0.05)

    return [
        {
            "id": _id(),
            "type": "icon_text",
            "x": 10,
            "y": 10,
            "icon_src": icon_src,
            "icon_x": 0,
            "icon_y": (height - 20 - icon_size) / 2,
            "icon_size": int(icon_size),
            "text": text,
            "text_x": int(icon_size + gap),
            "text_y": (height - 20 - font_size) / 2,
            "size": font_size,
            "weight": 700,
            "font": "RobotoCondensed.ttf",
            "width": width - 20,
            "height": height - 20,
            "align": "left",
            "fit_to_width": True,
        }
    ]


def build_qr_text(width, height, params):
    text = params.get("text", "Scan Me")
    data = params.get("data", "https://catlabel.com")

    is_landscape = width > height
    items = []

    if is_landscape:
        qr_size = height - 20
        items.append(
            {
                "id": _id(),
                "type": "qrcode",
                "data": data,
                "x": 10,
                "y": 10,
                "width": int(qr_size),
                "height": int(qr_size),
            }
        )
        items.append(
            _text_item(
                qr_size + 20,
                10,
                width - qr_size - 30,
                height - 20,
                text,
                size=32,
                align="left",
                fit=True,
            )
        )
    else:
        qr_size = width - 40
        items.append(
            {
                "id": _id(),
                "type": "qrcode",
                "data": data,
                "x": 20,
                "y": 10,
                "width": int(qr_size),
                "height": int(qr_size),
            }
        )
        items.append(
            _text_item(
                10,
                qr_size + 20,
                width - 20,
                height - qr_size - 30,
                text,
                size=24,
                align="center",
                fit=True,
            )
        )
    return items


TEMPLATE_REGISTRY = {
    "centered_text": build_centered_text,
    "title_subtitle": build_title_subtitle,
    "icon_text": build_icon_text,
    "qr_text": build_qr_text,
    "price_tag": build_price_tag,
    "inventory_tag": build_inventory_tag,
    "cable_flag": build_cable_flag,
    "shipping_address": build_shipping_address,
    "warning_banner": build_warning_banner,
    "sale_tag": build_sale_tag,
    "asset_tag": build_asset_tag,
    "spice_jar": build_spice_jar,
}


TEMPLATE_METADATA = [
    {
        "id": "centered_text",
        "category": "Layout",
        "name": "Centered Text",
        "description": "A single, perfectly auto-scaling text block.",
        "fields": [{"name": "text", "label": "Main Text", "type": "textarea"}],
    },
    {
        "id": "title_subtitle",
        "category": "Layout",
        "name": "Title & Subtitle",
        "description": "Stacked text with a large bold title.",
        "fields": [
            {"name": "title", "label": "Title", "type": "text"},
            {"name": "subtitle", "label": "Subtitle", "type": "text"},
        ],
    },
    {
        "id": "icon_text",
        "category": "Layout",
        "name": "Icon + Text",
        "description": "A clean icon next to your text.",
        "fields": [
            {"name": "icon_src", "label": "Icon", "type": "icon"},
            {"name": "text", "label": "Text", "type": "text", "default": "Label"},
            {
                "name": "direction",
                "label": "Layout",
                "type": "select",
                "options": [
                    {"label": "Row (Left to Right)", "value": "row"},
                    {"label": "Column (Top to Bottom)", "value": "col"},
                ],
                "default": "row",
            },
        ],
    },
    {
        "id": "qr_text",
        "category": "Layout",
        "name": "QR Code + Text",
        "description": "A QR code with adjacent text.",
        "fields": [
            {"name": "data", "label": "QR Data", "type": "text", "default": "https://google.com"},
            {"name": "text", "label": "Text", "type": "textarea", "default": "Scan Me"},
        ],
    },
    {
        "id": "price_tag",
        "category": "Dedicated",
        "name": "Pro Price Tag",
        "description": "Retail price tag. Automatically adapts to square or wide labels.",
        "fields": [
            {"name": "currency_symbol", "label": "Currency Symbol", "type": "text", "default": "$"},
            {"name": "price_main", "label": "Main Price", "type": "text", "default": "19"},
            {"name": "price_cents", "label": "Cents", "type": "text", "default": "99"},
            {"name": "unit", "label": "Unit (e.g. /ea)", "type": "text", "default": ""},
            {"name": "product_name", "label": "Product Name", "type": "text", "default": "Product Name"},
            {"name": "barcode", "label": "Barcode (Leave blank to omit)", "type": "text", "default": "123456789"},
        ],
    },
    {
        "id": "inventory_tag",
        "category": "Dedicated",
        "name": "Modern Inventory Tag",
        "description": "Professional asset tag with inverted department header and QR/Barcode.",
        "fields": [
            {"name": "department", "label": "Department / Category", "type": "text", "default": "WAREHOUSE"},
            {"name": "title", "label": "Item Name", "type": "text", "default": "Item Name"},
            {"name": "sku", "label": "SKU / Subtext", "type": "text", "default": "SKU-123"},
            {"name": "code_type", "label": "Code Type (qrcode or barcode)", "type": "text", "default": "qrcode"},
            {"name": "code_data", "label": "Code Data", "type": "text", "default": "INV-001"},
        ],
    },
    {
        "id": "cable_flag",
        "category": "Dedicated",
        "name": "Cable Flag",
        "description": "Fold-over tag with a dashed center line. Repeats text on both sides.",
        "fields": [{"name": "text", "label": "Cable ID / Text", "type": "text"}],
    },
    {
        "id": "shipping_address",
        "category": "Dedicated",
        "name": "Shipping Address",
        "description": "Professional shipping label with service banner and sender/recipient blocks.",
        "fields": [
            {"name": "service", "label": "Service Type (e.g. PRIORITY, STANDARD)", "type": "text", "default": "PRIORITY"},
            {"name": "sender", "label": "Sender Address", "type": "textarea"},
            {"name": "recipient", "label": "Recipient Address", "type": "textarea"},
        ],
    },
    {
        "id": "warning_banner",
        "category": "Dedicated",
        "name": "Warning Banner",
        "description": "Inverted black background with bold white text.",
        "fields": [
            {"name": "text", "label": "Warning Text", "type": "text", "default": "FRAGILE"}
        ],
    },
    {
        "id": "sale_tag",
        "category": "Dedicated",
        "name": "Retail Sale Tag",
        "description": "High contrast inverted price box.",
        "fields": [
            {"name": "product_name", "label": "Product", "type": "text"},
            {"name": "old_price", "label": "Old Price", "type": "text"},
            {"name": "new_price", "label": "New Price", "type": "text"},
            {"name": "currency", "label": "Currency", "type": "text", "default": "$"},
        ],
    },
    {
        "id": "asset_tag",
        "category": "Dedicated",
        "name": "IT Asset Tag",
        "description": "Header bar, QR code, and details.",
        "fields": [
            {"name": "department", "label": "Department", "type": "text"},
            {"name": "asset_id", "label": "Asset ID", "type": "text"},
            {"name": "description", "label": "Description", "type": "text"},
        ],
    },
    {
        "id": "spice_jar",
        "category": "Dedicated",
        "name": "Pantry / Spice Jar",
        "description": "Elegant typography for home organization.",
        "fields": [
            {"name": "title", "label": "Main Label", "type": "text"},
            {"name": "subtitle", "label": "Botanical/Subtitle", "type": "text"},
        ],
    },
]


def generate_template_items(template_id: str, width: int, height: int, params: dict):
    """Executes the requested template and returns the list of layout items."""
    generator = TEMPLATE_REGISTRY.get(template_id)
    if not generator:
        return None
    return generator(width, height, params)
