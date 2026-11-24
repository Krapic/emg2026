# Pokretanje EMG laboratorija

Uključite Bluetooth, dinamometar i odabrane Shimmere. Izvadite Shimmere iz
docka i zatvorite druge aplikacije koje koriste uređaje. Ručku dinamometra
ostavite neopterećenom tijekom početnog nuliranja.

U terminalu u korijenu projekta pokrenite:

```bash
./pokreni.sh
```

Pokretač koristi jedan Shimmer pri 512 Hz. Prvo pokušava iskoristiti postojeći
ROS tok, a zatim isprobava uparene uređaje dok ne dobije svježe uzorke.
Za izravan odabir uređaja 4C91, za koji je snimljen referentni model,
koristite `./pokreni.sh --shimmers 1`. Za snimanje s više uređaja navedite
njihove brojeve, primjerice `./pokreni.sh --shimmers 1 2 3`.
Brojevi 1–4 odgovaraju uređajima 4C91, 9D2C, 4C87 i 9D23. Uređaj 9D23 u
[dijagnostici od 30. listopada](diagnostics/9D23/README.md) nije dao valjan
EMG tok, pa ga prije snimanja provjerite s `./pokreni.sh --shimmers 4`.
Skripta sama učitava ROS Humble, provjerava Bluetooth i po potrebi
priprema RFCOMM portove. Ako zatraži `sudo`, lozinku unesite u terminal.

Pokretač provjerava podatke s uređaja, pokreće obradu i čeka servise za snimanje,
treniranje i učitavanje modela. Kad ispiše **SPREMNO**, u PlotJuggleru potvrdite
odabrane topice s **OK**. PlotJuggler prikazuje Shimmere koji se koriste za snimanje.
Uz izmjerenu silu prikazuje se cilj tijekom
vođenog snimanja i procjena nakon učitavanja modela.

```bash
./pokreni.sh status      # provjera svježih sirovih i obrađenih tokova i sile
./pokreni.sh stop        # zaustavljanje procesa ovog pokretača
./pokreni.sh prepare     # priprema Bluetootha i porta za 9D2C
./pokreni.sh --no-gui    # cijeli sustav bez PlotJugglera
./pokreni.sh self-test   # tehnička provjera bez Bluetootha i sudionika
```

Pokretač možete zaustaviti i s **Ctrl+C**. Zapisnici su u
`.lab-run/<datum-vrijeme>/`. Skripta ponovno koristi postojeće sirove tokove
senzora pri istoj frekvenciji. Ako se obrada ili servisi već izvode iz zasebnog terminala, zaustavite
taj prethodni launch prije pokretanja skripte. Ako korisnik nema pristup
serijskim portovima, dodajte ga u grupu `dialout` i ponovno se prijavite.

Za prvu izgradnju sva tri paketa slijedite [upute za novo računalo](KRENI_OVDJE.md#prvo-kod-kuće). Nakon izmjene ROS koda izgradite odgovarajuće pakete.

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select emg_grip_interfaces --cmake-args -DAMENT_CMAKE_SYMLINK_INSTALL=OFF
source install/setup.bash
colcon build --symlink-install --packages-select shimmer_ros2
```

Za vođeno snimanje, treniranje i estimaciju pogledajte [upute za mjerenje](SNIMANJE_I_MODEL.md).

## Procjena bez dinamometra

Ako je laboratorij već pokrenut, zaustavite ga s `./pokreni.sh stop`. Sa
spremljenim modelom za Shimmer 4C91 pri 512 Hz pokrenite:

```bash
./pokreni.sh --model grip_data/models/5a7118ac2e564532a642e958fdc0eb69.json
```

Pokretač odabire Shimmer iz modela, pokreće obradu i automatski učitava
model. Ispisuje **SPREMNO** nakon primitka svježe procjene. PlotJuggler prikazuje
obrađeni EMG i estimiranu silu, a `./pokreni.sh status` provjerava oba EMG
toka i procjenu. Za snimanje i treniranje koristite redovno pokretanje uz
dinamometar.
