"""Полный Android-клиент оператора для системы распознавания людей (Kivy).

По функционалу повторяет Windows-клиент (client_windows/client_windows.py):
MJPEG-просмотр камер и управление ими (добавить/удалить/вкл/звук/интервалы),
карточки людей (просмотр/создание/редактирование/удаление, фото, дубли по
лицу и по ФИО, объединение), журнал идентификаций (фильтры, кадры, удаление,
экспорт XLSX), отчёты (сводка, посещаемость, таймлайн, по дням, неопознанные,
экспорт XLSX).

Запуск на ПК (для проверки):
    python client_android.py                  — окно ввода IP сервера
    python client_android.py http://IP:8000

Сборка APK (Samsung S24 Ultra: Android 14, arm64-v8a):
    buildozer -v android debug
"""
import io
import os
import sys
import threading
import time

import requests
from PIL import Image

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.graphics.texture import Texture
from kivy.lang import Builder
from kivy.properties import ObjectProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image as KivyImage
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.checkbox import CheckBox
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.textinput import TextInput

try:
    from kivy.utils import platform
except Exception:
    platform = "win"

SERVER_DEFAULT = "http://127.0.0.1:8000"

ACCENT = (0.18, 0.45, 0.78, 1)
DARK = (0.08, 0.09, 0.12, 1)
CARD = (0.15, 0.17, 0.21, 1)
TEXT = (0.92, 0.92, 0.95, 1)
MUT = (0.62, 0.62, 0.68, 1)


def human_dur(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}ч {m}м"
    if m:
        return f"{m}м {s}с"
    return f"{s}с"


def normalize_server(host, port=8000):
    host = (host or "").strip()
    if not host:
        return SERVER_DEFAULT
    if "://" not in host:
        host = "http://" + host
    host = host.rstrip("/")
    _, _, rest = host.partition("://")
    if ":" not in rest:
        host = f"{host}:{port}"
    return host


# --------------------------------------------------------------------------
#  Сетевой слой (используется в фоновых потоках)
# --------------------------------------------------------------------------
class Api:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def _req(self, method, path, **kw):
        kw.setdefault("timeout", 25)
        r = requests.request(method, self.base + path, **kw)
        body = {}
        try:
            body = r.json() if r.content else {}
        except Exception:
            pass
        if r.status_code >= 400:
            raise RuntimeError(body.get("error") or f"HTTP {r.status_code}")
        return body

    def get(self, path, **params):
        return self._req("GET", path, params=params)

    def post(self, path, **kw):
        return self._req("POST", path, **kw)

    def put(self, path, **kw):
        return self._req("PUT", path, **kw)

    def patch(self, path, **kw):
        return self._req("PATCH", path, **kw)

    def delete(self, path, **params):
        return self._req("DELETE", path, params=params)

    def cameras(self):
        return self.get("/api/cameras")

    def add_camera(self, data):
        return self.post("/api/cameras", json=data)

    def delete_camera(self, cid):
        return self.delete(f"/api/cameras/{cid}")

    def patch_camera(self, cid, **kw):
        return self.patch(f"/api/cameras/{cid}", json=kw)

    def people(self, **params):
        return self.get("/api/people", **params)

    def person(self, pid):
        return self.get(f"/api/people/{pid}")

    def create_person(self, data):
        return self.post("/api/people", json=data)

    def update_person(self, pid, data):
        return self.put(f"/api/people/{pid}", json=data)

    def delete_person(self, pid):
        return self.delete(f"/api/people/{pid}")

    def duplicates(self, pid):
        return self.get(f"/api/people/{pid}/duplicates")

    def name_duplicates(self, name):
        return self.get("/api/people/name-duplicates", name=name)

    def merge(self, target, source):
        return self.post("/api/people/merge",
                         params={"target_id": target, "source_id": source})

    def _uri_to_file(self, uri):
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            resolver = activity.getContentResolver()
            Uri = autoclass("android.net.Uri")
            input_stream = resolver.openInputStream(Uri.parse(uri))
            if input_stream is None:
                return None
            import tempfile
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            buffer = bytearray(65536)
            while True:
                n = input_stream.read(buffer, 0, len(buffer))
                if n <= 0:
                    break
                tmp.write(buffer[:n])
            tmp.close()
            input_stream.close()
            return tmp.name
        except Exception:
            return None

    def upload_photo(self, pid, filepath, filename=None):
        real_path = filepath
        fname = filename or os.path.basename(filepath)
        if isinstance(filepath, str) and filepath.startswith("content://"):
            real_path = self._uri_to_file(filepath)
        if real_path and os.path.exists(real_path):
            with open(real_path, "rb") as f:
                return self.post(f"/api/people/{pid}/photo",
                                 files={"file": (fname, f, "image/jpeg")},
                                 timeout=120)
        else:
            with open(filepath, "rb") as f:
                return self.post(f"/api/people/{pid}/photo",
                                 files={"file": (fname, f, "image/jpeg")},
                                 timeout=120)

    def delete_photo(self, pid, fid):
        return self.delete(f"/api/people/{pid}/photo/{fid}")

    def events(self, **params):
        return self.get("/api/events", **params)

    def delete_event(self, eid):
        return self.delete(f"/api/events/{eid}")

    def delete_unknowns(self, **params):
        return self.delete("/api/events/unknowns", **params)

    def summary(self, **params):
        return self.get("/api/reports/summary", **params)

    def attendance(self, **params):
        return self.get("/api/reports/attendance", **params)

    def timeline(self, **params):
        return self.get("/api/reports/timeline", **params)

    def daily(self, **params):
        return self.get("/api/reports/daily", **params)

    def unknowns(self, **params):
        return self.get("/api/reports/unknowns", **params)

    def xlsx(self, path, **params):
        r = requests.get(self.base + path, params=params, timeout=90)
        if r.status_code >= 400:
            raise RuntimeError("Ошибка экспорта XLSX")
        return r.content


# --------------------------------------------------------------------------
#  Изображения: скачивание в фоне, текстура — строго в главном потоке
# --------------------------------------------------------------------------
def _tex_from_pil(pil):
    img = pil.convert("RGBA")
    tex = Texture.create(size=img.size, colorfmt="rgba")
    tex.blit_buffer(bytes(img.tobytes()), colorfmt="rgba", bufferfmt="ubyte")
    return tex


class NetImage(KivyImage):
    """Kivy-изображение, грузящееся из URL (без утечек, без StateWriteError)."""
    url = StringProperty("")

    def on_url(self, *a):
        if self.url:
            self._load_url(self.url)

    def _load_url(self, url):
        def work():
            try:
                r = requests.get(url, timeout=25)
                if r.status_code >= 400:
                    return
                pil = Image.open(io.BytesIO(r.content))
                pil.load()
                Clock.schedule_once(lambda dt, p=pil: self._apply(p))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _apply(self, pil):
        try:
            self.texture = _tex_from_pil(pil)
        except Exception:
            pass


