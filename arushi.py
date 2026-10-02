"""
Cost of a Click 2.0 - Receipt Printer Script
Prints an environmental cost receipt on a Rongta 80mm ESC/POS thermal printer.

SETUP REQUIRED:
1. pip install python-escpos pywin32
2. Confirm PRINTER_NAME below matches the exact name shown in your
   Windows Print queues list (Devices and Printers).
3. Printer's Windows port must be set to its USB port (not LPT1) -
   check Printer Properties > Ports tab if nothing prints.

DESIGN NOTE:
Icons (cup, phone, CO2 cloud, bottle, car) from the mockup are not yet
included - they require bitmap images printed via p.image(). This
version matches all text, layout, spacing, and the inverse-print
black bar exactly. Icons can be layered in as a follow-up once this
text layout is confirmed against a physical printout.
"""

from escpos.printer import Win32Raw
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import os
import tempfile

import cost_model

# ---- CONFIG ----
PRINTER_NAME = "RONGTA 80mm Series Printer"  # must match Windows printer name exactly
LINE_WIDTH = 48  # standard for 80mm paper in Font A; adjust if text wraps oddly
ICON_DIR = os.path.join(os.path.dirname(__file__), "icons")
PRINT_WIDTH_PX = 512  # TM-T88III profile's max image width (not 576 as initially assumed)

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
if not os.path.exists(FONT_DIR):
    FONT_DIR = None  # falls back to PIL default font on systems without DejaVu

def _font(name, size):
    if FONT_DIR:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    return ImageFont.load_default()

# Text scale knob. Image pixels map 1:1 to printer dots, so these are
# absolute sizes on paper, NOT relative to the on-screen preview.
# At PRINT_WIDTH_PX=512 (~64mm), TEXT_SCALE=1.0 is roughly the printer's
# own Font A size. Raise this if text prints too small; lower if it wraps badly.
TEXT_SCALE = 1.5

def _s(px):
    return int(px * TEXT_SCALE)

F_NUM = lambda: _font("DejaVuSans-Bold.ttf", _s(70))
F_UNIT = lambda: _font("DejaVuSans-Bold.ttf", _s(32))
F_LABEL = lambda: _font("DejaVuSans-Bold.ttf", _s(30))
F_TEXT = lambda: _font("DejaVuSans.ttf", _s(24))
F_AMOUNT = lambda: _font("DejaVuSans-Bold.ttf", _s(40))


def _wrap_px(draw, text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_usage_block(number, unit, label, equivalent, description, icon_filename):
    """Composes number+unit / label / equivalent / description on the left,
    icon vertically centered on the right, into a single image."""
    icon_path = os.path.join(ICON_DIR, icon_filename)
    icon_size = _s(120)
    icon = None
    if os.path.exists(icon_path):
        icon = Image.open(icon_path).convert("L").resize((icon_size, icon_size))

    W = PRINT_WIDTH_PX
    pad = 20
    icon_x = W - icon_size - pad if icon else W
    text_max_w = icon_x - pad - pad

    img = Image.new("L", (W, 10), 255)  # placeholder height, cropped later
    draw = ImageDraw.Draw(img)

    desc_lines = _wrap_px(draw, description.replace("\n", " "), F_TEXT(), text_max_w)

    H = pad + _s(82) + _s(42) + _s(34) + (_s(30) * len(desc_lines)) + pad
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)

    x, y = pad, pad
    draw.text((x, y), number, font=F_NUM(), fill=0)
    num_w = draw.textbbox((0, 0), number, font=F_NUM())[2]
    draw.text((x + num_w + _s(8), y + _s(32)), unit, font=F_UNIT(), fill=0)

    y += _s(86)
    draw.text((x, y), label, font=F_LABEL(), fill=0)
    y += _s(40)
    draw.text((x, y), f"= {equivalent}", font=F_TEXT(), fill=0)
    y += _s(34)
    for line in desc_lines:
        draw.text((x, y), line, font=F_TEXT(), fill=0)
        y += _s(30)

    if icon:
        icon_y = (H - icon_size) // 2
        img.paste(icon, (icon_x, icon_y))

    return img.convert("1")


