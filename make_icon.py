"""Создаёт icon.ico для программы. Запускается один раз (build.bat делает это сам)."""
from PIL import Image, ImageDraw


def draw_icon(size: int) -> Image.Image:
    def p(value: float) -> int:
        return int(size * value)

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=p(0.2), fill=(24, 24, 27, 255))
    draw.ellipse((p(0.12), p(0.12), p(0.88), p(0.88)), fill=(220, 38, 38, 255))
    draw.polygon(
        [(p(0.42), p(0.30)), (p(0.42), p(0.70)), (p(0.72), p(0.50))],
        fill=(255, 255, 255, 255),
    )
    return image


if __name__ == "__main__":
    draw_icon(256).save(
        "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    print("icon.ico создан")
