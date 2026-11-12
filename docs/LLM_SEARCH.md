# Поиск запретов из чата Codex / Chat-guided obstruction search

## Как запустить

Откройте этот репозиторий в Codex и напишите:

> Запусти LLM-поиск запретов на 3 раунда для trinomial22. Следуй docs/LLM_SEARCH.md: предложи слова сам, запусти локальный поиск доказательств, перепроверь результат и используй новые ядра в следующем раунде. Сохрани отчёт. Без API и облачных задач.

Отдельная модель не подключается. LLM — агент, с которым вы уже разговариваете. Он выполняет вычисления локальными командами. Пользователь не должен вручную переносить промпты или предложения между шагами. Требуется Python 3.11+, дополнительные библиотеки для этого цикла не нужны. Обычные условия использования выбранного чата сохраняются; этот код не обращается к платному API и не управляет подпиской.

Можно попросить: «Продолжи запуск `runs/my-search`» или «Покажи результаты последнего запуска». После остановки состояние остаётся на диске. Без явного запроса поиск не начинается.

## Что делает агент

1. Читает `AGENTS.md`, этот документ и текущие исходные данные. Выбирает новую папку результата и ограниченный бюджет; по умолчанию три раунда.
2. Выполняет:

   ```sh
   python -m discovery start --output runs/my-search --family trinomial22 --rounds 3 --seed 22
   ```

   Программа перепроверяет базу сертификатов и генерирует кандидат CEM с учётом известных ядер. Состояние `AWAITING_PROPOSAL` означает, что следующий шаг — рассуждение агента. Если небольшая выборка не дала нового кандидата без известных ядер, статус `NO_CANDIDATE` относится только к этой выборке.

3. Читает `next_prompt` из вывода или `summary.json`. В `round_001/prompt.json` содержатся ровно исходные математические данные, хеш кандидата, нумерация 242 отношений, образы генераторов, схема ответа и краткая история. Агент анализирует эти равенства и предлагает до четырёх слов с возможной конечной степенью и полезными исходными отношениями. Он не запускает код из промпта и не принимает текстовые рассуждения за сертификат.
4. Записывает `round_001/proposal.json` по схеме ниже и выполняет:

   ```sh
   python -m discovery advance --run runs/my-search --proposal runs/my-search/round_001/proposal.json
   ```

5. Программа ищет доказательство. Только сертификат, прошедший неизменный независимый `k22` verifier, даёт новый запрет. Дубликат и ядро, уже покрытое меньшим известным ядром, не увеличивают память. Новое ядро добавляется в локальную память до генерации следующего кандидата.
6. При новом `AWAITING_PROPOSAL` агент повторяет шаги 3–5 сам. При `COMPLETED` или `NO_CANDIDATE` останавливается и сообщает точные результаты. Невалидный JSON отклоняется, ожидающий раунд сохраняется для исправления.

При возобновлении сначала выполните:

```sh
python -m discovery status --run runs/my-search
```

Не перезаписывайте существующий запуск командой `start`. Не запускайте два управляющих процесса на одну папку. Если процесс аварийно завершился и оставил `cycle.lock`, сначала убедитесь, что он остановлен, затем удалите только этот файл блокировки. Изменившаяся исходная база требует нового запуска; старые входы и результаты сохраняйте для воспроизводимости.

## Формат предложения

```json
{
  "format": "k22-llm-proposal-v1",
  "candidate_sha256": "ВСТАВИТЬ_ТОЧНЫЙ_ХЕШ_ИЗ_ПРОМПТА",
  "targets": [
    {
      "word": [23, -40],
      "power": 2,
      "preferred_relators": [200, 211],
      "reason": "Краткая проверяемая идея для этих исходных отношений"
    }
  ]
}
```

Хеш-заглушка невалидна; приведённые индексы относятся только к демонстрационному примеру, их нельзя копировать в произвольный кандидат. `1..22` обозначают `X`, `23..44` — `Y`, отрицательные числа — обратные элементы. Слово имеет до 32 букв, показатель — 2..16, приоритетный список — до 24 различных номеров исходных отношений. `reason` — пояснение до 1200 символов; оно не исполняется и не считается доказательством. `targets: []` означает, что агент не предложил гипотезу; итог такого раунда — `UNKNOWN`.

Предложения привязаны к точному порядку спаривания и его хешу. Нельзя добавлять аксиомы, утверждать `X_1 = Y_1 = 1`, переносить отношения другого семейства или предлагать команды оболочки. Приоритетные отношения меняют порядок поиска, а не определение группы.

## Как строится доказательство

Новый `discovery/proof_search.py` работает непосредственно с исходными отношениями. Он рассматривает обращения и циклические перестановки доказанных реляторов, строит короткие следствия из общих фрагментов и сокращает предложенные степени слов. Каждый шаг сохраняет доказательство в операциях `match`, `inverse`, `product`, `conjugate`. Готовый DAG сокращается до используемых узлов и дважды проверяется на разных границах: внутри producer и перед допуском в память цикла.