def render_scale_row(amount, label, description, icon_filename):
    """Composes amount+label on the left with icon vertically centered
    on the right, description wrapped beneath - for the x25 scale table."""
    icon_path = os.path.join(ICON_DIR, icon_filename)
    icon_size = _s(100)
    icon = None
    if os.path.exists(icon_path):
        icon = Image.open(icon_path).convert("L").resize((icon_size, icon_size))

    W = PRINT_WIDTH_PX
    pad = 16
    icon_x = W - icon_size - pad if icon else W
    text_max_w = icon_x - pad - pad

    dummy = Image.new("L", (W, 10), 255)
    draw = ImageDraw.Draw(dummy)
    desc_lines = _wrap_px(draw, description, F_TEXT(), text_max_w)

    # Auto-shrink the amount text if it would run into the icon.
    amount_font = F_AMOUNT()
    amount_size = _s(40)
    while draw.textbbox((0, 0), amount, font=amount_font)[2] > text_max_w and amount_size > 12:
        amount_size -= 2
        amount_font = _font("DejaVuSans-Bold.ttf", amount_size)

    H = pad + _s(50) + (_s(38) if label else 0) + (_s(30) * len(desc_lines)) + pad
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)

    x, y = pad, pad
    draw.text((x, y), amount, font=amount_font, fill=0)
    y += _s(52)
    if label:
        draw.text((x, y), label, font=F_LABEL(), fill=0)
        y += _s(38)
    for line in desc_lines:
        draw.text((x, y), line, font=F_TEXT(), fill=0)
        y += _s(30)

    if icon:
        icon_y = (H - icon_size) // 2
        img.paste(icon, (icon_x, icon_y))

    return img.convert("1")


