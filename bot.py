import logging
import os
import json
import re
from datetime import datetime
import pytz
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# ── Load .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# ── Logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Timezone WIB
WIB = pytz.timezone("Asia/Jakarta")

# ── Hari & Bulan
HARI = {
    "Monday": "SENIN", "Tuesday": "SELASA", "Wednesday": "RABU",
    "Thursday": "KAMIS", "Friday": "JUMAT", "Saturday": "SABTU",
    "Sunday": "MINGGU"
}
BULAN = {
    1: "JANUARI", 2: "FEBRUARI", 3: "MARET", 4: "APRIL",
    5: "MEI", 6: "JUNI", 7: "JULI", 8: "AGUSTUS",
    9: "SEPTEMBER", 10: "OKTOBER", 11: "NOVEMBER", 12: "DESEMBER"
}

# ── Simpan mapping pesan → data sheet
saved_messages = {}

# ── Google Sheets Setup
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def get_sheet():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(
            "telegram-bot-496706-e8c55e2944e2.json", scopes=SCOPES
        )
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet("TRANSAKSI")

# ── Format label
def format_label_hari(dt):
    return f"═══════ {HARI[dt.strftime('%A')]}, {dt.day} {BULAN[dt.month]} {dt.year} ═══════"

def format_label_total(dt):
    return f"TOTAL {HARI[dt.strftime('%A')]}, {dt.day} {BULAN[dt.month]} {dt.year}"

def get_shift(dt):
    jam = dt.hour
    if 0 <= jam < 8:
        return "── SHIFT SUBUH ──"
    elif 8 <= jam < 16:
        return "── SHIFT PAGI ──"
    else:
        return "── SHIFT SORE ──"

# ── Cek tipe baris
def is_pembatas(row):
    return any("═══════" in str(cell) for cell in row)

def is_total(row):
    return any(str(cell).startswith("TOTAL ") for cell in row)

def is_shift(row):
    return any("SHIFT" in str(cell) for cell in row)

def is_empty(row):
    return not any(cell.strip() for cell in row)

def is_special(row):
    return is_pembatas(row) or is_total(row) or is_shift(row) or is_empty(row)

# ── Format angka
def format_rupiah(value):
    try:
        angka = int(str(value).replace(".", "").replace(",", "").strip())
        return "Rp {:,.0f}".format(angka).replace(",", ".")
    except:
        return str(value)

def parse_rupiah(value):
    try:
        clean = str(value).replace("Rp", "").replace(".", "").replace(",", "").strip()
        return int(clean)
    except:
        return 0

def format_jumlah(value):
    try:
        angka = int(str(value).strip())
        hasil = angka / 1000
        if hasil == int(hasil):
            return str(int(hasil))
        else:
            return str(round(hasil, 10)).replace(".", ",")
    except:
        return str(value)

def parse_jumlah_dari_sheet(value):
    try:
        return float(str(value).replace(",", ".").strip())
    except:
        return 0

def format_total_jumlah(total):
    if total == int(total):
        return str(int(total))
    return str(round(total, 10)).replace(".", ",")

# ── Validasi
def validasi_wa(value):
    if not value.strip():
        return True, ""
    value = value.strip()
    if not value.startswith("62"):
        return False, "❌ Nomor Whatsapp salah!\nHarus diawali dengan 62\nFormat yang benar: 62 8XX-XXXX-XXXX"
    if re.search(r'[a-zA-Z]', value):
        return False, "❌ Nomor Whatsapp salah!\nTidak boleh ada huruf\nFormat yang benar: 62 8XX-XXXX-XXXX"
    if not re.match(r'^62[\s\d\-]+\d$', value):
        return False, "❌ Nomor Whatsapp salah!\nTidak boleh ada karakter lain di ujung\nFormat yang benar: 62 8XX-XXXX-XXXX"
    return True, ""

def validasi_id(value):
    if not value.strip():
        return True, ""
    if not value.strip().isdigit():
        return False, "❌ ID hanya boleh berisi angka!\nContoh yang benar: 12345"
    return True, ""

def validasi_username(value):
    if not value.strip():
        return True, ""
    value = value.strip()
    if value.isdigit():
        return False, "❌ Username tidak boleh angka semua!\nHarus ada kombinasi huruf\nContoh: @budi123 atau royal"
    if not re.search(r'[a-zA-Z]', value):
        return False, "❌ Username harus mengandung huruf!\nContoh: @budi123 atau royal"
    return True, ""

