import json
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import barcode
from barcode.writer import ImageWriter
import qrcode

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
        x = item.get("x", 0)
        y = item.get("y", 0)
        
        if item_type == "text":
            text = item.get("text", "")
            # Substitute variables (e.g., {{ sku }})
            for k, v in variables.items():
                text = text.replace(f"{{{{ {k} }}}}", str(v))
                text = text.replace(f"{{{{{k}}}}}", str(v))
            
            size = item.get("size", 24)
            try:
                font = ImageFont.truetype(item.get("font", "arial.ttf"), size)
            except IOError:
                font = ImageFont.load_default()
                
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
