import csv
import os
import tempfile
import textwrap

import inkex
import lxml.etree
from inkex.command import inkscape


class BomPdfPublisher(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument("--pdf_path", type=str, default="")
        pars.add_argument("--allow_overwrite", type=inkex.utils.Boolean, default=False)
        pars.add_argument("--csv_path_1", type=str, default="")
        pars.add_argument("--csv_path_2", type=str, default="")
        pars.add_argument("--csv_path_3", type=str, default="")
        pars.add_argument("--csv_path_4", type=str, default="")
        pars.add_argument("--csv_path_5", type=str, default="")

    def get_doc_path(self):
        """Attempts to find the absolute path of the currently opened SVG document."""
        if hasattr(self, "svg_path"):
            path = self.svg_path()
            if path:
                return path

        docname = self.svg.get("sodipodi:docname")
        if docname:
            return os.path.abspath(docname)

        return None

    def process_csv(self, csv_file_path):
        with open(csv_file_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            return None

        max_cols = max(len(r) for r in rows)
        rows = [r + [""] * (max_cols - len(r)) for r in rows]

        title_text = "Bill of Materials"
        fg_index = -1
        for i, row in enumerate(rows):
            if i > 0 and len(row) > 0 and row[0].strip().lower() == "finished good":
                fg_index = i
                pn = row[1] if len(row) > 1 else ""
                desc = row[2] if len(row) > 2 else ""

                title_parts = [p for p in (pn, desc) if p.strip()]
                if title_parts:
                    title_text = " - ".join(title_parts)
                break

        if fg_index != -1:
            rows.pop(fg_index)

        if max_cols > 0:
            rows = [r[1:] for r in rows]
            max_cols -= 1

        for _ in range(2):
            if max_cols > 0 and all(row[-1].strip() == "" for row in rows):
                max_cols -= 1
                rows = [r[:-1] for r in rows]

        num_cols = max_cols

        margin = 30
        base_col_width = 100
        col_widths = [
            base_col_width * 3 if i == 1 else base_col_width for i in range(num_cols)
        ]

        total_table_width = sum(col_widths)
        bom_page_width = total_table_width + (margin * 2)

        line_height = 14
        padding_y = 12
        title_space = 30
        total_height = (margin * 2) + title_space
        processed_rows = []

        for row in rows:
            processed_cells = []
            max_lines = 1
            for col_idx, cell_text in enumerate(row):
                if col_idx == 1:
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

        return {
            "title": title_text,
            "rows": processed_rows,
            "page_width": bom_page_width,
            "page_height": bom_page_height,
            "table_width": total_table_width,
            "col_widths": col_widths,
            "margin": margin,
            "title_space": title_space,
            "line_height": line_height,
        }

    def setup_pages(self, bom_data_list):
        self.added_original_page = False

        for old_bom in self.svg.xpath("//*[starts-with(@id, 'bom_table_group')]"):
            old_bom.getparent().remove(old_bom)
        for old_page in self.svg.xpath("//inkscape:page[starts-with(@id, 'bom_page')]"):
            old_page.getparent().remove(old_page)

        namedviews = self.svg.xpath("//sodipodi:namedview")
        if not namedviews:
            inkex.utils.errormsg("No namedview found in SVG.")
            return []

        namedview = namedviews[0]
        pages = self.svg.xpath("//sodipodi:namedview/inkscape:page")

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
        current_x = (
            float(last_page.get("x", 0))
            + float(last_page.get("width", self.svg.viewbox_width))
            + 50
        )
        current_y = float(last_page.get("y", 0))

        page_coords = []

        for i, bom_data in enumerate(bom_data_list):
            lxml.etree.SubElement(
                namedview,
                inkex.addNS("page", "inkscape"),
                {
                    "id": f"bom_page_{i}",
                    "x": str(current_x),
                    "y": str(current_y),
                    "width": str(bom_data["page_width"]),
                    "height": str(bom_data["page_height"]),
                },
            )
            page_coords.append((current_x, current_y))
            current_x += bom_data["page_width"] + 50

        return page_coords

    def effect(self):
        pdf_path = self.options.pdf_path

        # 1. Get the path the first way (Safely handling if it's already a directory)
        doc_path = self.get_doc_path()
        target_dir = None
        if doc_path:
            if os.path.isdir(doc_path):
                target_dir = doc_path
            else:
                target_dir = os.path.dirname(doc_path)

        # 2. Get the filename the second way
        docname = self.svg.get("sodipodi:docname")

        # Combine them if the user didn't specify a manual override path
        if (
            not pdf_path
            or not pdf_path.strip()
            or pdf_path == "C:\\Users\\User\\Documents\\output.pdf"
        ):
            if target_dir and docname:
                base_name = os.path.splitext(os.path.basename(docname))[0]
                pdf_path = os.path.join(target_dir, base_name + ".pdf")
            else:
                inkex.utils.errormsg(
                    "Your drawing appears to be unsaved. Please save it first, or manually specify the Output PDF path."
                )
                return

        # Explicit Overwrite Check
        if os.path.exists(pdf_path) and not self.options.allow_overwrite:
            inkex.utils.errormsg(
                f"The file '{os.path.basename(pdf_path)}' already exists.\n\nPlease check 'Overwrite existing PDF' in the extension settings to overwrite it, or specify a different Output PDF path."
            )
            return

        potential_paths = [
            self.options.csv_path_1,
            self.options.csv_path_2,
            self.options.csv_path_3,
            self.options.csv_path_4,
            self.options.csv_path_5,
        ]

        csv_files = []
        for path in potential_paths:
            if path and os.path.isfile(path) and path.lower().endswith(".csv"):
                csv_files.append(path)

        if not csv_files:
            inkex.utils.errormsg("No valid CSV files were selected.")
            return

        bom_data_list = []
        for csv_file in csv_files:
            data = self.process_csv(csv_file)
            if data:
                bom_data_list.append(data)

        if not bom_data_list:
            inkex.utils.errormsg("CSVs were empty or unreadable.")
            return

        page_coords = self.setup_pages(bom_data_list)

        for i, bom_data in enumerate(bom_data_list):
            new_x, new_y = page_coords[i]
            margin = bom_data["margin"]
            line_height = bom_data["line_height"]
            col_widths = bom_data["col_widths"]

            def get_col_x(idx):
                return sum(col_widths[:idx])

            group = inkex.Group()
            group.set("id", f"bom_table_group_{i}")
            group.transform = inkex.Transform(
                translate=(new_x + margin, new_y + margin)
            )

            title_elem = inkex.TextElement()
            title_elem.set("x", "0")
            title_elem.set("y", "0")
            title_elem.text = bom_data["title"]
            title_elem.style = {
                "font-size": "16px",
                "fill": "black",
                "font-family": "sans-serif",
                "font-weight": "bold",
            }
            group.append(title_elem)

            current_y = bom_data["title_space"]
            for row_idx, row_data in enumerate(bom_data["rows"]):
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

                    if row_idx == 0:
                        text_elem.style["font-weight"] = "bold"

                    is_link = col_idx == 0 and row_idx > 0
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
                    line.set(
                        "d", f"M 0,{current_y} L {bom_data['table_width']},{current_y}"
                    )
                    line.style = {"stroke": "black", "stroke-width": "1px"}
                    group.append(line)

            self.svg.append(group)

        # Temporary file is securely placed directly in the target directory
        temp_svg = tempfile.NamedTemporaryFile(
            dir=target_dir, suffix=".svg", delete=False
        )
        temp_path = temp_svg.name
        temp_svg.close()

        try:
            with open(temp_path, "wb") as f:
                f.write(lxml.etree.tostring(self.document))

            inkscape(
                temp_path,
                export_filename=pdf_path,
                export_type="pdf",
                export_pdf_version="1.5",
                export_text_to_path=False,
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        for bom_elem in self.svg.xpath("//*[starts-with(@id, 'bom_table_group')]"):
            bom_elem.getparent().remove(bom_elem)
        for page_elem in self.svg.xpath(
            "//inkscape:page[starts-with(@id, 'bom_page')]"
        ):
            page_elem.getparent().remove(page_elem)

        if getattr(self, "added_original_page", False):
            for orig_page in self.svg.xpath("//inkscape:page[@id='original_page']"):
                orig_page.getparent().remove(orig_page)

        num_boms = len(bom_data_list)
        inkex.utils.errormsg(
            f"Success: Saved drawing and {num_boms} BOM page(s) to:\n{pdf_path}"
        )


if __name__ == "__main__":
    BomPdfPublisher().run()