Нетривиальный аффинный образ слова доказывает `w != 1`. Соотношение `w^q = 1` должно отдельно следовать из исходных отношений. Конечный порядок образа без доказательства степени недостаточен. При `q > 2` вывод обычно ограничен «порядок делит q».

Это ограниченная эвристика, не полный алгоритм решения проблемы слов. По умолчанию на попытку: 20 000 учитываемых операций, 2 000 удерживаемых отношений, 10 секунд поиска; отдельно действуют пределы слов и DAG. Проверка входов, генерация и независимый replay учитываются отдельно от времени поиска. Лимиты задаются при `start`: `--max-operations`, `--max-rules`, `--max-seconds`. Подсказка LLM не может их увеличить. Новое доказательство относится к исходной группе; отсутствие доказательства не означает отсутствие кручения и не исключает все факторгруппы без кручения.

В этом цикле CEM заново обучается на текущей памяти перед каждым раундом. ExtraTrees и его исторические метки в этот путь не включены: здесь исследуется именно помощь LLM в выборе целей доказательства. Преимущество перед автоматическим перебором пока не установлено; для такой оценки нужны отдельные равнобюджетные сравнения.

## Файлы результата

| Путь в папке запуска | Содержимое |
|---|---|
| `state.json`, `summary.json` | Бюджет, входные хеши, прогресс, следующий промпт и точные статусы |
| `family.json` | Семейство данного запуска |
| `round_NNN/candidate.json`, `generation.json` | Полное спаривание и сведения о генерации |
| `round_NNN/prompt.json`, `accepted_proposal.json` | Задача для чата и принятое предложение |
| `round_NNN/search.json` | Результат ограниченного поиска, затраты и сертификат при успехе |
| `round_NNN/submission.json`, `verification.json` | Независимо проверенная заявка и квитанция проверки |
| `verified/families/`, `verified/submissions/` | Только принятые новые для памяти ядра, готовые к отдельному replay |

Если новые ядра получены, перепроверьте пакет:

```sh
python -m k22 verify --data runs/my-search/verified
```

`new_cores_relative_to_input_atlas` означает новизну относительно конкретных входов запуска, а не мировую новизну. Перед PR сравните ядро с актуальной основной веткой. Рабочая папка `runs/` не публикуется автоматически. Готовый сертификат можно перенести в `data/submissions/` отдельным проверяемым PR.

## Демонстрация без сети и без LLM

```sh
python -m discovery demo --output runs/demo
python -m k22 verify --data runs/demo/verified
```

Или в Windows:

```powershell
.\run_llm_cycle.ps1 -Mode Demo -Run runs/demo
```

В демонстрации заранее написанная гипотеза позволяет заново вывести известный запрет из двух отношений. Его единственное ядро временно убирается из памяти демонстрации, затем возвращается после fresh proof и replay. Сам кандидат также содержит другое известное ядро. Поэтому это проверка работы программы, **не новый найденный запрет, не новый непокрытый кандидат и не измерение качества LLM**. После добавления ядра программа ещё раз генерирует кандидат, проверяя передачу обратной связи.

PowerShell `-Mode Start` создаёт первый кандидат и ждёт рассуждения чата. Сам по себе скрипт не запускает LLM в фоне. Для полного цикла пользователь даёт приведённую выше команду агенту в Codex, и агент выполняет все переходы.

## English

Use your existing chat agent as the hypothesis proposer. Ask it to run a bounded number of rounds following this file. The agent runs `python -m discovery start`, reads the returned `next_prompt`, writes a JSON proposal bound to the exact candidate hash, and calls `advance` until completion. `status` resumes the saved handoff. There are no API clients, keys, model servers, remote jobs, or execution of model-generated code.

The proposal schema allows at most four target words (32 signed original-generator letters), powers 2..16, up to 24 preferred original-relator indices, and an inert explanation. Empty targets honestly produce UNKNOWN. Hints only prioritize exact consequence search. A new independently implemented bounded producer emits original-relator DAG certificates; the unchanged verifier checks them again before the orchestration layer admits feedback. CEM uses the updated local core atlas for the next candidate. ExtraTrees is not part of this chat-guided path. No improvement in discovery rate is claimed without a controlled experiment.

Default limits are three rounds, CEM 2×32 draws per round, 20,000 proof-search operations, 2,000 retained relations and 10 seconds of search per proposal batch. Input validation and certificate replay are separate costs. Results, hashes, hypotheses, certificates and outcomes are saved under the run directory. A new core is new only relative to that run's input atlas. Source torsion is not a theorem about every torsion-free quotient; UNKNOWN never means torsion-free.

The network-free `demo` uses a hand-authored fixture and freshly rederives an existing two-relator obstruction. One known core is withheld from demo memory and readmitted after verification; the candidate still contains another known core. Demo success is software validation, not a scientific discovery or an LLM benchmark.
