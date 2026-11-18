# pi-switch-dock

[EN](#english) · [RU](#русский)

## English

A USB dock for Nintendo Switch Lite built around a Raspberry Pi 4. Switch Frame
Tap sends video and audio over USB; the Pi outputs them to an HDMI display.

### Requirements

- Raspberry Pi 4 running Raspberry Pi OS Lite Trixie, 64-bit.
- Switch Lite with [Switch Frame Tap](https://github.com/TomasUribe/switch-frame-tap) installed.
- A USB data cable.
- An HDMI display, connected and switched on.
- SSH access to the Pi and internet access for installation and updates.

Gameplay uses USB. The network is used for administration and downloads.
Switch software is installed and updated separately.

### Installation

Run on the Pi:

```sh
curl -fsSL https://raw.githubusercontent.com/vault-boy-13/pi-switch-dock/refs/heads/main/install.sh | sudo bash
```

This bootstrap selects the latest published stable release and runs the
installer from that same tag. Project tools are downloaded from the release
assets; upstream source is fetched separately and checked against its pinned
SHA256.

The installer prepares dependencies, USB, HDMI and the Lite Dock startup screen.
The receiver is compiled on the Pi, which may take several minutes.
Initial setup installs a GPIO18 fan-control service. Fan control requires an
optional add-on board; the dock works without it. The fan curve is 20% from
45 °C, 45% from 55 °C, 80% from 65 °C and 100% from 70 °C, with a brief
100% startup kick.

If the installer requests a reboot:

```sh
sudo reboot
```

After rebooting, reconnect over SSH and finish installation:

```sh
sudo pi-switch-dock-update
```

The receiver starts automatically at boot. The HDMI output is detected during
installation; keep using the same connector when updating.

### Updates and rollback

Check for an update:

```sh
sudo pi-switch-dock-update --check
```

Install an update:

```sh
sudo pi-switch-dock-update
```

Updates come from stable releases of `vault-boy-13/pi-switch-dock`.
For explicit candidate testing, use
`sudo pi-switch-dock-update --candidate v0.7.22` (add `--check` to preview).
Candidates must be published prereleases; ordinary updates ignore them.
If the version is already installed, the command makes no changes.
To force a rebuild of the selected release:

```sh
sudo pi-switch-dock-update --reinstall
```

Restore the saved previous version:

```sh
sudo pi-switch-dock-rollback
```

A rollback archive is created during updates. Rollback restores the receiver
and its preferences; the startup screen and boot settings are preserved.

### Display and startup screen

For displays above 1080p, the receiver selects an advertised 1080p120 mode,
otherwise 1080p60. The display handles scaling; capture quality is preserved.

The English **Lite Dock / Starting dock...** screen and quiet boot settings
are installed once. Receiver updates, rebuilds and rollback leave them unchanged.
The startup screen closes when the receiver starts.

### Diagnostics

Receiver status:

```sh
systemctl status switch-frame-tap-viewer --no-pager
```

Live receiver logs:

```sh
sudo journalctl -u switch-frame-tap-viewer -f
```

Startup screen logs:

```sh
sudo journalctl -u lite-dock-splash -b --no-pager
```

Receiver backups are stored in `/root/pi-switch-dock/backups/`;
original boot files are in `/var/lib/lite-dock-splash/backup/`.

### Acknowledgments

Thanks to Tomas Uribe for [Switch Frame Tap](https://github.com/TomasUribe/switch-frame-tap),
the original project that pi-switch-dock is based on.

pi-switch-dock was created with AI assistance. AI tools helped develop the
scripts, patches, startup screen and documentation.

Release preparation: [RELEASING.md](RELEASING.md).
License: [GPL-2.0-only](LICENSE). Attribution: [NOTICE](NOTICE).

## Русский

USB-док для Nintendo Switch Lite на базе Raspberry Pi 4. Switch Frame Tap
передаёт видео и звук по USB, а Pi выводит их на HDMI-дисплей.

### Требования

- Raspberry Pi 4 с Raspberry Pi OS Lite Trixie, 64 бит.
- Switch Lite с установленным [Switch Frame Tap](https://github.com/TomasUribe/switch-frame-tap).
- USB-кабель с передачей данных.
- Подключённый и включённый HDMI-дисплей.
- Доступ к Pi по SSH и интернет для установки и обновлений.

Игровой поток передаётся по USB. Подключение к сети нужно для администрирования
и скачивания файлов. Программы на Switch устанавливаются и обновляются отдельно.

### Установка

Выполните на Pi:

```sh
curl -fsSL https://raw.githubusercontent.com/vault-boy-13/pi-switch-dock/refs/heads/main/install.sh | sudo bash
```

Этот загрузчик выбирает последний опубликованный стабильный релиз и запускает
установщик из того же тега. Инструменты проекта скачиваются из assets релиза;
исходники upstream загружаются отдельно и проверяются по закреплённому SHA256.

Установщик подготовит зависимости, USB, HDMI и заставку Lite Dock.
Приёмник собирается на Pi; это может занять несколько минут.
При первой настройке устанавливается служба управления вентилятором на GPIO18.
Для её работы нужна дополнительная плата управления вентилятором; она
устанавливается опционально, док работает и без неё. Кривая вентилятора:
20% от 45 °C, 45% от 55 °C, 80% от 65 °C, 100% от 70 °C; при запуске —
кратковременно 100%.

Если установщик попросит перезагрузку:

```sh
sudo reboot
```

После перезагрузки снова подключитесь по SSH и завершите установку:

```sh
sudo pi-switch-dock-update
```

Приёмник запускается автоматически при включении Pi. HDMI-выход определяется
при установке; используйте тот же разъём при обновлении.

### Обновление и откат

Проверить наличие обновления:

```sh
sudo pi-switch-dock-update --check
```

Установить обновление:

```sh
sudo pi-switch-dock-update
```

Обновления берутся из стабильных релизов `vault-boy-13/pi-switch-dock`.
Для явной проверки кандидата используйте
`sudo pi-switch-dock-update --candidate v0.7.22` (`--check` для проверки наличия).
Кандидат должен быть опубликован как prerelease; обычное обновление его пропускает.
Если версия уже установлена, команда ничего не меняет.
Для принудительной повторной сборки выбранного релиза:

```sh
sudo pi-switch-dock-update --reinstall
```

Вернуться к сохранённой предыдущей версии:

```sh
sudo pi-switch-dock-rollback
```

Архив отката создаётся при обновлении. Откат восстанавливает приёмник и его
настройки; заставка и загрузочные настройки сохраняются.

### Экран и заставка

Для дисплеев выше 1080p приёмник выбирает заявленный дисплеем режим 1080p120,
иначе 1080p60. Масштабирование выполняет дисплей; качество захвата не меняется.

Английская заставка **Lite Dock / Starting dock...** устанавливается один раз
вместе с настройкой тихой загрузки. Обновление, повторная сборка и откат приёмника
её не меняют. При запуске приёмника заставка закрывается.

### Диагностика

Состояние приёмника:

```sh
systemctl status switch-frame-tap-viewer --no-pager
```

Логи приёмника в реальном времени:

```sh
sudo journalctl -u switch-frame-tap-viewer -f
```

Логи заставки:

```sh
sudo journalctl -u lite-dock-splash -b --no-pager
```

Резервные копии приёмника находятся в `/root/pi-switch-dock/backups/`,
исходные загрузочные файлы — в `/var/lib/lite-dock-splash/backup/`.

### Благодарности

Спасибо Tomas Uribe за [Switch Frame Tap](https://github.com/TomasUribe/switch-frame-tap) —
оригинальный проект, на котором основан pi-switch-dock.

pi-switch-dock создан с помощью ИИ: при разработке скриптов, патчей, заставки
и документации использовались инструменты ИИ.

Подготовка релизов: [RELEASING.md](RELEASING.md).
Лицензия: [GPL-2.0-only](LICENSE), сведения об авторстве: [NOTICE](NOTICE).