# --------------------------------------------------------------------------
#  MJPEG-стример  (декод в потоке, текстура на главном потоке)
# --------------------------------------------------------------------------
class StreamViewer:
    def __init__(self, base, cam_id, image_widget):
        self.base = base
        self.cam_id = cam_id
        self.image = image_widget
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def is_alive(self):
        return self._thread.is_alive()

    def _loop(self):
        while not self._stop.is_set():
            try:
                r = requests.get(self.base + f"/api/cameras/{self.cam_id}/stream",
                                 timeout=5, stream=True)
                buf = b""
                for chunk in r.iter_content(chunk_size=16384):
                    if self._stop.is_set():
                        return
                    buf += chunk
                    a = buf.find(b"\xff\xd8")
                    b = buf.find(b"\xff\xd9")
                    while a != -1 and b != -1:
                        jpg = buf[a:b + 2]
                        buf = buf[b + 2:]
                        try:
                            pil = Image.open(io.BytesIO(jpg))
                            pil.load()
                        except Exception:
                            pass
                        else:
                            Clock.schedule_once(lambda dt, p=pil: self._show(p))
                        a = buf.find(b"\xff\xd8")
                        b = buf.find(b"\xff\xd9")
            except Exception:
                pass
            if not self._stop.is_set():
                time.sleep(0.05)

    def _show(self, pil):
        if self._stop.is_set():
            return
        try:
            self.image.texture = _tex_from_pil(pil)
        except Exception:
            pass


# --------------------------------------------------------------------------
#  Модальные окна
# --------------------------------------------------------------------------
class _Field(BoxLayout):
    def __init__(self, label, value="", hint="", **kw):
        super().__init__(**kw)
        self.label = label
        self.orientation = "vertical"
        self.size_hint_y = None
        self.height = "56dp" if not hint else "70dp"
        self.spacing = "2dp"
        self.add_widget(Label(text=label, color=MUT, halign="left", valign="middle",
                              font_size="12sp", size_hint_y=None, height="18dp"))
        inp = TextInput(text=value, hint_text=hint, multiline=("Примечания" in label),
                        font_size="14sp", size_hint_y=None, height="36dp" if not hint else "48dp")
        inp.bind(minimum_height=inp.setter("height"))
        self.input = inp
        self.add_widget(inp)


# --------------------------------------------------------------------------
#  Экранные классы
# --------------------------------------------------------------------------
class CamerasScreen(BoxLayout):
    pass


class PeopleScreen(BoxLayout):
    pass


class JournalScreen(BoxLayout):
    pass


class ReportsScreen(BoxLayout):
    pass


class MainWindow(BoxLayout):
    pass


# --------------------------------------------------------------------------
#  KV
# --------------------------------------------------------------------------
KV = """
<MainWindow>:
    orientation: 'vertical'

    BoxLayout:
        size_hint_y: None
        height: dp(38)
        padding: dp(10), 0
        spacing: dp(8)
        canvas.before:
            Color:
                rgba: 0.11, 0.13, 0.17, 1
            Rectangle:
                pos: self.pos
                size: self.size
        Label:
            text: 'PeopleRecognition'
            font_size: '15sp'
            bold: True
            color: 1, 1, 1, 1
        Label:
            id: server_label
            text: 'сервер не подключён'
            font_size: '10sp'
            color: 0.7, 0.7, 0.7, 1

    BoxLayout:
        size_hint_y: None
        height: dp(40)
        padding: dp(8), 0
        spacing: dp(8)
        TextInput:
            id: server_input
            text: 'http://127.0.0.1:8000'
            multiline: False
            font_size: '13sp'
        Button:
            text: 'Подключить'
            size_hint_x: None
            width: dp(112)
            on_release: app.do_connect()

    TabbedPanel:
        id: tabs
        do_default_tab: False
        tab_pos: 'top_mid'

        TabbedPanelItem:
            text: 'Камеры'
            CamerasScreen:
                id: cam_screen
                app: app

        TabbedPanelItem:
            text: 'Люди'
            PeopleScreen:
                id: people_screen
                app: app

        TabbedPanelItem:
            text: 'Журнал'
            JournalScreen:
                id: journal_screen
                app: app

        TabbedPanelItem:
            text: 'Отчёты'
            ReportsScreen:
                id: reports_screen
                app: app
"""

