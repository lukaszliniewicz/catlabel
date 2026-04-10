import json
import base64
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import barcode
from barcode.writer import ImageWriter
import qrcode
import os

def render_template(template_data: dict, variables: dict, default_font: str = "arial.ttf") -> Image.Image:
    """
    Takes a JSON-like dictionary representing the canvas state and a dictionary
    of variables, and renders a Pillow Image ready to be encoded for the printer.
    """
    width = template_data.get("width", 384)
    height = template_data.get("height", 384)
    
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    
    items = template_data.get("items", [])
    for item in items:
        x = int(item.get("x", 0))
        y = int(item.get("y", 0))
        item_type = item.get("type")
        
        item_h = item.get("height")
        if not item_h:
            if item_type == "text":
                item_h = int(item.get("size", 24))
            else:
                item_h = 50

        actual_drawn_height = item_h 

        if item_type == "image":
            b64_src = item.get("src", "")
            if "," in b64_src:
                b64_src = b64_src.split(",")[1]
            try:
                img_data = base64.b64decode(b64_src)
                insert_img = Image.open(BytesIO(img_data)).convert("RGBA")
                iw = int(item.get("width", insert_img.width))
                ih = int(item.get("height", insert_img.height))
                insert_img = insert_img.resize((iw, ih), Image.Resampling.LANCZOS)
                
                bg = Image.new("RGBA", insert_img.size, "WHITE")
                bg.paste(insert_img, (0, 0), insert_img)
                img.paste(bg.convert("RGB"), (x, y))
                actual_drawn_height = ih
            except Exception:
                pass

        elif item_type == "html":
            item_w = int(item.get("width", 384))
            item_h = int(item.get("height", 200))
            html_str = item.get("html", "")
            
            try:
                from html2image import Html2Image
                hti = Html2Image(custom_flags=['--no-sandbox', '--disable-gpu'])
                tmp_path = f"html_{id(item)}.png"
                hti.screenshot(html_str=html_str, save_as=tmp_path, size=(item_w, item_h))
                
                if os.path.exists(tmp_path):
                    insert_img = Image.open(tmp_path).convert("RGBA")
                    bg = Image.new("RGBA", insert_img.size, "WHITE")
                    bg.paste(insert_img, (0, 0), insert_img)
                    img.paste(bg.convert("RGB"), (x, y))
                    os.remove(tmp_path)
                actual_drawn_height = item_h
            except Exception as e:
                print(f"HTML Rendering Error: {e}")
                draw.rectangle([x, y, x + item_w, y + item_h], outline="red", width=2)
                draw.text((x + 5, y + 5), "HTML Render Failed (Check html2image)", fill="red")
                actual_drawn_height = item_h
                
        elif item_type == "cut_line_indicator":
            is_vert = item.get("isVertical", False)
            w = int(item.get("width", width))
            h = int(item.get("height", height))
            
            if is_vert:
                for dash_y in range(y, y + h, 15):
                    draw.line([(x, dash_y), (x, dash_y + 8)], fill="black", width=2)
            else:
                for dash_x in range(x, x + w, 15):
                    draw.line([(dash_x, y), (dash_x + 8, y)], fill="black", width=2)

        elif item_type == "icon_text":
            b64_src = item.get("icon_src", "")
            if "," in b64_src:
                b64_src = b64_src.split(",")[1]
            try:
                img_data = base64.b64decode(b64_src)
                insert_img = Image.open(BytesIO(img_data)).convert("RGBA")
                icon_w = int(item.get("icon_size", 50))
                insert_img = insert_img.resize((icon_w, icon_w), Image.Resampling.LANCZOS)
                
                bg = Image.new("RGBA", insert_img.size, "WHITE")
                bg.paste(insert_img, (0, 0), insert_img)
                
                icon_x = x + int(item.get("icon_x", 0))
                icon_y = y + int(item.get("icon_y", 0))
                img.paste(bg.convert("RGB"), (icon_x, icon_y))
            except Exception:
                pass

            text = item.get("text", "")
            for k, v in variables.items():
                text = text.replace(f"{{{{ {k} }}}}", str(v))
                text = text.replace(f"{{{{{k}}}}}", str(v))
            
            size = item.get("size", 24)
            font_name = item.get("font", default_font)
            def get_font(f_size):
                local_font_path = os.path.join("fonts", font_name)
                if os.path.exists(local_font_path):
                    return ImageFont.truetype(local_font_path, int(f_size))
                try:
                    return ImageFont.truetype(font_name, int(f_size))
                except IOError:
                    return ImageFont.load_default()
            
            font = get_font(size)
            text_x = x + int(item.get("text_x", 0))
            text_y = y + int(item.get("text_y", 0))
            bbox = font.getbbox(text)
            draw.text((text_x - bbox[0], text_y - bbox[1]), text, fill="black", font=font)
            actual_drawn_height = int(item.get("height", max(icon_w, size)))

        elif item_type == "text":
            text = str(item.get("text", ""))
            for k, v in variables.items():
                text = text.replace(f"{{{{ {k} }}}}", str(v))
                text = text.replace(f"{{{{{k}}}}}", str(v))
            
            size = int(item.get("size", 24))
            font_name = item.get("font", default_font)
            box_width = item.get("width")
            no_wrap = item.get("no_wrap", False)
            invert = item.get("invert", False)
            bg_white = item.get("bg_white", False)
            text_color = "white" if invert else "black"
            bg_color = "black" if invert else ("white" if bg_white else None)
            
            def get_font(f_size):
                local_font_path = os.path.join("fonts", font_name)
                if os.path.exists(local_font_path):
                    return ImageFont.truetype(local_font_path, int(f_size))
                try:
                    return ImageFont.truetype(font_name, int(f_size))
                except IOError:
                    return ImageFont.load_default()

            if item.get("fit_to_width") and box_width:
                low, high, best_size = 6, 800, size
                test_text = text.split('\n')[0] 
                while low <= high:
                    mid = (low + high) // 2
                    t_font = get_font(mid)
                    bbox = t_font.getbbox(test_text)
                    if (bbox[2] - bbox[0]) <= box_width:
                        best_size = mid
                        low = mid + 1
                    else:
                        high = mid - 1
                size = best_size

            font = get_font(size)
            align = item.get("align", "left")
            
            if box_width:
                if no_wrap:
                    bbox = font.getbbox(text)
                    left_offset = bbox[0]
                    top_offset = bbox[1] 
                    line_w = bbox[2] - bbox[0]
                    line_h = bbox[3] - bbox[1]
                    
                    if align == "center":
                        line_x = x + (box_width - line_w) / 2 - left_offset
                    elif align == "right":
                        line_x = x + box_width - line_w - left_offset
                    else:
                        line_x = x - left_offset
                    
                    if bg_color:
                        draw.rectangle([x, y, x + box_width, y + line_h + 4], fill=bg_color)
                    
                    draw.text((line_x, y - top_offset), text, fill=text_color, font=font)
                    actual_drawn_height = line_h + 4
                else:
                    lines = []
                    for paragraph in text.split('\n'):
                        words = paragraph.split(' ')
                        current_line = []
                        for word in words:
                            test_line = ' '.join(current_line + [word]) if current_line else word
                            bbox = font.getbbox(test_line)
                            if (bbox[2] - bbox[0]) <= box_width:
                                current_line.append(word)
                            else:
                                if current_line:
                                    lines.append(' '.join(current_line))
                                    current_line = [word]
                                else:
                                    lines.append(word)
                                    current_line = []
                        if current_line:
                            lines.append(' '.join(current_line))
                    
                    y_offset = y
                    
                    total_h = 0
                    for line in lines:
                        if not line.strip():
                            total_h += size
                        else:
                            bbox = font.getbbox(line)
                            total_h += int((bbox[3] - bbox[1]) * 1.15)
                            
                    if bg_color:
                        draw.rectangle([x, y, x + box_width, y + total_h], fill=bg_color)
                        
                    for j, line in enumerate(lines):
                        if not line.strip():
                            y_offset += size
                            continue
                            
                        bbox = font.getbbox(line)
                        left_offset = bbox[0]
                        top_offset = bbox[1]
                        line_w = bbox[2] - bbox[0]
                        line_h = bbox[3] - bbox[1]
                        
                        if align == "center":
                            line_x = x + (box_width - line_w) / 2 - left_offset
                        elif align == "right":
                            line_x = x + box_width - line_w - left_offset
                        else:
                            line_x = x - left_offset
                            
                        draw_y = y_offset - top_offset if j == 0 else y_offset
                        draw.text((line_x, draw_y), line, fill=text_color, font=font)
                        y_offset += int(line_h * 1.15) 
                    actual_drawn_height = total_h
            else:
                bbox = draw.multiline_textbbox((x, y), text, font=font)
                if bg_color:
                    draw.rectangle([bbox[0], bbox[1], bbox[2], bbox[3] + 4], fill=bg_color)
                draw.multiline_text((x, y), text, fill=text_color, font=font)
                actual_drawn_height = (bbox[3] - bbox[1]) + 4
            
        elif item_type == "barcode":
            data = item.get("data", "")
            for k, v in variables.items():
                data = data.replace(f"{{{{ {k} }}}}", str(v))
                data = data.replace(f"{{{{{k}}}}}", str(v))
                
            bclass = barcode.get_barcode_class(item.get("barcode_type", "code128"))
            writer = ImageWriter()
            writer.set_options({'write_text': False, 'module_height': 10.0, 'quiet_zone': 1.0})
            bcode = bclass(data, writer=writer)
            
            fp = BytesIO()
            bcode.write(fp)
            fp.seek(0)
            bc_img = Image.open(fp).convert("RGBA")
            
            bw = int(item.get("width", bc_img.width))
            bh = int(item.get("height", bc_img.height))
            # CRITICAL: Use NEAREST to prevent anti-aliasing which breaks thermal dithering
            bc_img = bc_img.resize((bw, bh), Image.Resampling.NEAREST)
            
            img.paste(bc_img, (x, y), bc_img)
            actual_drawn_height = bh
            
        elif item_type == "qrcode":
            data = item.get("data", "")
            for k, v in variables.items():
                data = data.replace(f"{{{{ {k} }}}}", str(v))
                data = data.replace(f"{{{{{k}}}}}", str(v))
                
            qr = qrcode.QRCode(box_size=item.get("box_size", 10), border=item.get("border", 1))
            qr.add_data(data)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
            
            bw = int(item.get("width", qr_img.width))
            bh = int(item.get("height", qr_img.height))
            # CRITICAL: Use NEAREST to prevent anti-aliasing which breaks thermal dithering
            qr_img = qr_img.resize((bw, bh), Image.Resampling.NEAREST)
            
            img.paste(qr_img, (x, y), qr_img)
            actual_drawn_height = bh

        border = item.get("border_style", "none")
        b_thick = int(item.get("border_thickness", 2))
        if border != "none":
            item_w = int(item.get("width", 100))
            if border == "box":
                draw.rectangle([x, y, x + item_w, y + actual_drawn_height], outline="black", width=b_thick)
            elif border == "top":
                draw.line([(x, y), (x + item_w, y)], fill="black", width=b_thick)
            elif border == "bottom":
                draw.line([(x, y + actual_drawn_height), (x + item_w, y + actual_drawn_height)], fill="black", width=b_thick)
            elif border == "cut_line":
                for dash_x in range(x, x + item_w, 15):
                    draw.line([(dash_x, y + actual_drawn_height + 2), (dash_x + 8, y + actual_drawn_height + 2)], fill="black", width=b_thick)

        if "height" not in item:
            item["height"] = actual_drawn_height

    canvas_border = template_data.get("canvasBorder", "none")
    cv_thick = int(template_data.get("canvasBorderThickness", 2))
    if canvas_border != "none":
        if canvas_border == "box":
            draw.rectangle([0, 0, width - 1, height - 1], outline="black", width=cv_thick)
        elif canvas_border == "top":
            draw.line([(0, 0), (width, 0)], fill="black", width=cv_thick)
        elif canvas_border == "bottom":
            draw.line([(0, height - 1), (width, height - 1)], fill="black", width=cv_thick)
        elif canvas_border == "cut_line":
            for dash_x in range(0, width, 15):
                draw.line([(dash_x, height - 1), (dash_x + 8, height - 1)], fill="black", width=cv_thick)

    if template_data.get("isRotated"):
        img = img.rotate(90, expand=True)

    return img
