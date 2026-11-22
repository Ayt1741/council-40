#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Исполнитель: СВОИ 100 поисковых запросов по своей полосе (требование заказчика хода 60).

Заказчик: «с 40 агентами сделать 4000 запросов» — 10 руководителей × 100 + 30 исполнителей × 100.
Исполнитель получает полосу своего руководителя (shard % 10) и придумывает 100 СВОИХ запросов,
отличающихся от плана руководителя: другие углы (ошибки, флаги, версии, сравнения, рус./англ.).
"""
import argparse
import json
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cr_common as c  # noqa: E402

ЗДЕСЬ = os.path.dirname(os.path.abspath(__file__))


def вытащить_запросы(ответ):
    """Достаёт запросы из любого ответа модели: плоский массив, вложенная структура,
    обрезанный хвост. Возвращает список словарей вида {"q": ...}."""
    if not ответ:
        return []
    д = c.разобрать_json(ответ)
    итог = []

    def обойти(узел, глубина=0):
        if глубина > 4 or узел is None:
            return
        if isinstance(узел, list):
            for э in узел:
                if isinstance(э, str) and len(э.strip()) > 3:
                    итог.append({"q": э.strip(), "cat": "inside", "lang": "ru" if re.search("[а-яА-Я]", э) else "en", "want": ""})
                else:
                    обойти(э, глубина + 1)
        elif isinstance(узел, dict):
            if isinstance(узел.get("q"), str) and узел["q"].strip():
                итог.append(узел)
                return
            # ВАЖНО: если в объекте есть поле со списком запросов — берём ТОЛЬКО его
            # (иначе в «запросы» попадут restated_task, sub_hypotheses — пересказ задачи, а не запросы)
            найден_список = False
            for ключ in ("queries", "запросы", "new_queries", "items", "results", "list"):
                if ключ in узел:
                    обойти(узел[ключ], глубина + 1)
                    найден_список = True
            if найден_список:
                return
            for зн in узел.values():
                if isinstance(зн, (list, dict)):
                    обойти(зн, глубина + 1)

    обойти(д)
    # добор регуляркой: обрезанный JSON разбирается частично — добавляем всё, что видно
    for м in re.finditer(r'"q"\s*:\s*"((?:[^"\\]|\\.){3,220})"', ответ):
        if not any(м.group(1) == q.get("q") for q in итог):
            итог.append({"q": м.group(1), "cat": "inside", "lang": "en", "want": ""})
    if not итог:
        # последний шанс: вытащить ВСЕ строки "q": "..." даже из обрезанного JSON
        for м in re.finditer(r'"q"\s*:\s*"((?:[^"\\]|\\.){3,220})"', ответ):
            итог.append({"q": м.group(1), "cat": "inside", "lang": "en", "want": ""})
    return итог


def полосы():
    д = json.load(open(os.path.join(ЗДЕСЬ, "lanes.json"), encoding="utf-8"))
    return д["lanes"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--total", type=int, default=30)
    ap.add_argument("--plans", required=True, help="папка с планами руководителей")
    ap.add_argument("--out", required=True)
    ap.add_argument("--count", type=int, default=int(os.environ.get("CR_QUERIES", "100")))
    a = ap.parse_args()

    полосы_ = полосы()
    моя = полосы_[a.shard % len(полосы_)]
    # что уже придумал руководитель этой полосы (чтобы не повторяться)
    plan_путь = os.path.join(a.plans, "plan-%s.json" % моя["id"])
    былые = []
    try:
        п = json.load(open(plan_путь, encoding="utf-8"))
        былые = [q["q"] for q in (п.get("queries") or [])]
        if not былые:
            for файл in os.listdir(a.plans):
                if файл.endswith(".json"):
                    try:
                        д2 = json.load(open(os.path.join(a.plans, файл), encoding="utf-8"))
                        if (д2.get("lane") or {}).get("id") == моя["id"]:
                            былые = [q["q"] for q in (д2.get("queries") or [])]
                            break
                    except Exception:
                        pass
    except Exception:
        былые = []

    протокол, задача = c.протокол_и_задача()
    система = ("ТЫ — ИСПОЛНИТЕЛЬ №%d СОВЕТА (40 агентов). Твоя полоса: %s (гипотеза %s). "
               "Ты придумываешь СВОИ поисковые запросы — другие углы, чем у руководителя: "
               "точные сообщения об ошибках, флаги, версии, сравнения A/B, обходные пути, русскоязычные источники, "
               "форумы, официальная документация, issue на GitHub, arXiv. Отвечай ТОЛЬКО JSON-массивом.\n\n"
               "=== ПРОТОКОЛ ЗАКАЗЧИКА ===\n%s" % (a.shard + 1, моя["title"], моя["hyp"], протокол[:2500]))
    пользователь = ("=== ЗАДАЧА ===\n%s\n\n=== РУКОВОДИТЕЛЬ ЭТОЙ ПОЛОСЫ УЖЕ ПРЕДЛОЖИЛ (не повторяй) ===\n%s\n\n"
                    'Верни массив из РОВНО %d объектов: [{"q": "запрос", "cat": "inside|break|workaround|others|forbidden", '
                    '"lang": "en|ru", "want": "что хочу узнать, до 15 слов"}]. '
                    "Запросы должны быть разными и конкретными. Примерно каждая третья — на русском. "
                    "ЖЁСТКО: НЕ пиши решений и советов — только список поисковых запросов про память и правила ИИ-агентов."
                    % (задача[:2000], json.dumps(былые[:100], ensure_ascii=False), a.count))

    # БАТЧИ: 100 за один вызов модель обрывает и путает структуру → по 25, четыре вызова
    РАЗМЕР = int(os.environ.get("CR_BATCH", "25"))
    батчей = max(1, (a.count + РАЗМЕР - 1) // РАЗМЕР)
    все_сырые = []
    for б in range(батчей):
        польз_б = пользователь + ("\n\nЭТО БАТЧ %d из %d: выдай ровно %d запросов, продолжая список, без повторов."
                                  % (б + 1, батчей, min(РАЗМЕР, a.count - б * РАЗМЕР)))
        ответ = c.модель(система, польз_б, макс=int(os.environ.get("CR_MAXTOK", "9000")),
                         темп=0.4 + 0.1 * (б % 2), смещение=a.shard + б, сильные=True)
        все_сырые += вытащить_запросы(ответ)
        c.log("  батч %d/%d: вытащено %d" % (б + 1, батчей, len(вытащить_запросы(ответ))))
    # ДОБИВКА: пока не набрано count, просим добавить недостающие (не больше 2 попыток)
    for добор in range(2):
        недобор = a.count - len(все_сырые)
        if недобор <= 0:
            break
        уже = [q.get("q", "") for q in все_сырые][:120]
        польз_д = (пользователь + "\n\nУЖЕ ЕСТЬ (не повторяй): %s\n\nДОБАВЬ РОВНО %d НОВЫХ запросов, верни ТОЛЬКО их массив."
                   % (json.dumps(уже, ensure_ascii=False)[:4000], min(недобор, 30)))
        ответ_д = c.модель(система, польз_д, макс=int(os.environ.get("CR_MAXTOK", "9000")),
                           темп=0.6, смещение=a.shard + 7 + добор, сильные=True)
        добавили = вытащить_запросы(ответ_д)
        все_сырые += добавили
        c.log("  добор %d: +%d (теперь %d из %d)" % (добор + 1, len(добавили), len(все_сырые), a.count))
    данные = все_сырые
    if isinstance(данные, dict):
        данные = данные.get("queries") or []

    очищенные, видели = [], set()
    for q in данные if isinstance(данные, list) else []:
        if not isinstance(q, dict) or not str(q.get("q", "")).strip():
            continue
        текст = str(q["q"]).strip()[:220]
        if текст.lower() in видели:
            continue
        видели.add(текст.lower())
        очищенные.append({"id": "S%d-%03d" % (a.shard, len(очищенные) + 1), "q": текст,
                          "cat": str(q.get("cat", ""))[:12], "lang": str(q.get("lang", "en"))[:2],
                          "want": str(q.get("want", ""))[:160], "hyp": моя["hyp"], "leader": моя["id"]})
    c.писать_json(a.out, {"shard": a.shard, "lane": моя, "ok": bool(очищенные),
                          "queries": очищенные, "модели": c.СТАТИСТИКА_МОДЕЛЕЙ})
    c.log("исполнитель S%d: запросов %d" % (a.shard, len(очищенные)))
    return 0 if очищенные else 2


if __name__ == "__main__":
    sys.exit(main())
