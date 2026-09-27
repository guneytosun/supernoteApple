"""Command line entry point: `supernote-todo <command>`."""

from __future__ import annotations

import argparse
import getpass
import sys
import time
from datetime import datetime, timezone

from . import __version__
from .config import (config_path, load_config, load_state, ms_cache_path,
                     save_config, save_state)
from .mstodo import MicrosoftAuth, ToDoClient, ToDoError
from .supernote import SupernoteClient, SupernoteError, token_expiry
from .sync import Syncer


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _yes_no(prompt: str, default: bool) -> bool:
    answer = _ask(f"{prompt} (e/h)", "e" if default else "h").lower()
    return answer.startswith(("e", "y"))


def _todo_client(config: dict) -> ToDoClient:
    auth = MicrosoftAuth(config["ms_client_id"], config["ms_authority"], ms_cache_path())
    return ToDoClient(auth.token)


def cmd_setup(args, config) -> int:
    print("Ayarlar (Enter ile mevcut değeri koruyun)\n")
    config["ms_client_id"] = _ask("Microsoft uygulama (client) ID", config["ms_client_id"])
    config["ms_authority"] = _ask(
        "Hesap türü: consumers (kişisel) / organizations (iş-okul) / common",
        config["ms_authority"])
    mode = _ask("Liste düzeni: mirror (her Supernote listesi ayrı) / single (tek liste)",
                config["list_mode"])
    config["list_mode"] = "single" if mode.startswith("s") else "mirror"
    if config["list_mode"] == "single":
        config["target_list"] = _ask("Hedef Microsoft To Do listesi", config["target_list"])
    else:
        config["list_prefix"] = _ask("Liste adı öneki (boş bırakılabilir)", config["list_prefix"])
    config["include_completed"] = _yes_no(
        "Supernote'ta zaten tamamlanmış görevler de aktarılsın mı?", config["include_completed"])
    config["complete_back"] = _yes_no(
        "Microsoft To Do'da tamamlanan görevler Supernote'ta da tamamlansın mı?",
        config["complete_back"])
    config["delete_removed"] = _yes_no(
        "Supernote'tan silinen görevler Microsoft To Do'dan da silinsin mi?",
        config["delete_removed"])
    save_config(config)
    print(f"\nKaydedildi: {config_path()}")
    return 0


def cmd_login_supernote(args, config) -> int:
    email = args.email or _ask("Supernote e-posta", config["supernote_email"])
    password = getpass.getpass("Supernote şifre: ")
    client = SupernoteClient()

    def ask_code(address: str) -> str:
        print(f"Supernote {address} adresine bir doğrulama kodu gönderdi.")
        return _ask("Doğrulama kodu")

    token = client.login(email, password, ask_code)
    config["supernote_email"] = email
    config["supernote_token"] = token
    save_config(config)
    expires = token_expiry(token)
    print("Supernote girişi başarılı.")
    if expires:
        print(f"Oturum {expires.astimezone():%d.%m.%Y} tarihine kadar geçerli.")
    return 0


def cmd_login_microsoft(args, config) -> int:
    auth = MicrosoftAuth(config["ms_client_id"], config["ms_authority"], ms_cache_path())
    who = auth.login(lambda message: print(message))
    print(f"Microsoft girişi başarılı: {who}")
    return 0


def cmd_status(args, config) -> int:
    print(f"Ayar dosyası: {config_path()}")
    token = config.get("supernote_token")
    if not token:
        print("Supernote: giriş yapılmadı")
    else:
        expires = token_expiry(token)
        if expires and expires < datetime.now(timezone.utc):
            print("Supernote: oturum süresi dolmuş")
        elif expires:
            days = (expires - datetime.now(timezone.utc)).days
            print(f"Supernote: {config['supernote_email']} (oturum {days} gün daha geçerli)")
        else:
            print(f"Supernote: {config['supernote_email']}")

    sn = SupernoteClient(token)
    if token:
        try:
            lists = sn.lists()
            tasks = [t for t in sn.tasks() if not t.deleted]
            print(f"  {len(lists)} liste, {len(tasks)} görev "
                  f"({sum(not t.completed for t in tasks)} açık)")
            for l in lists:
                print(f"   - {l.title}")
        except SupernoteError as exc:
            print(f"  Hata: {exc}")

    try:
        todo = _todo_client(config)
        ms_lists = todo.lists()
        print(f"Microsoft To Do: {len(ms_lists)} liste")
        for l in ms_lists:
            print(f"   - {l['displayName']}")
    except ToDoError as exc:
        print(f"Microsoft To Do: {exc}")
    return 0


def run_sync(config, dry_run: bool) -> int:
    state = load_state()
    syncer = Syncer(SupernoteClient(config["supernote_token"]), _todo_client(config),
                    config, state, dry_run=dry_run)
    stats = syncer.run()
    if not dry_run:
        save_state(state)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{stamp}] {'(deneme) ' if dry_run else ''}{stats.summary()}")
    return 1 if stats.errors else 0


def cmd_sync(args, config) -> int:
    for key in ("include_completed", "complete_back", "delete_removed"):
        if getattr(args, key):
            config[key] = True
    if not args.watch:
        return run_sync(config, args.dry_run)
    print(f"Her {args.watch} dakikada bir senkronize ediliyor (durdurmak için Ctrl+C).")
    while True:
        try:
            run_sync(config, args.dry_run)
        except (SupernoteError, ToDoError) as exc:
            print(f"Hata: {exc}", file=sys.stderr)
        time.sleep(args.watch * 60)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="supernote-todo",
        description="Supernote To-Do görevlerini Microsoft To Do'ya aktarır.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Ayarları etkileşimli olarak yapılandır").set_defaults(func=cmd_setup)

    p = sub.add_parser("login-supernote", help="Supernote Cloud'a giriş yap")
    p.add_argument("--email")
    p.set_defaults(func=cmd_login_supernote)

    sub.add_parser("login-microsoft", help="Microsoft hesabına giriş yap") \
        .set_defaults(func=cmd_login_microsoft)
    sub.add_parser("status", help="Bağlantıları ve listeleri göster").set_defaults(func=cmd_status)

    p = sub.add_parser("sync", help="Görevleri Microsoft To Do'ya aktar")
    p.add_argument("--dry-run", action="store_true", help="Hiçbir şeyi değiştirmeden ne yapılacağını göster")
    p.add_argument("--watch", type=int, metavar="DAKIKA", help="Sürekli çalış, N dakikada bir senkronize et")
    p.add_argument("--include-completed", action="store_true",
                   help="Tamamlanmış görevleri de aktar")
    p.add_argument("--complete-back", action="store_true",
                   help="Microsoft To Do'da tamamlananları Supernote'ta da tamamla")
    p.add_argument("--delete-removed", action="store_true",
                   help="Supernote'tan silinenleri Microsoft To Do'dan da sil")
    p.set_defaults(func=cmd_sync)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    try:
        return args.func(args, config)
    except (SupernoteError, ToDoError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
