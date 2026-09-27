# Supernote → Apple Anımsatıcılar

Supernote'un yerleşik **To-Do** uygulamasındaki görevleri (elle eklenenler ve
bir not sayfasında daire içine alınarak oluşturulanlar) **Apple
Anımsatıcılar**'a (Reminders) aktaran küçük bir komut satırı aracı. Anımsatıcılar
iCloud üzerinden iPhone/iPad'e ve Anımsatıcılar'ı gösteren her yere (ör.
Microsoft To Do) kendiliğinden ulaşır.

- Supernote listelerin Anımsatıcılar'da aynı adla oluşturulur (veya hepsi tek
  bir listeye gider).
- Başlık, açıklama, bitiş tarihi ve tamamlanma durumu aktarılır; bir not
  sayfasından gelen görevlerde not adı ve sayfa numarası açıklamaya eklenir.
- Supernote'ta değişen görevler güncellenir; tekrar tekrar çalıştırmak kopya
  oluşturmaz.
- İsteğe bağlı: iPhone'da tamamladığın anımsatıcı Supernote'ta da tamamlanır.

Hedef olarak Microsoft To Do da seçilebilir (bkz. [Microsoft To Do
hedefi](#microsoft-to-do-hedefi)); bu bir Azure uygulama kaydı gerektirir.

> **Uyarı:** Supernote'un To-Do bulutu için resmi bir API yok. Bu araç,
> Supernote Partner uygulamasının kullandığı uç noktaları kullanır
> (`viewer.supernote.com`). Ratta bunları değiştirirse araç çalışmayı
> bırakabilir. Tabletinde Supernote Cloud senkronizasyonunun açık olduğundan
> emin ol; To-Do verileri buluta ancak böyle gider.

## Gereksinimler

- **macOS** (Anımsatıcılar'a Apple'ın EventKit çerçevesiyle yazılır; iCloud'un
  güncel Anımsatıcılar biçimine başka güvenilir bir yol yok) ve iCloud'da
  Anımsatıcılar açık.
- Python 3.9+ (`python3 --version`; yoksa `xcode-select --install` veya
  <https://www.python.org>).

## Kurulum

```bash
git clone https://github.com/guneytosun/supernoteApple.git
cd supernoteApple
python3 -m venv ~/.venvs/supernote-todo
~/.venvs/supernote-todo/bin/pip install .
# Kolaylık için ~/.zshrc'ye: export PATH="$HOME/.venvs/supernote-todo/bin:$PATH"
```

## Kullanım

```bash
supernote-todo setup              # liste düzeni ve seçenekler (hedef: reminders)
supernote-todo login-supernote    # e-posta + şifre; gerekirse e-postana gelen kod
supernote-todo status             # iki taraftaki listeleri gösterir
supernote-todo sync --dry-run     # ne yapılacağını gör, hiçbir şey değişmez
supernote-todo sync               # aktar
supernote-todo sync --watch 15    # açık kaldıkça 15 dakikada bir
```

İlk çalıştırmada macOS, Terminal'in Anımsatıcılar'a erişmesi için izin ister;
**Tam Erişim**'e izin ver. Yanlışlıkla reddettiysen: Sistem Ayarları →
Gizlilik ve Güvenlik → Anımsatıcılar → Terminal'i aç.

Örnek çıktı:

```
  Apple Reminders içinde 'İş' listesi oluşturuluyor
+ Faturayı öde
+ Toplantı notlarını gönder
~ Rapor yaz (due)
[2026-09-27 10:15] 2 yeni, 1 güncellendi, 0 Supernote'ta tamamlandı, 0 silindi, 3 atlandı
```

### Seçenekler

`setup` ile kalıcı olarak veya `sync` komutuna bayrak olarak verilebilir:

| Ayar | Bayrak | Varsayılan | Açıklama |
|---|---|---|---|
| `target` | `--target` | `reminders` | `reminders` (Apple Anımsatıcılar) veya `microsoft` (Microsoft To Do). |
| `list_mode` | – | `mirror` | `mirror`: her Supernote listesi için aynı adlı liste. `single`: hepsi `target_list`'e. Hiçbir listede olmayan görevler `mirror` modunda varsayılan listeye gider. |
| `list_prefix` | – | boş | Oluşturulan liste adlarının başına eklenir (ör. `SN - `). |
| `include_completed` | `--include-completed` | kapalı | Supernote'ta zaten tamamlanmış görevleri de aktar. |
| `complete_back` | `--complete-back` | kapalı | Hedefte tamamlanan görevi Supernote'ta da tamamla. |
| `delete_removed` | `--delete-removed` | kapalı | Supernote'tan silinen görevi hedeften de sil. |

## Otomatik çalıştırma

**macOS (launchd):** önce `supernote-todo sync`'i bir kez Terminal'den
çalıştırıp her şeyin yolunda olduğunu gör. Sonra
`examples/com.supernote-todo.sync.plist` dosyasındaki yolu
`which supernote-todo` çıktısıyla değiştir ve:

```bash
cp examples/com.supernote-todo.sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.supernote-todo.sync.plist
tail -f /tmp/supernote-todo.log
```

Arka planda çalışan süreç Terminal'in iznini devralmayabilir; macOS bu durumda
Python için ayrıca Anımsatıcılar izni isteyebilir. Günlükte "erişim izni yok" hatası
görürsen izni ver ya da bunun yerine bir Terminal penceresinde
`supernote-todo sync --watch 15` açık bırak.

## Nasıl çalışır / bilinmesi gerekenler

- **Kaynak Supernote'tur.** Bir görev Supernote'ta değiştiğinde karşıdaki
  kopyası güncellenir. Anımsatıcılar'da yaptığın düzenlemeler, aynı görev
  Supernote'ta tekrar değişene kadar korunur.
- Anımsatıcılar'da **sildiğin** bir görev tekrar oluşturulmaz.
- Supernote'ta bir görevi başka listeye taşımak, karşıdaki kopyasını taşımaz.
- **Supernote oturumu 30 gün geçerlidir** ve otomatik yenilenemez (Supernote
  böyle bir uç nokta sunmuyor). `supernote-todo status` kalan günü gösterir;
  süresi dolunca `supernote-todo login-supernote` ile tekrar gir.
- Ayarlar, oturumlar ve eşleşme bilgisi `~/.config/supernote-todo/` altında
  yalnızca senin okuyabileceğin dosyalarda (`chmod 600`) tutulur. Farklı bir
  klasör için `SUPERNOTE_TODO_HOME` ortam değişkenini kullan. Şifren
  kaydedilmez.
- Eşleşme dosyası (`state-reminders.json`) kaybolursa kopya oluşmaz: aracın
  oluşturduğu her anımsatıcının URL alanında `supernote-todo://task/…`
  işareti bulunur ve bir sonraki çalıştırmada eşleşmeler buradan geri kurulur.
  Bu URL alanını silme.

## Microsoft To Do hedefi

Anımsatıcılar yerine doğrudan Microsoft To Do'ya yazmak istersen (macOS
gerekmez) kendi Azure uygulama kaydın gerekir:

1. <https://portal.azure.com> → **Microsoft Entra ID** → **App registrations**
   → **New registration**. Hesap türü: kişisel hesap için *Personal Microsoft
   accounts only*. Redirect URI boş kalabilir.
2. **Application (client) ID** değerini kopyala.
3. **Authentication** → **Allow public client flows** → **Yes**.
4. **API permissions** → **Microsoft Graph** → **Delegated** → `Tasks.ReadWrite`.

Sonra `supernote-todo setup` içinde hedef olarak `microsoft` seç, client ID'yi
gir ve `supernote-todo login-microsoft` ile giriş yap. Şirket hesabında
uygulama kaydı yetkin yoksa bunu BT ekibinden istemen gerekir.

## Geliştirme

```bash
pip install -e '.[dev]'
pytest
```