def print_composed_image(p, img):
    """Saves a composed PIL image to a temp file and sends it to the printer."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        img.save(tmp.name)
        tmp_path = tmp.name
    try:
        p.image(tmp_path)
    finally:
        os.remove(tmp_path)


def print_icon(p, filename, size=None):
    """Prints an icon PNG on its own line, centered. Silently skips if the
    file is missing so one bad path never kills the whole receipt."""
    path = os.path.join(ICON_DIR, filename)
    if not os.path.exists(path):
        return
    try:
        img = Image.open(path).convert("L")
        if size:
            img = img.resize((size, size))
        # center manually by padding, since profile centering is unreliable
        canvas = Image.new("L", (PRINT_WIDTH_PX, img.height), 255)
        canvas.paste(img, ((PRINT_WIDTH_PX - img.width) // 2, 0))
        print_composed_image(p, canvas.convert("1"))
    except Exception as e:
        print(f"Warning: could not print icon {filename}: {e}")


def dotted_line():
    return "." * LINE_WIDTH + "\n"


def letter_spaced(text):
    """Mimics the small-caps/letter-spaced look of the subtitle in the mockup."""
    return " ".join(list(text))


def print_receipt(prompt_text, water_ml, elec_wh, carbon_g,
                   data_center_city, data_center_state, data_center_count,
                   distance_miles, receipt_num, qr_url):

    p = Win32Raw(PRINTER_NAME, profile="TM-T88III")
    now = datetime.now()

    # ---------------- Header ----------------
    p.set(align='center', bold=True, double_height=True, double_width=False)
    p.text("COST OF A CLICK\n")
    p.set(align='center', bold=False, double_height=False, double_width=False)
    p.text(letter_spaced("ENVIRONMENTAL RECEIPT") + "\n")
    p.text("-" * LINE_WIDTH + "\n\n")

    # ---------------- Metadata ----------------
    # Font B is the printer's compact face - smaller than Font A.
    p.set(align='left', bold=False, font='b')
    p.text(f"RECEIPT #{receipt_num:04d} \u00b7 {now.strftime('%b %d %Y').upper()} \u00b7 {now.strftime('%I:%M %p')}\n")
    p.set(font='a')
    p.text(dotted_line())
    p.text("\n")

    # ---------------- Prompt (blockquote style) ----------------
    p.set(bold=True)
    p.text("YOUR PROMPT\n\n")
    p.set(bold=False)
    wrapped = _wrap(prompt_text, LINE_WIDTH - 6)
    for i, line in enumerate(wrapped):
        prefix = f'"{line}' if i == 0 else line
        p.text(f"| {prefix}\n")
    p.text("\n")
    p.set(align='center')
    p.text("v\n\n")
    p.set(align='left')

    # ---------------- Usage blocks ----------------
    p.set(bold=True)
    p.text("THIS PROMPT USED\n")
    p.set(bold=False)
    p.text(dotted_line())

    _usage_block(p, f"{water_ml}", "mL", "WATER",
                 cost_model.water_equiv(water_ml),
                 "Used to cool servers and\ndata center systems.")
    print_icon(p, "cup.png", size=120)
    p.text(dotted_line())

    _usage_block(p, f"{elec_wh}", "Wh", "ELECTRICITY",
                 cost_model.energy_equiv(elec_wh),
                 "Drawn from the grid to\ncompute your answer.")
    print_icon(p, "phone.png", size=120)
    p.text(dotted_line())

    _usage_block(p, f"{carbon_g}", "g CO2e", "CARBON EMITTED",
                 cost_model.carbon_equiv(carbon_g),
                 "Released into the\natmosphere.")
    print_icon(p, "cloud_co2.png", size=120)
    p.text(dotted_line())
    p.text("\n")
    p.set(align='center')
    p.text("v\n\n")
    p.set(align='left')

    # ---------------- Origin box (bordered) ----------------
    box_w = LINE_WIDTH
    p.text("+" + "-" * (box_w - 2) + "+\n")
    p.text("| " + "YOUR WATER CAME FROM".ljust(box_w - 4) + " |\n")
    p.set(bold=True, double_height=True)
    p.text(f"{data_center_city.upper()}, {data_center_state.upper()}\n")
    p.set(bold=False, double_height=False)
    origin_desc = _wrap(
        f"One of {data_center_count}+ data centers in the area, "
        f"{distance_miles} miles from where you are standing.",
        box_w - 4
    )
    for line in origin_desc:
        p.text("| " + line.ljust(box_w - 4) + " |\n")
    p.text("+" + "-" * (box_w - 2) + "+\n\n")

    # ---------------- Scale table (inverse black bar headline) ----------------
    p.set(align='center', bold=True, invert=True)
    p.text(" WHAT IF YOU DID THIS 25 TIMES TODAY? \n")
    p.set(align='left', bold=False, invert=False)
    p.text("\n")

    w25, e25, c25 = water_ml * 25, elec_wh * 25, carbon_g * 25

    _scale_row(p, _fmt_qty(w25, "mL", "L", 1000), "WATER",
               cost_model.water_equiv_long(w25))
    print_icon(p, "bottle.png", size=100)
    p.text("-" * LINE_WIDTH + "\n")

    _scale_row(p, _fmt_qty(e25, "Wh", "kWh", 1000), "ELECTRICITY",
               cost_model.energy_equiv_long(e25))
    print_icon(p, "phone.png", size=100)
    p.text("-" * LINE_WIDTH + "\n")

    _scale_row(p, _fmt_qty(c25, "g CO2e", "kg CO2e", 1000), "CARBON",
               cost_model.carbon_equiv_long(c25))
    print_icon(p, "car.png", size=100)
    p.text("-" * LINE_WIDTH + "\n\n")

    # ---------------- QR code ----------------
    p.set(align='center', bold=True)
    p.text("SCAN TO LEARN MORE\n")
    p.set(bold=False)
    p.text("This goes to our website.\n\n")
    print_icon(p, "qr-coac.png", size=260)
    p.text("\n")

    # ---------------- Footer ----------------
    p.set(align='center', bold=False)
    p.text(" ".join(["*"] * 12) + "\n\n")
    p.set(bold=True)
    p.text("THANK YOU\n\n")

    # Footer note: figures are estimates, sources live on the website.
    p.set(align='center', bold=False, font='b')
    p.text("Estimated figures. Sources and method\n")
    p.text("at our website - scan the code above.\n")
    p.set(font='a')

    p.cut()


def set_text_size(p, width=1, height=1):
    """Sets character size via the raw ESC/POS 'GS !' command, which supports
    multiples up to 8x - larger than python-escpos's double_width/double_height
    flags allow. width/height are 1-8."""
    w = max(1, min(int(width), 8)) - 1
    h = max(1, min(int(height), 8)) - 1
    try:
        p._raw(b'\x1d\x21' + bytes([(w << 4) | h]))
    except Exception:
        # Fall back to the standard flags if the raw command is unavailable
        p.set(double_width=(width > 1), double_height=(height > 1))


def _usage_block(p, number, unit, label, equivalent_caps, description):
    p.set(align='left', bold=True)
    set_text_size(p, 3, 3)          # big resource number
    p.text(f"{number}")
    set_text_size(p, 1, 1)
    p.set(bold=True)
    p.text(f" {unit}\n")
    p.set(bold=True)
    set_text_size(p, 1, 2)          # label slightly taller than body text
    p.text(f"{label}\n")
    set_text_size(p, 1, 1)
    p.set(bold=False)
    p.text(f"= {equivalent_caps}\n")
    p.text(f"{description}\n")


def _fmt_qty(value, small_unit, big_unit, threshold):
    """Keeps the x25 figures readable: 12500 mL becomes 12.5 L."""
    if value >= threshold:
        return f"{value/threshold:.1f} {big_unit}"
    if value >= 100:
        return f"{value:.0f} {small_unit}"
    return f"{value:.1f} {small_unit}"


def _scale_row(p, amount, label, description):
    p.set(bold=True)
    set_text_size(p, 2, 2)
    p.text(f"{amount}\n")
    set_text_size(p, 1, 1)
    p.set(bold=True)
    p.text(f"{label}\n")
    p.set(bold=False)
    p.text(f"{description}\n")


def _wrap(text, width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= width:
            cur = f"{cur} {w}".strip()
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# Equivalence phrasing now lives in cost_model.py, alongside the
# sourced constants those phrases depend on.


if __name__ == "__main__":
    # Test print using the real sourced figures from cost_model.
    sample_prompt = "Write me a short poem about the Chicago river."
    r = cost_model.calculate(sample_prompt)

    print_receipt(
        prompt_text=sample_prompt,
        water_ml=r["water_ml"],
        elec_wh=r["energy_wh"],
        carbon_g=r["carbon_g"],
        data_center_city="Elk Grove Village",
        data_center_state="IL",
        data_center_count=80,
        distance_miles=12,
        receipt_num=42,
        qr_url="https://example.com/cost-of-a-click"
    )