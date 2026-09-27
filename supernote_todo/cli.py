"""Command line entry point: `supernote-todo <command>`."""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone
from typing import Optional

from . import __version__
from .config import (config_path, load_config, load_state, ms_cache_path,
                     save_config, save_state)
from .mstodo import MicrosoftAuth, MicrosoftTarget, ToDoClient
from .notify import notify_new_tasks
from .supernote import SupernoteClient, SupernoteError, token_expiry
from .sync import Syncer, valid_alarm_time
from .watch import Watcher
from .target import Target, TargetError


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _yes_no(prompt: str, default: bool) -> bool:
    answer = _ask(f"{prompt} (e/h)", "e" if default else "h").lower()
    return answer.startswith(("e", "y"))


def make_target(config: dict) -> Target:
    if config.get("target") == "microsoft":
        auth = MicrosoftAuth(config["ms_client_id"], config["ms_authority"], ms_cache_path())
        return MicrosoftTarget(ToDoClient(auth.token))
    from .reminders import RemindersTarget
    return RemindersTarget()


def cmd_setup(args, config) -> int:
    print("Ayarlar (Enter ile mevcut değeri koruyun)\n")
    target = _ask("Hedef: reminders (Apple Anımsatıcılar) / microsoft (Microsoft To Do)",
                  config["target"])
    config["target"] = "microsoft" if target.startswith("m") else "reminders"
    if config["target"] == "microsoft":
        config["ms_client_id"] = _ask("Microsoft uygulama (client) ID", config["ms_client_id"])
        config["ms_authority"] = _ask(
            "Hesap türü: consumers (kişisel) / organizations (iş-okul) / common",
            config["ms_authority"])
    mode = _ask("Liste düzeni: mirror (her Supernote listesi ayrı) / single (tek liste)",
                config["list_mode"])
    config["list_mode"] = "single" if mode.startswith("s") else "mirror"
    if config["list_mode"] == "single":
        config["target_list"] = _ask("Hedef liste adı", config["target_list"])
    else:
        config["list_prefix"] = _ask("Liste adı öneki (boş bırakılabilir)", config["list_prefix"])
    config["include_completed"] = _yes_no(
        "Supernote'ta zaten tamamlanmış görevler de aktarılsın mı?", config["include_completed"])
    config["complete_back"] = _yes_no(
        "Hedefte tamamlanan görevler Supernote'ta da tamamlansın mı?",
        config["complete_back"])
    config["delete_removed"] = _yes_no(
        "Supernote'tan silinen görevler hedeften de silinsin mi?",
        config["delete_removed"])
    while True:
        answer = _ask("Tarihli görevler için hatırlatma saati (SS:DD, kapatmak için -)",
                      config.get("alarm_time") or "-")
        if answer.strip() == "-":
            config["alarm_time"] = ""
            break
        if valid_alarm_time(answer):
            config["alarm_time"] = valid_alarm_time(answer)
            break
        print("Saat SS:DD biçiminde olmalı, ör. 09:00")
    config["notify"] = _yes_no(
        "Supernote'tan yeni görev gelince Mac'te bildirim gösterilsin mi?",
        config["notify"])
    save_config(config)
    print(f"\nKaydedildi: {config_path()}")
    return 0


def parse_account(text: str, country: str = "90") -> tuple[str, Optional[int]]:
    """"ad@ornek.com" -> (e-mail, None); "0532 123 45 67" -> ("5321234567", 90).

    A leading "+<code>" overrides ``country``: "+90 532 123 45 67" works too.
    """
    text = text.strip()
    if "@" in text:
        return text, None
    digits = "".join(ch for ch in text if ch.isdigit())
    if text.startswith("+") and digits.startswith(country):
        digits = digits[len(country):]
    digits = digits.lstrip("0")
    if not digits:
        raise ValueError("Geçerli bir e-posta veya telefon numarası girin.")
    return digits, int(country)


def cmd_login_supernote(args, config) -> int:
    saved = config.get("supernote_account") or config.get("supernote_email") or ""
    raw = args.account or _ask("Supernote hesabı (cep telefonu veya e-posta)", saved)
    if "@" in raw:
        account, country = parse_account(raw)
    else:
        code = args.country or _ask("Ülke kodu", str(config.get("supernote_country") or 90))
        account, country = parse_account(raw, code.lstrip("+"))
    password = getpass.getpass("Supernote şifre: ")
    client = SupernoteClient()

    def ask_code(where: str) -> str:
        print(f"Supernote {where} için bir doğrulama kodu gönderdi.")
        return _ask("Doğrulama kodu")

    token = client.login(account, password, ask_code, country_code=country)
    config["supernote_account"] = account
    config["supernote_country"] = country
    config.pop("supernote_email", None)
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


