# RobloxCodeRules — общие правила Roblox-кода

## 1. Об этом документе
<!-- summary: Дополнение к LLM_START. Появляется только в Roblox-режиме. Про общие правила Roblox, не про конкретный проект. -->
<!-- tags: roblox, addendum, about -->

Это **дополнение** к `LLM_START`. Появляется ниже, когда пользователь включил в GUI галку «+ RobloxCodeRules.md».

**Что здесь:** общие правила разработки под Roblox — Edit vs Play, constraints, UI-вёрстка, типовые ошибки движка. Применимо к любой Roblox-игре.

**Что здесь нет:** правил конкретного проекта, специфики кодовой базы, работы с мостом (см. `MCPBridgeRules.md`).

**При конфликте с `LLM_START`** — приоритет у `LLM_START`, потому что он описывает механику утилиты.

## 2. Общие правила
<!-- summary: Edit vs Play, Terrain, CharacterAdded, constraints, CollectionService, UI-вёрстка, комментарии. -->
<!-- tags: roblox, rules -->

- **Edit vs Play.** Содержимое `StarterGui` / `StarterPlayerScripts` и события (`RunService.Heartbeat`, `PlayerAdded` и т.п.) не проявляются в Edit-режиме — только после того, как человек нажмёт Play.
- **Terrain не BasePart.** При массовом удалении объектов через `obj:IsA('BasePart')` проверяй `not obj:IsA('Terrain')`, иначе скрипт упадёт с `Cannot Destroy() Terrain`.
- **CharacterAdded и HumanoidRootPart.** Перед установкой `CFrame` нужно `WaitForChild('HumanoidRootPart')`, иначе позиция не применится.
- **Движение "спутника" за игроком.** Если объект должен быть виден всем игрокам и физически двигаться — используй констрейнты (`AlignPosition` / `AlignOrientation`), а не ручной `CFrame` в `LocalScript`. `SetNetworkOwner` применим только к НЕ-`Anchored` объектам. Если эффект нужен только одному игроку — делай целиком в `LocalScript`, без создания на сервере вообще.
- **CollectionService в ModuleScript.** Все используемые сервисы (включая `CollectionService`) должны быть явно объявлены в начале модуля, даже если они используются только в `Init()`.
- **Динамическая вёрстка UI.** Избегай сложной вёрстки через `Instance.new`. Закладывай структуру из `Frame` и `ScrollingFrame` с `UIListLayout` прямо в `StarterGui`. В коде только наполняй их контентом. `UIListLayout` автоматически управляет позициями и размером Canvas, что предотвращает ошибки с перекрытием и скроллом.
- **Комментарии.** Пишутся только там, где логика не очевидна из кода или в `summary`. Язык комментариев — всегда английский.