def validasi_nominal(value):
    if not value.strip():
        return True, ""
    try:
        angka = int(str(value).replace(".", "").replace(",", "").strip())
        if angka < 4000:
            return False, f"❌ Nominal minimum Rp 4.000!\nKamu memasukan {format_rupiah(str(angka))}\nSilakan masukan nominal yang benar"
    except:
        return False, "❌ Nominal hanya boleh angka!\nSilakan masukan nominal yang benar"
    return True, ""

def validasi_jumlah(value):
    if not value.strip():
        return True, ""
    value = value.strip()
    if "." in value:
        return False, f"❌ Jumlah tidak boleh menggunakan titik!\nKamu memasukan: {value}\nMasukan angka saja: {value.replace('.', '')}"
    if "," in value:
        return False, f"❌ Jumlah tidak boleh menggunakan koma!\nKamu memasukan: {value}\nMasukan angka saja: {value.replace(',', '')}"
    if not value.isdigit():
        return False, f"❌ Jumlah hanya boleh berisi angka!\nKamu memasukan: {value}"
    if len(value) < 3:
        return False, f"❌ Jumlah minimal 3 digit!\nKamu memasukan: {value}\nMinimal: 100"
    return True, ""

def validasi_rd_hdi(value):
    if not value.strip():
        return True, ""
    if not re.match(r'^[a-zA-Z\s/]+$', value.strip()):
        return False, "❌ RD/HDI hanya boleh berisi huruf!\nContoh yang benar: RD atau HDI"
    return True, ""

def validasi_bank(value):
    if not value.strip():
        return True, ""
    if not re.match(r'^[a-zA-Z\s]+$', value.strip()):
        return False, "❌ Bank hanya boleh berisi huruf!\nContoh yang benar: BCA atau DANA"
    return True, ""

# ── Format ulang sheet
def format_ulang_sheet(sheet):
    try:
        all_data = sheet.get_all_values()
        for idx, row in enumerate(all_data[1:], start=2):
            if is_pembatas(row):
                sheet.merge_cells(f"A{idx}:H{idx}")
                sheet.format(f"A{idx}:H{idx}", {
                    "horizontalAlignment": "CENTER",
                    "textFormat"         : {"bold": True},
                    "backgroundColor"    : {"red": 0.8, "green": 0.8, "blue": 0.8}
                })
            elif is_total(row):
                sheet.format(f"A{idx}:H{idx}", {
                    "textFormat"      : {"bold": True},
                    "backgroundColor" : {"red": 1.0, "green": 0.95, "blue": 0.4}
                })
            elif is_shift(row):
                sheet.merge_cells(f"A{idx}:H{idx}")
                sheet.format(f"A{idx}:H{idx}", {
                    "horizontalAlignment": "CENTER",
                    "textFormat"         : {"bold": True, "italic": True},
                    "backgroundColor"    : {"red": 0.9, "green": 0.95, "blue": 1.0}
                })
    except Exception as e:
        logger.error(f"❌ Gagal format: {e}")

# ── Hitung total HANYA untuk 1 hari
def hitung_total_satu_hari(all_data, target_date):
    total_nominal = 0
    total_jumlah  = 0.0
    for row in all_data[1:]:
        if is_special(row):
            continue
        try:
            dt_row = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            if dt_row.date() != target_date:
                continue
            total_nominal += parse_rupiah(row[4])
            total_jumlah  += parse_jumlah_dari_sheet(row[5])
        except:
            continue
    return total_nominal, total_jumlah

