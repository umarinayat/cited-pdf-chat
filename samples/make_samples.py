"""Generate the demo documents: a fictional annual report (digital PDF) and a 'scanned' copy of it.

Run:  backend/.venv/Scripts/python samples/make_samples.py
Everything in the report is invented; it exists to give the demo prose, tables, numbers and a
bilingual line to answer questions about.
"""

from io import BytesIO
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageFilter

HERE = Path(__file__).parent
W, H = 612, 792
LEFT, RIGHT = 64, 548
INK = (0.12, 0.15, 0.2)
MUTED = (0.42, 0.46, 0.52)
ACCENT = (0.16, 0.38, 0.62)
TITLE = "Riverside Community Library  ·  Annual Report 2025"


class Writer:
    def __init__(self):
        self.doc = pymupdf.open()
        self.page = None
        self.y = 0

    def new_page(self):
        self.page = self.doc.new_page(width=W, height=H)
        n = self.doc.page_count
        if n > 1:
            self.page.insert_text((LEFT, 42), TITLE, fontname="helv", fontsize=8.5, color=MUTED)
            self.page.draw_line((LEFT, 50), (RIGHT, 50), color=(0.85, 0.87, 0.9), width=0.6)
        self.page.insert_text((RIGHT - 30, H - 36), f"Page {n}", fontname="helv", fontsize=8.5, color=MUTED)
        self.y = 78

    def heading(self, text, size=15, gap=8):
        self.page.insert_text((LEFT, self.y + size), text, fontname="hebo", fontsize=size, color=ACCENT)
        self.y += size + gap + 6

    def subheading(self, text):
        self.page.insert_text((LEFT, self.y + 11), text, fontname="hebo", fontsize=11, color=INK)
        self.y += 19

    def para(self, text, size=10.5, gap=10):
        rect = pymupdf.Rect(LEFT, self.y, RIGHT, H - 60)
        left = self.page.insert_textbox(rect, text, fontname="helv", fontsize=size, color=INK, lineheight=1.4)
        assert left >= 0, f"paragraph overflowed the page: {text[:40]}"
        self.y += rect.height - left + gap

    def table(self, header, rows, widths, size=9.6, bold_last=False):
        row_h = size * 2.1
        x0 = LEFT
        total_w = sum(widths)
        self.page.draw_rect(pymupdf.Rect(x0, self.y, x0 + total_w, self.y + row_h), color=None, fill=(0.92, 0.95, 0.98))
        self._row(header, widths, "hebo", size, row_h)
        for i, row in enumerate(rows):
            last = bold_last and i == len(rows) - 1
            if last:
                self.page.draw_line((x0, self.y), (x0 + total_w, self.y), color=(0.55, 0.6, 0.66), width=0.8)
            self._row(row, widths, "hebo" if last else "helv", size, row_h)
            self.page.draw_line((x0, self.y), (x0 + total_w, self.y), color=(0.88, 0.9, 0.93), width=0.5)
        self.y += 14

    def _row(self, cells, widths, font, size, row_h):
        x = LEFT
        base = self.y + row_h * 0.66
        for i, (cell, w) in enumerate(zip(cells, widths)):
            if i == 0:
                self.page.insert_text((x + 6, base), cell, fontname=font, fontsize=size, color=INK)
            else:  # numbers right-aligned in their column
                tw = pymupdf.get_text_length(cell, fontname=font, fontsize=size)
                self.page.insert_text((x + w - 6 - tw, base), cell, fontname=font, fontsize=size, color=INK)
            x += w
        self.y += row_h


