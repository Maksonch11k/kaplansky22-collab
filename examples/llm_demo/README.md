# Known-core rediscovery demo / Демонстрация повторного вывода известного ядра

## Русский

Эти два JSON-файла — **подготовленный вручную демонстрационный пример**. Для их создания не вызывалась LLM. Они не являются новым математическим результатом и не измеряют способность модели самостоятельно найти свидетельство кручения.

- `candidate.json` содержит полное спаривание из уже опубликованной заявки [`3790f085…`](../../data/submissions/3790f085a9b33d1bc998777a9c18c044b73bc2faafe639bd5a9017a5b60d51db.json). Порядок 242 пар и ориентация каждой пары сохранены точно.
- `proposal.json` предлагает проверить слово `[23,-40]`, то есть `Y_1 Y_18^-1`, в степени 2. Подсказки `preferred_relators: [200,211]` ссылаются на исходные соотношения в `candidate.json`; индексы начинаются с 1. Причина явно помечена как ручной demo fixture.
- В этих файлах **нет сертификата и DAG доказательства**. Поисковый модуль должен сам построить доказательство из исходных соотношений; затем публичный `k22` verifier должен независимо его проверить.

Точные идентификаторы:

```text
family_id: trinomial22
family_sha256:
cc33492bf45db6d33f48d58eaa41f825ee88d7f205566983e0fbfbc02eecd28d
candidate_sha256:
8aa2e8cc2102680d8915816c71caa1f07ea5f5baef413c3c9b8b47a70672a7da
known submission / demo-held-out core:
3790f085a9b33d1bc998777a9c18c044b73bc2faafe639bd5a9017a5b60d51db
```

Ядро состоит из двух необязательных рёбер:

```text
((16,1),  (22,18))   — исходная пара 200
((16,18), (22,1))    — исходная пара 211
```

Запуск из корня clone, без API-ключей и сетевых запросов:

```sh
python -m discovery demo --output runs/llm-demo
```

Demo временно исключает **только это ядро** из своей начальной памяти, чтобы показать цепочку «подсказка → поиск доказательства → проверка → пополнение памяти». Возврат ядра нов только относительно этой искусственно уменьшенной памяти; публичный atlas уже содержит его. Исходные файлы в `data/` не меняются.

Существует дополнительная важная оговорка: то же спаривание содержит другое опубликованное ядро `c8931aa4420f06e0b5e9d4b687c2a0635518757207152e391b2b21f972646b13`. Поэтому даже после исключения первого ядра кандидат остаётся запрещённым известными данными. Demo намеренно повторно исследует его; оно не демонстрирует обнаружение ранее непокрытого спаривания. Повторный обход того же подтверждённого ядра не должен увеличивать память ещё раз.

Успешный исход — проверенный сертификат кручения исходной группы и корректное добавление ядра в локальную память запуска. Неуспех ограниченного поиска остаётся `UNKNOWN`. Ни один исход не является доказательством отсутствия кручения, новым контрпримером или исключением всех факторов без кручения.

## English

These JSON files are a **hand-authored demonstration fixture**, created without an LLM call. They are not a new mathematical discovery or an evaluation of autonomous model discovery.

`candidate.json` preserves every pair and its orientation from the linked published submission. `proposal.json` suggests the target `[23,-40] = Y_1 Y_18^-1`, power 2, and one-based original-relator indices `[200,211]`. The reason explicitly identifies the fixture as hand-authored. Neither file contains a certificate or proof DAG: the search engine must construct a proof from the original relations, and the independent public verifier must replay it.

Run `python -m discovery demo --output runs/llm-demo` from the repository clone. It needs no API credentials or network requests. The demo removes just the specified known core from its initial local memory to illustrate `proposal -> proof search -> verification -> feedback`. Rediscovery is new only relative to that artificial memory, never relative to the public atlas. Repository data remain unchanged, and repeated feedback for the same core must not increase memory again.

The candidate also contains the other known core `c8931aa4420f06e0b5e9d4b687c2a0635518757207152e391b2b21f972646b13`. It is therefore already forbidden even after the first core is held out. This demo intentionally reexamines it and does not claim to uncover a previously uncovered matching.

Success means a replayed source-torsion certificate and a correctly updated local core memory. A bounded search miss remains `UNKNOWN`. Neither outcome establishes torsion-freeness, a counterexample, or exclusion of every torsion-free quotient.