# ── Tambah total + pembatas + shift
def tambah_total_dan_pembatas(sheet, dt_sekarang):
    try:
        all_data = sheet.get_all_values()
        if len(all_data) <= 1:
            sheet.append_row([format_label_hari(dt_sekarang)] + [""] * 7)
            sheet.append_row([get_shift(dt_sekarang)] + [""] * 7)
            format_ulang_sheet(sheet)
            return

        baris_terakhir = None
        for row in reversed(all_data[1:]):
            if not is_special(row):
                baris_terakhir = row
                break

        if baris_terakhir is None:
            sheet.append_row([format_label_hari(dt_sekarang)] + [""] * 7)
            sheet.append_row([get_shift(dt_sekarang)] + [""] * 7)
            format_ulang_sheet(sheet)
            return

        try:
            dt_terakhir = datetime.strptime(baris_terakhir[0], "%Y-%m-%d %H:%M:%S")
        except:
            return

        if dt_terakhir.date() >= dt_sekarang.date():
            return

        label_total = format_label_total(dt_terakhir)
        for row in all_data[1:]:
            if is_total(row) and label_total in str(row[0]):
                return

        total_nominal, total_jumlah = hitung_total_satu_hari(
            all_data, dt_terakhir.date()
        )

        tn_str = format_rupiah(str(total_nominal))
        tj_str = format_total_jumlah(total_jumlah)

        sheet.append_row([label_total, "", "", "", tn_str, tj_str, "", ""])
        sheet.append_row([format_label_hari(dt_sekarang)] + [""] * 7)
        sheet.append_row([get_shift(dt_sekarang)] + [""] * 7)
        format_ulang_sheet(sheet)
        logger.info(f"✅ Total + pembatas + shift: {label_total}")

    except Exception as e:
        logger.error(f"❌ Gagal tambah total: {e}")

# ── Cek shift baru
def cek_tambah_shift(sheet, dt_sekarang):
    try:
        all_data  = sheet.get_all_values()
        shift_now = get_shift(dt_sekarang)

        shift_terakhir = None
        for row in reversed(all_data[1:]):
            if is_shift(row):
                shift_terakhir = row[0].strip()
                break

        if shift_terakhir == shift_now:
            return

        label_hari_ini        = format_label_hari(dt_sekarang)
        ada_pembatas_hari_ini = any(
            is_pembatas(row) and label_hari_ini in str(row[0])
            for row in all_data[1:]
        )

        if ada_pembatas_hari_ini:
            sheet.append_row([shift_now] + [""] * 7)
            format_ulang_sheet(sheet)
            logger.info(f"✅ Shift: {shift_now}")

    except Exception as e:
        logger.error(f"❌ Gagal cek shift: {e}")

# ── Hapus data dari sheet
def hapus_dari_sheet(sheet, timestamp):
    try:
        all_data  = sheet.get_all_values()
        header    = all_data[0]
        rows      = all_data[1:]
        new_rows  = []
        ditemukan = False

        for row in rows:
            if (not is_special(row) and len(row) > 0 and row[0] == timestamp):
                ditemukan = True
                continue
            new_rows.append(row)

        if ditemukan:
            sheet.clear()
            sheet.append_row(header)
            if new_rows:
                sheet.append_rows(new_rows)
            rapikan_sheet(sheet)
            logger.info(f"✅ Data dihapus: {timestamp}")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ Gagal hapus: {e}")
        return False

# ── Rapikan sheet
def rapikan_sheet(sheet):
    try:
        all_data = sheet.get_all_values()
        if len(all_data) <= 1:
            return

        header = all_data[0]
        rows   = all_data[1:]

        new_rows = []
        i = 0
        while i < len(rows):
            if is_empty(rows[i]):
                kosong_count = 0
                j = i
                while j < len(rows) and is_empty(rows[j]):
                    kosong_count += 1
                    j += 1
                if kosong_count == 1:
                    i += 1
                else:
                    for k in range(kosong_count):
                        new_rows.append(rows[i + k])
                    i += kosong_count
            else:
                new_rows.append(rows[i])
                i += 1

        data_rows  = [r for r in new_rows if not is_special(r)]
        empty_rows = [r for r in new_rows if is_empty(r)]

        def get_ts(row):
            try:
                return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            except:
                return datetime.min

        data_rows.sort(key=get_ts)

        grouped = {}
        for row in data_rows:
            try:
                d = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").date()
            except:
                d = None
            if d not in grouped:
                grouped[d] = []
            grouped[d].append(row)

        sorted_dates = sorted([d for d in grouped.keys() if d is not None])
        hari_ini     = datetime.now(WIB).date()
        final_rows   = []

        for i, d in enumerate(sorted_dates):
            rows_hari     = grouped[d]
            dt_hari       = datetime.combine(d, datetime.min.time())
            current_shift = None

            final_rows.append([format_label_hari(dt_hari)] + [""] * 7)

            for row in rows_hari:
                try:
                    dt_row    = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                    row_shift = get_shift(dt_row)
                except:
                    row_shift = None

                if row_shift != current_shift:
                    current_shift = row_shift
                    final_rows.append([current_shift] + [""] * 7)

                final_rows.append(row)

            if d < hari_ini:
                tn = sum(parse_rupiah(r[4]) for r in rows_hari)
                tj = sum(parse_jumlah_dari_sheet(r[5]) for r in rows_hari)
                tn_str = format_rupiah(str(tn))
                tj_str = format_total_jumlah(tj)
                final_rows.append([
                    format_label_total(dt_hari),
                    "", "", "", tn_str, tj_str, "", ""
                ])

        final_rows += empty_rows

        sheet.clear()
        sheet.append_row(header)
        if final_rows:
            sheet.append_rows(final_rows)

        format_ulang_sheet(sheet)
        logger.info("✅ Sheet berhasil dirapikan!")
    except Exception as e:
        logger.error(f"❌ Gagal rapikan: {e}")

