#!/usr/bin/env python3
"""Збирає базу знань: вибирає потрібні статті з ПОВНИХ офіційних текстів законів.

Куди класти тексти: sources/<назва>.txt (або .html, .md, .docx), де <назва> береться
з scripts/kb_articles.json (npu, kupap, kpk, konstytutsiia).
Тексти завантажуємо з офіційного сайту zakon.rada.gov.ua (кнопка "Завантажити").
Результат: knowledge/<назва>.md. Слово в слово, без переписування.

Запуск: python3 scripts/build_kb.py
Якщо локального файлу немає, скрипт пробує завантажити текст з zakon.rada.gov.ua
(це може не працювати з-за кордону).
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SRC = os.path.join(ROOT, "sources")
OUT = os.path.join(ROOT, "knowledge")


def html_to_text(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</tr>", "\n", h)
    h = re.sub(r"<[^>]+>", "", h)
    return html.unescape(h)


def docx_to_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", " ", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return html.unescape(xml)


def read_local(slug):
    for ext in ("txt", "md", "html", "htm", "docx"):
        p = os.path.join(SRC, "%s.%s" % (slug, ext))
        if not os.path.exists(p):
            continue
        if ext == "docx":
            return docx_to_text(p), p
        raw = open(p, "rb").read()
        for enc in ("utf-8-sig", "cp1251"):
            try:
                t = raw.decode(enc)
                break
            except UnicodeDecodeError:
                t = None
        if t is None:
            t = raw.decode("utf-8", errors="replace")
        return (html_to_text(t) if ext in ("html", "htm") else t), p
    return None, None


def http_get(url, timeout=25, tries=1):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (musorAI kb builder)"})
            return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", errors="replace")
        except Exception as e:
            last = e
            time.sleep(8 * (i + 1))
    raise last


def archive_get(url):
    api = "https://archive.org/wayback/available?url=%s&timestamp=20261120" % urllib.parse.quote(url, safe="")
    snap = json.loads(http_get(api, 30, 3)).get("archived_snapshots", {}).get("closest")
    if not snap or not snap.get("available"):
        raise RuntimeError("немає знімка в Інтернет-архіві: " + url)
    ts = snap["timestamp"]
    return html_to_text(http_get("https://web.archive.org/web/%sid_/%s" % (ts, url), 120, 3)), "%s-%s-%s" % (ts[:4], ts[4:6], ts[6:8])


def fetch_remote(code):
    """Спершу офіційний сайт, потім копія його сторінки з Інтернет-архіву (із зазначенням дати знімка)."""
    base = "https://zakon.rada.gov.ua/laws/show/%s/print" % code
    try:
        return html_to_text(http_get(base)), "завантажено з zakon.rada.gov.ua", None
    except Exception:
        pass
    text, day = archive_get(base)
    return text, "копія офіційної сторінки zakon.rada.gov.ua з Інтернет-архіву, знімок від %s (редакція може бути не найновішою)" % day, day


def covers(arts, c):
    ok = all(a in arts for a in c.get("articles", []))
    for lo, hi in c.get("ranges", []):
        ok = ok and any(lo <= int(k.split("-")[0]) <= hi for k in arts)
    return ok


def normalize(t):
    t = t.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[ \t]+\n", "\n", t)


def split_articles(text):
    """Повертає {номер: текст} за заголовками "Стаття N." (перше входження)."""
    out = {}
    for part in re.split(r"\n\s*(?=Стаття\s+\d+(?:-\d+)?(?:\.|[ \t]*\n))", "\n" + text):
        m = re.match(r"\s*Стаття\s+(\d+(?:-\d+)?)(?:\.|[ \t]*\n)", part)
        if m and m.group(1) not in out:
            out[m.group(1)] = re.sub(r"\n{3,}", "\n\n", part).strip()
    return out


def find_point(text, n, start=0):
    m = re.compile(r"(?m)^%d\.\s" % n).search(text, start)
    return m.start() if m else None


def wanted(keys, cfg):
    exact = set(cfg.get("articles", []))
    ranges = cfg.get("ranges", [])
    res = []
    for k in keys:
        base = int(k.split("-")[0])
        if k in exact or any(a <= base <= b for a, b in ranges):
            res.append(k)
    return res


def sort_key(k):
    p = k.split("-")
    return (int(p[0]), int(p[1]) if len(p) > 1 else 0)


def main():
    with open(os.path.join(HERE, "kb_articles.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    os.makedirs(OUT, exist_ok=True)
    only = [x for x in os.environ.get("KB_ONLY", "").split(",") if x]
    for slug, c in cfg.items():
        if only and slug not in only:
            continue
        text, path = read_local(slug)
        origin = "завантажено вручну з офіційного сайту zakon.rada.gov.ua"
        if text is None:
            try:
                text, origin, day = fetch_remote(c["code"])
                if day and not covers(split_articles(normalize(text)), c):
                    for n in range(2, 10):  # довгі закони Рада ділить на сторінки
                        try:
                            more, _ = archive_get("https://zakon.rada.gov.ua/laws/show/%s/page%d" % (c["code"], n))
                        except Exception:
                            continue
                        text += "\n" + more
                        if covers(split_articles(normalize(text)), c):
                            break
            except Exception as e:
                print("[пропущено] %s: немає sources/%s.txt, а завантаження не вдалося (%s)" % (slug, slug, e))
                continue
        if "points" in c:  # нормативні акти з нумерованими пунктами (не статтями)
            text = normalize(text)
            parts, missing = [], []
            for lo, hi in c["points"]:
                a = find_point(text, lo)
                e = find_point(text, hi + 1, a + 1) if a is not None else None
                if a is None or e is None:
                    missing.append("%d-%d" % (lo, hi))
                    continue
                parts.append(text[a:e].strip())
            if not parts:
                print("[!] %s: пункти не знайдено" % slug)
                continue
            head = "# %s (витяг: пункти %s)\n\nДжерело: %s. Офіційна сторінка: https://zakon.rada.gov.ua/laws/show/%s\nПункти подано без змін, як у вихідному тексті.\n\n" % (c["title"], ", ".join("%d-%d" % tuple(r) for r in c["points"]), origin, c["code"])
            with open(os.path.join(OUT, slug + ".md"), "w", encoding="utf-8") as f:
                f.write(head + "\n\n".join(parts) + "\n")
            print("%s: %d фрагментів (%d символів)%s" % (slug, len(parts), sum(len(x) for x in parts), "; не знайдено: " + ", ".join(missing) if missing else ""))
            continue
        arts = split_articles(normalize(text))
        keys = sorted(wanted(arts.keys(), c), key=sort_key)
        listed = set(c.get("articles", []))
        missing = [a for a in c.get("articles", []) if a not in arts]
        if not keys:
            print("[!] %s: статті не знайдено, перевірте формат файлу" % slug)
            continue
        head = "# %s (витяг)\n\nДжерело: %s. Офіційна сторінка: https://zakon.rada.gov.ua/laws/show/%s\nСтатті подано без змін, як у вихідному тексті.\n\n" % (c["title"], origin, c["code"])
        with open(os.path.join(OUT, slug + ".md"), "w", encoding="utf-8") as f:
            f.write(head + "\n\n".join(arts[k] for k in keys) + "\n")
        msg = "%s: %d статей (%d символів)" % (slug, len(keys), sum(len(arts[k]) for k in keys))
        if missing:
            msg += "; не знайдено: " + ", ".join(missing)
        print(msg)


if __name__ == "__main__":
    sys.exit(main())
