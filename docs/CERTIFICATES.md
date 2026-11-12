# Certificates and cores / Сертификаты и ядра

## Русский

Проверяющий код использует только Python 3.11+ и стандартную библиотеку:

```sh
python -m k22 verify --data data --report verification-report.json
```

Файл отчёта — удобный результат запуска; источником математического утверждения остаются исходные данные и повторяемое доказательство. Текущий формат подтверждает только кручение исходной группы. Он не принимает сертификаты отсутствия кручения или утверждения обо всех факторах без кручения.

### 1. Семейство

`data/families/<family_id>.json` содержит ровно поля:

| Поле | Значение |
|---|---|
| `format` | `k22-family-v1` |
| `family_id` | Имя вида `parallel22` или `trinomial22`. |
| `n`, `m` | Оба равны 22. |
| `left`, `right` | Два **упорядоченных** списка 22 аффинных образов `[translation, signs]`. |
| `image_index_sha256` | Отпечаток таблицы произведений. |

Каноническая сериализация для всех отпечатков:

```python
json.dumps(obj, sort_keys=True, separators=(',', ':'),
           ensure_ascii=True, allow_nan=False).encode('utf-8')
```

К хешируемым байтам не добавляется перевод строки. `family_sha256` — SHA-256 всего объекта семейства. `image_index_sha256` — SHA-256 списка 484 строк `[i,j,translation,signs]`, где образ равен `left[i-1]*right[j-1]`, сначала меняется `j`, затем `i`. Индексы клеток начинаются с **1**. Перестановка носителя создаёт другие данные; прежний сертификат автоматически не переносится.

### 2. Заявка

`data/submissions/<submission_id>.json` содержит ровно:

```text
format = "k22-submission-v1"
submission_id, family_id, family_sha256, image_index_sha256
matching, optional_core, certificate
```

`matching` — список 242 пар клеток, покрывающий каждую клетку ровно один раз. Образы произведений в каждой паре должны совпадать. **Порядок пар и ориентация каждой пары сохраняются:** на них ссылаются листья доказательства.

Для `optional_core` каждое ребро превращается в лексикографически отсортированную пару клеток; затем удаляются повторы и сортируется весь список. Ядро должно точно совпадать с рёбрами, указанными в листьях `match` сертификата, за вычетом обязательных рёбер из слоёв размера 2. Оно может быть пустым, если сертификат использует только обязательные рёбра. Формат не обещает минимальность ядра.

```python
submission_id = sha256(canonical_bytes({
    "family_sha256": family_sha256,
    "optional_core": optional_core,
})).hexdigest()
```

Одинаковый ID означает одно и то же ядро в одном и том же семействе. Другое доказательство того же ядра — улучшение существующей заявки, а не новое ядро. Сравните также включение множеств: уже известное меньшее ядро может делать новое избыточным.

### 3. Доказательство

`certificate` имеет поля:

```text
format = "k22-normal-closure-dag-v1"
target_word, power, nodes, root
used_original_matches_one_based
expanded_original_relator_factor_count
```

Слово — список ненулевых целых чисел: `1..22` обозначают `X_1..X_22`, `23..44` — `Y_1..Y_22`, отрицательные числа — обратные элементы. Для ориентированной пары `((i,j),(k,l))` исходный релятор имеет вид `[i,22+j,-(22+l),-k]`.

Доказательство — ациклический список узлов. Каждый ребёнок уже должен существовать; индексы узлов начинаются с **0**. Допустимы только операции:

```json
{"op":"match","match":1}
{"op":"inverse","child":0}
{"op":"product","children":[0,1]}
{"op":"conjugate","child":0,"conjugator":[1,-23]}
```

Это примеры формата узлов, а не готовый сертификат. `match` ссылается на **1-based** номер исходной пары. `inverse` обращает слово, `product` перемножает слова, `conjugate` означает `u * child * u^-1`. Проверяющий код свободно сокращает слова и требует, чтобы `root` совпал со свободным сокращением `target_word ** power`.

