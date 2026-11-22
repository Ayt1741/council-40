#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Руководитель: ЭТАП 0 протокола заказчика для своей полосы (формулировка, под-гипотезы, 10–14 запросов по категориям)."""
import argparse
import json
import os
import sys
import time

import cr_common as c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    протокол, задача = c.протокол_и_задача()
    полоса = c.полосы()[a.id]
    номер = int(a.id[1:])
    система = ("ТЫ — РУКОВОДИТЕЛЬ %s СОВЕТА. Работай по протоколу заказчика (ниже). Сейчас выполняется ТОЛЬКО ЭТАП 0 для твоей полосы. "
               "Ничего не выдумывай: названия инструментов, флагов, проектов и ошибок — точные. Отвечай ТОЛЬКО JSON без пояснений.\n\n"
               "=== ПРОТОКОЛ ЗАКАЗЧИКА ===\n%s" % (a.id, протокол))
    пользователь = ("=== ЗАДАЧА И ФАКТЫ ===\n%s\n\n=== ТВОЯ ПОЛОСА ===\n%s (гипотеза %s): %s\n\n"
                    "Верни JSON такого вида:\n"
                    '{"restated_task": "задача одним абзацем, как ты её понял (3-4 предложения)",\n'
                    ' "contradictions": ["противоречия в условии, если есть"],\n'
                    ' "sub_hypotheses": ["2-3 проверяемых конкурирующих под-гипотезы внутри твоей полосы"],\n'
                    ' "own_new_hypothesis": "ещё ОДНА гипотеза причины, которой нет среди полос совета (1-2 предложения)",\n'
                    ' "count": %d,\n'
                    ' "queries": [{"q": "текст запроса", "cat": "inside|break|workaround|others|forbidden", "lang": "en|ru", "want": "что хочу узнать, до 15 слов"}]}\n\n'
                    "ТРЕБОВАНИЯ К queries: ровно числа из поля count (число задано заказчиком); обязательно есть каждая из категорий inside (как устроено внутри: документация, спеки, баг-трекеры), "
                    "break (как ломается: точные цитаты ошибок, номера issue, названия флагов), workaround (как обходят), others (как делают другие: проекты с открытым кодом), "
                    "forbidden (что официально запрещено или не работает); примерно каждая третья — на русском (lang=ru), остальные на английском; "
                    "вставляй ТОЧНЫЕ имена (Claude Code, AGENTS.md, CLAUDE.md, PreCompact, UserPromptSubmit, LangGraph, Mem0, Letta и т.п. — только те, что реально существуют); "
                    "добавляй слова github / arxiv / issue там, где нужен код или исследование; ищи по формулировке ПРОБЛЕМЫ, а не по своему решению. Запросы НЕ должны повторяться.\n"
                    "ЖЁСТКО: НЕ пиши решений, НЕ пиши советов, НЕ пиши ответов на задачу. Только список поисковых запросов. "
                    "Не уходи в другие темы (Spring, DNS, Kubernetes и т.п.) — только память и правила ИИ-агентов.\n\n"
                    % (задача, a.id, полоса["hyp"], полоса["title"], int(os.environ.get("CR_QUERIES", "30"))))
    time.sleep(int(os.environ.get("CR_STAGGER", "0")) * (номер - 1))
    # БАТЧИ: 100 запросов за вызов модель не выдаёт → по 25, затем добивка
    цель = int(os.environ.get("CR_QUERIES", "30"))
    РАЗМЕР = int(os.environ.get("CR_BATCH", "25"))
    батчей = max(1, (цель + РАЗМЕР - 1) // РАЗМЕР)
    from exec_plan import вытащить_запросы as _выт
    все_q = []
    данные = {}
    for б in range(батчей):
        польз_б = пользователь + ("\n\nЭТО БАТЧ %d из %d: выдай ровно %d объектов queries, продолжая список без повторов."
                                  % (б + 1, батчей, min(РАЗМЕР, цель - б * РАЗМЕР)))
        ответ = c.модель(система, польз_б, макс=int(os.environ.get("CR_MAXTOK", "9000")),
                         темп=0.4 + 0.1 * (б % 2), смещение=номер + б, сильные=True)
        д_б = c.разобрать_json(ответ) or {}
        if isinstance(д_б, dict) and not данные:
            данные = д_б                      # restated_task, sub_hypotheses — из первого батча
        все_q += _выт(ответ)
        c.log("  %s батч %d/%d: +%d (всего %d)" % (a.id, б + 1, батчей, len(_выт(ответ)), len(все_q)))
    for добор in range(2):
        if len(все_q) >= цель:
            break
        польз_д = (пользователь + "\n\nУЖЕ ЕСТЬ (не повторяй): %s\n\nДОБАВЬ РОВНО %d НОВЫХ, верни только их массив."
                   % (json.dumps([q.get("q", "") for q in все_q][:120], ensure_ascii=False)[:4000], min(цель - len(все_q), 30)))
        все_q += _выт(c.модель(система, польз_д, макс=int(os.environ.get("CR_MAXTOK", "9000")),
                               темп=0.6, смещение=номер + 7 + добор, сильные=True))
        c.log("  %s добор %d: теперь %d из %d" % (a.id, добор + 1, len(все_q), цель))
    очищенные = []
    видели = set()
    for q in все_q:
        if not isinstance(q, dict) or not str(q.get("q", "")).strip():
            continue
        т = str(q["q"]).strip()[:220]
        if т.lower() in видели:
            continue
        видели.add(т.lower())
        очищенные.append({"id": "%s-%03d" % (a.id, len(очищенные) + 1), "q": т, "cat": str(q.get("cat", ""))[:12],
                          "lang": str(q.get("lang", "en"))[:2], "want": str(q.get("want", ""))[:160], "hyp": полоса["hyp"]})
        if len(очищенные) >= цель:
            break
    итог = {"leader": a.id, "lane": полоса, "ok": bool(очищенные), "restated_task": данные.get("restated_task", ""),
            "contradictions": данные.get("contradictions", []), "sub_hypotheses": данные.get("sub_hypotheses", []),
            "own_new_hypothesis": данные.get("own_new_hypothesis", ""), "queries": очищенные,
            "модели": c.СТАТИСТИКА_МОДЕЛЕЙ}
    c.писать_json(a.out, итог)
    c.log("%s: запросов %d, под-гипотез %d" % (a.id, len(очищенные), len(итог["sub_hypotheses"])))
    return 0 if очищенные else 2


if __name__ == "__main__":
    sys.exit(main())
