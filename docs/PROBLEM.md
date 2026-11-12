# Problem and scope / Постановка и границы

## Русский

Ищем явную группу без кручения `G` и ненулевые элементы `alpha, beta` групповой алгебры `F_2[G]`, для которых `alpha * beta = 0`. Основное рабочее пространство — пары носителей размера 22. Текущая коллекция содержит проверенные **препятствия** для конкретных спариваний, а не найденный контрпример.

Для диаграммы `D` спариваем все 484 клетки `(i,j)` таблицы 22×22 в 242 пары. Паре `((i,j),(k,l))` соответствует соотношение

```text
X_i Y_j = X_k Y_l.
G_D = <X_1,...,X_22,Y_1,...,Y_22 | все соотношения спаривания>.
alpha = X_1 + ... + X_22,   beta = Y_1 + ... + Y_22.
```

В `F_2[G_D]` произведение равно нулю попарным сокращением. Чтобы это стало нужным контрпримером, необходимо доказать, что **вся группа `G_D` не имеет кручения** и оба множителя ненулевые. В публичных семействах различные аффинные образы элементов каждого носителя гарантируют ненулевые множители в исходной группе.

Файл семейства задаёт упорядоченные аффинные образы `left` и `right`. Образ записывается как `[translation, signs]`, где обе тройки целочисленные, а знаки равны ±1. Умножение: `(v,s)(w,t) = (v+s*w,s*t)` покоординатно. Клетки с одинаковым образом произведения образуют *слой произведения* (product fiber). Допустимые здесь спаривания соединяют клетки внутри одного слоя. Слой из двух клеток даёт обязательное ребро; в больших слоях есть выбор.

**Ядро запрета (core)** — набор необязательных рёбер, который вместе с обязательными рёбрами семейства поддерживает проверенное доказательство кручения. Доказательство устанавливает `w^q = 1`, а общий для семейства аффинный образ устанавливает `w != 1`. Поэтому любое допустимое полное спаривание, содержащее ядро, тоже имеет кручение в исходной группе. Ядро не обязано быть минимальным. При этом добавление произвольных соотношений вне данного семейства может убить `w`: перенос запрета требует сохранения нетривиального образа.

| Результат | Что он означает |
|---|---|
| `UNPROVED_CANDIDATE` | Допустимое спаривание, ещё без нужного группового доказательства. |
| `UNKNOWN` при лимите | Данный алгоритм не разрешил вопрос за данный бюджет. |
| Сертификат кручения | Исходная группа этого спаривания не является группой без кручения. |
| Обход всех известных ядер | Только отсутствие перечисленных препятствий. |
| Теорема обо всех факторах без кручения | Более сильный отдельный результат; сертификаты текущего публичного формата этого не утверждают. |

Бесконечный порядок некоторых «элементарных» отношений также не доказывает отсутствие кручения всей группы. Конечный порядок образа не доказывает конечный порядок прообраза. Эти различия обязательны при описании экспериментов и обучении моделей.

Стартовая коллекция содержит 235 ядер `parallel22` и 297 ядер `trinomial22`. Это 532 различных ядра, а не обязательно 532 различных спаривания. Результат покрытия относится только к явно указанному фиксированному семейству и мере/подсчёту спариваний; его нельзя переносить на все таблицы 22×22 или на задачу в целом.

## English

We seek an explicit torsion-free group `G` with nonzero `alpha, beta` in `F_2[G]` satisfying `alpha * beta = 0`. The main working space uses two supports of size 22. The current collection consists of checked **obstructions**, not a counterexample.

A diagram pairs the 484 cells of a 22×22 table into 242 pairs. The pair `((i,j),(k,l))` imposes `X_i Y_j = X_k Y_l` in the universal source group `G_D`. Consequently `(sum X_i)(sum Y_j)=0` over `F_2`. A counterexample additionally requires the **entire source group** to be torsion-free and both factors to be nonzero. Distinct affine images within each public support certify nonzero factors in the source group.

A family fixes ordered affine images, encoded as `[translation, signs]`, with multiplication `(v,s)(w,t)=(v+s*w,s*t)` coordinatewise. A *product fiber* consists of cells with the same product image. Compatible matchings pair cells within each fiber. A two-cell fiber forces its single edge.

A **forbidden core** is a set of optional edges supporting a checked torsion proof together with the family's forced edges. The proof gives `w^q=1`, and the common affine representation gives `w!=1`. Every compatible completion containing this core therefore has source torsion. Cores need not be minimal. Arbitrary additional relations outside the fixed family may kill the witness; transferring a core must preserve its nonidentity certificate.

Keep the outcomes distinct: an unproved candidate is only a matching; bounded `UNKNOWN` is only a search outcome; a source-torsion certificate rejects that source; avoiding known cores only avoids the listed obstructions. A theorem excluding every torsion-free quotient is a stronger, separate statement, unsupported by the current public certificate format. Infinite order of selected elementary quotients does not prove that the entire group is torsion-free, and a finite-order image does not prove finite order in the source.

The seed collection contains 235 `parallel22` cores and 297 `trinomial22` cores: 532 distinct cores, not necessarily 532 distinct matchings. Coverage claims apply only to the specified fixed family and counting measure, never automatically to all 22×22 diagrams or to the full conjecture.