`used_original_matches_one_based` — отсортированный список всех номеров `match`, присутствующих в списке узлов. `expanded_original_relator_factor_count` — число исходных реляторов после развёртывания корневого DAG с повторениями. Метаданные пересчитываются, а не принимаются на доверие. Чтобы не раздувать ядро, не добавляйте неиспользуемые ветви доказательства.

Затем проверяется нетривиальность аффинного образа `target_word`. Совместно с доказанным равенством это даёт ненулевой элемент конечного порядка в исходной группе. При `power > 2` заявляйте только, что порядок делит `power`, если точный порядок не доказан отдельно.

### 4. Подготовка PR

Если у вас уже есть полный список спариваний и сертификат публичного формата:

```sh
python -m k22 prepare --family data/families/trinomial22.json --matching matching.json --certificate certificate.json --output data/submissions
python -m k22 verify --data data
```

`matching.json` должен быть голым JSON-списком пар. `prepare` вычисляет ядро и ID, проверяет доказательство и только после успеха создаёт файл; существующий файл не перезаписывается. Команда не ищет доказательство за вас и не преобразует автоматически произвольные старые форматы.

Перед PR проверьте совпадение семейства/индексов, отсутствие дубликата, точную формулировку вывода и полный replay. Не удаляйте рёбра из ядра вручную без нового доказательства. Новые правила доказательства, больший размер таблицы, иной тип аффинного образа и перенос по симметрии требуют отдельного обсуждения и изменения проверяющего кода с тестами. Действуют ограничения ресурсов в `k22/verifier.py`; превышение лимита не опровергает математику, но такой файл не принят текущей проверкой.

## English

Run `python -m k22 verify --data data --report verification-report.json` with Python 3.11+. The verifier uses only the standard library. A receipt is a run result; the data and replayable proof remain the evidence. The current format establishes **source torsion only**, not torsion-freeness or exclusion of every torsion-free quotient.

Families use the exact fields in section 1. Supports are ordered. Hashes use the canonical JSON bytes shown above, with no trailing newline. `family_sha256` hashes the whole family object; `image_index_sha256` hashes the row-major list of 484 `[i,j,translation,signs]` product rows. Cell indices are one-based. Reindexing is not an automatic certificate transport.

Submissions use the exact fields in section 2. `matching` is an ordered list of 242 oriented cell pairs covering the table exactly once, with equal product images in each pair. Preserve both order and orientation because proof leaves refer to these relators. `optional_core` is a sorted, duplicate-free list of canonically oriented edges: precisely all listed proof-leaf edges minus the forced two-cell-fiber edges. It need not be minimal and can be empty. The submission ID is the SHA-256 of the object containing `family_sha256` and `optional_core`. The same core in the same family has the same ID, irrespective of its proof.

Certificates use the fields in section 3. Signed letters `1..22` encode the `X` generators, `23..44` the `Y` generators. A matched pair gives the relator `[i,22+j,-(22+l),-k]`. DAG children and the root are zero-based, refer only to earlier nodes, and support only `match`, `inverse`, `product`, and `conjugate`; the node examples above specify their exact fields. A `match` reference is one-based. Conjugation is `u * child * u^-1`.

The root must freely reduce to the declared power of the target word. The verifier recomputes the used-match manifest and expanded relator count, and checks that the target's affine image is nonidentity. Thus the target is nonidentity in the source while its declared power is trivial. A power greater than two is an order bound, not automatically the exact order. Unused DAG branches unnecessarily enlarge the core and should be removed by the proof exporter.

Use the `k22 prepare` command in section 4 to create a submission from a bare matching list and a certificate already in the public format. It derives the core and ID, replays the proof, and writes only on success, without overwriting an existing file. It does not discover a proof or automatically convert legacy formats. Then verify the entire dataset and open a focused PR. Check for duplicate or subsumed cores. New proof rules, dimensions, image types, and symmetry transports need a separate verifier proposal with tests. Resource limits are explicit in `k22/verifier.py`; exceeding them means the present checker did not accept the file, not that the mathematical claim is false.
