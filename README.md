# Клиент оператора для Android — PeopleRecognition

Полнофункциональный Android-клиент, повторяющий Windows-клиент (client_windows):
- **Камеры**: список, MJPEG-стрим, добавить/удалить, вкл/выкл, звук, настройки интервалов
- **Люди**: поиск, создание/редактирование/удаление карточек, фото, дубли по лицу и по ФИО, объединение
- **Журнал**: фильтры (дата, камера, только неопознанные), просмотр кадров, удаление, экспорт XLSX
- **Отчёты**: сводка, посещаемость, таймлайн, по дням, неопознанные, экспорт XLSX

---

## Сборка APK для Samsung Galaxy S24 Ultra (Android 14, arm64-v8a)

S24 Ultra требует arm64 (64-бит). Buildozer нативно не работает на Windows — используйте **GitHub Actions** (рекомендуется) или **WSL2**.

### Вариант 1: GitHub Actions (рекомендуется, без локальной настройки)

1. Создайте репозиторий на GitHub и загрузите проект.
2. В GitHub откройте **Actions → Build Android APK → Run workflow**.
3. После завершения (~30–60 мин) скачайте артефакт `peoplerecognition-apk` (файл `.apk`).
4. Перенесите `.apk` на телефон (через кабель/облако/Telegram) и установите.

**Файл workflow**: `.github/workflows/build-apk.yml`

---

### Вариант 2: WSL2 (Ubuntu) локально

Требуется Windows 10/11 с включенным WSL2.

```powershell
# В PowerShell (администратор):
wsl --install
# Перезагрузка → Ubuntu настройка пользователя
```

В WSL (Ubuntu):
```bash
sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk \
  autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev \
  libtinfo5 cmake libffi-dev libssl-dev

pip3 install --upgrade buildozer cython

# Клонируйте проект или скопируйте папку client_android в WSL
cd /mnt/c/путь/к/проекту/client_android   # путь к папке client_android
bash build_wsl.sh
```

APK появится в `bin/*.apk`.

---

### Вариант 3: Google Colab (бесплатно, в браузере)

1. Откройте Colab, включите GPU (Runtime → Change runtime type → T4 GPU).
2. Выполните ячейки:
```python
!git clone https://github.com/ВАШ_РЕПО.git repo
%cd repo/client_android
!apt-get update -qq && apt-get install -y -qq git zip unzip openjdk-17-jdk autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev > /dev/null
!pip install -q buildozer cython
!buildozer -v android debug
```
3. Скачайте `bin/*.apk` через Files браузер Colab.

---

## Запуск на ПК (для проверки без Android)

```bat
python client_android.py http://IP_СЕРВЕРА:8000
```
Требует: `pip install kivy requests pillow`

---

## Особенности сборки под S24 Ultra

- `android.archs = arm64-v8a` — только 64-бит (S24 Ultra не поддерживает 32-бит).
- `android.api = 34`, `android.minapi = 24` — Android 14 (API 34) / 7.0+ (API 24).
- `android.ndk = 25b`, `android.sdk = 34` — актуальный тулчейн для Android 14.
- Зависимости: `kivy`, `requests`, `pillow`, `certifi` (SSL).
- Разрешения: `INTERNET`, `ACCESS_NETWORK_STATE`, `WRITE_EXTERNAL_STORAGE`, `READ_EXTERNAL_STORAGE` (файлы сохраняются в Downloads через MediaStore для совместимости с Samsung Galaxy Ultra).

---

## Установка на телефон

1. Включите «Установка из неизвестных источников» для файлового менеджера/браузера.
2. Откройте `.apk` → Установить.
3. При первом запуске введите адрес сервера: `http://192.168.x.x:8000` (IP ПК в одной сети).
4. Нажмите «Подключить».

---

## Структура папки client_android

```
client_android/
├── client_android.py     # Основной код (Kivy)
├── buildozer.spec        # Конфигурация сборки APK
├── build_wsl.sh          # Скрипт для WSL
├── requirements.txt      # Для запуска на ПК
├── install.bat           # Установщик зависимостей на ПК
└── README.md             # Этот файл
```

---

## Полезные ссылки

- Buildozer docs: https://buildozer.readthedocs.io
- python-for-android: https://python-for-android.readthedocs.io
- Kivy on Android: https://kivy.org/doc/stable/guide/android.html