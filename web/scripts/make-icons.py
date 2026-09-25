from pathlib import Path
from PIL import Image, ImageDraw

icons = Path('public/icons')
icons.mkdir(parents=True, exist_ok=True)
for size in (72, 96, 128, 144, 152, 192, 384, 512):
    image = Image.new('RGB', (size, size), '#102126')
    draw = ImageDraw.Draw(image)
    m = size * .19
    width = max(3, round(size * .043))
    color = '#c4f478'
    length = size * .21
    for x, y, dx, dy in ((m, m, 1, 1), (size-m, m, -1, 1), (m, size-m, 1, -1), (size-m, size-m, -1, -1)):
        draw.line((x, y, x + dx * length, y), fill=color, width=width)
        draw.line((x, y, x, y + dy * length), fill=color, width=width)
    center = size / 2
    r = size * .07
    draw.ellipse((center-r, center-r, center+r, center+r), outline=color, width=width)
    image.save(icons / f'icon-{size}x{size}.png')
    if size == 192:
        image.save('public/favicon.ico', format='ICO', sizes=[(32, 32), (48, 48)])
