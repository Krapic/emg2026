# Dijagnostika Shimmera 9D23, 30. 10. 2026.

- Bluetooth MAC: `60:8A:10:40:9D:23`.
- Uparivanje i trust uspješno dovršeni automatskim unosom standardnog PIN-a.
- SDP potvrđuje SerialPort na RFCOMM kanalu **6**, ne 1.
- `/dev/rfcomm3` vezan je na ispravnu adresu i kanal.
- Veza se otvara, ali nema valjanih odgovora na upite naziva, firmwarea,
  hardvera i inquiry. Pojavljuju se prazni odgovori i prekidi serijske veze.
- Testiran je i samostalno, uz zaustavljene druge EMG tokove i BLE dinamometar;
  ni tada nisu dobiveni odgovori na osnovne upite.
- USB uređaj identificiran kao **Shimmer Base6U Rev2**, četiri FTDI porta.
- Upravljački kanal baze: `/dev/ttyUSB1`, 115200 8N1, DTR=false, RTS=true.
- Baza vraća `V,2,1,0,1,0` i zauzetost `Q,001000` (utor 3).
- Odabir UART pristupa utoru potvrđen je s `P,03`, ali konfiguracija firmwarea
  senzora nije uspješno očitana preko UART-a. Verzija samog senzora ostaje
  nepotvrđena.
- SD pristup utoru potvrđen je s `C,03`. Kartica se pojavila kao
  `/dev/sda1`, montirana na `/media/ums-08/94FB-E101`.
- `sdlog.original.cfg` je neizmijenjena sigurnosna kopija pročitane datoteke.
  To je konfiguracijska datoteka SD kartice, ne puna sigurnosna kopija firmwarea
  ili njegove konfiguracijske memorije.
- U izvorniku: EXG1 24-bit uključen, sampling 250.14 Hz, sync=0,
  shimmername=S9D23, baud_rate=11.
- Kao ograničena dijagnostička izmjena promijenjen je samo `baud_rate=11` u
  `baud_rate=9` (460800 bit/s), uz provjeru zapisa. Kartica je sigurno odmontirana
  i SD pristup baze zatvoren prije fizičkog ponovnog uključivanja.
- Izmjena nije dovela do potvrđenog prijenosa EMG-a. Nije potvrđeno je li
  firmware preuzeo izmjenu iz datoteke. Nije mijenjan firmware ni kalibracija.

Kod 11 označava 1 Mbit/s i dopušten je na određenim verzijama RN4678 radija;
nije sam po sebi dokaz pogrešne konfiguracije. Službeni kod bilježi probleme
na verzijama 1.13.5 i 1.22, dok ga podržava 1.23:
[shimmer_bt_uart.h](https://github.com/ShimmerResearch/log-and-stream-common/blob/main/Comms/shimmer_bt_uart.h).

Sljedeća provjera: u Consensysu očitati točnu verziju firmwarea i radija te
usporediti konfiguraciju s ispravnim uređajem 9D2C. Ako to nije moguće ni preko
baze, provjeriti kontakte, napajanje i uređaj s nastavnikom. Reset ili ponovno
programiranje nisu provedeni na temelju nepotvrđene dijagnoze.
