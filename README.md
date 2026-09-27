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
~/.venvs/supernote-todo/bin/pip install --upgrade pip
~/.venvs/supernote-todo/bin/pip install .
echo 'export PATH="$HOME/.venvs/supernote-todo/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Kurulum hata verdiyse (`Failed to build pyobjc-core`) ya da `command not found:
supernote-todo` görüyorsan: bu klasörde `git pull` yapıp yukarıdaki pip
komutlarını tekrar çalıştır. `supernote-todo`, `PATH` ayarlanmadan önce
`~/.venvs/supernote-todo/bin/supernote-todo` olarak da çağrılabilir.

## Kullanım

```bash
supernote-todo setup              # liste düzeni ve seçenekler (hedef: reminders)
supernote-todo login-supernote    # e-posta + şifre; gerekirse e-postana gelen kod
supernote-todo status             # iki taraftaki listeleri gösterir
supernote-todo sync --dry-run     # ne yapılacağını gör, hiçbir şey değişmez
supernote-todo sync               # bir kez aktar
supernote-todo watch              # sürekli çalış, değişiklikleri hemen aktar
```

### Anlık senkronizasyon (`watch`)

`supernote-todo watch` açık kaldığı sürece:

- **Anımsatıcılar → Supernote** (`complete_back` açıksa) anlıktır: macOS
  Anımsatıcılar'daki her değişikliği (iPhone'dan iCloud ile gelenler dahil)
  bildirir, araç ~2 saniye içinde senkronize eder.
- **Supernote → Anımsatıcılar**: Supernote Cloud bildirim göndermediği için
  30 saniyede bir tek bir küçük istekle yoklanır (`--interval` ile
  değiştirilebilir); yalnızca bir şey değiştiyse tam senkronizasyon yapılır.
  Toplam gecikme = tabletin buluta senkronize etme süresi + en fazla 30 sn.
  Tablette görev ekledikten sonra hemen görmek istersen tabletten elle
  senkronize et.
- Güvenlik ağı olarak her 10 dakikada bir tam senkronizasyon yapılır. Hata
  olursa bekleme süresi giderek uzar; Supernote oturumu dolduysa 30 dakikada
  bir tekrar denenir.

Terminal'den ilk çalıştırmada macOS, Terminal'in Anımsatıcılar'a erişmesi için
izin ister; **Tam Erişim**'e izin ver. Yanlışlıkla reddettiysen: Sistem
Ayarları → Gizlilik ve Güvenlik → Anımsatıcılar → Terminal'i aç. Arka planda
çalıştırmak için aşağıdaki `install-app` bölümüne bak.

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

## Arka planda sürekli çalıştırma (macOS)

```bash
supernote-todo install-app
```

Bu komut `~/Applications/Supernote ToDo.app` adında küçük bir uygulama
oluşturur, onu Giriş Öğeleri'ne ekler ve başlatır. Uygulama Dock'ta görünmez;
arka planda `supernote-todo watch` çalıştırır ve kapanırsa bir dakika içinde
yeniden başlatır. İlk açılışta macOS **"Supernote ToDo" Anımsatıcılar'a
erişmek istiyor** diye sorar; izin ver. Sistem Etkinlikleri'ni (System Events)
denetleme izni sorarsa ona da izin ver (Giriş Öğeleri'ne eklemek için).

```bash
tail -f ~/Library/Logs/supernote-todo.log   # günlük
supernote-todo uninstall-app                # durdur ve kaldır
```

Kodu güncelledikten sonra (`git pull && pip install .`) `supernote-todo
install-app` komutunu tekrar çalıştır.

> **Neden launchd değil?** macOS Anımsatıcılar iznini bir *uygulamaya* verir.
> launchd ile başlatılan bir süreç hiçbir uygulamaya bağlı olmadığı için
> izin penceresi hiç çıkmadan reddedilir ve Sistem Ayarları'nda da
> görünmez. Daha önce launchd görevini kurduysan `install-app` onu
> kendiliğinden kaldırır.

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