def _who(config: dict) -> str:
    account = config.get("supernote_account") or config.get("supernote_email") or ""
    country = config.get("supernote_country")
    return f"+{country} {account}" if country else account


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
            print(f"Supernote: {_who(config)} (oturum {days} gün daha geçerli)")
        else:
            print(f"Supernote: {_who(config)}")

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
        target = make_target(config)
        target_lists = target.lists()
        print(f"{target.name}: {len(target_lists)} liste")
        for l in target_lists:
            print(f"   - {l.name}{' (varsayılan)' if l.is_default else ''}")
    except TargetError as exc:
        print(f"Hedef: {exc}")
    return 0


def _apply_flags(args, config) -> None:
    if getattr(args, "target", None):
        config["target"] = args.target
    for key in ("include_completed", "complete_back", "delete_removed"):
        if getattr(args, key, False):
            config[key] = True


def _notify(config: dict, stats) -> None:
    if config.get("notify", True):
        notify_new_tasks(stats.created_titles)


def cmd_sync(args, config) -> int:
    _apply_flags(args, config)
    state = load_state(config["target"])
    syncer = Syncer(SupernoteClient(config["supernote_token"]), make_target(config),
                    config, state, dry_run=args.dry_run)
    stats = syncer.run()
    if not args.dry_run:
        save_state(config["target"], state)
        _notify(config, stats)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{stamp}] {'(deneme) ' if args.dry_run else ''}{stats.summary()}")
    return 1 if stats.errors else 0


def cmd_watch(args, config) -> int:
    _apply_flags(args, config)
    sn = SupernoteClient(config["supernote_token"])
    target = make_target(config)
    state = load_state(config["target"])

    def run_pass():
        stats = Syncer(sn, target, config, state, log=_log).run()
        save_state(config["target"], state)
        _notify(config, stats)
        return stats

    def reload_token() -> bool:
        # A `login-supernote` run while this keeps going takes effect at once.
        token = load_config().get("supernote_token") or ""
        changed, sn.token = token != sn.token, token
        return changed

    Watcher(sn, target, run_pass, interval=args.interval, log=_log,
            before_poll=reload_token).run()
    return 0


def cmd_install_app(args, config) -> int:
    from . import macapp
    try:
        macapp.install()
    except (RuntimeError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_uninstall_app(args, config) -> int:
    from . import macapp
    macapp.uninstall()
    return 0


def _log(message: str) -> None:
    print(message, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="supernote-todo",
        description="Supernote To-Do görevlerini Apple Anımsatıcılar'a "
                    "(veya Microsoft To Do'ya) aktarır.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Ayarları etkileşimli olarak yapılandır").set_defaults(func=cmd_setup)

    p = sub.add_parser("login-supernote", help="Supernote Cloud'a giriş yap")
    p.add_argument("--account", "--email", dest="account",
                   help="E-posta veya cep telefonu (ör. 5321234567)")
    p.add_argument("--country", help="Telefon için ülke kodu (varsayılan 90)")
    p.set_defaults(func=cmd_login_supernote)

    sub.add_parser("login-microsoft", help="Microsoft hesabına giriş yap (yalnızca Microsoft hedefi)") \
        .set_defaults(func=cmd_login_microsoft)
    sub.add_parser("status", help="Bağlantıları ve listeleri göster").set_defaults(func=cmd_status)

    p = sub.add_parser("sync", help="Görevleri hedefe aktar")
    p.add_argument("--target", choices=["reminders", "microsoft"],
                   help="Bu çalıştırma için hedefi değiştir")
    p.add_argument("--dry-run", action="store_true", help="Hiçbir şeyi değiştirmeden ne yapılacağını göster")
    p.add_argument("--include-completed", action="store_true",
                   help="Tamamlanmış görevleri de aktar")
    p.add_argument("--complete-back", action="store_true",
                   help="Hedefte tamamlananları Supernote'ta da tamamla")
    p.add_argument("--delete-removed", action="store_true",
                   help="Supernote'tan silinenleri hedeften de sil")
    p.set_defaults(func=cmd_sync)

    sub.add_parser("install-app", help="macOS: arka planda çalışan uygulamayı kur ve başlat") \
        .set_defaults(func=cmd_install_app)
    sub.add_parser("uninstall-app", help="macOS: arka plan uygulamasını durdur ve kaldır") \
        .set_defaults(func=cmd_uninstall_app)

    p = sub.add_parser("watch", help="Sürekli çalış, değişiklikleri hemen aktar")
    p.add_argument("--target", choices=["reminders", "microsoft"],
                   help="Bu çalıştırma için hedefi değiştir")
    p.add_argument("--interval", type=int, default=30, metavar="SN",
                   help="Supernote'u kaç saniyede bir yokla (varsayılan 30)")
    p.add_argument("--include-completed", action="store_true",
                   help="Tamamlanmış görevleri de aktar")
    p.add_argument("--complete-back", action="store_true",
                   help="Hedefte tamamlananları Supernote'ta da tamamla")
    p.add_argument("--delete-removed", action="store_true",
                   help="Supernote'tan silinenleri hedeften de sil")
    p.set_defaults(func=cmd_watch)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    try:
        return args.func(args, config)
    except (SupernoteError, TargetError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
