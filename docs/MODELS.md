# Search models / Модели поиска

## Русский

Здесь опубликованы две изменяемые исходные реализации: [ML + SAT](../models/mlsat.py) и [табличный CEM](../models/cem.py). Они генерируют и ранжируют спаривания. **Ни одна модель не доказывает отсутствие кручения.** Доказательные выводы принимает отдельный `k22` verifier.

### 1. ML + SAT: ограничения, признаки, ранжирование

Публичный модуль `models.mlsat` содержит четыре отдельные команды: `generate`, `features`, `train`, `rank`. Для них нужны дополнительные пакеты:

```sh
python -m pip install -e ".[ml]"
python -m models.mlsat train --output runs/mlsat-train
python -m models.mlsat generate --family parallel22 --count 4 --seed 22 --output runs/sat-demo
```

Выполняйте команды из clone репозитория: устанавливаемый пакет содержит код, а публичные данные остаются в папках этого clone.

SAT-генератор вводит булеву переменную для каждого допустимого ребра внутри слоя произведения. Для каждой клетки ровно одно инцидентное ребро должно быть выбрано. Для проверенного ядра `C` добавляется запрет `OR(not edge for edge in C)`. Найденное полное спаривание блокируется, чтобы следующий ответ был другим. Случайные начальные предположения добавляют разнообразие, но это **не равномерное** распределение по решениям. Тайм-аут SAT даёт `unknown`, а не доказательство несовместности. `unsat` после снятия случайных предположений относится только к фиксированным ограничениям данного семейства и текущим блокировкам.

Ранжирующая модель — `ExtraTreesClassifier`:

| Параметр | Значение |
|---|---:|
| `n_estimators` | 400 |
| `min_samples_leaf` | 4 |
| `max_features` | 0.7 |
| `class_weight` | `balanced` |
| `random_state` | 2266 |
| `n_jobs` | 1 |

Она обучается на 681 исторической записи с 155 числовыми признаками. Данные опубликованы в `models/training_records.json`, происхождение и список признаков — в `models/training_manifest.json`. Метка `old_bounded_unknown = 1` означает, что **старый ограниченный поиск не нашёл доказательство**; `0` означает отсутствие этого статуса в прежнем журнале. Всего 170 единиц и 511 нулей. Более позднее доказательство не переписывает историческую метку. Имена исторических кампаний в таблице не являются ID публичных семейств; в частности, `kaggle22_cross_output` нельзя отождествлять с `trinomial22`.

Признаки используют спаривание и предоставленное сокращённое представление: кратности связей между строками/столбцами, число соседей и треугольников, спектры матриц, расстояния индексов; число активных генераторов, длины и число реляторов, частоты букв, размерности абелианизации по модулям 2 и 3, собственные степени и циклические 2-/3-граммы. В признаках нет результата проверки, времени поиска или размера итогового доказательства. При этом признаки сокращённого представления зависят от выбранного алгоритма сокращения.

Для нового кандидата нужен явный `trace.json` с `active_generators` и `relators`:

```sh
python -m models.mlsat features --candidate runs/sat-demo/candidate_0000.json --trace trace.json --output runs/features.json
python -m models.mlsat rank --candidates runs/features.json --output runs/ranking.json
```

Команда `features` **не создаёт и не удостоверяет** преобразование исходного представления в этот trace. Исторический упрощатель и поиск доказательств не включены в данный модуль. Их можно подключить отдельным проверяемым адаптером. Если использовать другой упрощатель, изменится распределение признаков и потребуется заново оценить качество модели.

Публичная команда `train` делает grouped holdout 75/25 по отпечатку спаривания, затем обучает модель на всей таблице. Это отдельная диагностика: исторический первый эксперимент использовал хронологическое разделение 70/30 внутри кампаний. Не смешивайте эти оценки. `rank` заново обучает модель по опубликованному рецепту; исполняемые pickle-файлы не нужны. Оценка `score_old_bounded_unknown` — вероятность прежней метки по модели, **не вероятность отсутствия кручения**. Перенос на новое семейство требует отдельного prospective-теста.

Архитектура полного цикла: `SAT -> признаки -> ML-ranking -> ограниченный поиск доказательства -> точный replay -> новые ядра`. Генерация SAT и ML-ranking здесь отдельные этапы. Эта реализация не вмешивается в внутреннее ветвление SAT и не является NeuroCore. Обучаемое ветвление — возможное дальнейшее улучшение, которое нужно сравнивать с контролем.

### 2. CEM: политика локальных выборов

`models.cem` работает на стандартной библиотеке. Это **табличный cross-entropy method**, а не deep RL и не нейронная сеть. Он реализует элитное обновление распределения пошаговых спариваний.

```sh
python -m models.cem --family trinomial22 --output runs/cem-demo --seed 22
python -m unittest models.test_cem -v
```

