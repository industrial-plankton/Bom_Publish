import csv
import os
import tempfile
import textwrap

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
        self.added_original_page = False

        # Clean up old BOMs from previous runs (in case the file was manually saved with one)
        for old_bom in self.svg.xpath("//*[@id='bom_table_group']"):
            old_bom.getparent().remove(old_bom)
        for old_page in self.svg.xpath("//inkscape:page[@id='bom_page']"):
            old_page.getparent().remove(old_page)

        namedviews = self.svg.xpath("//sodipodi:namedview")
        if not namedviews:
            inkex.utils.errormsg("No namedview found in SVG.")
            return 0, 0

        namedview = namedviews[0]
        pages = self.svg.xpath("//sodipodi:namedview/inkscape:page")

        # Ensure Page 1 is explicitly defined
        if not pages:
            self.added_original_page = True
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

        last_page = pages[-1]
        last_x = float(last_page.get("x", 0))
        last_y = float(last_page.get("y", 0))
        last_w = float(last_page.get("width", self.svg.viewbox_width))

        new_x = last_x + last_w + 50
        new_y = last_y

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

        with open(self.options.csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            inkex.utils.errormsg("CSV is empty.")
            return

        # 1. Normalize row lengths
        max_cols = max(len(r) for r in rows)
        rows = [r + [""] * (max_cols - len(r)) for r in rows]

        # 2. Drop up to 2 trailing columns if they are completely blank
        for _ in range(2):
            if max_cols > 0 and all(row[-1].strip() == "" for row in rows):
                max_cols -= 1
                rows = [r[:-1] for r in rows]

        num_cols = max_cols

        # 3. Calculate column widths (3rd column is 3x width)
        margin = 30
        base_col_width = 100
        col_widths = [
            base_col_width * 3 if i == 2 else base_col_width for i in range(num_cols)
        ]

        def get_col_x(idx):
            return sum(col_widths[:idx])

        total_table_width = sum(col_widths)
        bom_page_width = total_table_width + (margin * 2)

        # 4. Process text wrapping and dynamic row heights
        line_height = 14
        padding_y = 12
        total_height = margin * 2
        processed_rows = []

        for row in rows:
            processed_cells = []
            max_lines = 1
            for col_idx, cell_text in enumerate(row):
                if col_idx == 2:
                    chars_per_line = int(col_widths[col_idx] / 6.5)
                    wrapped = textwrap.wrap(cell_text, width=chars_per_line)
                    if not wrapped:
                        wrapped = [""]
                else:
                    wrapped = [cell_text]

                max_lines = max(max_lines, len(wrapped))

                processed_cells.append(
                    {"lines": wrapped, "original": cell_text.strip()}
                )

            row_height = (max_lines * line_height) + padding_y
            processed_rows.append({"cells": processed_cells, "height": row_height})
            total_height += row_height

        bom_page_height = total_height

        # 5. Setup the Document Canvas
        new_x, new_y = self.setup_pages(bom_page_width, bom_page_height)

        group = inkex.Group()
        group.set("id", "bom_table_group")
        group.transform = inkex.Transform(translate=(new_x + margin, new_y + margin))

        # 6. Draw the Table
        current_y = 0
        for row_idx, row_data in enumerate(processed_rows):
            for col_idx, cell_data in enumerate(row_data["cells"]):
                lines = cell_data["lines"]
                original_text = cell_data["original"]
                col_x = get_col_x(col_idx)

                text_elem = inkex.TextElement()
                text_elem.style = {
                    "font-size": "12px",
                    "fill": "black",
                    "font-family": "sans-serif",
                }

                # Bold the first row (headers)
                if row_idx == 0:
                    text_elem.style["font-weight"] = "bold"

                # Format column 2 (index 1) as a hyperlink
                is_link = col_idx == 1 and row_idx > 0
                if is_link:
                    text_elem.style["fill"] = "#0056b3"
                    text_elem.style["text-decoration"] = "underline"

                for line_idx, line in enumerate(lines):
                    tspan = inkex.Tspan()
                    tspan.set("x", str(col_x))
                    tspan.set(
                        "y", str(current_y + line_height + (line_idx * line_height))
                    )
                    tspan.text = line
                    text_elem.append(tspan)

                if is_link and original_text:
                    base_pn = original_text.split("-")[0]
                    a = lxml.etree.Element("{http://www.w3.org/2000/svg}a")
                    a.set(
                        "{http://www.w3.org/1999/xlink}href",
                        f"https://industrialplankton.net/parts/{base_pn}",
                    )
                    a.append(text_elem)
                    group.append(a)
                else:
                    group.append(text_elem)

            current_y += row_data["height"]

            if row_idx == 0:
                line = inkex.PathElement()
                line.set("d", f"M 0,{current_y} L {total_table_width},{current_y}")
                line.style = {"stroke": "black", "stroke-width": "1px"}
                group.append(line)

        self.svg.append(group)

        # 7. Save Temp SVG & Export PDF
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

        # 8. Clean up the document before passing it back to the live Inkscape GUI
        for bom_elem in self.svg.xpath("//*[@id='bom_table_group']"):
            bom_elem.getparent().remove(bom_elem)
        for page_elem in self.svg.xpath("//inkscape:page[@id='bom_page']"):
            page_elem.getparent().remove(page_elem)

        if getattr(self, "added_original_page", False):
            for orig_page in self.svg.xpath("//inkscape:page[@id='original_page']"):
                orig_page.getparent().remove(orig_page)

        inkex.utils.errormsg(f"Success: PDF saved to {self.options.pdf_path}")


if __name__ == "__main__":
    BomPdfPublisher().run()
