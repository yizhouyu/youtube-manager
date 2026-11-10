"""App icon (DESIGN.md): a white rounded square with a black play triangle and a small champagne check notch
cut into its right edge ("review -> approve"). Writes a 1024 px PNG; build.sh turns it into AppIcon.icns.

    python app/make_icon.py <out.png>
"""
import sys

from PIL import Image, ImageDraw, ImageFilter

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
# macOS icon grid: ~824 px rounded square centred, soft shadow under it
m, r = 100, 185
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle((m, m + 14, S - m, S - m + 14), r, fill=(0, 0, 0, 90))
img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
d = ImageDraw.Draw(img)
d.rounded_rectangle((m, m, S - m, S - m), r, fill=(255, 255, 255, 255))
# play triangle, optically centred a bit right
cx, cy, h = 492, 512, 400
d.polygon([(cx - h * 0.40, cy - h / 2), (cx - h * 0.40, cy + h / 2), (cx + h * 0.48, cy)], fill=(29, 29, 31, 255))
# champagne check notch on the right edge
gold = (201, 169, 110, 255)
d.line([(728, 560), (774, 606), (858, 506)], fill=gold, width=34, joint="curve")
img.save(sys.argv[1])
