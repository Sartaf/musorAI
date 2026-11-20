#!/usr/bin/env python3
"""Завантажує потрібні статті з zakon.rada.gov.ua у knowledge/*.md.

Запуск: python3 scripts/build_kb.py
Список статей редагується в scripts/kb_articles.json.
Якщо сайт не віддає текст, збережіть його вручну в knowledge/<назва>.md.
"""
import html
import json
import os
import re
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "knowledge")


def fetch(code):
    url = "https://zakon.rada.gov.ua/laws/show/%s/print" % code
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (musorAI kb builder)"})
    return urllib.request.urlopen(req, timeout=90).read().decode("utf-8", errors="replace")


def to_text(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</tr>", "\n", h)
    h = re.sub(r"<[^>]+>", "", h)
    return html.unescape(h).replace("\xa0", " ")


def articles(text):
    out = {}
    for part in re.split(r"\n\s*(?=Стаття\s+\d+(?:-\d+)?\.)", text):
        m = re.match(r"Стаття\s+(\d+(?:-\d+)?)\.", part)
        if m and m.group(1) not in out:
            out[m.group(1)] = re.sub(r"\n{3,}", "\n\n", part).strip()
    return out


def main():
    with open(os.path.join(HERE, "kb_articles.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    os.makedirs(OUT, exist_ok=True)
    for slug, c in cfg.items():
        try:
            arts = articles(to_text(fetch(c["code"])))
        except Exception as e:
            print("[!] %s: не вдалося завантажити (%s). Збережіть текст вручну в knowledge/%s.md" % (slug, e, slug))
            continue
        parts, missing = [], []
        for n in c["articles"]:
            if n in arts:
                parts.append(arts[n])
            else:
                missing.append(n)
        head = "# %s (витяг, офіційний текст з zakon.rada.gov.ua)\n\n" % c["title"]
        with open(os.path.join(OUT, slug + ".md"), "w", encoding="utf-8") as f:
            f.write(head + "\n\n".join(parts) + "\n")
        msg = "%s: %d статей" % (slug, len(parts))
        if missing:
            msg += ", не знайдено: " + ", ".join(missing)
        print(msg)


if __name__ == "__main__":
    main()
