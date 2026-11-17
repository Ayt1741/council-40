#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Руководитель: ЭТАП 0 протокола заказчика для своей полосы (формулировка, под-гипотезы, 10–14 запросов по категориям)."""
import argparse
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
                    ' "queries": [{"q": "текст запроса", "cat": "inside|break|workaround|others|forbidden", "lang": "en|ru", "want": "что хочу узнать, до 15 слов"}]}\n\n'
                    "ТРЕБОВАНИЯ К queries: от 12 до 14 штук; обязательно есть каждая из категорий inside (как устроено внутри: документация, спеки, баг-трекеры), "
                    "break (как ломается: точные цитаты ошибок, номера issue, названия флагов), workaround (как обходят), others (как делают другие: проекты с открытым кодом), "
                    "forbidden (что официально запрещено или не работает); минимум 3 запроса на русском (lang=ru), остальные на английском; "
                    "вставляй ТОЧНЫЕ имена (Claude Code, AGENTS.md, CLAUDE.md, PreCompact, UserPromptSubmit, LangGraph, Mem0, Letta и т.п. — только те, что реально существуют); "
                    "добавляй слова github / arxiv / issue там, где нужен код или исследование; ищи по формулировке ПРОБЛЕМЫ, а не по своему решению."
                    % (задача, a.id, полоса["hyp"], полоса["title"]))
    time.sleep(int(os.environ.get("CR_STAGGER", "0")) * (номер - 1))
    ответ = c.модель(система, пользователь, макс=2600, темп=0.4, смещение=номер, сильные=True)
    данные = c.разобрать_json(ответ) or {}
    очищенные = []
    for i, q in enumerate(данные.get("queries") or [], 1):
        if not isinstance(q, dict) or not str(q.get("q", "")).strip():
            continue
        очищенные.append({"id": "%s-%02d" % (a.id, i), "q": str(q["q"]).strip()[:220], "cat": str(q.get("cat", ""))[:12],
                          "lang": str(q.get("lang", "en"))[:2], "want": str(q.get("want", ""))[:160], "hyp": полоса["hyp"]})
    итог = {"leader": a.id, "lane": полоса, "ok": bool(очищенные), "restated_task": данные.get("restated_task", ""),
            "contradictions": данные.get("contradictions", []), "sub_hypotheses": данные.get("sub_hypotheses", []),
            "own_new_hypothesis": данные.get("own_new_hypothesis", ""), "queries": очищенные,
            "модели": c.СТАТИСТИКА_МОДЕЛЕЙ}
    c.писать_json(a.out, итог)
    c.log("%s: запросов %d, под-гипотез %d" % (a.id, len(очищенные), len(итог["sub_hypotheses"])))
    return 0 if очищенные else 2


if __name__ == "__main__":
    sys.exit(main())
