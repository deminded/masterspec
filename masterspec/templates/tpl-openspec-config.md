# tpl-openspec-config — дескриптор openspec/config.yaml для layout=openspec

Шаблон содержимого `openspec/config.yaml`. Создаётся при инициализации фабрики в
openspec-режиме (derive/recover), ЕСЛИ файла ещё нет; существующий не перезаписывать —
в нём может жить контекст владельца.

```yaml
schema: spec-driven

# Фабрика ведётся мета-моделью masterspec (github.com/deminded/masterspec).
# Источник истины — артефакты masterspec; этот файл — дескриптор для инструментов OpenSpec.
context: |
  This repository uses the masterspec meta-model inside the OpenSpec layout.
  - specs/ holds the masterspec factory tree, NOT OpenSpec capability specs:
    01-requirements/ (functions fn-*, NFR, rules, data model, dictionaries,
    acceptance tests tc-acc-*), 02-specifications/ (components cmp-*, scenarios
    scn-*, algorithms alg-*, APIs, data schemas, integration tests), 03-codemap/
    (traces to code), 04-decisions/ (ADR). Index: specs/00-masterspec-index.md.
  - changes/<name>/change.md is the source of truth for a change (8-section
    masterspec format, Russian); proposal.md next to it is a generated bridge
    summary, .openspec.yaml marks skip_specs because behavior details live in
    masterspec artifacts, not in OpenSpec spec deltas.
  - Do not create specs/**/spec.md capability files unless explicitly asked:
    the masterspec tree is the requirement source here.

rules:
  proposal:
    - proposal.md is a projection of change.md §1-§2; never add facts that are
      absent from change.md - fix change.md first, then regenerate the bridge.
```

Правила подстановки: содержимое `context:` можно дополнять фактами проекта (стек, домен),
но блок про мета-модель и мосты — оставить, он и есть «понятный openspec дескриптор».
