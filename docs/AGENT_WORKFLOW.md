# Bring your own agent / Как подключить своего агента

## Русский

Репозиторий — общая точка обмена задачами, кодом и доказательствами. Он не подключается к аккаунту вашего агента и не принимает ключи. Подойдёт любой агент, умеющий читать файлы, запускать Python и готовить изменения в Git. Вы управляете его доступом и вычислительным бюджетом.

1. Сделайте fork репозитория, затем clone своего fork. В своей среде откройте папку проекта и дайте агенту прочитать `AGENTS.md` и связанные документы.
2. Выберите или создайте issue. Укажите, что работа начата, ожидаемый результат и срок следующего обновления. Укажите точный `family_sha256` для математической задачи. Если несколько агентов работают параллельно, разделите вопросы, файлы и диапазоны seeds.
3. Создайте отдельную ветку. Агент может приватно исследовать идеи и сохранять промежуточные результаты локально. В репозиторий должны попадать воспроизводимые артефакты, а не личная история чата.
4. Запустите проверки. Попросите агента объяснить итог своими словами: что доказано, что осталось `UNKNOWN`, какие файлы это подтверждают и как повторить проверку.
5. Просмотрите изменения и откройте draft PR со ссылкой на issue. Для доказанного ядра достаточно публичного JSON-сертификата и воспроизводимой проверки; API-ключи и доступ к вашей машине не нужны.

Пример задания агенту:

> Прочитай AGENTS.md и issue #123. Работай в отдельной ветке только над указанным семейством и файлами. Бюджет — 10 минут локального CPU, без удалённых расходов. Не считай UNKNOWN доказательством отсутствия кручения. Сначала проверь существующие ядра, затем подготовь воспроизводимый результат и draft PR. Для любого нового запрета нужен успешный replay публичным verifier.

Хорошие первые задачи: объяснить короткий сертификат человеку; добавить отрицательный тест для verifier; проверить дубликаты; улучшить воспроизводимость модели; предложить проверяемый транспорт симметрии; подготовить новый доказанный core. Идея без сертификата тоже полезна — оформите её как вопрос или гипотезу в issue.

Перед долгими вычислениями обновите issue, чтобы другие участники не повторяли тот же диапазон. Освободите задачу, если перестали над ней работать. Обсуждайте изменения метода и бюджета явно; не предполагается, что владелец репозитория оплачивает вычисления участников.

## English

This repository coordinates tasks, code, and proofs. It does not connect to your agent account or collect keys. Any agent capable of reading files, running Python, and preparing Git changes can participate. You control its permissions and compute budget.

Fork and clone the repository, open it in your own environment, and ask the agent to read `AGENTS.md`. Claim a focused issue or comment that you are working on it. State the family fingerprint, deliverable, budget, and next update. Use a dedicated branch. For parallel agents, divide questions, file ownership, and seed ranges.

Private exploratory work stays in your environment. Share reproducible artifacts rather than private chat histories. Before opening a draft PR, review the changes and run verification. Ask the agent to distinguish what was proved, what remains `UNKNOWN`, and how another person can reproduce the result. A public JSON proof does not require access to your machine or API credentials.

Example task:

> Read AGENTS.md and issue #123. Work on a separate branch within the assigned family and files. Use at most 10 minutes of local CPU and no paid remote jobs. UNKNOWN is not torsion-freeness. Check existing cores first, then prepare a reproducible result and draft PR. Every new obstruction must pass the public proof verifier.

Good first tasks include explaining a short certificate, adding a verifier rejection test, checking duplicates, improving model reproducibility, proposing a checked symmetry transport, or supplying a new certified core. Unproved ideas belong in issues as questions or hypotheses. Update the issue before a long run, release it when no longer active, and coordinate overlapping work. The repository owner does not implicitly fund participants' computations.
