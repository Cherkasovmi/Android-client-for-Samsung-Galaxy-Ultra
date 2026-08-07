[app]
title = PeopleRecognition
package.name = peoplerecognition
package.domain = org.peoplerecognition
source.dir = .
source.main = client_android.py
source.include_exts = py,png,jpg,kv,atlas
version = 1.0
requirements = python3,kivy,requests,pillow,certifi,urllib3,idna,charset_normalizer
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 34
android.minapi = 24
android.ndk = 25b
android.sdk = 34
android.archs = arm64-v8a
android.accept_sdk_license = True
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 1