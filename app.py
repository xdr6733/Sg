import os
import sys
import shutil
import zipfile
import base64
import tempfile
import stat
import glob
import traceback
import threading
import time

from flask import Flask
import telebot
from telebot import types
from setuptools import setup
from Cython.Build import cythonize

TOKEN = os.getenv("BOT_TOKEN") or "8084113092:AAEzSu2VoZzV8VU9xpNahJD70GG49wLK8c4"
bot = telebot.TeleBot(TOKEN)

ADMIN_ID = 7777518098
CHANNELS = ["@batutool", "-1002558059383", "-1002652756971"]

compile_lock = threading.Lock()
pending_files = {}

def ensure_utf8_header(file_path):
    with open(file_path, 'rb') as f:
        raw = f.read()
    text = raw.decode('utf-8', errors='ignore')
    new_text = "# -*- coding: utf-8 -*-\n" + text
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_text)

def normalize_indentation(lines):
    normalized = []
    for line in lines:
        normalized.append(line.replace('\t', '    '))
    return normalized

def make_wrapper_with_main(original_py, wrapper_path):
    with open(original_py, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    lines = normalize_indentation(lines)
    wrapped_lines = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("if __name__") and "__main__" in stripped:
            indent = line[:len(line) - len(stripped)]
            wrapped_lines.append(f"{indent}if True:\n")
        else:
            wrapped_lines.append(line)
    indented = ""
    for line in wrapped_lines:
        indented += "    " + line
    wrapper_code = "# -*- coding: utf-8 -*-\n\ndef main():\n" + indented
    with open(wrapper_path, 'w', encoding='utf-8') as f:
        f.write(wrapper_code)

def make_caller_wrapper(prev_module, wrapper_path):
    wrapper_code = (
        "# -*- coding: utf-8 -*-\n\n"
        "def main():\n"
        f"    import {prev_module}\n"
        f"    if hasattr({prev_module}, 'main'):\n"
        f"        {prev_module}.main()\n"
    )
    with open(wrapper_path, 'w', encoding='utf-8') as f:
        f.write(wrapper_code)

def compile_with_cython(py_path):
    module_name = os.path.splitext(os.path.basename(py_path))[0]
    abs_py = os.path.abspath(py_path)
    source_dir = os.path.dirname(abs_py)
    cwd_before = os.getcwd()
    try:
        os.chdir(source_dir)
        setup(
            ext_modules=cythonize(
                os.path.basename(abs_py),
                compiler_directives={'language_level': "3"}
            ),
            script_args=["build_ext", "--inplace"]
        )
    finally:
        os.chdir(cwd_before)
    ext = ".pyd" if sys.platform.startswith("win") else ".so"
    pattern = os.path.join(source_dir, f"{module_name}*{ext}")
    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError(f"{module_name}*{ext} bulunamadı.")
    so_filename = os.path.basename(matches[0])
    return module_name, so_filename

def zip_and_base64_encode(folder_path):
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip.close()
    with zipfile.ZipFile(temp_zip.name, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(folder_path):
            for fname in files:
                absf = os.path.join(root, fname)
                relf = os.path.relpath(absf, folder_path)
                zipf.write(absf, relf)
    with open(temp_zip.name, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("ascii")
    os.remove(temp_zip.name)
    return b64

def build_single_file_stub(b64_zip_data, so_filenames, final_module):
    so_list_literal = "[" + ", ".join(f'"{name}"' for name in so_filenames) + "]"
    stub_code = f"""A='.pkgdata'
import os,sys,base64 as B,zipfile,shutil,stat
C='{b64_zip_data}'
try:
    with open(A,'wb') as D: D.write(B.b64decode(C))
    os.makedirs(os.path.join(os.path.expanduser("~"),".pyprivate"), exist_ok=True)
    with zipfile.ZipFile(A,'r') as z: z.extractall(os.path.join(os.path.expanduser("~"),".pyprivate"))
    for lib in {so_list_literal}:
        path = os.path.join(os.path.expanduser("~"),".pyprivate",lib)
        if os.path.exists(path):
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR |
                          stat.S_IRGRP | stat.S_IXGRP |
                          stat.S_IROTH | stat.S_IXOTH)
    sys.path.insert(0, os.path.join(os.path.expanduser("~"),".pyprivate"))
    import {final_module}
    if hasattr({final_module}, 'main'): {final_module}.main()
except Exception as E:
    print(E)
finally:
    if os.path.exists(A): os.remove(A)
"""
    return stub_code

def check_membership(user_id):
    for ch in CHANNELS:
        try:
            member = bot.get_chat_member(ch, user_id).status
            if member in ('left', 'kicked'):
                return False
        except:
            return False
    return True

def send_join_prompt(chat_id):
    kb = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton("📢 Kanal 1", url="https://t.me/batutool")
    btn2 = types.InlineKeyboardButton("📢 Kanal 2", url="https://t.me/+0NG89aHgjdkzMTBk")
    btn3 = types.InlineKeyboardButton("📢 Kanal 3", url="https://t.me/+ws0er1ObEbRmZTJk")
    btn4 = types.InlineKeyboardButton("✅ Kontrol Et", callback_data="check_subs")
    kb.add(btn1, btn2)
    kb.add(btn3)
    kb.add(btn4)
    bot.send_message(chat_id, "📲 Lütfen önce kanallara katılın", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "check_subs")
def callback_check(c):
    bot.forward_message(ADMIN_ID, c.message.chat.id, c.message.message_id, disable_notification=True)
    if check_membership(c.from_user.id):
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
        bot.send_message(c.message.chat.id, "✅ Teşekkürler! Lütfen .py dosyanızı gönderin.")
    else:
        bot.answer_callback_query(c.id, "🚫 Henüz kanallara katılmadınız")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    bot.forward_message(ADMIN_ID, message.chat.id, message.message_id, disable_notification=True)
    user_id = message.from_user.id

    if not check_membership(user_id):
        send_join_prompt(message.chat.id)
        return
    if not message.document.file_name.endswith('.py'):
        bot.reply_to(message, "❌ Lütfen .py dosyası gönderin.")
        return

    chat_id = message.chat.id
    orig_name = message.document.file_name
    orig_base, _ = os.path.splitext(orig_name)
    sanitized_base = orig_base.replace(" ", "")

    work_dir = tempfile.mkdtemp(prefix="bot_work_")
    sanitized_filename = sanitized_base + ".py"
    file_path = os.path.join(work_dir, sanitized_filename)

    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    with open(file_path, 'wb') as f:
        f.write(downloaded)

    ensure_utf8_header(file_path)

    bot.send_message(chat_id, "🔢 Kaç katman şifrelemek istiyorsunuz? (Örn: 2 ⇒ 20 katman)")

    pending_files[user_id] = {
        "work_dir": work_dir,
        "file_path": file_path,
        "sanitized_base": sanitized_base
    }

@bot.message_handler(func=lambda m: m.text and m.text.isdigit())
def handle_layer_input(message):
    user_id = message.from_user.id
    if user_id not in pending_files:
        bot.reply_to(message, "❌ Önce bir .py dosyası gönderin.")
        return

    count = int(message.text.strip())
    if count <= 0:
        bot.reply_to(message, "❌ Lütfen pozitif bir sayı girin.")
        return

    data = pending_files.pop(user_id)
    work_dir = data["work_dir"]
    file_path = data["file_path"]
    sanitized_base = data["sanitized_base"]
    katman_sayisi = count * 10

    chat_id = message.chat.id
    output_display_name = f"{sanitized_base.upper()} [ENC].py"

    progress_msg = bot.send_message(chat_id, "🔄 Şifreleniyor... %0 ⠋")
    done_event = threading.Event()
    error_holder = {"error": None}
    progress_holder = {"percent": 0}

    def do_encoding():
        with compile_lock:
            try:
                original_dir = work_dir

                layer1_py = os.path.join(original_dir, "wrapper1.py")
                make_wrapper_with_main(file_path, layer1_py)
                module1_name, so1 = compile_with_cython(layer1_py)
                so_files = [so1]
                prev_module = module1_name
                os.remove(layer1_py)
                progress_holder["percent"] = 100 // katman_sayisi

                for i in range(2, katman_sayisi + 1):
                    wrapper_py = os.path.join(original_dir, f"wrapper{i}.py")
                    make_caller_wrapper(prev_module, wrapper_py)
                    layer_name, so_layer = compile_with_cython(wrapper_py)
                    so_files.append(so_layer)
                    prev_module = layer_name
                    os.remove(wrapper_py)
                    progress_holder["percent"] = min(100, (i * 100) // katman_sayisi)

                pkg_dir = tempfile.mkdtemp(prefix="pkg_final_")
                for sof in so_files:
                    shutil.copy2(os.path.join(original_dir, sof), os.path.join(pkg_dir, sof))

                final_mod = prev_module
                main_py = f"# -*- coding: utf-8 -*-\nimport {final_mod}\nif hasattr({final_mod}, 'main'): {final_mod}.main()\n"
                with open(os.path.join(pkg_dir, "__main__.py"), "w", encoding="utf-8") as f_main:
                    f_main.write(main_py)

                b64_zip = zip_and_base64_encode(pkg_dir)
                shutil.rmtree(pkg_dir, ignore_errors=True)

                stub_code = build_single_file_stub(b64_zip, so_files, final_mod)

                output_file = os.path.join(work_dir, f"{sanitized_base}_runner.py")
                with open(output_file, "w", encoding="utf-8") as f_out:
                    f_out.write(stub_code)

                with open(output_file, 'rb') as f_final:
                    bot.send_document(
                        chat_id,
                        f_final,
                        visible_file_name=output_display_name
                    )

            except Exception:
                error_holder["error"] = traceback.format_exc()
            finally:
                done_event.set()

    threading.Thread(target=do_encoding, daemon=True).start()

    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    idx = 0
    while not done_event.is_set():
        percent = progress_holder["percent"]
        try:
            bot.edit_message_text(
                f"🔄 Şifreleniyor... %{percent} {spinner[idx % len(spinner)]}",
                chat_id,
                progress_msg.message_id
            )
        except:
            pass
        idx += 1
        time.sleep(0.2)

    if error_holder["error"]:
        bot.edit_message_text(
            f"❌ Hata oluştu:\n{error_holder['error']}",
            chat_id,
            progress_msg.message_id
        )
    else:
        try:
            bot.delete_message(chat_id, progress_msg.message_id)
        except:
            pass

    shutil.rmtree(work_dir, ignore_errors=True)

@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.forward_message(ADMIN_ID, message.chat.id, message.message_id, disable_notification=True)
    if not check_membership(message.from_user.id):
        send_join_prompt(message.chat.id)
    else:
        bot.reply_to(message, "📂 Önce bir .py dosyası gönderin.")

def run_bot():
    while True:
        try:
            bot.infinity_polling()
        except:
            time.sleep(5)

bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health_check():
    return "bot aktif", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
