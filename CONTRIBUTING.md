# Contributing / Как участвовать

## Русский

Цель — совместный поиск явного контрпримера с **группой без кручения**. Такой контрпример здесь не заявлен. Проверяемые запреты и воспроизводимые отрицательные результаты тоже продвигают поиск. Сначала прочитайте [постановку](docs/PROBLEM.md), [формат доказательств](docs/CERTIFICATES.md) и, если работает агент, [AGENTS.md](AGENTS.md).

1. Найдите существующий issue или откройте новый с конкретным вопросом. Укажите семейство, его `family_sha256`, метод, бюджет и ожидаемый результат. Проверьте открытые PR и уже имеющиеся ядра. Назначьте issue на себя, если можете; иначе оставьте комментарий о начале работы.
2. Сделайте fork/clone и отдельную ветку, например `agent/123-smaller-core` или `human/123-verifier-test`. В одном PR решайте один понятный вопрос. Для параллельных агентов используйте разные ветки или worktree и заранее разделите файлы.
3. Сохраните seed, параметры, версию кода, отпечаток входных данных и точный статус результата. Ограничьте время и расходы заранее. Идею, неподтверждённый кандидат или `UNKNOWN` обсуждайте в issue; они не входят в `data/submissions/`.
4. Для нового запрета добавьте **один JSON с полным доказательством** в `data/submissions/<submission_id>.json`. Схема, вычисление ID и ограничения описаны в [CERTIFICATES.md](docs/CERTIFICATES.md). Не меняйте порядок `matching` после создания доказательства. Новое семейство сначала обсудите в issue и предоставьте его явные упорядоченные данные и отпечатки.
5. Запустите из корня репозитория (Python 3.11+):

   ```sh
   python -m k22 verify --data data --report verification-report.json
   python -m unittest discover -s tests -v
   python -m unittest models.test_cem -v
   ```

6. Откройте draft PR со ссылкой на issue, точным утверждением, файлами доказательства и результатом проверки. Объясните, что нового добавлено: меньшее ядро, новый класс запрещённых продолжений, проверка, исправление или улучшение модели. Для ускорения модели приведите сравнение с контролем при одинаковом бюджете. Не называйте лучшую оценку модели математическим доказательством.

Проверка сертификата подтверждает кручение **в исходной группе спаривания**. Она не доказывает, что любой её фактор без кручения обнуляет множители. Показатель `q` в доказанном `w^q = 1` обычно означает «порядок делит q»; точный порядок требует дополнительного обоснования. При `q = 2` и проверенном `w != 1` порядок равен двум.

Не загружайте ключи API, `kaggle.json`, токены, личные переписки, приватные пути или данные чужих аккаунтов. Участник запускает агента под своим управлением; общая регистрация ключей не требуется. Подробнее: [как подключить своего агента](docs/AGENT_WORKFLOW.md).

## English

The goal is a collaborative search for an explicit counterexample with a **torsion-free group**. No such counterexample is claimed here. Checked obstructions and reproducible negative results also advance the search. Read the [problem](docs/PROBLEM.md), [certificate protocol](docs/CERTIFICATES.md), and [AGENTS.md](AGENTS.md) before using an agent.

1. Find or open a focused issue. State the family, `family_sha256`, method, budget, and expected deliverable. Check existing issues, PRs, and cores for duplicate work. Assign yourself if permitted; otherwise comment that you are working on it.
2. Fork/clone and create a separate branch, such as `agent/123-smaller-core` or `human/123-verifier-test`. Keep each PR focused. Give parallel agents separate branches/worktrees and explicit file ownership.
3. Record seeds, parameters, code revision, input fingerprints, and exact outcome labels. Bound time and spending in advance. Discuss hypotheses, unproved candidates, and `UNKNOWN` results in issues; do not put them in `data/submissions/`.
4. Submit a new obstruction as **one JSON file with its full proof**, named `data/submissions/<submission_id>.json`. Follow [CERTIFICATES.md](docs/CERTIFICATES.md). Never reorder the matching after producing its certificate. Propose new families in an issue with explicit ordered data and fingerprints.
5. Run the three commands above from the repository root with Python 3.11 or later.
6. Open a draft PR linking the issue. Include the precise claim, proof files, verification result, and what is new. For model improvements, compare against a control with the same budget. A model score is not a mathematical certificate.

A certificate proves torsion **in the matching's source group**. It does not prove that every torsion-free quotient kills the factors. A proved `w^q = 1` normally gives an order dividing `q`, not an exact order. For `q = 2`, checked nonidentity gives exact order two.

Never upload API keys, `kaggle.json`, tokens, private messages, private paths, or another person's account data. Participants control their own agents; no shared key registry is needed. See the [agent workflow](docs/AGENT_WORKFLOW.md).
