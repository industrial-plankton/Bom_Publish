import csv
import os
import re
import tempfile
import textwrap

import inkex
import lxml.etree
from inkex.command import inkscape


def get_freq_tag(pn, desc):
    combined = (str(pn) + " " + str(desc)).lower()
    if "50 hz" in combined or "50hz" in combined:
        return "50 Hz"
    if "60 hz" in combined or "60hz" in combined:
        return "60 Hz"
    return "Other"


class BomPdfPublisher(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument("--pdf_path", type=str, default="")
        pars.add_argument("--allow_overwrite", type=inkex.Boolean, default=False)
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

    def read_and_clean_csv(self, csv_file_path):
        with open(csv_file_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            return None

        max_cols = max(len(r) for r in rows)
        rows = [r + [""] * (max_cols - len(r)) for r in rows]

        fg_pn = ""
        fg_desc = ""
        fg_index = -1

        for i, row in enumerate(rows):
            if i > 0 and len(row) > 0 and row[0].strip().lower() == "finished good":
                fg_index = i
                fg_pn = row[1].strip() if len(row) > 1 else ""
                fg_desc = row[2].strip() if len(row) > 2 else ""
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

        return {"fg_pn": fg_pn, "fg_desc": fg_desc, "rows": rows}

    def layout_bom(self, raw_bom):
        title_segments = raw_bom["title_segments"]
        rows = raw_bom["rows"]

        if not rows:
            return None

        num_cols = max(len(r) for r in rows)

        margin = 30
        base_col_width = 100
        col_widths = [
            base_col_width * 3 if i == 1 else base_col_width for i in range(num_cols)
        ]

        total_table_width = sum(col_widths)
        bom_page_width = total_table_width + (margin * 2)

        # --- TITLE WRAPPING LOGIC ---
        # Calculate approx. max characters per line for a 16px sans-serif font (~8.5px wide per char)
        chars_per_line = max(10, int(total_table_width / 8.5))
        title_lines = []
        current_line = []
        current_line_len = 0

        for seg in title_segments:
            link = seg["link"]
            # Split the text by spaces while preserving them so we can break gracefully on words
            words = str(seg["text"]).split(" ")
            for i, word in enumerate(words):
                word_w_space = word + (" " if i < len(words) - 1 else "")

                if not word_w_space:
                    continue

                # If adding this word exceeds the line length, wrap to a new line
                if (
                    current_line_len + len(word_w_space) > chars_per_line
                    and current_line_len > 0
                ):
                    title_lines.append(current_line)
                    current_line = []
                    current_line_len = 0
                    word_w_space = (
                        word_w_space.lstrip()
                    )  # Prevent line from starting with a space
                    if not word_w_space:
                        continue

                # Merge into the existing segment block if it shares the same link to prevent fragmented tags
                if current_line and current_line[-1]["link"] == link:
                    current_line[-1]["text"] += word_w_space
                else:
                    current_line.append({"text": word_w_space, "link": link})
                current_line_len += len(word_w_space)

        if current_line:
            title_lines.append(current_line)

        title_line_height = 20
        # Calculate total space needed for the title block before rendering the table
        # 16px is added to shift the baseline of the first line down properly
        title_space = 16 + (len(title_lines) * title_line_height) + 15

        # --- TABLE RENDERING LOGIC ---
        line_height = 14
        padding_y = 12
        total_height = (margin * 2) + title_space
        processed_rows = []

        for row in rows:
            processed_cells = []
            max_lines = 1
            for col_idx, cell_text in enumerate(row):
                if col_idx == 1:
                    cell_chars_per_line = int(col_widths[col_idx] / 6.5)
                    wrapped = textwrap.wrap(str(cell_text), width=cell_chars_per_line)
                    if not wrapped:
                        wrapped = [""]
                else:
                    wrapped = [str(cell_text)]

                max_lines = max(max_lines, len(wrapped))
                processed_cells.append(
                    {"lines": wrapped, "original": str(cell_text).strip()}
                )

            row_height = (max_lines * line_height) + padding_y
            processed_rows.append({"cells": processed_cells, "height": row_height})
            total_height += row_height

        bom_page_height = total_height

        return {
            "title_lines": title_lines,
            "title_line_height": title_line_height,
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

        doc_path = self.get_doc_path()
        target_dir = None
        if doc_path:
            if os.path.isdir(doc_path):
                target_dir = doc_path
            else:
                target_dir = os.path.dirname(doc_path)

        docname = self.svg.get("sodipodi:docname")

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
            if target_dir and os.path.exists(target_dir):
                for f in os.listdir(target_dir):
                    if f.lower().endswith(".csv"):
                        csv_files.append(os.path.join(target_dir, f))

            if not csv_files:
                inkex.utils.errormsg(
                    "No CSV files were selected in the menu, and no CSV files were found automatically in the SVG's folder."
                )
                return

        raw_boms = []
        for csv_file in csv_files:
            data = self.read_and_clean_csv(csv_file)
            if data and data["rows"]:
                raw_boms.append(data)

        if not raw_boms:
            inkex.utils.errormsg("CSVs were empty or unreadable.")
            return

        has_50 = any(
            get_freq_tag(b["fg_pn"], b["fg_desc"]) == "50 Hz" for b in raw_boms
        )
        has_60 = any(
            get_freq_tag(b["fg_pn"], b["fg_desc"]) == "60 Hz" for b in raw_boms
        )

        if len(raw_boms) >= 2 and has_50 and has_60:
            bom_50 = next(
                (
                    b
                    for b in raw_boms
                    if get_freq_tag(b["fg_pn"], b["fg_desc"]) == "50 Hz"
                ),
                None,
            )
            bom_60 = next(
                (
                    b
                    for b in raw_boms
                    if get_freq_tag(b["fg_pn"], b["fg_desc"]) == "60 Hz"
                ),
                None,
            )

            pn_50 = bom_50["fg_pn"] if bom_50 else ""
            pn_60 = bom_60["fg_pn"] if bom_60 else ""

            desc_50 = bom_50["fg_desc"] if bom_50 else ""

            clean_desc = re.sub(r"(?i)\b(50|60)\s*hz\b", "", desc_50).strip()
            clean_desc = re.sub(r"(?i)50/60\s*hz\b", "", clean_desc).strip()
            clean_desc = clean_desc.replace("()", "").replace("  ", " ").strip()
            if clean_desc.startswith("- "):
                clean_desc = clean_desc[2:]
            if clean_desc.endswith(" -"):
                clean_desc = clean_desc[:-2]

            title_segments = []
            if pn_50:
                title_segments.append({"text": pn_50, "link": pn_50})
                title_segments.append({"text": " (50 Hz)", "link": None})
            if pn_50 and pn_60:
                title_segments.append({"text": " / ", "link": None})
            if pn_60:
                title_segments.append({"text": pn_60, "link": pn_60})
                title_segments.append({"text": " (60 Hz)", "link": None})

            if clean_desc:
                title_segments.append({"text": f" - {clean_desc}", "link": None})

            header_row = raw_boms[0]["rows"][0] if raw_boms[0]["rows"] else []
            for b in raw_boms:
                if b["rows"]:
                    b["rows"].pop(0)

            all_parts = {}
            ordered_pns = []
            available_tags = set()

            for b in raw_boms:
                tag = get_freq_tag(b["fg_pn"], b["fg_desc"])
                available_tags.add(tag)

                for row in b["rows"]:
                    pn = row[0] if len(row) > 0 else ""
                    key = pn if pn.strip() else str(row)

                    if key not in all_parts:
                        ordered_pns.append(key)
                        all_parts[key] = {}

                    if tag not in all_parts[key]:
                        all_parts[key][tag] = []

                    all_parts[key][tag].append(row)

            merged_rows = [header_row] if header_row else []

            for key in ordered_pns:
                tag_dict = all_parts[key]
                unique_rows = {}

                for tag, rows_for_tag in tag_dict.items():
                    for row in rows_for_tag:
                        t_row = tuple(row)
                        if t_row not in unique_rows:
                            unique_rows[t_row] = []
                        if tag not in unique_rows[t_row]:
                            unique_rows[t_row].append(tag)

                for t_row, tags in unique_rows.items():
                    new_row = list(t_row)

                    if len(tags) < len(available_tags):
                        flag = f" ({'/'.join(tags)})"
                        if len(new_row) > 2:
                            new_row[2] = str(new_row[2]) + flag
                        elif len(new_row) > 1:
                            new_row[1] = str(new_row[1]) + flag

                    merged_rows.append(new_row)

            raw_boms = [{"title_segments": title_segments, "rows": merged_rows}]

        else:
            for b in raw_boms:
                ts = []
                if b["fg_pn"]:
                    ts.append({"text": b["fg_pn"], "link": b["fg_pn"]})
                if b["fg_desc"]:
                    sep = " - " if b["fg_pn"] else ""
                    ts.append({"text": f"{sep}{b['fg_desc']}", "link": None})
                if not ts:
                    ts.append({"text": "Bill of Materials", "link": None})
                b["title_segments"] = ts

        bom_data_list = []
        for raw_bom in raw_boms:
            data = self.layout_bom(raw_bom)
            if data:
                bom_data_list.append(data)

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

            # Render the wrapped Title Lines
            for line_idx, line_segs in enumerate(bom_data["title_lines"]):
                title_elem = inkex.TextElement()
                title_elem.set("x", "0")
                # Drop baseline relative to the line index to properly stack them
                title_elem.set(
                    "y", str(16 + (line_idx * bom_data["title_line_height"]))
                )
                title_elem.set(inkex.addNS("space", "xml"), "preserve")
                title_elem.style = {
                    "font-size": "16px",
                    "fill": "black",
                    "font-family": "sans-serif",
                    "font-weight": "bold",
                }

                for seg in line_segs:
                    if seg["link"]:
                        base_pn = seg["link"].split("-")[0]
                        a = lxml.etree.Element("{http://www.w3.org/2000/svg}a")
                        a.set(
                            "{http://www.w3.org/1999/xlink}href",
                            f"https://industrialplankton.net/parts/{base_pn}",
                        )

                        tspan = inkex.Tspan()
                        tspan.text = seg["text"]
                        tspan.style = {
                            "fill": "#0056b3",
                            "text-decoration": "underline",
                        }
                        a.append(tspan)
                        title_elem.append(a)
                    else:
                        tspan = inkex.Tspan()
                        tspan.text = seg["text"]
                        title_elem.append(tspan)

                group.append(title_elem)

            # Draw the Table Elements
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
