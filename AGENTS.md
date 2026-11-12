# Agent instructions / Инструкции агентам

These instructions apply throughout this repository. / Эти инструкции действуют во всём репозитории.

## Chat-guided search / Поиск из текущего чата

When the user asks to run the LLM obstruction cycle, follow [docs/LLM_SEARCH.md](docs/LLM_SEARCH.md). You are the hypothesis proposer in the existing chat: no API key or separate model service is required. Run `discovery start`, read the returned prompt, reason about the actual candidate, write a bounded proposal JSON, then run `discovery advance`. Repeat until the requested round budget is complete or a concrete blocker occurs; do not hand the user each intermediate command. If no budget is supplied, use three rounds with the documented defaults. A request to explain the process does not start a search. A request to stop overrides this loop immediately.

Resume an explicitly named run with `discovery status`; do not replace its saved candidate. If the user asks to resume the latest run without a path, inspect only this repository's `runs/*/state.json` and select the most recent unfinished run, stating the path. Never invent a proposal from another candidate, copy a fixture as a new finding, or write generated code into the proof search. An empty `targets` list is an honest no-hypothesis result. Treat the proof producer as untrusted: only independent `k22` replay permits a core into feedback. Do not publish run artifacts automatically; prepare a focused PR only when authorized.

Когда пользователь просит запустить цикл, самостоятельно выполните все его раунды через локальные команды и JSON, используя рассуждения текущего чата. По умолчанию — три раунда. Не просите API-ключ и не требуйте, чтобы пользователь вручную передавал промежуточные файлы. Состояние сохраняется, остановленный пользователем поиск не возобновляйте без новой команды. Подробный протокол и формат ответа находятся в `docs/LLM_SEARCH.md`.

## English

1. Read `README.md`, `CONTRIBUTING.md`, `docs/PROBLEM.md`, and `docs/CERTIFICATES.md` before working. For model tasks also read `docs/MODELS.md`. Follow the user's assigned scope; do not restart a mathematical campaign when the task is documentation, review, or packaging.
2. Coordinate through an issue and a dedicated branch/worktree. State the family fingerprint, intended deliverable, file ownership, seed range, and budget. Check existing cores, open issues, and PRs first. Do not overwrite another contributor's work. Report overlapping work before spending a large budget.
3. Keep claims separate: `UNPROVED_CANDIDATE`, bounded `UNKNOWN`, certified source torsion, and a separately proved statement about all torsion-free quotients. No missing proof, ML score, finite-power check, or SAT solution certifies torsion-freeness.
4. Only independently checked source-torsion submissions belong in `data/submissions/`. Preserve the exact ordered family and original matching order/orientation used by the proof. A source torsion witness needs both a proof of `w^q = 1` and checked `w != 1`; a finite-order affine image alone is insufficient.
5. Use the public verifier as the trust boundary. Do not loosen verification or resource limits just to admit a failing submission. Propose verifier changes separately with a mathematical explanation and positive/negative tests. JSON is data, never executable code.
6. Cores belong to one fixed family fingerprint. Do not transfer them by row permutations, transpose, inversion, or another apparent symmetry without an explicit checked transport of both relations and the nonidentity witness. Smaller cores require a new valid proof; deleting edges from a JSON list is not minimization.
7. Make experiments reproducible: record code revision, data fingerprint, seeds, limits, metrics, and actual statuses. Give model and baseline the same constraints and budgets; report generation/training overhead separately. Keep held-out random streams separate from training and from other seeds.
8. Work locally or in the participant's authorized environment. Never collect, request for publication, log, or commit credentials. Do not create paid/long remote jobs without the user's authorization. Do not send messages to others or publish under another person's account without authorization.
9. Before a PR run `python -m k22 verify --data data` and `python -m unittest discover -s tests -v`; for CEM changes also run `python -m unittest models.test_cem -v`. Add focused tests for mathematical or verifier changes. Include a short result and limitations in the PR. A draft PR is the normal review handoff; merging follows the repository's review process.

## Русский

1. До работы прочитайте `README.md`, `CONTRIBUTING.md`, `docs/PROBLEM.md` и `docs/CERTIFICATES.md`; для моделей также `docs/MODELS.md`. Соблюдайте задачу пользователя: работа над документацией или упаковкой не означает разрешения возобновить математический поиск.
2. Закрепите работу за issue и отдельной веткой/worktree. Укажите отпечаток семейства, результат, свои файлы, seeds и бюджет. Проверьте существующие ядра, issues и PR. Не перезаписывайте чужую работу и заранее сообщайте о пересечениях задач.
3. Разделяйте неподтверждённый кандидат, ограниченный `UNKNOWN`, доказанное кручение исходной группы и отдельную теорему обо всех факторах без кручения. Отсутствие найденного доказательства, оценка ML, проверка конечного числа степеней и решение SAT не доказывают отсутствие кручения.
4. В `data/submissions/` входят только проверенные сертификаты кручения. Сохраняйте порядок семейства и порядок/ориентацию спариваний, к которым относится доказательство. Нужны и `w^q = 1`, и `w != 1`; конечный порядок аффинного образа сам по себе недостаточен.
5. Граница доверия — публичный verifier. Не ослабляйте проверку ради принятия невалидных данных. Изменения verifier оформляйте отдельно с объяснением и положительными/отрицательными тестами. JSON не должен исполняться как код.
6. Ядро привязано к одному отпечатку семейства. Перенос по перестановке, транспонированию или обращению требует явной проверки переноса соотношений и нетривиального свидетеля. Для уменьшенного ядра нужно новое доказательство, а не простое удаление рёбер.
7. Сохраняйте версию кода, отпечаток данных, seeds, лимиты, метрики и реальные статусы. Сравнивайте модель с контролем при одинаковых ограничениях и бюджетах; отдельно учитывайте обучение и генерацию. Разделяйте случайные потоки обучения, проверки и разных повторов.
8. Работайте в разрешённой пользователем среде. Не собирайте и не публикуйте ключи; не записывайте их в логи. Долгие/платные удалённые вычисления, сообщения другим людям и публикации от чужого имени требуют разрешения пользователя.
9. Перед PR выполните команды проверки из английского пункта 9. Для математических изменений добавьте содержательные тесты. В draft PR укажите результат и границы утверждения; слияние проходит обычный процесс review.