Каждый слой произведения имеет фиксированную сортировку клеток. Состояние политики — `(номер слоя, битовая маска оставшихся клеток)`. Берётся первая оставшаяся клетка, действие выбирает её партнёра. Обе клетки удаляются, процесс повторяется. В слоях размера 2 выбор принудительный. При равномерном выборе партнёра этот алгоритм даёт равномерное распределение по всем полным спариваниям каждого слоя: у каждого возможного первого партнёра одинаковое число продолжений.

Для выбранных необязательных рёбер `M` и каждого проверенного ядра `C` положим `d_C = |C \ M|`. Точная используемая награда:

```text
violations = number of C with d_C == 0
pressure = sum(2 ** (-min(d_C, 16)) for C in known_cores)
novelty = 1 - max(|M intersect R| for R in reference_matchings) / |M|
reward = -1000 * violations - pressure + 0.05 * novelty
```

`R` — необязательные рёбра полных спариваний из проверенных заявок. При отсутствии эталонов максимум считается нулём; нулевой знаменатель заменяется единицей. Ограничение `min(d_C,16)` сохранено из исторического CEM-кода. Награда поощряет обход известных ядер и отличие от прежних спариваний; она не содержит метки `UNKNOWN` и не оценивает истинную группу как «без кручения».

Defaults: 10 эпох по 128 кандидатов на каждый метод; 25 лучших CEM-кандидатов образуют элиту (`floor(0.2*128)`). Для посещённого состояния эмпирические частоты элиты смешиваются со старой политикой:

```text
p_new = (1 - 0.65) * p_old + 0.65 * elite_frequencies
p_sample = (1 - 0.15) * p_new + 0.15 * uniform
```

Непосещённые состояния остаются прежними, неизвестные состояния используют равномерный выбор. Нельзя считать состояния независимыми в математической задаче: это ограничение модели, пригодное для улучшения.

Одновременно генерируется равномерный контроль с тем же количеством кандидатов и тем же набором ядер. После обучения оба метода получают ещё по 128 отдельных holdout-кандидатов. Потоки RNG разделены по seed, методу и фазе; seed не увеличивается на один для каждого holdout-элемента. Число сгенерированных кандидатов равно, время работы методов не обязано быть одинаковым. Совпавшие спаривания учитываются как повторы, а число уникальных выводится отдельно.

Результаты:

| Файл | Содержимое |
|---|---|
| `metrics.json` | Отпечатки входов, seeds, параметры, эпохи, обучение/holdout, уникальность, хеши holdout-кандидатов, время. |
| `policy.json` | Таблица вероятностей с порядком слоёв и отпечатком семейства. |
| `input_verification.json` | Replay публичного набора доказательств перед запуском. |
| `selected/{cem,uniform}/caseNNN/candidate.json` | Лучшие различные спаривания, статус `UNPROVED_CANDIDATE`. |
| `selected/{cem,uniform}/caseNNN/ranking.json` | Компоненты эвристической оценки. |

Команда не перезаписывает непустую папку результатов. Общий модуль `models.common` загружает публичные семейства/сертификаты и проверяет их через `k22`. Никакие приватные helpers, ключи или исторические абсолютные пути не используются. Избежание всех известных ядер не гарантировано CEM и не равно доказательству отсутствия кручения.

### Адаптер точной проверки и улучшения

Обе модели сохраняют `k22-candidate-v1`: `family_id`, `family_sha256`, `image_index_sha256`, `matching`, `candidate_sha256`, `status`. Это рабочий формат генератора, **не** заявка в `data/submissions/`.

Внешний proof oracle должен принять точный кандидат, неизменённое семейство и явный бюджет; вернуть либо сертификат `k22-normal-closure-dag-v1`, либо ограниченный `UNKNOWN` с использованным бюджетом, либо ошибку. Возвращённое доказательство остаётся неподтверждённым до `prepare_submission(family, matching, certificate)` из `k22.verifier` или CLI `k22 prepare`. Успешная проверка даёт публичную заявку; только её ядро можно включить в следующий цикл. Текущие генераторы такой oracle автоматически не запускают.

Набор из 532 опубликованных ядер — итоговый стартовый atlas этого репозитория. В прежних экспериментах использовались более ранние checkpoints. Новый запуск на нынешнем atlas не воспроизводит численные показатели старого эксперимента с другим набором ядер.

Для честного сравнения зафиксируйте исходный atlas и одинаковые бюджеты обеих ветвей; новые проверенные ядра передавайте обеим. Сохраняйте все статусы и повторы, отдельно учитывайте генерацию/обучение/проверку. Для улучшения архитектуры сравните общий budget с uniform/SAT-контролем, несколько независимых seeds и новые семейства. Полезные направления: признаки со строгим происхождением, менее зависимая от индексации политика, проверяемые симметрии, адаптивное добавление коротких ядер. Новый высокий score сам по себе не входит в доказательный датасет.

