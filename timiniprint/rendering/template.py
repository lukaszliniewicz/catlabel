import json
import base64
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import barcode
from barcode.writer import ImageWriter
import qrcode
import os

def render_template(template_data: dict, variables: dict) -> Image.Image:
    """
    Takes a JSON-like dictionary representing the canvas state and a dictionary
    of variables, and renders a Pillow Image.
    """
    width = template_data.get("width", 384)
    height = template_data.get("height", 384)
    
    # Create a white canvas (RGB is easier to draw on, we convert to 1-bit later)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    
    items = template_data.get("items", [])
    for item in items:
        item_type = item.get("type")
        x = int(item.get("x", 0))
        y = int(item.get("y", 0))
        
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
                
                # Create a temporary white background so transparent PNGs print nicely
                bg = Image.new("RGBA", insert_img.size, "WHITE")
                bg.paste(insert_img, (0, 0), insert_img)
                
                img.paste(bg.convert("RGB"), (x, y))
            except Exception as e:
                print(f"Failed to render image item: {e}")

        elif item_type == "text":
            text = item.get("text", "")
            # Substitute variables (e.g., {{ sku }})
            for k, v in variables.items():
                text = text.replace(f"{{{{ {k} }}}}", str(v))
                text = text.replace(f"{{{{{k}}}}}", str(v))
            
            size = item.get("size", 24)
            font_name = item.get("font", "arial.ttf")
            box_width = item.get("width")
            
            def get_font(f_size):
                local_font_path = os.path.join("fonts", font_name)
                try:
                    if os.path.exists(local_font_path):
                        return ImageFont.truetype(local_font_path, f_size)
                    return ImageFont.truetype(font_name, f_size)
                except IOError:
                    return ImageFont.load_default()

            # Auto fit to width logic
            if item.get("fit_to_width") and box_width:
                low, high, best_size = 6, 200, size
                test_text = text.split('\n')[0] # approximate based on longest line usually
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
                for line in lines:
                    bbox = font.getbbox(line)
                    line_w = bbox[2] - bbox[0]
                    # Fallback for empty lines
                    line_h = (bbox[3] - bbox[1]) if line.strip() else size
                    
                    if align == "center":
                        line_x = x + (box_width - line_w) / 2
                    elif align == "right":
                        line_x = x + (box_width - line_w)
                    else:
                        line_x = x
                        
                    draw.text((line_x, y_offset), line, fill="black", font=font)
                    y_offset += int(line_h * 1.2) # 1.2 line height multiplier
            else:
                draw.text((x, y), text, fill="black", font=font)
            
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
            
            bw = item.get("width", bc_img.width)
            bh = item.get("height", bc_img.height)
            bc_img = bc_img.resize((bw, bh))
            
            img.paste(bc_img, (x, y), bc_img)
            
        elif item_type == "qrcode":
            data = item.get("data", "")
            for k, v in variables.items():
                data = data.replace(f"{{{{ {k} }}}}", str(v))
                data = data.replace(f"{{{{{k}}}}}", str(v))
                
            qr = qrcode.QRCode(box_size=item.get("box_size", 10), border=item.get("border", 1))
            qr.add_data(data)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
            
            bw = item.get("width", qr_img.width)
            bh = item.get("height", qr_img.height)
            qr_img = qr_img.resize((bw, bh))
            
            img.paste(qr_img, (x, y), qr_img)

    return img
