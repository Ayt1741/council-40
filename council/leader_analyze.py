#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Руководитель: ЭТАП 1 — разбор после батча: что подтвердилось (с дословной цитатой), что опровергнуто, какие НОВЫЕ вопросы."""
import argparse
import glob
import json
import os
import sys
import time

import cr_common as c


def загрузить(папка, шаблон):
    рез = []
    for п in sorted(glob.glob(os.path.join(папка, шаблон))):
        try:
            рез.append(json.load(open(п, encoding="utf-8")))
        except Exception:
            pass
    return рез



def _первый(д, *ключи):
    for к in ключи:
        if isinstance(д, dict) and д.get(к) not in (None, "", [], {}):
            return д[к]
    return None


def нормализовать_разбор(д):
    """Модели иногда называют ключи по-своему (status вместо verdict, evidence_confirmed вместо confirmed). Приводим к одной схеме, ничего не придумывая."""
    if not isinstance(д, dict):
        return {}
    for обёртка in ("analysis", "result", "response", "output", "answer"):
        if isinstance(д.get(обёртка), dict) and len(д) <= 3:
            д = д[обёртка]
    сырой = str(_первый(д, "verdict", "status", "conclusion", "hypothesis_status", "result") or "").lower()
    if any(x in сырой for x in ("refut", "reject", "опровер", "не подтвер", "false")):
        вердикт = "refuted"
    elif any(x in сырой for x in ("confirm", "support", "подтвер", "true")):
        вердикт = "confirmed"
    elif сырой:
        вердикт = "unclear"
    else:
        вердикт = ""
    вес = _первый(д, "weight", "confidence", "score")
    try:
        вес = max(0.0, min(1.0, float(str(вес).replace(",", ".")))) if вес is not None else None
    except ValueError:
        вес = None

    def список(*ключи):
        рез = []
        for o in (_первый(д, *ключи) or []):
            if not isinstance(o, dict):
                continue
            рез.append({**o, "claim": str(_первый(o, "claim", "statement", "finding", "what", "summary", "text") or "")[:300],
                        "e": str(_первый(o, "e", "evidence", "evidence_id", "id", "source") or ""),
                        "quote": str(_первый(o, "quote", "citation", "evidence_quote", "excerpt") or "")})
        return рез
    return {"verdict": вердикт, "weight": вес, "reason": str(_первый(д, "reason", "summary", "rationale", "explanation") or ""),
            "confirmed": список("confirmed", "evidence_confirmed", "confirmed_claims", "supporting", "supported", "confirmations"),
            "refuted": список("refuted", "evidence_refuted", "refuted_claims", "contradicting", "contradicted"),
            "ready_solutions": список("ready_solutions", "solutions", "ready_made_solutions", "ready"),
            "gaps": str(_первый(д, "gaps", "unclear", "open_questions") or "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--plans", required=True)
    ap.add_argument("--execs", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    протокол, задача = c.протокол_и_задача()
    полоса = c.полосы()[a.id]
    элементы = [it for e in загрузить(a.execs, "exec1-*.json") for it in e.get("items", [])]
    свои = [it for it in элементы if it["leader"] == a.id]
    чужие = [it for it in элементы if it["leader"] != a.id]
    # доказательства: до 3 лучших результатов на каждый свой запрос + до 6 чужих, где упомянута моя гипотеза
    доказательства, индекс = [], {}

    def добавить(it, r):
        eid = "E%d" % (len(индекс) + 1)
        индекс[eid] = {"url": r["url"], "text": r["text"], "title": r["title"], "qid": it["qid"], "src": r["src"]}
        доказательства.append({"e": eid, "qid": it["qid"], "q": it["q"], "title": r["title"][:120], "text": r["text"][:300], "rel": r.get("rel")})

    кандидаты_свои = [(it, r) for it in свои for r in it["results"]]
    кандидаты_свои.sort(key=lambda x: -(x[1].get("rel") or 0))
    использованные_запросы = {}
    for it, r in кандидаты_свои:
        if len(доказательства) >= 12:
            break
        if использованные_запросы.get(it["qid"], 0) >= 2:      # не больше двух результатов с одного запроса
            continue
        использованные_запросы[it["qid"]] = использованные_запросы.get(it["qid"], 0) + 1
        добавить(it, r)
    n_чужих = 0
    for it in чужие:
        for r in it["results"]:
            if полоса["hyp"] in (r.get("hyp") or []) and (r.get("rel") or 0) >= 2 and n_чужих < 3:
                добавить(it, r)
                n_чужих += 1
    система = ("ТЫ — РУКОВОДИТЕЛЬ %s СОВЕТА. Выполняется ЭТАП 1: разбор после батча по протоколу заказчика. Ты видишь ТОЛЬКО присланные доказательства. "
               "Цитата (quote) — ДОСЛОВНЫЙ фрагмент из поля text указанного доказательства (минимум 12 знаков), иначе она будет отброшена. "
               "Ссылки сам не пиши — указывай номер доказательства e (E1…). Отвечай ТОЛЬКО JSON.\n\n=== ПРОТОКОЛ ЗАКАЗЧИКА ===\n%s" % (a.id, протокол))
    пользователь = ("=== ЗАДАЧА ===\n%s\n\n=== ТВОЯ ПОЛОСА ===\n%s: %s\n\n=== ДОКАЗАТЕЛЬСТВА (%d) ===\n%s\n\n"
                    "Верни JSON:\n"
                    '{"verdict": "confirmed|refuted|unclear", "weight": число 0..1 (насколько гипотеза объясняет проблему), "reason": "до 40 слов",\n'
                    ' "confirmed": [{"claim": "что подтвердилось", "e": "E3", "quote": "дословный фрагмент"}],\n'
                    ' "refuted": [{"claim": "что опровергнуто", "e": "E5", "quote": "дословный фрагмент"}],\n'
                    ' "ready_solutions": [{"name": "название готового решения/проекта/приёма", "e": "E2", "what": "что делает, до 30 слов", "quote": "дословный фрагмент", '
                    '"stop_condition": "code|official|two_sources"}],\n'
                    ' "gaps": "что осталось неясным, до 30 слов"}\n'
                    "ТРЕБОВАНИЯ: ready_solutions — только если есть рабочий код/приём, официальное подтверждение или ≥2 независимых источника; КАЖДЫЙ элемент обязан содержать e и дословную quote "
                    "(пример: {\"name\": \"PreCompact hook\", \"e\": \"E3\", \"what\": \"сохраняет правила перед сжатием\", \"quote\": \"фрагмент из text E3\", \"stop_condition\": \"code\"}); не выдумывай."
                    "\nИТОГ: верни один JSON-объект и ТОЛЬКО с ключами verdict, weight, reason, confirmed, refuted, ready_solutions, gaps (названия ключей не менять)."
                    % (задача, a.id, полоса["title"], len(доказательства), json.dumps(доказательства, ensure_ascii=False)))
    time.sleep(int(os.environ.get("CR_STAGGER", "0")) * (int(a.id[1:]) - 1))

    def проверить(список, ключ_цитаты="quote"):
        ок, плохо = [], []
        for o in (список or []):
            if not isinstance(o, dict):
                continue
            ev = индекс.get(str(o.get("e", "")))
            if ev and c.цитата_дословна(o.get(ключ_цитаты, ""), ev["text"]):
                ок.append({**o, "claim": o.get("claim") or ev["title"], "url": ev["url"], "title": ev["title"], "qid": ev["qid"], "verified": True})
            else:
                плохо.append({**o, "verified": False})
        return ок, плохо

    д, лучший = {}, ({}, -1)
    for попытка in range(3):                 # принимаем разбор, только если в нём есть хотя бы одно ПРОВЕРЕННОЕ подтверждение/решение
        ответ = c.модель(система, пользователь, макс=2200, темп=0.2 + 0.15 * попытка, смещение=int(a.id[1:]) + попытка, сильные=True)
        if os.environ.get("CR_DEBUG"):
            open(a.out + ".raw%d.txt" % попытка, "w", encoding="utf-8").write(ответ or "")
        кандидат = нормализовать_разбор(c.разобрать_json(ответ) or {})
        качество = (len(проверить(кандидат.get("confirmed"))[0]) + len(проверить(кандидат.get("refuted"))[0]) + len(проверить(кандидат.get("ready_solutions"))[0])) if isinstance(кандидат, dict) else 0
        if качество > лучший[1]:
            лучший = (кандидат, качество)
        if качество >= 2:
            break
        c.log("%s: разбор слабый (проверенных элементов %d) — повтор %d" % (a.id, качество, попытка + 1))
    д = лучший[0] if isinstance(лучший[0], dict) else {}
    подтверждено, не_подтверждено = проверить(д.get("confirmed"))
    # ЭТАП 1, п.7: НОВЫЕ вопросы по ходу — отдельным коротким вызовом по новым именам/проектам/флагам из найденного
    были = [q["q"] for q in свои][:60]
    имена_найденного = [e["title"][:90] for e in доказательства][:12] + [str(x.get("name", ""))[:60] for x in (д.get("ready_solutions") or []) if isinstance(x, dict)]
    система2 = ("ТЫ — РУКОВОДИТЕЛЬ %s СОВЕТА. ЭТАП 1, п.7 протокола заказчика: придумай НОВЫЕ поисковые запросы ПО ХОДУ — такие, которых не было в плане. "
                "Они должны опираться на НОВЫЕ имена, флаги, проекты, номера issue и ошибки, которые видны в найденном. Точные имена; для кода добавляй github/issue; "
                "ищи по формулировке проблемы. Отвечай ТОЛЬКО JSON-массивом." % a.id)
    польз2 = ("Гипотеза полосы: %s\nЗапросы, которые уже были: %s\nЧто нашли (заголовки и названия): %s\nГде пробел: %s\n\n"
              'Верни массив из %d объектов (число задано заказчиком): [{"q": "запрос", "cat": "inside|break|workaround|others|forbidden", "lang": "en|ru", "want": "что узнать, до 15 слов"}]'
              % (полоса["title"], json.dumps(были, ensure_ascii=False), json.dumps(имена_найденного, ensure_ascii=False), str(д.get("gaps", ""))[:200], int(os.environ.get("CR_NEW_QUERIES", "30"))))
    массив_новых = c.разобрать_json(c.модель(система2, польз2, макс=int(os.environ.get("CR_MAXNEW", "4000")), темп=0.5, смещение=int(a.id[1:]), сильные=True)) or []
    if isinstance(массив_новых, dict):
        массив_новых = массив_новых.get("queries") or массив_новых.get("new_queries") or []
    опровергнуто, _ = проверить(д.get("refuted"))
    решения, решения_без = проверить(д.get("ready_solutions"))
    новые = []
    for i, q in enumerate(массив_новых if isinstance(массив_новых, list) else [], 1):
        if isinstance(q, dict) and str(q.get("q", "")).strip():
            новые.append({"id": "%s-N%02d" % (a.id, i), "q": str(q["q"]).strip()[:220], "cat": str(q.get("cat", ""))[:12],
                          "lang": str(q.get("lang", "en"))[:2], "want": str(q.get("want", ""))[:160], "hyp": полоса["hyp"]})
    опр_число = len(опровергнуто)
    вердикт_модели = д.get("verdict") or ""
    if вердикт_модели:
        вердикт, источник_вердикта = вердикт_модели, "модель"
    else:
        вердикт = "confirmed" if (len(подтверждено) >= 2 and опр_число == 0) else "refuted" if (опр_число >= 2 and not подтверждено) else "unclear"
        источник_вердикта = "выведен по числу проверенных цитат (модель вердикт не дала)"
    итог = {"leader": a.id, "lane": полоса, "ok": bool(д), "verdict": вердикт, "verdict_source": источник_вердикта, "weight": д.get("weight"), "reason": str(д.get("reason", ""))[:300],
            "confirmed": подтверждено, "refuted": опровергнуто, "ready_solutions": решения, "unverified_claims": len(не_подтверждено) + len(решения_без),
            "new_queries": новые, "gaps": str(д.get("gaps", ""))[:300], "evidence_count": len(доказательства), "модели": c.СТАТИСТИКА_МОДЕЛЕЙ}
    c.писать_json(a.out, итог)
    c.log("%s: вердикт %s, подтверждений %d (отброшено без дословной цитаты %d), решений %d, новых запросов %d" % (
        a.id, итог["verdict"], len(подтверждено), итог["unverified_claims"], len(решения), len(новые)))
    return 0 if д else 2


if __name__ == "__main__":
    sys.exit(main())
