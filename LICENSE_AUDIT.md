# Лицензионный аудит Makepad SandStudio

Проверено 13 ноября 2026 года. Объём проверки включает исходный кандидат предварительного релиза и возможный состав установщика Windows. Распространение гостевых приложений требует отдельного решения владельцев прав.

| Область | Статус | Основание |
| --- | --- | --- |
| Лицензия существующего MSS | Подтверждена | Корневой MIT `LICENSE` появился в коммите `30b5bb53977a8ee1b16ec72db4ca6feeb17f0fee`. Cargo workspace объявляет MIT. |
| Новые файлы MSS | Проверка происхождения открыта | Право на публикацию собственных изменений дано владельцем репозитория. У локальных ранее неопубликованных изменений Desktop, launcher, MCP, записи и handoff требуется подтверждение авторства и условий включения по списку файлов. |
| Исходный preview | Кандидат | Выборка содержит исходники и ссылки на закреплённые внешние зависимости. Окончательный статус зависит от проверки происхождения новых файлов, отдельной проверки дерева на приватные данные и прохождения сборки. |
| Windows installer | BLOCKED для публичного распространения | Отсутствует подтверждённая ведомость фактически включённых двоичных файлов, шрифтов и ресурсов с лицензиями. Требуется отдельно проверить переносимый запуск и установку. |

## Исходники MSS

На момент инвентаризации рабочий Git HEAD `83ff50112fbbdc1cd2a43ccd2ac1650504394a67` содержит корневой MIT и первоначальный каркас. Локальные изменения проверяются отдельно от этого SHA. Исторический аудит публикации 54 файлов относится к дереву `8199dd237c358684686c8f3f5bd1ac2cbf4b0060`. Эти результаты не идентифицируют текущий кандидат.

Проверка новых Rust- и Python-файлов по строкам атрибуции не обнаружила явных заявлений о прямом копировании внешнего кода. Такой поиск выявляет отдельные признаки заимствования и не устанавливает цепочку прав. Для публикации сохранить перечень новых файлов с источником и владельцем прав, исходные notices там, где установлено заимствование, и SHA-256 финального дерева. Существующий `LICENSE` сохранить.

Фильтр состава исходного preview допускает MSS Rust, Python, PowerShell, документацию, SKLT, обезличенные примеры и зафиксированные манифесты. Профили конкретной машины, доказательства с данными пользователей, SDK checkout, бинарники, пользовательские документы и содержимое кешей хранятся отдельно. Перед отправкой проверяется точное коммитируемое дерево.