SCREENS_KV = """
<CamerasScreen>:
    orientation: 'vertical'
    BoxLayout:
        size_hint_y: None
        height: dp(44)
        padding: dp(4), 0
        spacing: dp(4)
        Button:
            text: 'Обновить'
            on_release: app.load_cameras()
        Button:
            text: 'Добавить'
            on_release: app.camera_add_popup()
        Button:
            text: 'Вкл/Выкл'
            on_release: app.camera_toggle_selected()
        Button:
            text: 'Звук'
            on_release: app.camera_audio_selected()
        Button:
            text: 'Настр.'
            on_release: app.camera_settings_selected()
        Button:
            text: 'Удалить'
            on_release: app.camera_delete_selected()
    BoxLayout:
        size_hint_y: None
        height: dp(42)
        padding: dp(4), 0
        spacing: dp(4)
        Button:
            text: '▶ Смотреть'
            on_release: app.camera_watch_selected()
        Label:
            id: cam_selected_label
            text: 'не выбрана'
            color: MUT
            font_size: '12sp'
            halign: 'left'
    ScrollView:
        id: cam_list_scroll
        GridLayout:
            id: cam_list
            cols: 1
            size_hint_y: None
            height: self.minimum_height
            spacing: '4dp'
    Label:
        id: cam_status
        text: ''
        color: MUT
        font_size: '12sp'
        size_hint_y: None
        height: '22dp'

<PeopleScreen>:
    orientation: 'vertical'
    BoxLayout:
        size_hint_y: None
        height: dp(42)
        padding: dp(4), 0
        spacing: dp(4)
        TextInput:
            id: people_search
            hint_text: 'Поиск по ФИО/должности'
            multiline: False
            font_size: '13sp'
            on_text_validate: app.load_people(self.text)
        Spinner:
            id: people_status
            text: 'all'
            values: ['all', 'confirmed', 'pending']
            size_hint_x: None
            width: dp(120)
            font_size: '12sp'
            on_text: app.load_people(root.ids.people_search.text)
    BoxLayout:
        size_hint_y: None
        height: dp(42)
        padding: dp(4), 0
        spacing: dp(4)
        Button:
            text: 'Обновить'
            on_release: app.load_people(root.ids.people_search.text)
        Button:
            text: 'Создать'
            on_release: app.person_create_popup()
        Button:
            text: 'Редактировать'
            on_release: app.person_edit_selected()
        Button:
            text: 'Удалить'
            on_release: app.person_delete_selected()
        Button:
            text: 'Открыть'
            on_release: app.person_open_selected()
    ScrollView:
        GridLayout:
            id: people_list
            cols: 1
            size_hint_y: None
            height: self.minimum_height
            spacing: '4dp'
    Label:
        id: people_status_label
        text: ''
        color: MUT
        font_size: '12sp'
        size_hint_y: None
        height: '22dp'

<JournalScreen>:
    orientation: 'vertical'
    BoxLayout:
        size_hint_y: None
        height: dp(40)
        padding: dp(4), 0
        spacing: dp(4)
        Label:
            text: 'С:'
            size_hint_x: None
            width: dp(22)
        TextInput:
            id: j_from
            hint_text: 'ГГГГ-ММ-ДД'
            multiline: False
            font_size: '12sp'
        Label:
            text: 'по:'
            size_hint_x: None
            width: dp(26)
        TextInput:
            id: j_to
            hint_text: 'ГГГГ-ММ-ДД'
            multiline: False
            font_size: '12sp'
    BoxLayout:
        size_hint_y: None
        height: dp(40)
        padding: dp(4), 0
        spacing: dp(4)
        Spinner:
            id: j_cam
            text: 'все камеры'
            font_size: '12sp'
        CheckBox:
            id: j_new
        Label:
            text: 'только неопознанные'
            color: MUT
            font_size: '12sp'
    BoxLayout:
        size_hint_y: None
        height: dp(42)
        padding: dp(4), 0
        spacing: dp(4)
        Button:
            text: 'Обновить'
            on_release: app.load_events()
        Button:
            text: 'Кадр'
            on_release: app.event_show_shot()
        Button:
            text: 'Удалить'
            on_release: app.event_delete_selected()
        Button:
            text: 'Неопозн.'
            on_release: app.event_delete_unknowns()
        Button:
            text: 'XLSX'
            on_release: app.event_export_journal()
    ScrollView:
        GridLayout:
            id: event_list
            cols: 1
            size_hint_y: None
            height: self.minimum_height
            spacing: '4dp'
    Label:
        id: event_status
        text: ''
        color: MUT
        font_size: '12sp'
        size_hint_y: None
        height: '22dp'

<ReportsScreen>:
    orientation: 'vertical'
    BoxLayout:
        size_hint_y: None
        height: dp(40)
        padding: dp(4), 0
        spacing: dp(4)
        Label:
            text: 'С:'
            size_hint_x: None
            width: dp(22)
        TextInput:
            id: r_from
            hint_text: 'ГГГГ-ММ-ДД'
            multiline: False
            font_size: '12sp'
        Label:
            text: 'по:'
            size_hint_x: None
            width: dp(26)
        TextInput:
            id: r_to
            hint_text: 'ГГГГ-ММ-ДД'
            multiline: False
            font_size: '12sp'
    BoxLayout:
        size_hint_y: None
        height: dp(40)
        padding: dp(4), 0
        spacing: dp(4)
        Spinner:
            id: rep_type
            text: 'Сводка'
            values: ['Сводка', 'Посещаемость', 'Таймлайн', 'По дням', 'Неопознанные']
            font_size: '12sp'
            on_text: app.render_reports()
        Button:
            text: 'Обновить'
            on_release: app.load_reports()
        Button:
            text: 'XLSX'
            on_release: app.report_export()
    ScrollView:
        id: rep_scroll
        BoxLayout:
            id: rep_list
            orientation: 'vertical'
            size_hint_y: None
            height: self.minimum_height
            padding: '4dp', '4dp'
"""

Builder.load_string(KV)
Builder.load_string(SCREENS_KV)


