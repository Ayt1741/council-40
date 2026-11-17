#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Совет: кластеризация готовых решений, голосование 10 руководителей, сборка plan.md / findings.md / council-result.json / REPORT.md."""
import argparse
import glob
import json
import os
import sys

import cr_common as c


def загрузить(папка, шаблон):
    рез = []
    for п in sorted(glob.glob(os.path.join(папка, шаблон))):
        try:
            рез.append(json.load(open(п, encoding="utf-8")))
        except Exception:
            pass
    return рез


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plans", required=True)
    ap.add_argument("--exec1", required=True)
    ap.add_argument("--analyses", required=True)
    ap.add_argument("--exec2", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    планы = загрузить(a.plans, "plan-*.json")
    анализы = загрузить(a.analyses, "analysis-*.json")
    e1 = [it for e in загрузить(a.exec1, "exec1-*.json") for it in e.get("items", [])]
    e2 = [it for e in загрузить(a.exec2, "exec2-*.json") for it in e.get("items", [])]
    протокол, задача = c.протокол_и_задача()

    # --- plan.md: ЭТАП 0, п.4
    строки = ["# plan.md — план запросов (протокол заказчика, этап 0)", "", "| № | гипотеза | текст запроса | что хочу узнать |", "|---|---|---|---|"]
    n = 0
    for p in sorted(планы, key=lambda x: int(x["leader"][1:])):
        for q in p["queries"]:
            n += 1
            строки.append("| %d | %s | %s | %s |" % (n, q["hyp"] + " " + q["cat"], q["q"].replace("|", "/"), (q["want"] or "").replace("|", "/")))
    n1 = n
    for an in sorted(анализы, key=lambda x: int(x["leader"][1:])):
        for q in an["new_queries"]:
            n += 1
            строки.append("| %d | %s %s (ПО ХОДУ) | %s | %s |" % (n, q["hyp"], q["cat"], q["q"].replace("|", "/"), (q["want"] or "").replace("|", "/")))
    open(os.path.join(a.out, "plan.md"), "w", encoding="utf-8").write("\n".join(строки) + "\n")
    n2 = n - n1

    # --- findings.md: гипотеза → что нашли → ссылка → вердикт
    ф = ["# findings.md — гипотеза → что нашли → ссылка → вердикт", ""]
    for an in sorted(анализы, key=lambda x: int(x["leader"][1:])):
        ф.append("## %s · %s — вердикт: %s (вес %s)" % (an["leader"], an["lane"]["title"], an["verdict"], an.get("weight")))
        ф.append("Руководитель: %s" % an["reason"])
        for x in an["confirmed"]:
            ф.append("- ПОДТВЕРЖДЕНО: %s — «%s» — %s" % (x.get("claim", ""), str(x.get("quote", ""))[:220], x["url"]))
        for x in an["refuted"]:
            ф.append("- ОПРОВЕРГНУТО: %s — «%s» — %s" % (x.get("claim", ""), str(x.get("quote", ""))[:220], x["url"]))
        for x in an["ready_solutions"]:
            ф.append("- ГОТОВОЕ РЕШЕНИЕ: **%s** — %s (%s) — %s" % (x.get("name", ""), x.get("what", ""), x.get("stop_condition", ""), x["url"]))
        if an.get("unverified_claims"):
            ф.append("- (отброшено без дословной цитаты: %d)" % an["unverified_claims"])
        ф.append("")
    open(os.path.join(a.out, "findings.md"), "w", encoding="utf-8").write("\n".join(ф) + "\n")

    # --- кластеризация решений
    элементы = []
    for an in анализы:
        for x in an["ready_solutions"]:
            элементы.append({"leader": an["leader"], "name": x.get("name", ""), "url": x["url"], "what": x.get("what", "")})
    for it in e2:
        for r in it["results"]:
            if (r.get("rel") or 0) >= 2 and len(элементы) < 36:
                элементы.append({"leader": it["leader"], "name": r["title"][:80], "url": r["url"], "what": r.get("note", "")})
    элементы = [{**x, "what": x["what"][:120], "name": x["name"][:70]} for x in элементы[:36]]
    for i, x in enumerate(элементы, 1):
        x["r"] = "R%d" % i
    система = ("Ты — секретарь совета. Сгруппируй найденные готовые решения в НЕ БОЛЕЕ 10 кандидатов (семейств приёмов). Используй ТОЛЬКО присланные элементы: "
               "названия и ссылки не выдумывай. Отвечай только JSON.")
    польз = ("Элементы (R-номер, руководитель, название, ссылка, что делает):\n%s\n\nВерни JSON: "
             '{"candidates": [{"id": "S1", "name": "короткое название семейства приёмов", "what": "что это и как применить к задаче, до 40 слов", "members": ["R1","R4"]}]}\n\nЗадача:\n%s'
             % (json.dumps(элементы, ensure_ascii=False), задача[:1500]))
    д = c.разобрать_json(c.модель(система, польз, макс=2000, темп=0.2, сильные=True)) or {}
    кандидаты = []
    for k in (д.get("candidates") or [])[:10]:
        if not isinstance(k, dict):
            continue
        члены = [x for x in элементы if x["r"] in (k.get("members") or [])]
        кандидаты.append({"id": str(k.get("id", "S%d" % (len(кандидаты) + 1))), "name": str(k.get("name", ""))[:100], "what": str(k.get("what", ""))[:300],
                          "sources": sorted({x["url"] for x in члены})[:6], "leaders": sorted({x["leader"] for x in члены})})

    # --- голосование десяти
    голоса = []
    if кандидаты:
        список = [{"id": k["id"], "name": k["name"], "what": k["what"], "источников": len(k["sources"])} for k in кандидаты]
        for an in sorted(анализы, key=lambda x: int(x["leader"][1:])):
            система_в = ("ТЫ — РУКОВОДИТЕЛЬ %s СОВЕТА, у тебя ГОЛОС. Выбери три лучших кандидата решения проблемы заказчика (на первом месте — самый сильный). "
                         "Голосуй по доказательствам и ограничениям задачи (бесплатно, stdlib, без внешних хуков). Отвечай только JSON." % an["leader"])
            польз_в = ("Задача и ограничения:\n%s\n\nТвой разбор (%s): вердикт %s — %s\n\nКандидаты:\n%s\n\n"
                       'Верни JSON: {"top3": ["S2","S1","S5"], "reason": "до 40 слов", "against": ["S7"], "risk": "главный риск выбранного, до 25 слов"}'
                       % (задача[:1800], an["lane"]["title"], an["verdict"], an["reason"], json.dumps(список, ensure_ascii=False)))
            г = c.разобрать_json(c.модель(система_в, польз_в, макс=700, темп=0.2, смещение=int(an["leader"][1:]), сильные=True)) or {}
            top = [str(x) for x in (г.get("top3") or []) if str(x) in {k["id"] for k in кандидаты}][:3]
            голоса.append({"leader": an["leader"], "top3": top, "reason": str(г.get("reason", ""))[:240], "against": г.get("against", []), "risk": str(г.get("risk", ""))[:200]})
    очки = {k["id"]: 0 for k in кандидаты}
    for g in голоса:
        for место, sid in enumerate(g["top3"]):
            очки[sid] += 3 - место
    рейтинг = sorted(кандидаты, key=lambda k: -очки[k["id"]])
    for k in рейтинг:
        k["очки"] = очки[k["id"]]

    # --- итоговый отчёт (этап 4 протокола)
    система_о = ("Ты — секретарь совета. Напиши отчёт строго по протоколу заказчика, ЭТАП 4, ТОЛЬКО на основе присланных данных: таблица «источник → что дал → что внедрить или отвергнуть», "
                 "отдельный блок «границы возможного», отдельный блок «что делать, если не заработало». Не выдумывай ссылки и факты. По-русски, кратко.")
    польз_о = ("Рейтинг кандидатов (очки голосов, источники):\n%s\n\nВердикты полос:\n%s\n\nЗадача:\n%s"
               % (json.dumps(рейтинг, ensure_ascii=False)[:4500],
                  json.dumps([{"полоса": x["lane"]["title"], "вердикт": x["verdict"], "вес": x.get("weight"), "причина": x["reason"]} for x in анализы], ensure_ascii=False)[:2200],
                  задача[:1500]))
    отчёт = c.модель(система_о, польз_о, макс=1900, темп=0.2, сильные=True) or "(секретарь не ответил)"
    статистика = {"запросов_раунд1": n1, "запросов_раунд2_по_ходу": n2, "доля_по_ходу": round(100.0 * n2 / max(1, n1 + n2), 1),
                  "исполнителей_раунд1": len(загрузить(a.exec1, "exec1-*.json")), "исполнителей_раунд2": len(загрузить(a.exec2, "exec2-*.json")),
                  "руководителей_план": len(планы), "руководителей_разбор": len(анализы), "голосов": len(голоса),
                  "результатов_раунд1": sum(len(it["results"]) for it in e1), "результатов_раунд2": sum(len(it["results"]) for it in e2),
                  "с_rel>=2": sum(1 for it in e1 + e2 for r in it["results"] if (r.get("rel") or 0) >= 2),
                  "модели_голосование": c.СТАТИСТИКА_МОДЕЛЕЙ}
    c.писать_json(os.path.join(a.out, "council-result.json"), {"статистика": статистика, "кандидаты": рейтинг, "голоса": голоса,
                                                              "вердикты": [{"leader": x["leader"], "title": x["lane"]["title"], "verdict": x["verdict"], "weight": x.get("weight"), "reason": x["reason"]} for x in анализы]})
    р = ["# REPORT.md — отчёт совета (этап 4 протокола)", "", "Статистика: %s" % json.dumps({k: v for k, v in статистика.items() if k != "модели_голосование"}, ensure_ascii=False), "",
         "## Рейтинг кандидатов (голосование 10 руководителей, очки Борда 3-2-1)", ""]
    for k in рейтинг:
        р.append("- **%s** (очков %d; руководители: %s) — %s\n  источники: %s" % (k["name"], k["очки"], ", ".join(k["leaders"]), k["what"], "; ".join(k["sources"][:4])))
    р += ["", "## Отчёт секретаря", "", отчёт, ""]
    open(os.path.join(a.out, "REPORT.md"), "w", encoding="utf-8").write("\n".join(р) + "\n")
    c.log("совет: кандидатов %d, голосов %d, запросов %d+%d" % (len(кандидаты), len(голоса), n1, n2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
