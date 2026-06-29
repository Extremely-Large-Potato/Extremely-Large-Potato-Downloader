# Developer Guide

این سند برای افرادی نوشته شده است که قصد توسعه یا مشارکت در پروژه را دارند.

---

## Requirements

* Python 3.11+
* pip

---

## نصب وابستگی‌ها

```bash
pip install -r requirements.txt
```

---

## کتابخانه‌های مورد استفاده

customtkinter
psutil
arabic-reshaper
python-bidi

---

## اجرای پروژه

```bash
python SteamDownloaderPro.pyw
```

---

## ساخت نسخه EXE

```bash
pyinstaller --onefile --windowed SteamDownloaderPro.pyw
```

---

## ساختار پروژه

```text
SteamDownloaderPro.pyw
config.json
requirements.txt
assets/
logs/
```

---

## افزودن قابلیت جدید

در صورت اضافه کردن ویژگی جدید لطفاً موارد زیر را رعایت کنید:

* مستندسازی کد
* ثبت تغییرات در CHANGELOG
* حفظ سازگاری با نسخه‌های قبلی
* جلوگیری از ایجاد Thread ناامن

---

## گزارش باگ

اگر باگی پیدا کردید لطفاً موارد زیر را ارسال کنید:

* نسخه برنامه
* نسخه ویندوز
* فایل Log
* تصویر خطا

---

## Pull Request

قبل از ارسال Pull Request لطفاً:

* کد را تست کنید.
* از سازگاری با نسخه فعلی اطمینان حاصل کنید.
* توضیح مناسبی برای تغییرات بنویسید.

---

Happy Coding!

Powered by Potato 🥔
