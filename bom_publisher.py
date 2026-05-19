import csv
import os
import tempfile

import inkex
import lxml.etree
from inkex.command import inkscape


class BomPdfPublisher(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument(
            "--pdf_path", type=str, default="C:\\Users\\User\\Documents\\output.pdf"
        )
        pars.add_argument(
            "--csv_path", type=str, default="C:\\Users\\User\\Documents\\bom.csv"
        )

    def setup_pages(self, bom_width, bom_height):
        # 1. Clean up old BOMs from previous runs of this script
        for old_bom in self.svg.xpath("//*[@id='bom_table_group']"):
            old_bom.getparent().remove(old_bom)
        for old_page in self.svg.xpath("//inkscape:page[@id='bom_page']"):
            old_page.getparent().remove(old_page)

        namedviews = self.svg.xpath("//sodipodi:namedview")
        if not namedviews:
            inkex.utils.errormsg(
                "No namedview found in SVG. Document may be malformed."
            )
            return 0, 0

        namedview = namedviews[0]
        pages = self.svg.xpath("//sodipodi:namedview/inkscape:page")

        # 2. If the original drawing has no explicit pages (standard for older/single-page SVGs),
        # we must define Page 1 so Inkscape knows it's a multi-page document.
        if not pages:
            lxml.etree.SubElement(
                namedview,
                inkex.addNS("page", "inkscape"),
                {
                    "id": "original_page",
                    "x": "0",
                    "y": "0",
                    "width": str(self.svg.viewbox_width),
                    "height": str(self.svg.viewbox_height),
                },
            )
            pages = self.svg.xpath("//sodipodi:namedview/inkscape:page")

        # 3. Calculate position for the new BOM page
        last_page = pages[-1]
        last_x = float(last_page.get("x", 0))
        last_y = float(last_page.get("y", 0))
        last_w = float(last_page.get("width", self.svg.viewbox_width))

        new_x = last_x + last_w + 50
        new_y = last_y

        # 4. Add the BOM page
        lxml.etree.SubElement(
            namedview,
            inkex.addNS("page", "inkscape"),
            {
                "id": "bom_page",
                "x": str(new_x),
                "y": str(new_y),
                "width": str(bom_width),
                "height": str(bom_height),
            },
        )

        return new_x, new_y

    def effect(self):
        if not os.path.isfile(self.options.csv_path):
            inkex.utils.errormsg("CSV file not found.")
            return

        margin = 20
        row_height = 20
        col_width = 150

        with open(self.options.csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            inkex.utils.errormsg("CSV is empty.")
            return

        num_rows = len(rows)
        num_cols = max(len(r) for r in rows)

        bom_page_width = (num_cols * col_width) + (margin * 2)
        bom_page_height = (num_rows * row_height) + (margin * 2)

        new_x, new_y = self.setup_pages(bom_page_width, bom_page_height)

        # Draw the BOM Table
        group = inkex.Group()
        group.set(
            "id", "bom_table_group"
        )  # ID allows us to clean this up on future runs
        group.transform = inkex.Transform(translate=(new_x + margin, new_y + margin))

        for row_idx, row in enumerate(rows):
            for col_idx, cell_text in enumerate(row):
                text = inkex.TextElement()
                text.set("x", str(col_idx * col_width))
                text.set("y", str((row_idx * row_height) + 12))
                text.text = str(cell_text)
                text.style = {
                    "font-size": "12px",
                    "fill": "black",
                    "font-family": "sans-serif",
                }
                group.append(text)

        self.svg.append(group)

        # Save Temp SVG & Export PDF
        original_file = self.options.input_file
        temp_dir = os.path.dirname(original_file) if original_file else None

        temp_svg = tempfile.NamedTemporaryFile(
            dir=temp_dir, suffix=".svg", delete=False
        )
        temp_path = temp_svg.name
        temp_svg.close()

        try:
            with open(temp_path, "wb") as f:
                f.write(lxml.etree.tostring(self.document))

            # Exporting without `export_area_page` forces Inkscape to fall back
            # to its native multi-page document export behavior
            inkscape(
                temp_path,
                export_filename=self.options.pdf_path,
                export_type="pdf",
                export_pdf_version="1.5",
                export_text_to_path=False,
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        inkex.utils.errormsg(f"Success: PDF saved to {self.options.pdf_path}")


if __name__ == "__main__":
    BomPdfPublisher().run()