# --------------------------------------------------------------------------
#  Приложение
# --------------------------------------------------------------------------
class RemoteClientApp(App):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.server_url = None
        self.api = None
        self.cameras = []
        self.people = []
        self.events = []
        self.selected_cam = None
        self.selected_person = None
        self.selected_event = None
        self._imgcache = {}
        self._person_popup = None
        self._stream_view = None
        self._stream = None
        self._last_report = None
        self._pending_photo_pid = None

    # ---------------------------------------------------------- helpers

    def run_ui(self, fn, *a, **k):
        Clock.schedule_once(lambda dt: fn(*a, **k), 0)

    def bg(self, fn, on_ok=None, on_err=None):
        def work():
            try:
                res = fn()
            except Exception as e:
                if on_err:
                    self.run_ui(on_err, str(e))
                return
            if on_ok:
                self.run_ui(on_ok, res)
        threading.Thread(target=work, daemon=True).start()

    def status(self, msg):
        try:
            self.root.ids.server_label.text = msg
        except Exception:
            pass

    def toast(self, msg):
        popup = Popup(title="Сообщение", content=Label(text=msg, color=TEXT),
                      size_hint=(0.85, 0.28))
        popup.bind(on_open=lambda p: Clock.schedule_once(lambda dt: p.dismiss(), 1.6))
        popup.open()

    def _cam_name(self, cid):
        for c in self.cameras:
            if c["id"] == cid:
                return c["name"]
        return cid or "—"

    # ---------------------------------------------------------- connect

    def do_connect(self, *a):
        try:
            url = normalize_server(self.root.ids.server_input.text, 8000)
        except Exception:
            url = SERVER_DEFAULT
        self.server_url = url
        self.api = Api(url)
        self.root.ids.server_label.text = url
        self.status("Подключение…")
        self.bg(lambda: self.api.cameras(),
                on_ok=lambda c: self._connected(),
                on_err=self._connect_error)

    def _connected(self):
        self.status(f"Сервер: {self.server_url}")
        self.load_cameras()
        self.load_people()
        self.load_events()
        self.load_reports()

    def _connect_error(self, msg):
        self.status(f"Ошибка: {msg}")
        self.toast(f"Не удалось подключиться:\n{msg}")

    # ======================================================== КАМЕРЫ

    def load_cameras(self, *a):
        if not self.api:
            return
        def ok(data):
            self.cameras = data
            self._render_cameras()
        self.bg(self.api.cameras, ok)

    def _render_cameras(self):
        if not self.root or "cam_list" not in self.root.ids:
            return
        lst = self.root.ids.cam_list
        lst.clear_widgets()
        for c in self.cameras:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height="58dp",
                            spacing="8dp", padding=("6dp", "2dp"))
            with row.canvas.before:
                Color(rgba=CARD)
                Rectangle(pos=row.pos, size=row.size)
            row.bind(pos=lambda w, v, r=row: self._row_bg(r),
                     size=lambda w, v, r=row: self._row_bg(r))
            st = self._cam_status_text(c)
            row.add_widget(Label(text=st, size_hint_x=None, width="110dp",
                                 font_size="13sp"))
            col = BoxLayout(orientation="vertical", spacing="1dp")
            col.add_widget(Label(text=c["name"], color=TEXT, font_size="14sp",
                                 halign="left", valign="middle"))
            act = c.get("activity") or {}
            sub = f"src: {c['source']}"
            if c.get("audio_enabled"):
                sub += "  🔊"
            if act.get("motion"):
                sub += "  движ."
            col.add_widget(Label(text=sub, color=MUT, font_size="11sp",
                                 halign="left", valign="middle"))
            row.add_widget(col)
            btn = Button(text="…", size_hint_x=None, width="44dp", font_size="16sp",
                         on_release=lambda b, cid=c["id"], c=c: self._select_cam(cid, c))
            row.add_widget(btn)
            lst.add_widget(row)
        self.root.ids.cam_selected_label.text = self._sel_cam_text()
        self.root.ids.cam_status.text = f"Камер: {len(self.cameras)}"

    def _row_bg(self, row):
        row.canvas.before.clear()
        with row.canvas.before:
            Color(rgba=CARD)
            Rectangle(pos=row.pos, size=row.size)

    @staticmethod
    def _cam_status_text(c):
        if c.get("running"):
            return "🟢 в работе"
        if c.get("error"):
            return "🟡 ошибка"
        if not c.get("enabled"):
            return "🔴 выкл"
        return "⚪ запуск"

    def _select_cam(self, cid, c=None):
        self.selected_cam = c or self._find_cam(cid)
        self.root.ids.cam_selected_label.text = self._sel_cam_text()

    def _find_cam(self, cid):
        for c in self.cameras:
            if c["id"] == cid:
                return c
        return None

    def _sel_cam_text(self):
        if not self.selected_cam:
            return "не выбрана"
        return f"{self.selected_cam['name']}"

    def _require_cam(self):
        if not self.selected_cam:
            self.toast("Выберите камеру")
            return None
        return self.selected_cam

    def camera_toggle_selected(self):
        c = self._require_cam()
        if not c:
            return
        new = not c.get("enabled")
        self.bg(lambda: self.api.patch_camera(c["id"], enabled=new),
                on_ok=lambda _: self.load_cameras(),
                on_err=self.toast)

    def camera_audio_selected(self):
        c = self._require_cam()
        if not c:
            return
        new = not c.get("audio_enabled")
        self.bg(lambda: self.api.patch_camera(c["id"], audio_enabled=new),
                on_ok=lambda _: self.load_cameras(),
                on_err=self.toast)

    def camera_delete_selected(self):
        c = self._require_cam()
        if not c:
            return
        self._confirm(f"Удалить камеру «{c['name']}»?",
                      lambda: (self.bg(lambda: self.api.delete_camera(c["id"]),
                                       on_ok=lambda _: (self.load_cameras(),
                                                        setattr(self, "selected_cam", None))),
                               ))

    def camera_add_popup(self):
        frm = BoxLayout(orientation="vertical", spacing="6dp", padding="10dp")
        f = {}
        f["name"] = _Field("Имя камеры", value="Камера")
        f["src"] = _Field("Источник (USB-номер или RTSP)", value="0")
        f["aud"] = _Field("Аудио-источник (необязательно)")
        for k in ("name", "src", "aud"):
            frm.add_widget(f[k])
        btn = Button(text="Добавить")
        frm.add_widget(btn)
        popup = Popup(title="Добавить камеру", content=frm, size_hint=(0.92, 0.55))
        btn.bind(on_release=lambda b: self._camera_add_ok(popup, f))
        popup.open()

    def _camera_add_ok(self, popup, f):
        data = {
            "name": f["name"].input.text.strip() or "Камера",
            "source": f["src"].input.text.strip() or "0",
            "audio_source": f["aud"].input.text.strip() or None,
            "audio_enabled": False,
        }
        popup.dismiss()
        self.bg(lambda: self.api.add_camera(data),
                on_ok=lambda _: self.load_cameras(),
                on_err=self.toast)

    def camera_settings_selected(self):
        c = self._require_cam()
        if not c:
            return
        frm = BoxLayout(orientation="vertical", spacing="6dp", padding="10dp")
        f = {}
        f["pi"] = _Field("Интервал без движения (0.01–10 с)",
                         value=str(c.get("process_interval", 1.0)))
        f["mi"] = _Field("Интервал при движении (0.01–5 с)",
                         value=str(c.get("motion_interval", 0.3)))
        frm.add_widget(f["pi"])
        frm.add_widget(f["mi"])
        btn = Button(text="Сохранить")
        frm.add_widget(btn)
        popup = Popup(title=f"Настройки: {c['name']}", content=frm, size_hint=(0.92, 0.5))
        btn.bind(on_release=lambda b: self._camera_settings_ok(popup, c["id"], f))
        popup.open()

    def _camera_settings_ok(self, popup, cid, f):
        try:
            data = {"process_interval": float(f["pi"].input.text),
                    "motion_interval": float(f["mi"].input.text)}
        except ValueError:
            self.toast("Введите числа")
            return
        popup.dismiss()
        self.bg(lambda: self.api.patch_camera(cid, **data),
                on_ok=lambda _: self.load_cameras(),
                on_err=self.toast)

    def camera_watch_selected(self):
        c = self._require_cam()
        if not c:
            return
        if self._stream and self._stream.is_alive():
            self._stream.stop()
            self._stream = None
            if self._stream_view:
                self._stream_view.dismiss()
                self._stream_view = None
            return
        img = NetImage()
        content = BoxLayout(orientation="vertical", spacing="6dp", padding="8dp")
        header = Label(text=f"Трансляция: {c['name']}", color=TEXT, font_size="13sp",
                       size_hint_y=None, height="28dp")
        content.add_widget(header)
        content.add_widget(img)
        stop = Button(text="■ Остановить", size_hint_y=None, height="44dp")
        content.add_widget(stop)
        view = ModalView(size_hint=(1, 0.92), background_color=DARK)
        view.add_widget(content)
        self._stream_view = view
        stop.bind(on_release=lambda b: view.dismiss())
        view.bind(on_dismiss=lambda v: self._stop_stream())
        view.open()
        self._stream = StreamViewer(self.api.base, c["id"], img)
        self._stream.start()

    def _stop_stream(self):
        if self._stream:
            self._stream.stop()
            self._stream = None
        self._stream_view = None

    # ======================================================== ЛЮДИ

    def load_people(self, query="", *a):
        if not self.api:
            return
        def ok(data):
            self.people = data
            self._render_people(query)
        params = {}
        try:
            if self.root:
                st = self.root.ids.people_status.text
                if st != "all":
                    params["status"] = st
                q = (query or self.root.ids.people_search.text).strip()
                if q:
                    params["q"] = q
        except Exception:
            pass
        self.bg(lambda: self.api.people(**params), ok)

    def _render_people(self, query=""):
        if not self.root or "people_list" not in self.root.ids:
            return
        lst = self.root.ids.people_list
        lst.clear_widgets()
        for p in self.people:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height="58dp",
                            spacing="8dp", padding=("6dp", "2dp"))
            with row.canvas.before:
                Color(rgba=CARD)
                Rectangle(pos=row.pos, size=row.size)
            row.bind(pos=lambda w, v, r=row: self._row_bg(r),
                     size=lambda w, v, r=row: self._row_bg(r))
            st = "заполнена" if p.get("status") == "confirmed" else "неопознан"
            name = p.get("full_name") or "неопознанный"
            row.add_widget(Label(text=st, size_hint_x=None, width="90dp",
                                 font_size="12sp", color=MUT))
            col = BoxLayout(orientation="vertical", spacing="1dp")
            col.add_widget(Label(text=name, color=TEXT, font_size="14sp",
                                 halign="left", valign="middle"))
            sub = " ".join(x for x in (p.get("position"), p.get("department")) if x)
            sub += f"  фото:{p.get('photo_count', 0)}  идент:{p.get('ident_count', 0)}"
            if p.get("last_seen"):
                sub += f"\n{p['last_seen'][:16]}"
            col.add_widget(Label(text=sub, color=MUT, font_size="11sp",
                                 halign="left", valign="middle"))
            row.add_widget(col)
            btn = Button(text="…", size_hint_x=None, width="44dp", font_size="16sp",
                         on_release=lambda b, pid=p["id"]: self._select_person(pid))
            row.add_widget(btn)
            lst.add_widget(row)
        self.root.ids.people_status_label.text = f"Людей: {len(self.people)}"

    def _select_person(self, pid):
        for p in self.people:
            if p["id"] == pid:
                self.selected_person = p
                return

    def _selected_person(self):
        if not self.selected_person:
            self.toast("Выберите человека")
        return self.selected_person

    def _person_form_data(self, popup, person=None):
        frm = popup.content
        fields = {}
        for child in frm.children:
            if isinstance(child, _Field):
                fields[child.label] = child.input.text
        status = "confirmed"
        try:
            status = frm.status_spinner.text
        except Exception:
            status = "confirmed"
        data = {
            "full_name": fields.get("ФИО", "").strip(),
            "position": fields.get("Должность", "").strip(),
            "department": fields.get("Отдел", "").strip(),
            "notes": fields.get("Примечания", "").strip(),
            "status": status,
        }
        return data

    def person_create_popup(self):
        frm = BoxLayout(orientation="vertical", spacing="4dp", padding="10dp")
        frm.add_widget(_Field("ФИО", hint="Фамилия Имя Отчество"))
        frm.add_widget(_Field("Должность", hint="должность/роль"))
        frm.add_widget(_Field("Отдел", hint="отдел/группа"))
        frm.add_widget(_Field("Примечания", hint="примечания"))
        sp = Spinner(text="confirmed", values=["confirmed", "pending"], font_size="12sp")
        sp.size_hint_y = None
        sp.height = "40dp"
        frm.status_spinner = sp
        frm.add_widget(sp)
        btn = Button(text="Создать")
        frm.add_widget(btn)
        popup = Popup(title="Новая карточка", content=frm, size_hint=(0.92, 0.75))
        btn.bind(on_release=lambda b: self._person_create_ok(popup))
        popup.open()

    def _person_create_ok(self, popup):
        data = self._person_form_data(popup)
        popup.dismiss()
        self.bg(lambda: self.api.create_person(data),
                on_ok=lambda _: self.load_people(),
                on_err=self.toast)

    def person_edit_selected(self):
        p = self._selected_person()
        if not p:
            return
        self.bg(lambda: self.api.person(p["id"]),
                on_ok=lambda full: self._person_edit_popup(full),
                on_err=self.toast)

    def _person_edit_popup(self, person):
        frm = BoxLayout(orientation="vertical", spacing="4dp", padding="10dp")
        frm.add_widget(_Field("ФИО", value=person.get("full_name", "")))
        frm.add_widget(_Field("Должность", value=person.get("position", "")))
        frm.add_widget(_Field("Отдел", value=person.get("department", "")))
        frm.add_widget(_Field("Примечания", value=person.get("notes", "")))
        sp = Spinner(text=person.get("status", "confirmed"),
                     values=["confirmed", "pending"], font_size="12sp")
        sp.size_hint_y = None
        sp.height = "40dp"
        frm.status_spinner = sp
        frm.add_widget(sp)
        btn = Button(text="Сохранить")
        frm.add_widget(btn)
        popup = Popup(title=f"Карточка №{person['id']}", content=frm, size_hint=(0.92, 0.78))
        btn.bind(on_release=lambda b: self._person_update_ok(popup, person["id"]))
        popup.open()

    def _person_update_ok(self, popup, pid):
        data = self._person_form_data(popup)
        popup.dismiss()
        self.bg(lambda: self.api.update_person(pid, data),
                on_ok=lambda _: (self.load_people(),
                                 self.toast("Сохранено")),
                on_err=self.toast)

    def person_delete_selected(self):
        p = self._selected_person()
        if not p:
            return
        self._confirm(f"Удалить карточку «{p.get('full_name')}»?",
                      lambda: self.bg(lambda: self.api.delete_person(p["id"]),
                                      on_ok=lambda _: (self.load_people(),
                                                       setattr(self, "selected_person", None)),
                                      on_err=self.toast))

    def person_open_selected(self):
        p = self._selected_person()
        if not p:
            return
        self.person_card(p["id"])

    def person_card(self, pid):
        frm = BoxLayout(orientation="vertical", spacing="4dp", padding="8dp")
        frm.add_widget(Label(text="Загрузка…", color=MUT))
        popup = Popup(title=f"Карточка №{pid}", content=frm,
                      size_hint=(0.96, 0.96))
        popup.open()
        self.bg(lambda: self.api.person(pid),
                on_ok=lambda person: self._render_person_card(popup, person),
                on_err=lambda m: (popup.dismiss(), self.toast(m)))

    def _render_person_card(self, popup, person):
        scroll = ScrollView()
        body = BoxLayout(orientation="vertical", spacing="6dp", padding="6dp",
                         size_hint_y=None)
        body.bind(minimum_height=body.setter("height"))
        scroll.add_widget(body)

        info = f"ФИО: {person.get('full_name') or '—'}\n" \
               f"Должность: {person.get('position') or '—'}\n" \
               f"Отдел: {person.get('department') or '—'}\n" \
               f"Статус: {'заполнена' if person.get('status') == 'confirmed' else 'неопознан'}\n" \
               f"Создан: {person.get('created_at', '—')}\n" \
               f"Примечания: {person.get('notes') or '—'}"
        info_l = Label(text=info, color=TEXT, halign="left", valign="top", font_size="13sp",
                       size_hint_y=None)
        info_l.bind(texture_size=info_l.setter("size"))
        body.add_widget(info_l)

        toolbar = BoxLayout(orientation="horizontal", spacing="4dp", size_hint_y=None, height="42dp")
        b_edit = Button(text="Редактировать")
        b_photo = Button(text="Фото")
        b_dups = Button(text="Дубли")
        b_ndups = Button(text="ФИО")
        toolbar.add_widget(b_edit)
        toolbar.add_widget(b_photo)
        toolbar.add_widget(b_dups)
        toolbar.add_widget(b_ndups)
        body.add_widget(toolbar)
        pid = person["id"]
        b_edit.bind(on_release=lambda b: self._person_edit_popup(person))
        b_photo.bind(on_release=lambda b: self._upload_photo(pid))
        b_dups.bind(on_release=lambda b: self._load_duplicates(pid))
        b_ndups.bind(on_release=lambda b: self._load_ndups(pid, person.get("full_name", "")))

        photos_title = Label(text="Фотографии", color=ACCENT, font_size="13sp",
                             size_hint_y=None, height="24dp")
        body.add_widget(photos_title)
        photos = person.get("photos", [])
        if photos:
            grid = BoxLayout(orientation="vertical", spacing="4dp", size_hint_y=None)
            for ph in photos:
                rw = BoxLayout(orientation="horizontal", spacing="4dp", size_hint_y=None,
                               height="120dp")
                url = self.api.base + ph.get("url", "")
                img = NetImage(fit_mode="contain", size_hint_x=None, width="150dp")
                img.url = url
                rw.add_widget(img)
                fid = ph.get("id")
                rw.add_widget(Button(text="✕ Удалить", size_hint_x=None, width="100dp",
                                     on_release=lambda b, fid=fid: self._delete_photo(pid, fid)))
                grid.add_widget(rw)
            body.add_widget(grid)
        else:
            body.add_widget(Label(text="Фото нет", color=MUT, size_hint_y=None, height="24dp"))

        ev_title = Label(text="События", color=ACCENT, font_size="13sp", size_hint_y=None, height="24dp")
        body.add_widget(ev_title)
        evs = person.get("events", [])
        if evs:
            for e in evs[:60]:
                tp = "неопознанный" if e.get("is_new") else "идентификация"
                conf = int(round((e.get("confidence") or 0) * 100))
                line = f"{e['event_time'][:16]}  [{self._cam_name(e.get('camera_id'))}] {tp} {conf}%"
                body.add_widget(Label(text=line, color=TEXT, font_size="12sp",
                                      halign="left", size_hint_y=None, height="24dp"))
        else:
            body.add_widget(Label(text="Событий нет", color=MUT, size_hint_y=None, height="24dp"))

        dup_box = BoxLayout(orientation="vertical", spacing="4dp", size_hint_y=None)
        body.add_widget(Label(text="Дубли", color=ACCENT, font_size="13sp", size_hint_y=None, height="24dp"))
        body.add_widget(dup_box)
        self.bg(lambda: self.api.duplicates(pid),
                on_ok=lambda d: self._render_dups(dup_box, pid, d, "по лицу"))
        self.bg(lambda: self.api.name_duplicates(person.get("full_name", "")),
                on_ok=lambda d: self._render_dups(dup_box, pid, d, "по ФИО"))

        close = Button(text="Закрыть", size_hint_y=None, height="44dp")
        body.add_widget(close)
        close.bind(on_release=lambda b: popup.dismiss())

        popup.content = scroll

    def _render_dups(self, box, pid, dups, kind):
        if not dups:
            box.add_widget(Label(text=f"Совпадений {kind} нет", color=MUT,
                                 size_hint_y=None, height="22dp", font_size="12sp"))
            return
        box.add_widget(Label(text=f"Совпадения {kind}:", color=YELLOW,
                             size_hint_y=None, height="22dp", font_size="12sp"))
        for d in dups:
            rw = BoxLayout(orientation="horizontal", size_hint_y=None, height="40dp", spacing="4dp")
            lab = f"{d.get('name') or d.get('id')}"
            if "sim" in d:
                lab += f" — {int(d['sim'] * 100)}%"
            rw.add_widget(Label(text=lab, color=TEXT, font_size="12sp"))
            sid = d["id"]
            rw.add_widget(Button(text="Объединить", size_hint_x=None, width="110dp",
                                 on_release=lambda b, s=sid: self._merge_confirm(pid, s)))
            box.add_widget(rw)

    def _merge_confirm(self, target, source):
        self._confirm(f"Объединить карточку №{source} в №{target}?",
                      lambda: self.bg(lambda: self.api.merge(target, source),
                                      on_ok=lambda _: (self.load_people(), self.toast("Объединено")),
                                      on_err=self.toast))

    def _load_duplicates(self, pid):
        def ok(d):
            popup = Popup(title="Дубли по лицу",
                          content=Label(text=self._dups_text(d, "по лицу") or "Совпадений нет",
                                        color=TEXT, font_size="13sp"),
                          size_hint=(0.9, 0.6))
            popup.open()
        self.bg(lambda: self.api.duplicates(pid), ok, on_err=self.toast)

    def _load_ndups(self, pid, name):
        def ok(d):
            popup = Popup(title="Совпадения по ФИО",
                          content=Label(text=self._dups_text(d, "по ФИО") or "Совпадений нет",
                                        color=TEXT, font_size="13sp"),
                          size_hint=(0.9, 0.6))
            popup.open()
        self.bg(lambda: self.api.name_duplicates(name), ok, on_err=self.toast)

    @staticmethod
    def _dups_text(dups, kind):
        if not dups:
            return None
        lines = [f"Совпадения {kind}:"]
        for d in dups:
            sim = f" — {int(d['sim'] * 100)}%" if "sim" in d else ""
            lines.append(f"#{d['id']} {d.get('name')}{sim}")
        return "\n".join(lines)

    def _upload_photo(self, pid):
        self._start_file_chooser(pid)

    def _start_file_chooser(self, pid):
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("image/*")
            intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, False)
            PythonActivity.mActivity.startActivityForResult(intent, 42)
            self._pending_photo_pid = pid
        except Exception as e:
            self.toast(f"Выбор файла недоступен: {e}")

    def on_activity_result(self, requestCode, resultCode, data):
        if requestCode == 42 and self._pending_photo_pid is not None:
            pid = self._pending_photo_pid
            self._pending_photo_pid = None
            try:
                from jnius import autoclass
                RESULT_OK = autoclass("android.app.Activity").RESULT_OK
                if resultCode == RESULT_OK and data is not None:
                    uri = data.getData()
                    if uri is not None:
                        uri_str = uri.toString()
                        filename = "photo.jpg"
                        self.bg(lambda: self.api.upload_photo(pid, uri_str, filename),
                                on_ok=lambda _: (self.load_people(), self.toast("Фото загружено")),
                                on_err=self.toast)
            except Exception as e:
                self.toast(f"Не удалось выбрать файл: {e}")

    def _photo_chosen(self, pid, selection):
        if not selection:
            return
        path = selection[0] if isinstance(selection, (list, tuple)) else selection
        fname = os.path.basename(path) if isinstance(path, str) else "photo.jpg"
        if isinstance(path, str) and path.startswith("content://"):
            self.bg(lambda: self.api.upload_photo(pid, path, fname),
                    on_ok=lambda _: (self.load_people(), self.toast("Фото загружено")),
                    on_err=self.toast)
        else:
            self.bg(lambda: self.api.upload_photo(pid, path),
                    on_ok=lambda _: (self.load_people(), self.toast("Фото загружено")),
                    on_err=self.toast)

    def _delete_photo(self, pid, fid):
        self._confirm("Удалить снимок и его эмбеддинг?",
                      lambda: self.bg(lambda: self.api.delete_photo(pid, fid),
                                      on_ok=lambda _: (self.load_people(), self.toast("Удалено")),
                                      on_err=self.toast))

    # ======================================================== ЖУРНАЛ

    def _journal_params(self):
        p = {}
        if not self.root:
            return p
        ids = self.root.ids
        if ids.j_from.text.strip():
            p["date_from"] = ids.j_from.text.strip()
        if ids.j_to.text.strip():
            p["date_to"] = ids.j_to.text.strip()
        if ids.j_new.active:
            p["is_new"] = 1
        cam = ids.j_cam.text
        if cam and cam != "все камеры":
            p["camera_id"] = cam
        return p

    def load_events(self, *a):
        if not self.api:
            return
        self._update_cam_spinner()
        params = dict(self._journal_params(), limit=500)
        self.bg(lambda: self.api.events(**params), self._render_events)

    def _update_cam_spinner(self):
        if not self.root or "j_cam" not in self.root.ids:
            return
        vals = ["все камеры"] + [c["id"] for c in self.cameras]
        self.root.ids.j_cam.values = vals

    def _render_events(self, events):
        if not self.root or "event_list" not in self.root.ids:
            return
        self.events = events
        lst = self.root.ids.event_list
        lst.clear_widgets()
        for e in events:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height="52dp",
                            spacing="6dp", padding=("6dp", "1dp"))
            with row.canvas.before:
                Color(rgba=CARD)
                Rectangle(pos=row.pos, size=row.size)
            row.bind(pos=lambda w, v, r=row: self._row_bg(r),
                     size=lambda w, v, r=row: self._row_bg(r))
            tp = "новый" if e.get("is_new") else "идент."
            conf = int(round((e.get("confidence") or 0) * 100))
            col = BoxLayout(orientation="vertical", spacing="1dp")
            col.add_widget(Label(text=f"{e['event_time'][:16]}  {e.get('full_name') or 'неопознанный'}",
                                 color=TEXT, font_size="13sp", halign="left", valign="middle"))
            col.add_widget(Label(text=f"[{self._cam_name(e.get('camera_id'))}] {tp} {conf}%  "
                                      f"{(e.get('position') or '')} {(e.get('department') or '')}",
                                 color=MUT, font_size="11sp", halign="left", valign="middle"))
            row.add_widget(col)
            row.add_widget(Button(text="…", size_hint_x=None, width="44dp", font_size="16sp",
                                  on_release=lambda b, eid=e["id"]: self._select_event(eid)))
            lst.add_widget(row)
        self.root.ids.event_status.text = f"Событий: {len(events)}"

    def _select_event(self, eid):
        for e in self.events:
            if e["id"] == eid:
                self.selected_event = e
                return

    def _selected_event(self):
        if not self.selected_event:
            self.toast("Выберите событие")
        return self.selected_event

    def event_show_shot(self):
        e = self._selected_event()
        if not e:
            return
        url = e.get("photo_url")
        if not url:
            self.toast("Кадра нет")
            return
        img = NetImage(fit_mode="contain")
        img.url = self.api.base + url
        content = BoxLayout(orientation="vertical", spacing="6dp", padding="8dp")
        content.add_widget(Label(text=e["event_time"][:16], color=TEXT, size_hint_y=None, height="26dp"))
        content.add_widget(img)
        close = Button(text="Закрыть", size_hint_y=None, height="42dp")
        content.add_widget(close)
        view = ModalView(size_hint=(1, 0.95), background_color=DARK)
        view.add_widget(content)
        close.bind(on_release=lambda b: view.dismiss())
        view.open()

    def event_delete_selected(self):
        e = self._selected_event()
        if not e:
            return
        self._confirm(f"Удалить событие №{e['id']}?",
                      lambda: self.bg(lambda: self.api.delete_event(e["id"]),
                                      on_ok=lambda _: (self.load_events(),
                                                       setattr(self, "selected_event", None)),
                                      on_err=self.toast))

    def event_delete_unknowns(self):
        self._confirm("Удалить все неопознанные события за период?",
                      lambda: self.bg(lambda: self.api.delete_unknowns(**self._journal_params()),
                                      on_ok=lambda r: (self.load_events(),
                                                       self.toast(f"Удалено: {r.get('deleted', 0)}")),
                                      on_err=self.toast))

    def event_export_journal(self):
        self._export_xlsx("/api/reports/journal.xlsx", "journal.xlsx",
                          self._journal_params())

    def report_export(self):
        if not self.root:
            return
        p = self._period()
        t = self.root.ids.rep_type.text
        if t == "Посещаемость":
            self._export_xlsx("/api/reports/attendance.xlsx", "attendance.xlsx", p)
        else:
            self._export_xlsx("/api/reports/journal.xlsx", "journal.xlsx",
                              dict(p, **self._journal_params()))

    def _export_xlsx(self, path, fname, params):
        self.bg(lambda: self.api.xlsx(path, **params),
                on_ok=lambda data: self._save_xlsx(fname, data),
                on_err=self.toast)

    def _save_xlsx(self, fname, data):
        if platform == "android":
            saved = self._save_xlsx_android(fname, data)
            self.toast(saved if isinstance(saved, str) else f"Сохранено: {saved}")
        else:
            import tkinter as tk
            from tkinter import filedialog, messagebox
            root = tk.Tk()
            root.withdraw()
            path = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile=fname)
            if path:
                with open(path, "wb") as f:
                    f.write(data)
                messagebox.showinfo("Экспорт", f"Сохранено:\n{path}")
            root.destroy()

    def _save_xlsx_android(self, fname, data):
        try:
            from jnius import autoclass
            ContentValues = autoclass("android.content.ContentValues")
            MediaStore = autoclass("android.provider.MediaStore")
            ctx = autoclass("org.kivy.android.PythonActivity").mActivity
            resolver = ctx.getContentResolver()
            cv = ContentValues()
            cv.put(MediaStore.Downloads.DISPLAY_NAME, fname)
            cv.put(MediaStore.Downloads.MIME_TYPE,
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            cv.put(MediaStore.Downloads.RELATIVE_PATH, "Download/PeopleRecognition")
            uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv)
            out = resolver.openOutputStream(uri)
            out.write(data)
            out.close()
            return f"Сохранено в Download/{fname}"
        except Exception as e:
            try:
                save_dir = os.path.join(os.path.expanduser("~"), "Download")
                os.makedirs(save_dir, exist_ok=True)
                with open(os.path.join(save_dir, fname), "wb") as f:
                    f.write(data)
                return f"Сохранено: {os.path.join(save_dir, fname)}"
            except Exception:
                return f"Не удалось сохранить файл: {e}"

    # ======================================================== ОТЧЁТЫ

    def _period(self):
        if not self.root:
            return {}
        ids = self.root.ids
        p = {}
        if ids.r_from.text.strip():
            p["date_from"] = ids.r_from.text.strip()
        if ids.r_to.text.strip():
            p["date_to"] = ids.r_to.text.strip()
        return p

    def load_reports(self, *a):
        if not self.api:
            return
        p = self._period()
        self.bg(lambda: self.api.summary(**p), lambda s: self._summary_store(s))
        self.bg(lambda: self.api.attendance(**p), lambda r: self._att_store(r))
        self.bg(lambda: self.api.timeline(**p), lambda r: self._tl_store(r))
        self.bg(lambda: self.api.daily(**p), lambda r: self._daily_store(r))
        self.bg(lambda: self.api.unknowns(**p), lambda r: self._unk_store(r))

    def _summary_store(self, s):
        self._report_data = getattr(self, "_report_data", {})
        self._report_data["summary"] = s
        self._report_data["period"] = self._period()
        self.render_reports()

    def _att_store(self, r):
        self._report_data = getattr(self, "_report_data", {})
        self._report_data["attendance"] = r
        self.render_reports()

    def _tl_store(self, r):
        self._report_data = getattr(self, "_report_data", {})
        self._report_data["timeline"] = r
        self.render_reports()

    def _daily_store(self, r):
        self._report_data = getattr(self, "_report_data", {})
        self._report_data["daily"] = r
        self.render_reports()

    def _unk_store(self, r):
        self._report_data = getattr(self, "_report_data", {})
        self._report_data["unknowns"] = r
        self.render_reports()

    def render_reports(self, *a):
        if not self.root or "rep_list" not in self.root.ids:
            return
        lst = self.root.ids.rep_list
        lst.clear_widgets()
        t = self.root.ids.rep_type.text
        data = getattr(self, "_report_data", {})
        if t == "Сводка":
            self._render_rep_summary(lst, data)
        elif t == "Посещаемость":
            self._render_rep_attendance(lst, data)
        elif t == "Таймлайн":
            self._render_rep_timeline(lst, data)
        elif t == "По дням":
            self._render_rep_daily(lst, data)
        elif t == "Неопознанные":
            self._render_rep_unknowns(lst, data)

    def _add_line(self, lst, text, color=TEXT, size="13sp", bold=False):
        l = Label(text=text, color=color, font_size=size, halign="left",
                  valign="top", bold=bold, size_hint_y=None, padding=(4, 2))
        l.bind(texture_size=l.setter("size"))
        lst.add_widget(l)

    def _render_rep_summary(self, lst, data):
        s = data.get("summary")
        if not s:
            self._add_line(lst, "Загрузка…", MUT)
            return
        p = data.get("period") or {}
        self._add_line(lst, f"Период: {s.get('date_from')} — {s.get('date_to')}", bold=True)
        self._add_line(lst, "")
        self._add_line(lst, f"Карточек всего: {s['total_people']}")
        self._add_line(lst, f"  заполнено: {s['confirmed']}")
        self._add_line(lst, f"  неопознано: {s['pending']}")
        self._add_line(lst, "")
        self._add_line(lst, f"Событий за период: {s['events']}")
        self._add_line(lst, f"Уникальных людей: {s['unique_people']}")
        self._add_line(lst, f"Общее время: {human_dur(s['total_seconds'])}")
        if s.get("by_camera"):
            self._add_line(lst, "")
            self._add_line(lst, "По камерам:", bold=True)
            for r in s["by_camera"]:
                self._add_line(lst, f"  {self._cam_name(r['camera_id'])}: {r['cnt']}")

    def _render_rep_attendance(self, lst, data):
        rows = data.get("attendance") or []
        if not data and not rows:
            self._add_line(lst, "Загрузка…", MUT)
            return
        if not rows:
            self._add_line(lst, "Нет данных")
            return
        for r in rows:
            self._add_line(lst,
                           f"{r.get('name') or '—'}  ({r.get('sessions')} сессий, "
                           f"{human_dur(r.get('seconds'))})\n"
                           f"  {r.get('position') or ''} {r.get('department') or ''}\n"
                           f"  первый: {r.get('first') or '—'}\n  последний: {r.get('last') or '—'}")

    def _render_rep_timeline(self, lst, data):
        rows = data.get("timeline")
        if rows is None:
            self._add_line(lst, "Загрузка…", MUT)
            return
        if not rows:
            self._add_line(lst, "Нет данных")
            return
        for r in rows:
            self._add_line(lst, f"{r['bucket']}  —  {r['count']} событий")

    def _render_rep_daily(self, lst, data):
        rows = data.get("daily")
        if rows is None:
            self._add_line(lst, "Загрузка…", MUT)
            return
        if not rows:
            self._add_line(lst, "Нет данных")
            return
        for d in rows:
            self._add_line(lst, f"{d['date']}  —  {d['count']} событий", bold=True)
            for e in d.get("events", [])[:5]:
                tp = "новый" if e.get("is_new") else "идент."
                conf = int(round((e.get("confidence") or 0) * 100))
                self._add_line(lst,
                               f"    {e['event_time'][11:16]} [{self._cam_name(e.get('camera_id'))}] "
                               f"{e.get('full_name') or '—'} {tp} {conf}%", MUT, "11sp")
            if len(d.get("events", [])) > 5:
                self._add_line(lst, f"    … ещё {len(d['events']) - 5}", MUT, "11sp")

    def _render_rep_unknowns(self, lst, data):
        rows = data.get("unknowns")
        if rows is None:
            self._add_line(lst, "Загрузка…", MUT)
            return
        if not rows:
            self._add_line(lst, "Неопознанных нет")
            return
        for r in rows:
            self._add_line(lst, f"#{r['person_id']}  {r.get('name') or 'неопознанный'}  "
                                f"(фото: {r.get('photo_count', 0)})")
            for url in (r.get("photos") or [])[:3]:
                img = NetImage(fit_mode="contain", size_hint_y=None, height="90dp")
                img.url = self.api.base + url
                lst.add_widget(img)
            self._add_line(lst, "─" * 12, MUT, "10sp")

    # ---------------------------------------------------------- общее

    def _confirm(self, msg, yes):
        frm = BoxLayout(orientation="vertical", padding="12dp", spacing="8dp")
        frm.add_widget(Label(text=msg, color=TEXT, font_size="13sp",
                             halign="center", valign="middle"))
        btns = BoxLayout(orientation="horizontal", spacing="8dp", size_hint_y=None, height="46dp")
        no = Button(text="Отмена")
        ye = Button(text="Да")
        btns.add_widget(no)
        btns.add_widget(ye)
        frm.add_widget(btns)
        popup = Popup(title="Подтверждение", content=frm, size_hint=(0.85, 0.35))
        no.bind(on_release=lambda b: popup.dismiss())
        ye.bind(on_release=lambda b: (popup.dismiss(), yes()))
        popup.open()

    def on_pause(self):
        self._stop_stream()
        return True

    def on_stop(self):
        self._stop_stream()


if __name__ == "__main__":
    RemoteClientApp().run()