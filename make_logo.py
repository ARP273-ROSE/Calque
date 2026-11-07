#!/usr/bin/env python3
"""Logo de Calque : UNE source SVG (logo.svg), tout le reste en est rendu.

    QT_QPA_PLATFORM=offscreen python make_logo.py      (PyQt6 + Pillow)

Un SSD et sa copie « sur calque » (contour pointillé, translucide), reliés
par une flèche ocre, sur fond bleu de Prusse. Sorties : logo.svg (la source),
logo_{16,32,64,128,256,512,1024}.png, logo.png (= 256), logo.ico (installeur
Windows, multi-tailles) et logo.icns (macOS).
"""
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
BLEU, BLEU_SOMBRE, OCRE, CALQUE, ENCRE = "#1D4E73", "#123651", "#E09A35", "#EAF2F7", "#0E2233"


def _ssd(x, y, remplissage, trait, opacite=1.0, pointille=False):
    """Un SSD M.2 vu de dessus : carte, connecteur à peignes, deux puces."""
    tirets = ' stroke-dasharray="14 9"' if pointille else ""
    t = [f'<g opacity="{opacite}">',
         f'<rect x="{x}" y="{y}" width="250" height="118" rx="12" fill="{remplissage}" '
         f'stroke="{trait}" stroke-width="5"{tirets}/>']
    for i in range(7):
        t.append(f'<rect x="{x + 214}" y="{y + 14 + i * 14}" width="26" height="8" rx="2" fill="{trait}"/>')
    t.append(f'<rect x="{x + 26}" y="{y + 26}" width="66" height="66" rx="6" fill="{trait}"/>')
    t.append(f'<rect x="{x + 112}" y="{y + 26}" width="80" height="66" rx="6" fill="{trait}"/>')
    t.append(f'<circle cx="{x + 14}" cy="{y + 59}" r="6" fill="none" stroke="{trait}" stroke-width="3"/>')
    t.append("</g>")
    return "\n".join(t)


def construire_svg() -> str:
    n = 512
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="{n}" height="{n}" viewBox="0 0 {n} {n}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="fond" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{BLEU}"/>
      <stop offset="100%" stop-color="{BLEU_SOMBRE}"/>
    </linearGradient>
  </defs>
  <rect x="16" y="16" width="480" height="480" rx="96" fill="url(#fond)"/>
  {_ssd(62, 104, CALQUE, ENCRE)}
  {_ssd(200, 290, CALQUE, ENCRE, 0.62, pointille=True)}
  <path d="M190 246 C 190 300, 210 330, 252 336" fill="none" stroke="{OCRE}" stroke-width="16" stroke-linecap="round"/>
  <polygon points="244,304 290,340 238,366" fill="{OCRE}"/>
</svg>
'''


def rendre(svg: Path, sortie: Path, taille: int) -> None:
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer
    img = QImage(taille, taille, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    QSvgRenderer(str(svg)).render(p, QRectF(0, 0, taille, taille))
    p.end()
    img.save(str(sortie), "PNG")


def main():
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)  # noqa: F841 — requis pour le rendu
    svg = ICI / "logo.svg"
    svg.write_text(construire_svg(), encoding="utf-8")
    for taille in (16, 32, 64, 128, 256, 512, 1024):
        rendre(svg, ICI / f"logo_{taille}.png", taille)
    (ICI / "logo.png").write_bytes((ICI / "logo_256.png").read_bytes())
    from PIL import Image
    img = Image.open(ICI / "logo_1024.png").convert("RGBA")
    img.save(ICI / "logo.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                      (64, 64), (128, 128), (256, 256)])
    img.save(ICI / "logo.icns")
    print("logo.svg -> logo_*.png, logo.png, logo.ico, logo.icns")


if __name__ == "__main__":
    main()
