# Supernote → Microsoft To Do

Supernote'un yerleşik **To-Do** uygulamasındaki görevleri (elle eklenenler ve
bir not sayfasında daire içine alınarak oluşturulanlar) **Microsoft To Do**'ya
aktaran küçük bir komut satırı aracı.

- Supernote listelerin Microsoft To Do'da aynı adla oluşturulur (veya hepsi tek
  bir listeye gider).
- Başlık, açıklama, bitiş tarihi ve tamamlanma durumu aktarılır; bir not
  sayfasından gelen görevlerde not adı ve sayfa numarası açıklamaya eklenir.
- Supernote'ta değişen görevler Microsoft To Do'da güncellenir; tekrar tekrar
  çalıştırmak kopya oluşturmaz.
- İsteğe bağlı: Microsoft To Do'da (ör. telefonda) tamamladığın görev
  Supernote'ta da tamamlanır.

> **Uyarı:** Supernote'un To-Do bulutu için resmi bir API yok. Bu araç,
> Supernote Partner uygulamasının kullandığı uç noktaları kullanır
> (`viewer.supernote.com`). Ratta bunları değiştirirse araç çalışmayı
> bırakabilir. Tabletinde **Ayarlar → Hesap** altında Supernote Cloud
> senkronizasyonunun açık olduğundan emin ol; To-Do verileri buluta ancak böyle
> gider.

## Kurulum

Python 3.9+ gerekir.

```bash
git clone https://github.com/guneytosun/supernoteApple.git
cd supernoteApple
python3 -m venv ~/.venvs/supernote-todo
~/.venvs/supernote-todo/bin/pip install .
# Kolaylık için: export PATH="$HOME/.venvs/supernote-todo/bin:$PATH"
```

## 1. Microsoft uygulaması kaydı (bir kereye mahsus, ~5 dk)

Microsoft Graph'a erişmek için kendi (ücretsiz) uygulama kaydın gerekir:

1. <https://portal.azure.com> → **Microsoft Entra ID** → **App registrations**
   → **New registration**. (Kişisel Microsoft hesabınla girebilirsin.)
2. Ad: `Supernote ToDo` (herhangi bir şey).
   **Supported account types**: kişisel hesap (outlook.com / hotmail / live)
   kullanıyorsan *Personal Microsoft accounts only*; iş/okul hesabıysa
   *Accounts in this organizational directory only*.
   Redirect URI boş kalabilir → **Register**.
3. Açılan sayfadaki **Application (client) ID** değerini kopyala.
4. Sol menü **Authentication** → en altta **Allow public client flows** →
   **Yes** → **Save**.
5. **API permissions** → **Add a permission** → **Microsoft Graph** →
   **Delegated** → `Tasks.ReadWrite` ekle.

## 2. Yapılandırma ve giriş

```bash
supernote-todo setup              # client ID, hesap türü, liste düzeni, seçenekler
supernote-todo login-supernote    # e-posta + şifre; gerekirse e-postana gelen kod
supernote-todo login-microsoft    # verilen kodu microsoft.com/devicelogin'e gir
supernote-todo status             # iki taraftaki listeleri gösterir
```

`setup` sırasında hesap türü için: kişisel hesap → `consumers`, iş/okul →
`organizations`.

## 3. Senkronizasyon

```bash
supernote-todo sync --dry-run   # önce ne yapılacağını gör, hiçbir şey değişmez
supernote-todo sync             # aktar
supernote-todo sync --watch 15  # açık kaldıkça 15 dakikada bir
```

Örnek çıktı:

```
+ Faturayı öde
+ Toplantı notlarını gönder
~ Rapor yaz (due)
[2026-09-27 10:15] 2 yeni, 1 güncellendi, 0 Supernote'ta tamamlandı, 0 silindi, 3 atlandı
```

### Seçenekler

`setup` ile kalıcı olarak veya `sync` komutuna bayrak olarak verilebilir:

| Ayar | Bayrak | Varsayılan | Açıklama |
|---|---|---|---|
| `list_mode` | – | `mirror` | `mirror`: her Supernote listesi için aynı adlı To Do listesi. `single`: hepsi `target_list`'e. Hiçbir listede olmayan görevler `mirror` modunda To Do'nun varsayılan **Görevler** listesine gider. |
| `list_prefix` | – | boş | Oluşturulan liste adlarının başına eklenir (ör. `SN - `). |
| `include_completed` | `--include-completed` | kapalı | Supernote'ta zaten tamamlanmış görevleri de aktar. |
| `complete_back` | `--complete-back` | kapalı | To Do'da tamamlanan görevi Supernote'ta da tamamla. |
| `delete_removed` | `--delete-removed` | kapalı | Supernote'tan silinen görevi To Do'dan da sil. |

## Otomatik çalıştırma

**macOS (launchd):** `examples/com.supernote-todo.sync.plist` dosyasındaki
yolu `which supernote-todo` çıktısıyla değiştir, sonra:

```bash
cp examples/com.supernote-todo.sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.supernote-todo.sync.plist
tail -f /tmp/supernote-todo.log
```

**Linux / macOS (cron):**

```
*/15 * * * * $HOME/.venvs/supernote-todo/bin/supernote-todo sync >> $HOME/supernote-todo.log 2>&1
```

## Nasıl çalışır / bilinmesi gerekenler

- **Kaynak Supernote'tur.** Bir görev Supernote'ta değiştiğinde To Do'daki
  kopyası güncellenir. To Do'da yaptığın düzenlemeler, aynı görev Supernote'ta
  tekrar değişene kadar korunur.
- To Do'da **sildiğin** bir görev tekrar oluşturulmaz.
- Supernote'ta bir görevi başka listeye taşımak, To Do'daki kopyasını taşımaz.
- **Supernote oturumu 30 gün geçerlidir** ve otomatik yenilenemez (Supernote
  böyle bir uç nokta sunmuyor). `supernote-todo status` kalan günü gösterir;
  süresi dolunca `supernote-todo login-supernote` ile tekrar gir. Microsoft
  oturumu kendiliğinden yenilenir.
- Ayarlar, oturumlar ve eşleşme bilgisi `~/.config/supernote-todo/` altında
  yalnızca senin okuyabileceğin dosyalarda (`chmod 600`) tutulur. Farklı bir
  klasör için `SUPERNOTE_TODO_HOME` ortam değişkenini kullan. Şifren
  kaydedilmez.
- Eşleşme dosyası (`state.json`) kaybolursa kopya oluşmaz: aracın
  oluşturduğu her görev, Supernote görev kimliğini taşıyan bir bağlantı içerir
  ve bir sonraki çalıştırmada eşleşmeler buradan geri kurulur.

## Geliştirme

```bash
pip install -e '.[dev]'
pytest
```
