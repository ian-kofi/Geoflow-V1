import os

try:
    import pymupdf as fitz
except ImportError:  # older PyMuPDF releases only ship the `fitz` name
    import fitz

MIN_DPI, MAX_DPI = 36, 1200


def svgToRaster(svg_path, dpi=300, tag=""):
    dpi = max(MIN_DPI, min(MAX_DPI, int(dpi)))
    output_filename = f"raster_{tag}.png" if tag else "raster_image.png"
    output_path = os.path.join("outputs", output_filename)
    os.makedirs("outputs", exist_ok=True)
    doc = fitz.open(svg_path)
    try:
        page = doc[0]
        zoom = dpi / 72
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=True)   # keep the SVG's transparency
        pix.save(output_path)
    finally:
        doc.close()
    print(f"Rasterized: {svg_path} → {output_path} at {dpi} DPI")
    return output_filename