## English

The repository publishes two editable source models: [ML + SAT](../models/mlsat.py) and [tabular CEM](../models/cem.py). They generate and rank matchings. **Neither certifies torsion-freeness.** The separate `k22` verifier is the trust boundary.

### ML + SAT

Run the installation and `train`, `generate`, `features`, and `rank` commands above from a repository clone. The installed package contains code; the public data remain in the clone. SAT has one variable per compatible fiber edge, exactly-one incident-edge constraints per cell, and one blocking clause per verified core. It blocks previously returned complete matchings. Random assumptions diversify proposals but do not produce uniform samples. Solver `unknown` is not unsatisfiability; final `unsat` concerns only the current fixed-family constraints and blocking clauses.

The ranker is `ExtraTreesClassifier` with 400 trees, minimum leaf size 4, `max_features=.7`, balanced class weights, seed 2266, and one worker. The published historical table has 681 rows, 155 features, 170 old bounded-UNKNOWN labels and 511 other outcomes. These labels record the old search, never torsion-freeness, and later proofs do not rewrite that historical observation. Historical campaign names are not public family IDs; the old cross campaign is not the trinomial family.

Features describe row/column multiplicities, neighbors, triangles, spectra and index distances, plus a supplied reduced presentation's generators, relator lengths, letter counts, abelianization dimensions modulo 2 and 3, proper powers and cyclic n-grams. They exclude proof outcomes, timings and final proof sizes. Presentation features depend on the simplifier. `features` accepts a candidate and a trace with `active_generators` and `relators`; it neither constructs nor certifies that reduction. The historical simplifier/proof finder is not bundled into this model.

Public `train` reports a grouped 75/25 holdout by matching hash, then fits all records. This differs from the historical chronological 70/30 split and must not be reported as the same evaluation. `rank` retrains from the published recipe, requiring no executable pickle. Its score predicts an old bounded-search label, not the probability of being torsion-free. New-family transfer requires a prospective evaluation.

The full architecture is `SAT -> features -> ML ranking -> bounded proof search -> exact replay -> new cores`. Public SAT generation and ranking are separate stages. This code does not modify SAT branching and is not a NeuroCore implementation. Learned branching remains a proposed extension requiring a controlled comparison.

### Tabular CEM

Run `python -m models.cem --family trinomial22 --output runs/cem-demo --seed 22`. It needs only the standard library. The policy stores partner probabilities indexed by `(product fiber, remaining-cell mask)`: pair the first remaining cell, remove the pair, and repeat. Uniform partner choices give a uniform perfect matching within each fiber because every first partner has the same number of completions. This is tabular cross-entropy optimization, **not a neural network or deep RL**.

The exact reward is `-1000*violations - pressure + .05*novelty`, with `pressure = sum(2**(-min(missing_core_edges,16)))`. Novelty is one minus the largest optional-edge overlap with a certified reference matching, divided by the number of optional chosen edges. The cap at 16 is inherited from the historical implementation. No bounded-UNKNOWN labels enter CEM rewards.

Defaults are 10 epochs, 128 candidates per arm per epoch, 25 elites, update weight .65 and uniform exploration .15. Unseen states are uniform. A uniform control receives the same sample budget and atlas. Each arm then receives 128 separate holdout draws. Continuous RNG streams are isolated by seed, arm and phase. Equal sample budgets do not imply equal wall time. Metrics report duplicates, unique matchings, holdout hashes, input fingerprints and timing.

Outputs are `metrics.json`, `policy.json`, `input_verification.json`, and ranked candidate/ranking files under `selected/{cem,uniform}/caseNNN/`. An existing nonempty output directory is rejected. Public families and proofs are loaded and verified through `models.common`; no private helpers or credentials are required. CEM may still hit known cores, and avoiding all known cores is not torsion-freeness.

### Proof-oracle boundary and fair improvements

Generated `k22-candidate-v1` files contain family/product fingerprints, the matching, candidate hash and `UNPROVED_CANDIDATE` status. They are not proof submissions. An external oracle should take this exact candidate, unchanged family and explicit budget; return a public-format proof, bounded `UNKNOWN` with consumed budget, or an error. A returned proof must pass `prepare_submission` from `k22.verifier` or the `k22 prepare` CLI before its core enters the trusted dataset. Current generators do not run an external oracle automatically.

For comparisons, freeze the initial atlas, use equal constraints and budgets, share newly verified feedback with both arms, retain repeats and all statuses, and report generation/training/proof-check overhead. Evaluate several independent seeds and new families. Improvements may target trace provenance, policies less sensitive to indexing, checked symmetry transport, or adaptive small-core feedback. A high model score alone never belongs in the proof dataset.

The 532 published cores form this repository's starting atlas. Earlier experiments used earlier checkpoints. Running a model against today's atlas is not a numerical reproduction of a historical experiment with a different core set.
