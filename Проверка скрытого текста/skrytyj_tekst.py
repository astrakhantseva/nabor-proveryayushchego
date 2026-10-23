"""Проверка файлов PDF на скрытый текст и подготовка их текста по страницам для агентской системы.

Текстовый слой каждой страницы извлекается по фрагментам и сравнивается с видимым
изображением страницы. Фрагмент попадает в перечень, если в его границах на отрисованной
странице нет знаков (цвет текста совпадает с фоном, невидимый режим отрисовки, текст
закрыт другим объектом), если кегль меньше 3 пт, если фрагмент лежит за границей видимой
области страницы или содержит знаки нулевой ширины. Отдельно просматриваются свойства
файла, примечания к страницам и вложенные файлы.

Перечень сохраняется вне рабочей папки, иначе агентская система прочитает найденные строки.
Текст каждого PDF записывается в рабочую папку файлом <имя>_текст.md с маркерами [СТРАНИЦА N],
скрытые строки в этот текст не попадают. Файлы .txt и .md копируются без изменений.
Запуск без аргументов берет файлы из папки «Исходные файлы» рядом с папкой скрипта и готовит
текст в папке «Рабочая папка проверки».
Запуск. python skrytyj_tekst.py [<папка или файл PDF> [<рабочая папка> [<файл перечня>]]]
"""
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "Исходные файлы"
TARGET = HERE.parent / "Рабочая папка проверки"
REPORT = HERE / "Перечень скрытого текста.txt"

MIN_PT = 3.0      # кегль меньше этого считается невидимым
ZOOM = 2.0        # масштаб отрисовки страницы
INK = 60          # отличие яркости знака от фона, 0—255
INK_SHARE = 0.002 # доля пикселей фрагмента, отличных от фона
ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
# знак нулевой ширины внутри слова или цепочка таких знаков; после косой черты в адресах он обычен
ZERO_WIDTH_SPLIT = re.compile("[^\\W\\d_][​‌‍⁠﻿]+[^\\W\\d_]|"
                              "[​‌‍⁠﻿]{3,}")
# слова, обычные для указаний модели и неуместные в свойствах файла
ADDRESSED = re.compile(
    r"игнорир|инструкц|указани|систем|модел|ассистент|нейросет|искусствен|проверяющ|"
    r"замечани|нарушени|соответств|ignore|instruction|system|assistant|model|prompt|\bAI\b|\bLLM\b",
    re.IGNORECASE)


def page_luma(page):
    """Яркость отрисованной страницы массивом numpy."""
    pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), alpha=False)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]
    return a @ np.array([0.299, 0.587, 0.114])


