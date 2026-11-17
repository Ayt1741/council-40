#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""СОВЕТ-40: общий код агентов (10 руководителей + 30 исполнителей). Только стандартная библиотека.

Правила (из протокола заказчика и законов):
  • искать НАСТОЯЩИМ поиском (Tavily / Jina / Firecrawl — сервисы для ИИ-агентов — и открытые API GitHub, arXiv, Hacker News,
    OpenAlex); парсеры выдачи Bing/DuckDuckGo и подмена браузерного UA НЕ используются; честный User-Agent;
  • цитата в отчёте — только ДОСЛОВНЫЙ фрагмент найденного текста (проверяется кодом: фрагмент обязан входить в текст источника);
  • ссылку и название выдумывать нельзя: берутся только из ответа поиска;
  • каждый вызов записывается в «квитанции» (инструмент, статус, число результатов, секунды).
"""
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "KuhnyaCouncil/1.0 (+https://github.com/Ayt1741/Horizon; research agent of the repo owner)"
T0 = time.time()


def log(*a):
    print("[%6.1fс]" % (time.time() - T0), *a, flush=True)


def http(метод, url, тело=None, заголовки=None, таймаут=45):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(заголовки or {})
    данные = None
    if тело is not None:
        данные = json.dumps(тело).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=данные, headers=h, method=метод)
    try:
        with urllib.request.urlopen(req, timeout=таймаут) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)
    except Exception as e:  # сеть, таймаут
        return 0, repr(e), {}


# ------------------------------------------------------------------ модели
def провайдеры():
    п = []
    if os.environ.get("GROQ_API_KEY", "").strip():
        п.append({"имя": "groq", "url": "https://api.groq.com/openai/v1/chat/completions", "ключ": os.environ["GROQ_API_KEY"].strip(),
                  "модели": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]})
    if os.environ.get("MISTRAL_API_KEY", "").strip():
        п.append({"имя": "mistral", "url": "https://api.mistral.ai/v1/chat/completions", "ключ": os.environ["MISTRAL_API_KEY"].strip(),
                  "модели": ["mistral-large-latest", "mistral-small-latest"]})
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        п.append({"имя": "openrouter", "url": "https://openrouter.ai/api/v1/chat/completions", "ключ": os.environ["OPENROUTER_API_KEY"].strip(),
                  "модели": ["openai/gpt-oss-120b:free", "meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen3-235b-a22b:free"]})
    # последний запас без ключа: анонимный бесплатный Pollinations (1 ответ в 45 с на IP; у каждой задачи Actions свой IP)
    п.append({"имя": "pollinations", "url": "https://text.pollinations.ai/openai", "ключ": "", "модели": ["openai"]})
    return п


СТАТИСТИКА_МОДЕЛЕЙ = {"вызовов": 0, "ошибок": 0, "по_провайдерам": {}}
# порядок предпочтения: сильные модели первыми; лимиты у каждой модели свои (Groq: 8000 токенов/мин на модель), поэтому при 429 сразу берём следующую
ПОРЯДОК = [("groq", "openai/gpt-oss-120b"), ("mistral", "mistral-large-latest"), ("openrouter", "openai/gpt-oss-120b:free"), ("groq", "qwen/qwen3.8-27b"),
           ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"), ("mistral", "mistral-small-latest"), ("groq", "openai/gpt-oss-20b"),
           ("openrouter", "qwen/qwen3-235b-a22b:free"), ("pollinations", "openai")]
СИЛЬНЫЕ = set(ПОРЯДОК[:5]) | {("pollinations", "openai")}
МЁРТВЫЕ = set()          # (провайдер, модель) или (провайдер, "*"): ключ отвергнут / модели нет — больше не пробуем в этом процессе


def варианты():
    по_имени = {п["имя"]: п for п in провайдеры()}
    return [(по_имени[имя], м) for имя, м in ПОРЯДОК if имя in по_имени]


def модель(система, пользователь, макс=2000, темп=0.3, смещение=0, попыток=4, сильные=False):
    """Один вызов модели. Идёт по вариантам (провайдер, модель) в порядке предпочтения; при 429/5xx сразу пробует следующий,
    после полного круга ждёт (retry-after) и повторяет. Возвращает текст или None."""
    вар = [x for x in варианты() if (x[0]["имя"], "*") not in МЁРТВЫЕ and (x[0]["имя"], x[1]) not in МЁРТВЫЕ]
    if сильные:                      # для разбора и голосования — только сильные модели: слабая при 429 отвечает одной строкой
        вар = [x for x in вар if (x[0]["имя"], x[1]) in СИЛЬНЫЕ]
    if not вар:
        log("НЕТ ключей ни одного подходящего провайдера моделей")
        return None
    оценка = (len(система) + len(пользователь)) / 2.3 + макс      # токены: кириллица ≈ 2,3 знака на токен
    if оценка > 7600:                                              # заведомо отклоняемое по лимиту 8000 токенов — режем данные
        пользователь = пользователь[: max(500, len(пользователь) - int((оценка - 7400) * 2.3))] + "\n[…часть данных опущена из-за лимита размера]"
    последняя = ""
    for цикл in range(попыток):
        макс_ожидание = 0.0
        начало = (смещение if цикл > 0 else 0) % len(вар)          # первый круг — от самой сильной; дальше расходимся по агентам
        for k in range(len(вар)):
            п, м = вар[(начало + k) % len(вар)]
            тело = {"model": м, "messages": [{"role": "system", "content": система}, {"role": "user", "content": пользователь}],
                    "max_tokens": макс, "temperature": темп}
            СТАТИСТИКА_МОДЕЛЕЙ["вызовов"] += 1
            if (п["имя"], "*") in МЁРТВЫЕ or (п["имя"], м) in МЁРТВЫЕ:
                continue
            с, б, заг = http("POST", п["url"], тело, {"Authorization": "Bearer " + п["ключ"]} if п["ключ"] else {}, таймаут=120)
            if с == 200:
                try:
                    текст = json.loads(б)["choices"][0]["message"].get("content") or ""
                except Exception:
                    текст = ""
                текст = re.sub(r"<think>.*?</think>", "", текст, flags=re.S).strip()
                if текст:
                    ключ_ст = п["имя"] + ":" + м
                    СТАТИСТИКА_МОДЕЛЕЙ["по_провайдерам"][ключ_ст] = СТАТИСТИКА_МОДЕЛЕЙ["по_провайдерам"].get(ключ_ст, 0) + 1
                    return текст
            СТАТИСТИКА_МОДЕЛЕЙ["ошибок"] += 1
            последняя = "%s/%s HTTP %s" % (п["имя"], м, с)
            if с in (401, 403) and п["имя"] != "pollinations":
                МЁРТВЫЕ.add((п["имя"], "*")); log("провайдер %s отвергнут (HTTP %s) — больше не используется" % (п["имя"], с))
            elif с == 404:
                МЁРТВЫЕ.add((п["имя"], м)); log("модель %s/%s не найдена — исключена" % (п["имя"], м))
            if с in (429, 402):
                try:
                    макс_ожидание = max(макс_ожидание, min(45.0, float(заг.get("retry-after") or заг.get("Retry-After") or 0)))
                except ValueError:
                    pass
            time.sleep(0.3)
        ждать = max(макс_ожидание, 6.0 * (цикл + 1)) + random.random() * 3
        log("модель: круг %d не удался (последняя: %s) — пауза %.0f с" % (цикл + 1, последняя, ждать))
        time.sleep(ждать)
    log("модель: сдаюсь после %d кругов (%s)" % (попыток, последняя))
    return None


def разобрать_json(текст):
    """Достаёт первый JSON-объект/массив из ответа модели; None, если не вышло."""
    if not текст:
        return None
    текст = re.sub(r"^```(?:json)?\s*|\s*```$", "", текст.strip(), flags=re.M)
    дек = json.JSONDecoder()
    for i, ch in enumerate(текст):
        if ch in "{[":
            try:
                return дек.raw_decode(текст[i:])[0]
            except ValueError:
                continue
    return None


def нормализовать(т):
    return re.sub(r"\s+", " ", (т or "")).strip().lower()


def цитата_дословна(цитата, источник_текст):
    """Цитата допустима, только если после нормализации пробелов входит в текст источника."""
    ц = нормализовать(цитата).strip(" .…\"'«»")
    return len(ц) >= 12 and ц in нормализовать(источник_текст)


# ------------------------------------------------------------------ поиск
def _res(заголовок, url, текст, источник):
    return {"title": (заголовок or "").strip()[:200], "url": (url or "").strip(), "text": re.sub(r"\s+", " ", текст or "").strip()[:900], "src": источник}


def tavily(q, n=5):
    к = os.environ.get("TAVILY_API_KEY", "").strip()
    if not к:
        return 0, []
    с, б, _ = http("POST", "https://api.tavily.com/search", {"api_key": к, "query": q, "max_results": n, "search_depth": "basic"})
    if с != 200:
        return с, []
    try:
        return с, [_res(r.get("title"), r.get("url"), r.get("content"), "tavily") for r in json.loads(б).get("results", [])]
    except Exception:
        return с, []


def jina(q, n=5):
    к = os.environ.get("JINA_API_KEY", "").strip()
    if not к:
        return 0, []
    с, б, _ = http("GET", "https://s.jina.ai/?q=" + urllib.parse.quote(q), None, {"Authorization": "Bearer " + к, "Accept": "application/json"})
    if с != 200:
        return с, []
    try:
        return с, [_res(r.get("title"), r.get("url"), r.get("description") or r.get("content"), "jina") for r in json.loads(б).get("data", [])[:n]]
    except Exception:
        return с, []


def firecrawl(q, n=5):
    к = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not к:
        return 0, []
    с, б, _ = http("POST", "https://api.firecrawl.dev/v1/search", {"query": q, "limit": n}, {"Authorization": "Bearer " + к})
    if с != 200:
        return с, []
    try:
        return с, [_res(r.get("title"), r.get("url"), r.get("description") or r.get("markdown"), "firecrawl") for r in json.loads(б).get("data", [])[:n]]
    except Exception:
        return с, []


def _github(url):
    h = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    for попытка in range(3):
        с, б, _ = http("GET", url, None, h)
        if с not in (403, 429):
            return с, б
        time.sleep(7 + попытка * 6 + random.random() * 4)
    return с, б


def github_репо(q, n=4):
    с, б = _github("https://api.github.com/search/repositories?per_page=%d&sort=stars&q=%s" % (n, urllib.parse.quote(q)))
    if с != 200:
        return с, []
    try:
        return с, [_res(r["full_name"] + " (★%s)" % r.get("stargazers_count"), r["html_url"], r.get("description"), "github") for r in json.loads(б).get("items", [])]
    except Exception:
        return с, []


def github_issues(q, n=4):
    с, б = _github("https://api.github.com/search/issues?per_page=%d&q=%s" % (n, urllib.parse.quote(q)))
    if с != 200:
        return с, []
    try:
        return с, [_res(r["title"], r["html_url"], (r.get("body") or "")[:900], "github-issue") for r in json.loads(б).get("items", [])]
    except Exception:
        return с, []


def arxiv(q, n=4):
    с, б, _ = http("GET", "http://export.arxiv.org/api/query?max_results=%d&search_query=all:%s" % (n, urllib.parse.quote(q)), None, {"Accept": "application/atom+xml"})
    if с != 200:
        return с, []
    рез = []
    try:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for e in ET.fromstring(б).findall("a:entry", ns):
            рез.append(_res(e.findtext("a:title", "", ns), e.findtext("a:id", "", ns), e.findtext("a:summary", "", ns), "arxiv"))
    except Exception:
        pass
    return с, рез


def hn(q, n=4):
    с, б, _ = http("GET", "https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage=%d&query=%s" % (n, urllib.parse.quote(q)))
    if с != 200:
        return с, []
    try:
        return с, [_res(h.get("title"), h.get("url") or "https://news.ycombinator.com/item?id=%s" % h.get("objectID"), h.get("story_text") or h.get("title"), "hn")
                   for h in json.loads(б).get("hits", [])]
    except Exception:
        return с, []


def openalex(q, n=4):
    с, б, _ = http("GET", "https://api.openalex.org/works?per-page=%d&search=%s" % (n, urllib.parse.quote(q)))
    if с != 200:
        return с, []
    рез = []
    try:
        for w in json.loads(б).get("results", []):
            инв = w.get("abstract_inverted_index") or {}
            слова = sorted(((п, сл) for сл, пп in инв.items() for п in пп))
            рез.append(_res(w.get("title"), w.get("doi") or w.get("id"), " ".join(сл for _, сл in слова)[:900], "openalex"))
    except Exception:
        pass
    return с, рез


def искать(q, n_основной=5):
    """Основной поиск (Tavily → Jina → Firecrawl) + один открытый API по смыслу запроса. Возвращает (результаты, квитанции)."""
    квит, рез = [], []
    for имя, функ in (("tavily", tavily), ("jina", jina), ("firecrawl", firecrawl)):
        t0 = time.time()
        с, r = функ(q, n_основной)
        квит.append({"инструмент": имя, "статус": с, "результатов": len(r), "сек": round(time.time() - t0, 1)})
        if r:
            рез += r
            break
        if с == 0 and имя != "tavily":
            continue
    низ = q.lower()
    допы = []
    if re.search(r"github|issue|repo|open.?source|plugin|library|hook|linter|\bcli\b|gist", низ):
        допы += [("github-issues", github_issues)] if (sum(map(ord, q)) % 2) else [("github-репо", github_репо)]   # один вызов GitHub на запрос
    if re.search(r"arxiv|paper|benchmark|study|survey|empirical|evaluation|dataset", низ):
        допы += [("arxiv", arxiv), ("openalex", openalex)]
    if not допы:
        допы = [("hn", hn)]
    for имя, функ in допы:
        t0 = time.time()
        с, r = функ(q)
        квит.append({"инструмент": имя, "статус": с, "результатов": len(r), "сек": round(time.time() - t0, 1)})
        рез += r
        time.sleep(0.4)
    # дедуп по url
    видели, итог = set(), []
    for r in рез:
        к = r["url"].split("#")[0].rstrip("/")
        if r["url"] and к not in видели:
            видели.add(к)
            итог.append(r)
    return итог[:10], квит


def читать(путь):
    with open(путь, encoding="utf-8") as f:
        return f.read()


def писать_json(путь, объект):
    with open(путь, "w", encoding="utf-8") as f:
        json.dump(объект, f, ensure_ascii=False, indent=1)


def протокол_и_задача(полный=False):
    """По умолчанию — сжатые тексты (лимит Groq 8000 токенов/мин на модель); полные лежат рядом (protocol.md, task.md)."""
    база = os.path.dirname(os.path.abspath(__file__))
    if полный:
        return читать(os.path.join(база, "protocol.md")), читать(os.path.join(база, "task.md"))
    return читать(os.path.join(база, "protocol-short.md")), читать(os.path.join(база, "task-short.md"))


def полосы():
    база = os.path.dirname(os.path.abspath(__file__))
    return {x["id"]: x for x in json.loads(читать(os.path.join(база, "lanes.json")))["lanes"]}