- [Коммит с лицензией MSS](https://github.com/paulgreenbox-beep/makepad-sandstudio/commit/30b5bb53977a8ee1b16ec72db4ca6feeb17f0fee)
- [Исходный HEAD рабочей копии на момент проверки](https://github.com/paulgreenbox-beep/makepad-sandstudio/tree/83ff50112fbbdc1cd2a43ccd2ac1650504394a67)

## Makepad и Cargo

`MSS_Desktop/Cargo.toml` закрепляет `makepad-widgets` 2.0.0 по `130be1d0318adcf69453d925342607466353152c`. В локальном Cargo checkout именно этой ревизии корневая лицензия MIT принадлежит Makepad B.V., а манифесты widgets, draw и platform объявляют `MIT OR Apache-2.0`. Makepad содержит вложенные компоненты с собственными условиями.

Проверенный `Cargo.lock` содержит 133 записи, включая 7 MSS, 100 из закреплённого Makepad и 26 из crates.io. Для 123 внешних записей найдены объявления лицензий в точных кешированных манифестах. Среди них есть Apache-2.0 без альтернативы у `ab_glyph_rasterizer`, ISC у `libloading`, Zlib у `foldhash`, CC0-1.0 у `hexf-parse` и Unicode-3.0 в выражении `unicode-ident`. Граф lockfile включает несколько платформ и не служит ведомостью состава Windows EXE.

У `makepad-fast-inflate`, `makepad-git` и `makepad-regex` отсутствуют поля лицензии в манифестах. Их присутствие наблюдается в исторической сборке Windows. Заголовки `makepad-fast-inflate` идентифицируют порты libdeflate и miniz_oxide под MIT, а `makepad-git/src/sha1.rs` указывает на RustCrypto/hashes под MIT/Apache-2.0. Для установщика нужны точный граф выбранной цели, сохранённые тексты лицензий и notices и проверка внешних заимствований этих компонентов.

Гостевой локальный Makepad checkout имеет базу `2271c0eb350cedd497c84373f17ad2b0b662cb72` и изменённый `libs/makepad_test/src/runtime.rs` с SHA-256 `215f7628b6e3e0cae4a4d1f256330f253f40b0a28590d2c6629ae9527c5a4044`. Патч меняет ожидание postconditions для селектора `nth`. Права и связь этого изменения с конкретным гостевым EXE отдельно не проверены. Checkout и производные гостевые бинарники исключены из публичного кандидата.

- [Закреплённая ревизия Desktop SDK](https://github.com/makepad/makepad/tree/130be1d0318adcf69453d925342607466353152c)
- [Гостевая базовая ревизия](https://github.com/makepad/makepad/tree/2271c0eb350cedd497c84373f17ad2b0b662cb72)
- [libdeflate](https://github.com/ebiggers/libdeflate)
- [miniz_oxide](https://github.com/Frommi/miniz_oxide)
- [RustCrypto/hashes](https://github.com/RustCrypto/hashes)

## Шрифты, иконки и ресурсы

В закреплённом Makepad `platform/src/font_policy.rs` перечисляет возможные ресурсы, включая `makepad_widgets/resources`. Список ниже описывает проверенные файлы из кеша SDK. Обязательный состав установки должен подтверждаться сборкой и запуском вне checkout и Cargo cache.

| Ресурс | Установлено по файлу и upstream |
| --- | --- |
| Inter 4.001, Roboto Flex 3.200 | SIL OFL 1.1, рядом присутствуют тексты OFL. |
| IBM Plex Sans 3.2/3.3, JetBrains Mono 2.304, Noto Sans 1.06, Noto Color Emoji 2.047, LXGW WenKai 1.330 | Встроенные метаданные указывают SIL OFL 1.1. При включении сохранить соответствующий текст и атрибуцию каждой семьи. |
| Font Awesome Free Solid 6.7.2 | Файл шрифта подпадает под SIL OFL 1.1. Если в пакет попадут SVG-иконки Font Awesome, для них действует CC BY 4.0. |
| Liberation Mono 1.04 | В файле указан Ascender и исторический URL. Upstream относит семейство 1.x к GPLv2 с исключением для встраивания шрифта. Условие OFL семейства 2.x неприменимо к этому файлу. Проверить условия распространения конкретной версии, включая исходники, до включения. |
| NewComputerModernMath 4.0 | Встроенный copyright указывает GUST Font License. Для включения нужен текст из соответствующей версии исходной поставки. |
| Прочие SVG, изображения и иконки | Установить происхождение по списку реально упакованных файлов. |

- [Liberation Fonts upstream, лицензии поколений](https://github.com/liberationfonts/liberation-fonts/wiki#distribution)
- [Font Awesome Free 6.7.2, условия по типам ресурсов](https://github.com/FortAwesome/Font-Awesome/blob/6.7.2/LICENSE.txt)
- [NewComputerModern upstream в CTAN](https://ctan.org/pkg/newcomputermodern)

## Windows runtime и гостевые приложения

| Компонент | Наблюдение | Граница распространения |
| --- | --- | --- |
| Python | Импорты MSS MCP относятся к стандартной библиотеке и собственным модулям. Desktop разрешает `MSS_DESKTOP_PYTHON` и содержит запасной путь в локальный кеш Codex. | Объявить внешнюю совместимую версию либо отдельно выбрать официальный CPython embeddable-пакет с его полными лицензиями и notices. Состав кеша Codex исключить. |
| PowerShell | Launcher вызывает `pwsh.exe`. Текущая реализация выводит его путь из расположения Python и проверяет SHA-256. | Для установщика нужен явный переносимый путь к внешнему PowerShell или отдельно проверенная официальная поставка PowerShell с её notices и условиями на включённые компоненты. |
| Codex CLI | Handoff использует установленный Codex, путь можно задать через `MSS_CODEX_EXE`. | Внешний компонент. Лицензия Apache-2.0 репозитория CLI не устанавливает состав или право распространения текущих файлов из WindowsApps. |
| Makepad Remote | Гостевые профили закрепляют внешний `makepad-remote.exe` и его хеш. | Требуется точное происхождение проверенного EXE и его notices для отдельной поставки. |
| RudraOffice и AI CAD | Внешние приложения в локальных профилях. | Исключить из установщика и исходного архива вместе с документами и пользовательскими данными. |
| Экспериментальный AI CAD DWG worker | Внешний `AiRevit.DwgWorker/1.0.0` использует `ACadSharp 3.8.35`. Локальный runtimeconfig требует `Microsoft.NETCore.App 10.0.0`. | ACadSharp объявлен MIT. Права на AI CAD и worker, точный состав поставки и условия Windows .NET проверяются отдельно. Весь экспериментальный payload исключён. |

- [Лицензия CPython](https://docs.python.org/3/license.html) и [официальная встраиваемая поставка для Windows](https://docs.python.org/3/using/windows.html#the-embeddable-package)
- [PowerShell LICENSE](https://github.com/PowerShell/PowerShell/blob/master/LICENSE.txt) и [ThirdPartyNotices](https://github.com/PowerShell/PowerShell/blob/master/ThirdPartyNotices.txt)
- [Лицензия исходников Codex](https://github.com/openai/codex/blob/main/docs/license.md)
- [ACadSharp 3.8.35](https://www.nuget.org/packages/ACadSharp/) и [ACadSharp LICENSE](https://github.com/DomCR/ACadSharp/blob/master/LICENSE)
- [Условия для исходников и поставок .NET](https://github.com/dotnet/core/blob/main/license-information.md)

## Условия завершения

Для исходного preview требуется зафиксировать происхождение новых файлов, проверить точный diff, права и отсутствие закрытых данных. Для публичного установщика дополнительно требуется ведомость состава с версиями, SHA-256, источниками и лицензиями, включённые тексты лицензий и notices и проверка запуска вне среды разработки. До выполнения этих условий публичное распространение соответствующего артефакта остаётся заблокированным.