# ── Parse pesan
def parse_message(text):
    data = {
        "id": "", "username": "", "nominal": "",
        "jumlah": "", "rd_hdi": "", "bank": "", "wa": "",
    }
    for line in text.strip().split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key   = key.strip().lower()
        value = value.strip()
        if key == "id":
            data["id"] = value
        elif key == "username":
            data["username"] = value
        elif key == "nominal":
            data["nominal"] = value
        elif key == "jumlah":
            data["jumlah"] = value
        elif key in ["rd / hdi", "rd/hdi", "rd"]:
            data["rd_hdi"] = value
        elif key == "bank":
            data["bank"] = value
        elif key in ["nomor whatsapp", "nomor wahtsapp", "no whatsapp", "wa"]:
            data["wa"] = value
    return data

# ── Keyboard tombol hapus
def buat_keyboard_hapus(orig_msg_id, user_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🗑️ Hapus Data",
            callback_data=f"HAPUS|{orig_msg_id}|{user_id}"
        )
    ]])

# ── Keyboard konfirmasi hapus
def buat_keyboard_konfirmasi_hapus(orig_msg_id, user_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ Ya, Hapus",
            callback_data=f"HAPUS_YA|{orig_msg_id}|{user_id}"
        ),
        InlineKeyboardButton(
            "❌ Batal",
            callback_data=f"HAPUS_BATAL|{orig_msg_id}|{user_id}"
        ),
    ]])

# ── Proses pesan
async def proses_pesan(msg, context, is_edit=False):
    if not msg or not msg.text:
        return

    user_id = msg.from_user.id
    chat_id = msg.chat_id
    text    = msg.text

    if ":" not in text:
        return

    # ── Tentukan timestamp
    if is_edit and msg.message_id in saved_messages:
        old_info  = saved_messages[msg.message_id]
        timestamp = old_info["timestamp"]
        logger.info(f"✅ Edit detected, timestamp lama: {timestamp}")
        try:
            sheet = get_sheet()
            hapus_dari_sheet(sheet, old_info["timestamp"])
            await context.bot.delete_message(
                chat_id=old_info["chat_id"],
                message_id=old_info["bot_msg_id"]
            )
            logger.info(f"✅ Data lama dihapus untuk edit")
        except Exception as e:
            logger.error(f"❌ Gagal hapus data lama: {e}")
        del saved_messages[msg.message_id]
    else:
        timestamp = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")

    dt_now = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    data   = parse_message(text)

    # ── Validasi
    validasi_list = [
        (validasi_wa,       data["wa"]),
        (validasi_id,       data["id"]),
        (validasi_username, data["username"]),
        (validasi_nominal,  data["nominal"]),
        (validasi_jumlah,   data["jumlah"]),
        (validasi_rd_hdi,   data["rd_hdi"]),
        (validasi_bank,     data["bank"]),
    ]

    for validasi_fn, field in validasi_list:
        valid, error_msg = validasi_fn(field)
        if not valid:
            await msg.reply_text(error_msg)
            return

    # ── Format
    if data["nominal"]:
        data["nominal"] = format_rupiah(data["nominal"])
    if data["jumlah"]:
        data["jumlah"] = format_jumlah(data["jumlah"])

    row = [
        timestamp, data["wa"], data["id"],
        data["username"], data["nominal"], data["jumlah"],
        data["rd_hdi"], data["bank"],
    ]

    try:
        sheet = get_sheet()
        tambah_total_dan_pembatas(sheet, dt_now)
        cek_tambah_shift(sheet, dt_now)
        sheet.append_row(row)
        logger.info(f"✅ Saved | {data['username']} | WA: {data['wa']}")
        rapikan_sheet(sheet)

        bot_msg = await msg.reply_text(
            f"✅ Data berhasil dicatat!\n\n"
            f"🔢 ID       : {data['id'] or '-'}\n"
            f"👤 Username : {data['username'] or '-'}\n"
            f"💰 Nominal  : {data['nominal'] or '-'}\n"
            f"📦 Jumlah   : {data['jumlah'] or '-'}\n"
            f"🏷️ RD/HDI   : {data['rd_hdi'] or '-'}\n"
            f"🏦 Bank     : {data['bank'] or '-'}\n"
            f"📱 WA       : {data['wa'] or '-'}",
            reply_markup=buat_keyboard_hapus(msg.message_id, user_id)
        )

        saved_messages[msg.message_id] = {
            "bot_msg_id" : bot_msg.message_id,
            "timestamp"  : timestamp,
            "user_id"    : user_id,
            "chat_id"    : chat_id,
        }

    except Exception as e:
        logger.error(f"❌ Failed: {e}")
        await msg.reply_text("❌ Gagal menyimpan data!")