def has_ink(luma, rect):
    """Есть ли в границах фрагмента пиксели, отличные от фона по краю области."""
    h, w = luma.shape
    x0, y0 = max(0, int(rect.x0 * ZOOM)), max(0, int(rect.y0 * ZOOM))
    x1, y1 = min(w, int(rect.x1 * ZOOM) + 1), min(h, int(rect.y1 * ZOOM) + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return False
    box = luma[y0:y1, x0:x1]
    bg = np.median(np.concatenate([box[0], box[-1], box[:, 0], box[:, -1]]))
    return (np.abs(box - bg) > INK).mean() > INK_SHARE


def invisible_mode(page, rot):
    """Границы фрагментов в невидимом режиме отрисовки или с нулевой непрозрачностью."""
    out = []
    for sp in page.get_texttrace():
        if sp["type"] == 3 or sp["opacity"] == 0:
            out.append(pymupdf.Rect(sp["bbox"]) * rot)
    return out


def is_short(text):
    """Номер, знак или одно-два слова. Указание модели в такой фрагмент не помещается."""
    return len(re.findall(r"[^\W\d_]{2,}", text)) < 3


def check_page(page):
    """Скрытые строки страницы, короткие скрытые фрагменты и признак распознанного скана."""
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_MEDIABOX_CLIP
    lines = []
    for block in page.get_text("dict", flags=flags, clip=pymupdf.INFINITE_RECT(), sort=True)["blocks"]:
        for ln in block.get("lines", []):
            spans = [sp for sp in ln["spans"] if sp["text"].strip()]
            if spans:
                lines.append(spans)
    if not lines:
        return [], [], False, []
    rot = page.rotation_matrix  # координаты текста даны для страницы без поворота
    luma = page_luma(page)
    hidden_mode = invisible_mode(page, rot)
    images = [pymupdf.Rect(im["bbox"]) * rot for im in page.get_image_info()]
    visible = page.rect
    found, minor, scan, page_text = [], [], False, []
    for spans in lines:
        marks = []
        for sp in spans:
            r = pymupdf.Rect(sp["bbox"]) * rot
            invisible = any(r.intersects(h) for h in hidden_mode)
            if not r.intersects(visible):
                reason = "за границей видимой области страницы"
            elif invisible and any(r.intersects(im) for im in images):
                scan = True  # текстовый слой распознанного скана поверх изображения
                reason = None
            elif sp["size"] < MIN_PT:
                reason = f"кегль {sp['size']:.1f} пт"
            elif not has_ink(luma, r & visible):
                if invisible:
                    reason = "невидимый режим отрисовки"
                else:
                    reason = "текст не виден на странице, цвет совпадает с фоном или текст закрыт"
            elif ZERO_WIDTH_SPLIT.search(sp["text"]):
                reason = "знаки нулевой ширины внутри текста"
            else:
                reason = None
            marks.append((reason, sp["text"]))
        # видимый текст строки для агентской системы, скрытые фрагменты заменяются пометкой
        shown, prev_hidden = [], False
        for reason, s in marks:
            if reason is None:
                shown.append(ZERO_WIDTH.sub("", s))
            elif not prev_hidden:
                shown.append(" [скрытый фрагмент исключен] ")
            prev_hidden = reason is not None
        box = pymupdf.Rect(spans[0]["bbox"])
        for sp in spans[1:]:
            box |= pymupdf.Rect(sp["bbox"])
        page_text.append((box * rot, "".join(shown).strip()))
        # соседние фрагменты строки с одним признаком сводятся в одну запись
        cur, buf = None, []
        for reason, text in marks + [(None, "")]:
            if reason != cur and buf:
                line = "".join(buf).strip()
                if is_short(line) and not cur.startswith("знаки"):
                    minor.append(line)
                else:
                    found.append((cur, line))
                buf = []
            cur = reason
            if reason:
                buf.append(text)
    return found, minor, scan, page_text


def check_outside(doc):
    """Текст вне страниц, свойства файла, примечания, вложения."""
    found = []
    for key, val in (doc.metadata or {}).items():
        if isinstance(val, str) and val.strip() and (ADDRESSED.search(val) or ZERO_WIDTH.search(val)
                                                     or len(val) > 300):
            found.append(("свойства файла", f"поле {key}", val.strip()))
    xmp = doc.get_xml_metadata() or ""
    xmp_text = " ".join(t.strip() for t in re.findall(r">([^<>]+)<", xmp) if t.strip())
    if ADDRESSED.search(xmp_text) or ZERO_WIDTH.search(xmp_text):
        found.append(("свойства файла", "метаданные XMP", xmp_text[:500]))
    for page in doc:
        for annot in page.annots() or []:
            text = (annot.info.get("content") or "").strip()
            if text:
                found.append(("примечание к странице", f"с. {page.number + 1}", text))
    for name in doc.embfile_names():
        found.append(("вложенный файл", "вложение", name))
    return found


def visual_rows(items):
    """Фрагменты на одной высоте страницы, например ячейки строки таблицы, сводятся в одну строку через «|»."""
    rows = []
    for box, s in sorted(items, key=lambda x: (x[0].y0, x[0].x0)):
        if not s:
            continue
        mid = (box.y0 + box.y1) / 2
        if rows and rows[-1][0] <= mid <= rows[-1][1]:
            rows[-1][2].append((box.x0, s))
        else:
            rows.append([box.y0, box.y1, [(box.x0, s)]])
    return [" | ".join(s for _, s in sorted(cells)) for _, _, cells in rows]


def page_note(page, scan, text):
    """Пометка о странице, текст которой взят со скана или отсутствует."""
    if not any(text):
        if page.get_image_info():
            return "[На странице нет текстового слоя, это изображение. Сведения с нее сверяются по изображению.]"
        return "[На странице нет текста.]"
    if scan:
        return "[Текст страницы распознан со скана, при расхождении верно изображение страницы.]"
    area = page.rect.width * page.rect.height
    if any(pymupdf.Rect(im["bbox"]).get_area() > 0.2 * area for im in page.get_image_info()):
        return "[На странице есть изображение без текстового слоя. Сведения с него сверяются по изображению.]"
    return ""


def check_pdf(path):
    rows, scans, minor, pages = [], [], {}, []
    doc = pymupdf.open(path)
    for page in doc:
        hidden, short, scan, text = check_page(page)
        lines = visual_rows(text)
        note = page_note(page, scan, lines)
        pages.append("\n".join(x for x in [f"[СТРАНИЦА {page.number + 1}]", note] + lines if x))
        rows += [(f"с. {page.number + 1}", reason, text) for reason, text in hidden]
        if short:
            minor[page.number + 1] = short
        if scan:
            scans.append(page.number + 1)
    rows += [(where, reason, text) for reason, where, text in check_outside(doc)]
    doc.close()
    return rows, scans, minor, pages


def pages_span(nums):
    """Перечень страниц с диапазонами, 3, 5—8, 11."""
    out, start = [], None
    for i, n in enumerate(nums):
        if start is None:
            start = n
        if i + 1 == len(nums) or nums[i + 1] != n + 1:
            out.append(str(start) if start == n else f"{start}—{n}")
            start = None
    return ", ".join(out)


def write_text(rel, pages, workdir):
    """Текст PDF по страницам в рабочую папку."""
    dst = workdir / rel.parent / f"{rel.stem}_текст.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    head = (f"# {rel.name}, текст по страницам\n\nТекст подготовлен из файла {rel.name} до начала сессии. "
            "Маркер [СТРАНИЦА N] обозначает лист N файла, номер, напечатанный на листе, приведен в самом тексте. "
            "Скрытые строки исключены, их перечень хранится вне рабочей папки.\n")
    dst.write_text(head + "\n" + "\n\n".join(pages) + "\n", encoding="utf-8")
    return dst


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    source = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else SOURCE
    workdir = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else TARGET
    report = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else REPORT
    if not source.exists():
        sys.exit(f"Папка или файл не найдены: {source}")
    folder = source if source.is_dir() else source.parent
    if workdir == report.parent or workdir in report.parents:
        sys.exit("Перечень сохраняется вне рабочей папки, укажите другой путь для перечня")
    files = [source] if source.is_file() else sorted(p for p in source.rglob("*") if p.is_file())
    files = [p for p in files if not p.name.startswith(("Что класть", "."))]
    pdfs = [p for p in files if p.suffix.lower() == ".pdf"]
    texts = [p for p in files if p.suffix.lower() in (".txt", ".md")]
    other = [p for p in files if p not in pdfs and p not in texts]
    blocks, total, npages, made = [], 0, 0, []
    for f in pdfs:
        rel = f.relative_to(folder)
        print("Проверяется", rel, flush=True)
        rows, scans, minor, pages = check_pdf(f)
        npages += len(pages)
        total += len(rows)
        made.append(write_text(rel, pages, workdir))
        for where, reason, text in rows:
            blocks += ["", f"{rel}, {where}", f"  признак  {reason}", f"  текст    {text}"]
        if minor:
            sample = " | ".join(x for v in minor.values() for x in v)
            blocks += ["", f"{rel}, справочно",
                       f"  на с. {pages_span(sorted(minor))} есть короткие скрытые фрагменты (номера, знаки, отдельные",
                       f"  слова), всего {sum(len(v) for v in minor.values())}, например {sample[:150]}"]
        if scans:
            blocks += ["", f"{rel}, справочно",
                       f"  на с. {pages_span(scans)} поверх изображения лежит текстовый слой распознанного скана,",
                       "  его совпадение с изображением скрипт не проверяет"]
    for f in texts:
        dst = workdir / f.relative_to(folder)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(f.read_bytes())
        made.append(dst)
    head = [f"Проверено файлов PDF {len(pdfs)}, страниц {npages}, найдено скрытых строк {total}"]
    if other:
        head.append("Файлы другого формата не проверялись и в рабочую папку не переданы, их нужно сохранить в PDF: "
                    + ", ".join(str(p.relative_to(folder)) for p in other))
    text = "\n".join(head + blocks)
    print()
    print(text)
    report.write_text(text + "\n", encoding="utf-8")
    print()
    print("Перечень сохранен в файл", report)
    print("Текст для агентской системы сохранен в рабочую папку, файлов", len(made))


if __name__ == "__main__":
    main()
