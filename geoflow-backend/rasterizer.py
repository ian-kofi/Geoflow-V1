"""Turns an SVG drawing into a PNG, for the Drawing to Picture node.

PyMuPDF does the work. It reads the SVG like a one page document and renders it at the
chosen DPI (dots per inch): 300 is good for printing, 96 is about screen size.
"""
import os

try:
    import pymupdf as fitz
except ImportError:  # older versions of PyMuPDF only have the name `fitz`
    import fitz

MIN_DPI, MAX_DPI = 36, 1200


def svgToRaster(svg_path, dpi=300, tag=""):
    """Renders the SVG as a PNG with a transparent background. Returns the PNG's file name."""
    dpi = max(MIN_DPI, min(MAX_DPI, int(dpi)))
    output_filename = f"raster_{tag}.png" if tag else "raster_image.png"
    output_path = os.path.join("outputs", output_filename)
    os.makedirs("outputs", exist_ok=True)
    doc = fitz.open(svg_path)
    try:
        page = doc[0]
        zoom = dpi / 72      # SVG sizes are in points, and there are 72 points to an inch
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=True)   # keep the SVG's transparency
        pix.save(output_path)
    finally:
        doc.close()
    print(f"Rasterized {svg_path} to {output_path} at {dpi} DPI")
    return output_filename