# ── Handler pesan
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.edited_message:
        await proses_pesan(update.edited_message, context, is_edit=True)
    elif update.message:
        await proses_pesan(update.message, context, is_edit=False)

# ── Handler callback
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    await query.answer()

    # ── Tombol HAPUS (tampilkan konfirmasi)
    if query.data.startswith("HAPUS|"):
        parts = query.data.split("|")
        if len(parts) != 3:
            return

        orig_msg_id   = int(parts[1])
        owner_user_id = int(parts[2])

        is_admin = False
        try:
            member   = await context.bot.get_chat_member(chat_id, user_id)
            is_admin = member.status in ["administrator", "creator"]
        except:
            pass

        if user_id != owner_user_id and not is_admin:
            await query.answer(
                "❌ Hanya pengirim atau admin yang bisa hapus data ini!",
                show_alert=True
            )
            return

        await query.edit_message_reply_markup(
            reply_markup=buat_keyboard_konfirmasi_hapus(orig_msg_id, owner_user_id)
        )
        return

    # ── Tombol HAPUS_YA
    if query.data.startswith("HAPUS_YA|"):
        parts = query.data.split("|")
        if len(parts) != 3:
            return

        orig_msg_id   = int(parts[1])
        owner_user_id = int(parts[2])

        is_admin = False
        try:
            member   = await context.bot.get_chat_member(chat_id, user_id)
            is_admin = member.status in ["administrator", "creator"]
        except:
            pass

        if user_id != owner_user_id and not is_admin:
            await query.answer(
                "❌ Hanya pengirim atau admin yang bisa hapus data ini!",
                show_alert=True
            )
            return

        if orig_msg_id in saved_messages:
            info = saved_messages[orig_msg_id]
            try:
                sheet = get_sheet()
                hapus_dari_sheet(sheet, info["timestamp"])
                await query.edit_message_text("🗑️ Data berhasil dihapus!")
                del saved_messages[orig_msg_id]
                logger.info(f"✅ Data dihapus via tombol")
            except Exception as e:
                logger.error(f"❌ Gagal hapus: {e}")
                await query.edit_message_text("❌ Gagal menghapus data!")
        else:
            await query.edit_message_text("⚠️ Data tidak ditemukan atau sudah dihapus!")
        return

    # ── Tombol HAPUS_BATAL
    if query.data.startswith("HAPUS_BATAL|"):
        parts = query.data.split("|")
        if len(parts) != 3:
            return

        orig_msg_id   = int(parts[1])
        owner_user_id = int(parts[2])

        if orig_msg_id in saved_messages:
            await query.edit_message_reply_markup(
                reply_markup=buat_keyboard_hapus(orig_msg_id, owner_user_id)
            )
        return

# ── Main
def main():
    logger.info("🚀 Bot starting...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("✅ Bot is running. Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