def build_report(path: Path):
    w = Writer()

    # 1. Cover + director's message
    w.new_page()
    w.page.draw_rect(pymupdf.Rect(0, 0, W, 210), color=None, fill=(0.13, 0.3, 0.5))
    w.page.insert_text((LEFT, 105), "Riverside Community Library", fontname="hebo", fontsize=26, color=(1, 1, 1))
    w.page.insert_text((LEFT, 140), "Annual Report 2025", fontname="helv", fontsize=17, color=(0.85, 0.92, 1))
    w.page.insert_text((LEFT, 178), "Serving the Riverside and Eastside neighbourhoods", fontname="helv", fontsize=10.5,
                       color=(0.85, 0.92, 1))
    w.y = 240
    w.heading("A message from the Director")
    w.para("2025 was the busiest year in the library's history. Visits rose 6.5% to 182,450, and members borrowed "
           "412,300 items, including 96,800 e-books and audiobooks. In March we opened the Eastside Branch, our first "
           "new location in 22 years.")
    w.para("We also ended overdue fines on children's materials, and 1,140 young readers returned to the library "
           "after their old fines were cleared. Program attendance grew faster than any other measure, with families "
           "filling our weekend story times and the new Makerspace.")
    w.para("None of this would be possible without our 214 volunteers, who gave 9,870 hours of their time, and the "
           "Friends of the Library, whose book sales raised $38,400. Thank you for another remarkable year.")
    w.para("Elena Marsh\nDirector, Riverside Community Library", gap=24)
    w.page.insert_text((LEFT, H - 60), "Fictional sample document created for a software demo. All names and figures "
                       "are invented.", fontname="helv", fontsize=8, color=MUTED)

    # 2. Year in numbers
    w.new_page()
    w.heading("2025 at a glance")
    w.para("The table compares the main service measures for the calendar years 2024 and 2025.")
    w.table(["Measure", "2024", "2025", "Change"], [
        ["Library visits", "171,300", "182,450", "+6.5%"],
        ["Items borrowed (all formats)", "389,900", "412,300", "+5.7%"],
        ["E-books and audiobooks borrowed", "81,200", "96,800", "+19.2%"],
        ["Registered members", "38,950", "41,720", "+7.1%"],
        ["Programs held", "1,180", "1,326", "+12.4%"],
        ["Program attendance", "24,600", "28,940", "+17.6%"],
        ["Public computer sessions", "52,400", "49,100", "-6.3%"],
        ["Wi-Fi sessions", "118,000", "131,500", "+11.4%"],
        ["Volunteer hours", "8,920", "9,870", "+10.7%"],
    ], [228, 82, 82, 82])
    w.para("Public computer use fell for the second year in a row as more visitors brought their own devices; Wi-Fi "
           "sessions grew by 11.4% over the same period. Digital borrowing continued to outpace print, but print "
           "still made up 76.5% of all items borrowed.")

    # 3. Programs and services
    w.new_page()
    w.heading("Programs and services")
    w.subheading("Children and teens")
    w.para("The Summer Reading Challenge drew 1,240 participants aged 4 to 17, who logged a combined 31,600 hours of "
           "reading. Homework Help ran four afternoons a week during the school year and served 2,310 student visits.")
    w.subheading("Adults")
    w.para("Digital Skills workshops covered email, online banking and spotting scams. We held 86 sessions with an "
           "average attendance of 11 people. The English Conversation Circle met every Tuesday and Thursday evening "
           "and welcomed learners speaking 23 different first languages.")
    w.subheading("Makerspace")
    w.para("The Makerspace opened in June with two 3D printers, a laser cutter and a sewing station. Members completed "
           "640 supervised projects by December. Using the laser cutter requires a 45-minute safety induction, "
           "offered every Saturday morning.")

    # 4. Finances
    w.new_page()
    w.heading("Finances")
    w.para("Figures are for the fiscal year that ended on 30 June 2025.")
    w.subheading("Revenue")
    w.table(["Source", "Amount"], [
        ["City operating grant", "$2,400,000"],
        ["State library aid", "$310,000"],
        ["Donations and fundraising", "$185,500"],
        ["Room rentals and printing", "$41,200"],
        ["Fines and fees", "$12,300"],
        ["Total revenue", "$2,949,000"],
    ], [300, 120], bold_last=True)
    w.subheading("Expenditure")
    w.table(["Category", "Amount"], [
        ["Staff salaries and benefits", "$1,912,000"],
        ["Books and digital collections", "$428,000"],
        ["Facilities and utilities", "$301,500"],
        ["Technology", "$164,000"],
        ["Programs and outreach", "$96,500"],
        ["Total expenditure", "$2,902,000"],
    ], [300, 120], bold_last=True)
    w.para("The year closed with a surplus of $47,000, which the Board of Trustees moved into the building reserve. "
           "Staff costs made up 65.9% of all spending.")

    # 5. Facilities and technology
    w.new_page()
    w.heading("Facilities and technology")
    w.subheading("Eastside Branch")
    w.para("The Eastside Branch opened on 14 March 2025 at 820 Alder Street. The 8,200-square-foot building cost $3.1 "
           "million, funded by a city bond and a $450,000 gift from the Hartley Family Foundation. It holds 26,000 "
           "items and is open six days a week.")
    w.subheading("Main Library")
    w.para("Solar panels installed on the Main Library roof in 2024 cut electricity costs by 18% in their first full "
           "year. We replaced 40 public laptops and added self-checkout kiosks at both branches.")
    w.subheading("Opening hours from 1 January 2026")
    w.table(["Branch", "Mon-Fri", "Saturday", "Sunday"], [
        ["Main Library", "9:00-20:00", "9:00-17:00", "12:00-17:00"],
        ["Eastside Branch", "10:00-19:00", "10:00-16:00", "Closed"],
    ], [180, 98, 98, 98])

    # 6. Policies and goals
    w.new_page()
    w.heading("Borrowing rules")
    w.para("Members may borrow up to 25 items at a time. Books and audiobooks are loaned for 21 days, DVDs for 7 days. "
           "Each item can be renewed twice unless another member has placed a hold. Overdue fines on adult materials "
           "are $0.25 per day, capped at $5 per item; children's and teen materials have no overdue fines. A "
           "replacement library card costs $2.")
    w.heading("Goals for 2026")
    w.para("1. Reach 200,000 visits across both branches.\n"
           "2. Open the Main Library on Sunday mornings from 10:00 by summer 2026.\n"
           "3. Grow the Spanish and Chinese language collections by 30%.\n"
           "4. Train 50 new volunteers for the Homework Help program.")
    w.heading("Chinese-language services", size=12)
    w.para("Library information is also published in Chinese. The notice below reads: \"The library offers free "
           "Chinese books, and Mandarin story time every Saturday at 10:30.\"")
    w.page.insert_text((LEFT, w.y + 12), "图书馆提供免费中文图书，每周六上午十点半有普通话故事时间。",
                       fontname="china-s", fontsize=11, color=INK)
    w.y += 30

    path.parent.mkdir(parents=True, exist_ok=True)
    w.doc.set_metadata({"title": "Riverside Community Library Annual Report 2025 (fictional sample)",
                        "author": "Cited PDF Chat demo"})
    w.doc.save(path, garbage=3, deflate=True)
    w.doc.close()


def build_scanned(src: Path, path: Path, dpi=150, seed=7):
    """Re-create the report as an image-only PDF: grey, slightly rotated, noisy, JPEG-compressed."""
    rng = np.random.default_rng(seed)
    src_doc = pymupdf.open(src)
    out = pymupdf.open()
    for i, page in enumerate(src_doc):
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        img = img.rotate((-0.6, 0.4, -0.3, 0.5, -0.45, 0.35)[i % 6], resample=Image.BICUBIC, fillcolor=255)
        arr = np.asarray(img).astype(np.float32)
        arr = arr * 0.93 + 12 + rng.normal(0, 7, arr.shape)  # paper tint + sensor noise
        img = Image.fromarray(arr.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.45))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=72)
        p = out.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, stream=buf.getvalue())
    out.save(path, garbage=3, deflate=True)
    out.close()
    src_doc.close()


if __name__ == "__main__":
    digital = HERE / "riverside-library-2025.pdf"
    build_report(digital)
    build_scanned(digital, HERE / "riverside-library-2025-scanned.pdf")
    print("wrote", digital.name, "and the scanned copy")
