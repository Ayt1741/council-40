#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Исполнитель: берёт свою долю запросов, ищет настоящим поиском, отмечает релевантность (модель), ничего не придумывает."""
import argparse
import glob
import os
import re
import sys

import cr_common as c


def собрать_запросы(раунд, src):
    qs = []
    if раунд == 1:
        # ход 60: сначала СВОИ запросы исполнителей (execplan-*.json), затем планы руководителей
        for п in sorted(glob.glob(os.path.join(src, "execplan-*.json"))):
            qs += json_запросы(п, "queries")
        for п in sorted(glob.glob(os.path.join(src, "plan-*.json"))):
            qs += json_запросы(п, "queries")
    else:
        for п in sorted(glob.glob(os.path.join(src, "analysis-*.json"))):
            qs += json_запросы(п, "new_queries")
    return qs


def json_запросы(путь, ключ):
    import json
    try:
        d = json.load(open(путь, encoding="utf-8"))
    except Exception:
        return []
    лидер, гип = d.get("leader", "?"), (d.get("lane") or {}).get("hyp", "")
    рез = []
    for i, q in enumerate(d.get(ключ) or [], 1):
        if isinstance(q, dict) and str(q.get("q", "")).strip():
            рез.append({"id": q.get("id") or "%s-N%02d" % (лидер, i), "q": str(q["q"]).strip()[:220], "cat": q.get("cat", ""),
                        "lang": q.get("lang", ""), "want": q.get("want", ""), "hyp": q.get("hyp") or гип, "leader": лидер})
    return рез


ТЕГИ = {"H1": r"compact|summariz|compress|сжат|сводк", "H2": r"system prompt|user message|recency|reminder|inject|hook|channel|напомин",
        "H3": r"too many|instruction (?:count|density|overload)|conflict|contradict|precedence|too long|перегруз|противореч",
        "H4": r"negat|prohibit|omission|don.?t|never|запрет|positive", "H5": r"verif|self.?check|judge|gate|guardrail|completion|false (?:success|done)|receipt|stop hook|провер",
        "H6": r"pressure|permission|override|persisten|continue|разрешен", "H7": r"multi.?turn|long (?:conversation|session)|context rot|fresh session|handoff|передач",
        "H8": r"hook|platform|agent mode|model switch|enforce|принужд"}
СТОП = {"with", "that", "this", "from", "agent", "agents", "what", "have", "does", "your", "when", "into", "about", "using"}


def оценить(q, r):
    """Детерминированная оценка релевантности (0-3) и гипотез: совпадение ключевых слов запроса с заголовком+текстом, бонус за код/открытые источники."""
    ключ = {w.lower() for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9_.\-]{4,}", q)} - СТОП
    текст = (r["title"] + " " + r["text"]).lower()
    доля = sum(1 for w in ключ if w in текст) / max(1, len(ключ))
    бонус = 1 if (r["src"] in ("github", "github-issue", "arxiv", "openalex") or "github.com" in r["url"]) else 0
    rel = 3 if (доля >= 0.6 and бонус) or доля >= 0.8 else 2 if доля >= 0.4 else 1 if доля >= 0.2 else 0
    теги = [h for h, ш in ТЕГИ.items() if re.search(ш, текст)]
    return rel, теги


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--total", type=int, default=30)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    все = собрать_запросы(a.round, a.src)
    мои = [q for i, q in enumerate(все) if i % a.total == a.shard]
    c.log("исполнитель %d (раунд %d): всего запросов %d, моих %d" % (a.shard, a.round, len(все), len(мои)))
    элементы = []
    for q in мои:
        рез, квит = c.искать(q["q"])
        результаты = []
        for i, r in enumerate(рез, 1):
            rel, теги = оценить(q["q"], r)
            результаты.append({**r, "i": i, "rel": rel, "hyp": теги, "note": r["text"][:160]})
        элементы.append({"qid": q["id"], "q": q["q"], "cat": q["cat"], "lang": q["lang"], "want": q["want"], "hyp": q["hyp"], "leader": q["leader"],
                         "results": результаты, "receipts": квит})
        c.log("  %s: результатов %d (%s)" % (q["id"], len(результаты), ", ".join("%s:%s" % (k["инструмент"], k["статус"]) for k in квит)))
    c.писать_json(a.out, {"shard": a.shard, "round": a.round, "items": элементы, "queries_total": len(все)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
