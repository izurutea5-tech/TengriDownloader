# Tengri Downloader — by tengritoon.site

Манга, манхва уншиж татдаг PC програм. **Windows, macOS, Linux** дээр ажиллана. Suwayomi-ийн хөдөлгүүрийг дотроо ажиллуулдаг тул Keiyoushi-ийн 1000+ сайтын өргөтгөлийг ашиглах боломжтой.

## Эхлүүлэх

### Windows
1. [Python 3.8+](https://www.python.org/downloads/) суулгана (суулгахдаа **Add to PATH**-г чагтална).
2. **`Tengri Downloader.bat`** дээр давхар дарна. Анх удаа сангуудаа өөрөө суулгана.
3. (Сонголтоор) **`Desktop shortcut.bat`** — Desktop болон Start цэсэнд Tengri логотой товчлол үүсгэнэ. Taskbar дээр Python-ий биш, Tengri-ийн дүрс харагдана.

### macOS
1. Python 3: https://www.python.org/downloads/macos/ эсвэл `brew install python`.
2. **`Tengri Downloader.command`** дээр давхар дарна.
   - «unidentified developer» гэвэл: файл дээр **баруун товч → Open → Open**.
   - Эсвэл Terminal-д: `bash "Tengri Downloader.command"`.

### Linux
```bash
sudo apt install python3 python3-venv          # Ubuntu / Debian / Mint
# (сонголтоор, тусдаа цонхонд нээх бол) sudo apt install python3-gi gir1.2-webkit2-4.1
./tengri-downloader.sh
```
Програмын цэсэнд нэмэх бол: `tools/install-linux-desktop.sh`. GTK WebKit суугаагүй бол програм таны хөтөч дээр нээгдэнэ (`http://127.0.0.1:4568`).

## Хөдөлгүүр (1000+ сайт)
**Тохиргоо → Хөдөлгүүр → «⬇ Автоматаар татах»** дарна. Програм таны системийг (Windows / Mac Intel / Mac Apple Silicon / Linux) өөрөө таньж, GitHub-аас Suwayomi-ийн сүүлийн хувилбарыг татна. Компьютерт Java 21+ байхгүй бол Java-г хамт татна.

Эсвэл гараар зааж болно: Suwayomi-ийн хавтас, `.zip` (Windows), `.tar.gz` (Mac/Linux) эсвэл `Suwayomi-Server.jar`.

Дараа нь: **Хайх → Repo → Keiyoushi → Нэмэх**, **Хайх → Өргөтгөл** хэсгээс сайтуудаа суулгана.

## Хэсгүүд
- **Хайх (Ctrl+K)**: дээд талын хайлтын нүдээс бүх эх сурвалжаас нэг дор хайна. Хайх хүрээг сонгож болно: сонгосон хэл, тогтоосон 📌, өөрийн сайтууд, эсвэл бүгд. Нэг зэрэг 5-аас илүү хүсэлт явуулахгүй тул хөдөлгүүр гацахгүй, олдсон үр дүн шууд гарч ирнэ.
- **Номын сан**: «Үргэлжлүүлэн унших» хэсэг, хайлт ( / ), эрэмбэлэлт, шүүлтүүр, ангилал, уншаагүй бүлгийн тоо.
- **Шинэчлэлт**, **Түүх**, **Татаж буй**, **Татагдсан**.
- **Уншигч**: Webtoon болон хуудсаар гэсэн хоёр горимтой. Товчлолууд: Space, ← →, [ ] (бүлэг солих), M (горим), F (бүтэн дэлгэц), Esc (буцах).
- **Тохиргоо**: татах хавтас (Сонгох… товчтой), CBZ, өнгөний сэдэв, нөөцлөлт/сэргээлт, кэш, хөдөлгүүр.

## Бэлэн эх сурвалжууд (хөдөлгүүргүйгээр)
MangaDex, SushiScan (франц), мөн Madara / MangaThemesia загвартай дурын сайт («Холбоосоор нээх» хэсгээр).

## Автомат шинэчлэлт
Шинэ хувилбар гармагц програм түүнийг **цаана нь өөрөө татна** (асах үед болон 6 цаг тутамд шалгадаг). Татагдаж дуусмагц «бэлэн боллоо» гэсэн мэдэгдэл гарна. **Дараагийн асалтад автоматаар суулгана**, эсвэл «Одоо дахин асаах» дарвал шууд суулгана. Номын сан, тохиргоо, өргөтгөлүүд хэвээр үлдэнэ. Тохиргоо → Програм хэсгээс автомат татахыг унтрааж болно (тэгвэл зөвхөн мэдэгдэл гарна).

### Шинэ хувилбар гаргах (хөгжүүлэгчид)
1. `app.py` доторх `VERSION`-ийг нэмэгдүүл (жишээ нь `"3.2"`).
2. (Сонголтоор) `RELEASE_NOTES.txt`-д шинэчлэлтийн тайлбар бич.
3. `python tools/make-release.py 3.2` → `dist_release/` дотор `TengriDownloader-3.2.zip` ба `latest.json` үүснэ.
4. GitHub Release гарга: `gh release create v3.2 dist_release/TengriDownloader-3.2.zip --title "Tengri Downloader 3.2" --notes-file dist_release/github-notes.md` (эсвэл GitHub → Releases → Draft a new release, zip-ээ хавсаргаж, `github-notes.md`-ийн текстийг тайлбарт хуул). Хэрэглэгчдийн програм `github:izurutea5-tech/TengriDownloader`-аас шинэчлэлтийг өөрөө олно.

Шинэчлэлтийн эх сурвалжийг Тохиргооноос сольж болно: `https://…/latest.json` эсвэл `github:owner/repo` (анхдагч: `github:izurutea5-tech/TengriDownloader`). Татсан файлыг `sha256`-аар шалгадаг тул гэмтсэн/өөрчлөгдсөн файл суухгүй.

## Windows .exe (хамгийн хялбар)
GitHub-ийн [Releases](https://github.com/izurutea5-tech/TengriDownloader/releases/latest) хуудаснаас **TengriDownloader.exe**-г татаад давхар дар. Python болон бусад зүйл суулгах шаардлагагүй. Номын сан, тохиргоо `%LOCALAPPDATA%\Tengri Downloader`-д, татсан манга `Documents\Tengri Downloader`-д хадгалагдана. .exe нь шинэ хувилбар гармагц **өөрөө шинэчлэгдэнэ**.

Шинэ хувилбар гаргахдаа `app.py` доторх `VERSION`-ийг өөрчилж commit хийгээд `git tag v3.2 && git push --tags` гэхэд GitHub Actions .exe болон zip-ийг өөрөө бүтээж Release гаргана.

## Программ болгох (гараар)
- Windows: `tools/build-windows-exe.bat` → `dist/TengriDownloader/TengriDownloader.exe`
- macOS: `tools/build-macos-app.sh` → `dist/Tengri Downloader.app`
- **Анхаар:** гараар бүтээсэн `.exe` хавтас болон `.app` автоматаар шинэчлэгдэхгүй (GitHub Release-ийн дан .exe шинэчлэгддэг) (шинэ хувилбарыг гараар татна). Эх кодоор (.bat/.sh/.command) ажиллуулсан хувилбар автоматаар шинэчлэгдэнэ. (өгөгдөл `~/Library/Application Support/Tengri Downloader`-д хадгалагдана)

## Асуудал гарвал
- `debug (console).bat` (Windows) эсвэл `./tengri-downloader.sh --browser` (Mac/Linux): програмыг хөтөч дээр, алдааны мэдээлэлтэйгээр ажиллуулна.
- `data/engine.log`: хөдөлгүүрийн лог.
- Програм аль хэдийн ажиллаж байхад дахин асаавал шинээр асахгүй, байгаа цонхыг нээнэ. 4568 порт эзэлсэн бол дараагийн сул портыг ашиглана.

## Izuru Manga-гаас шилжих
Хуучин `Izuru Manga` хавтсаас `data`, `engine`, `downloads` хавтсуудыг энэ хавтас руу хуулна. Номын сан, уншсан түүх, өргөтгөлүүд тань хэвээр үлдэнэ.
