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

    def get_page_bounds(self):
        pages = self.svg.xpath("//sodipodi:namedview/inkscape:page")
        if pages:
            last_page = pages[-1]
            return (
                float(last_page.get("x", 0)),
                float(last_page.get("y", 0)),
                float(last_page.get("width", self.svg.viewbox_width)),
                float(last_page.get("height", self.svg.viewbox_height)),
            )
        return 0, 0, self.svg.viewbox_width, self.svg.viewbox_height

    def append_new_page(self, last_x, last_y, width, height):
        namedview = self.svg.xpath("//sodipodi:namedview")[0]
        new_x = last_x + width + 50
        lxml.etree.SubElement(
            namedview,
            inkex.addNS("page", "inkscape"),
            {
                "x": str(new_x),
                "y": str(last_y),
                "width": str(width),
                "height": str(height),
            },
        )
        return new_x, last_y

    def generate_bom_table(self, csv_file_path, page_x, page_y):
        margin = 20
        row_height = 20
        col_width = 150

        group = inkex.Group()
        group.transform = inkex.Transform(translate=(page_x + margin, page_y + margin))

        with open(csv_file_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row_idx, row in enumerate(reader):
                for col_idx, cell_text in enumerate(row):
                    text = inkex.TextElement()
                    text.set("x", str(col_idx * col_width))
                    text.set("y", str(row_idx * row_height))
                    text.text = cell_text
                    text.style = {
                        "font-size": "12px",
                        "fill": "black",
                        "font-family": "sans-serif",
                    }
                    group.append(text)

        self.svg.append(group)

    def effect(self):
        if not os.path.isfile(self.options.csv_path):
            inkex.utils.errormsg("CSV file not found.")
            return

        last_x, last_y, width, height = self.get_page_bounds()
        new_x, new_y = self.append_new_page(last_x, last_y, width, height)
        self.generate_bom_table(self.options.csv_path, new_x, new_y)

        temp_svg = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
        temp_path = temp_svg.name
        temp_svg.close()
        try:
            with open(temp_path, "wb") as f:
                f.write(lxml.etree.tostring(self.document))

            inkscape(
                temp_path, export_filename=self.options.pdf_path, export_type="pdf"
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        inkex.utils.errormsg(f"Success: PDF saved to {self.options.pdf_path}")


if __name__ == "__main__":
    BomPdfPublisher().run()
