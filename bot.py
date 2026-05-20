import logging
import os
import json
import re
from datetime import datetime
import pytz
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

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

# ── Hitung total HANYA untuk 1 hari tertentu
def hitung_total_satu_hari(all_data, target_date):
    """
    Hitung total nominal dan jumlah
    HANYA dari baris data yang tanggalnya == target_date
    Tidak mempedulikan hari lain sama sekali
    """
    total_nominal = 0
    total_jumlah  = 0.0

    for row in all_data[1:]:
        # Skip baris special
        if is_special(row):
            continue
        try:
            dt_row = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            # Hanya proses baris yang tanggalnya sama dengan target
            if dt_row.date() != target_date:
                continue
            # Kolom E (index 4) = Nominal
            # Kolom F (index 5) = Jumlah
            nominal = parse_rupiah(row[4])
            jumlah  = parse_jumlah_dari_sheet(row[5])
            total_nominal += nominal
            total_jumlah  += jumlah
        except:
            continue

    return total_nominal, total_jumlah

# ── Format string total jumlah
def format_total_jumlah(total):
    if total == int(total):
        return str(int(total))
    else:
        return str(round(total, 10)).replace(".", ",")

# ── Tambah total + pembatas + shift saat hari berganti
def tambah_total_dan_pembatas(sheet, dt_sekarang):
    try:
        all_data = sheet.get_all_values()
        if len(all_data) <= 1:
            sheet.append_row([format_label_hari(dt_sekarang)] + [""] * 7)
            sheet.append_row([get_shift(dt_sekarang)] + [""] * 7)
            format_ulang_sheet(sheet)
            return

        # Cari data terakhir
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

        # Kalau tanggal sama, tidak perlu tambah total
        if dt_terakhir.date() >= dt_sekarang.date():
            return

        # Cek duplikat total
        label_total = format_label_total(dt_terakhir)
        for row in all_data[1:]:
            if is_total(row) and label_total in str(row[0]):
                logger.info(f"⚠️ Total sudah ada: {label_total}")
                return

        # Hitung total HANYA untuk hari terakhir
        total_nominal, total_jumlah = hitung_total_satu_hari(
            all_data,
            dt_terakhir.date()  # ← hanya tanggal ini
        )

        tn_str = format_rupiah(str(total_nominal))
        tj_str = format_total_jumlah(total_jumlah)

        logger.info(f"📊 Total {label_total}: Nominal={tn_str} Jumlah={tj_str}")

        # Tambah baris total
        sheet.append_row([label_total, "", "", "", tn_str, tj_str, "", ""])

        # Tambah pembatas hari baru
        sheet.append_row([format_label_hari(dt_sekarang)] + [""] * 7)

        # Tambah shift pertama hari baru
        sheet.append_row([get_shift(dt_sekarang)] + [""] * 7)

        format_ulang_sheet(sheet)
        logger.info(f"✅ Total + pembatas + shift: {label_total}")

    except Exception as e:
        logger.error(f"❌ Gagal tambah total: {e}")

# ── Cek dan tambah shift baru jika perlu
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

# ── Rapikan sheet
def rapikan_sheet(sheet):
    try:
        all_data = sheet.get_all_values()
        if len(all_data) <= 1:
            return

        header = all_data[0]
        rows   = all_data[1:]

        # Hapus tepat 1 baris kosong
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

        # Kelompokkan per hari
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

            # Pembatas hari
            final_rows.append([format_label_hari(dt_hari)] + [""] * 7)

            # Data per shift
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

            # Total hanya hari yang sudah selesai
            # Hitung HANYA dari rows_hari (data hari itu saja)
            if d < hari_ini:
                # Hitung langsung dari rows_hari bukan all_data
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

# ── Handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text      = msg.text
    dt_now    = datetime.now(WIB)
    timestamp = dt_now.strftime("%Y-%m-%d %H:%M:%S")

    if ":" not in text:
        return

    data = parse_message(text)

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
        timestamp,
        data["wa"],
        data["id"],
        data["username"],
        data["nominal"],
        data["jumlah"],
        data["rd_hdi"],
        data["bank"],
    ]

    try:
        sheet = get_sheet()
        tambah_total_dan_pembatas(sheet, dt_now)
        cek_tambah_shift(sheet, dt_now)
        sheet.append_row(row)
        logger.info(f"✅ Saved | {data['username']} | WA: {data['wa']}")
        rapikan_sheet(sheet)

        await msg.reply_text(
            f"✅ Data berhasil dicatat!\n\n"
            f"🔢 ID       : {data['id'] or '-'}\n"
            f"👤 Username : {data['username'] or '-'}\n"
            f"💰 Nominal  : {data['nominal'] or '-'}\n"
            f"📦 Jumlah   : {data['jumlah'] or '-'}\n"
            f"🏷️ RD/HDI   : {data['rd_hdi'] or '-'}\n"
            f"🏦 Bank     : {data['bank'] or '-'}\n"
            f"📱 WA       : {data['wa'] or '-'}"
        )
    except Exception as e:
        logger.error(f"❌ Failed: {e}")
        await msg.reply_text("❌ Gagal menyimpan data!")

# ── Main
def main():
    logger.info("🚀 Bot starting...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    logger.info("✅ Bot is running. Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
