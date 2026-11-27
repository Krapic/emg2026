# EMG 2026 — procjena sile stiska iz površinskog EMG-a

[![Provjera](https://github.com/Krapic/emg2026/actions/workflows/provjera.yml/badge.svg)](https://github.com/Krapic/emg2026/actions/workflows/provjera.yml)

ROS 2 Humble projekt koji iz signala senzora Shimmer3 EMG procjenjuje silu stiska šake. Kao referenca pri snimanju i učenju služi dinamometar Vernier Go Direct. Projekt je seminarski rad iz kolegija Upravljanje mehatroničkim sustavima.

## Kako radi

1. `shimmer_ros2` čita EMG s jednog ili više Shimmera, a `godirect_ros2` silu s dinamometra.
2. `emg_processor` filtrira EMG u frekvencijskoj domeni, ispravlja ga i gladi.
3. `./pokreni.sh record` snima obrađeni EMG i izmjerenu silu dok ispitanik prati zadane razine stiska.
4. `./pokreni.sh train` uči linearni model s vremenskim odgodama EMG-a do 500 ms.
5. Uz učitan model sustav objavljuje procijenjenu silu na `/grip_force_estimated` pri 200 Hz.
6. Hankel-DMD prediktor produljuje procjenu do 0,5 s unaprijed i objavljuje je na `/grip_force_predicted`.

Jedna naredba, `./pokreni.sh`, uparuje uređaje, pokreće čvorove i otvara PlotJuggler.

## Stanje

Snimanje, treniranje i procjena su implementirani i prolaze test na sintetičkim tokovima, koji se na GitHubu ponavlja nakon svakog slanja. Još nije pokazano da model radi na pravom stisku: u priloženim snimkama `P01_ucenje` i `P01_validacija` ispitanik gotovo ne stišće, pa objavljena pogreška (RMSE 4,17 N) opisuje mirovanje. Predikcija je implementirana, ali na postojećim snimkama nije pokazala jasnu korist u odnosu na zadržavanje zadnje procjene. Što je provjereno i što preostaje stoji u [PLAN_RADA.md](PLAN_RADA.md).

## Brzi početak

Za rad sa senzorima treba Ubuntu 22.04 s ROS 2 Humble. Ovisnosti su navedene u [KRENI_OVDJE.md](KRENI_OVDJE.md#prvo-kod-kuće).

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install --cmake-args -DAMENT_CMAKE_SYMLINK_INSTALL=OFF
./pokreni.sh self-test
```

`self-test` ne treba opremu: snima dva pokusa iz sintetičkih tokova, trenira model i provjerava procjenu.

Priložene snimke i model možeš pregledati bez ROS-a, na bilo kojem sustavu s Pythonom i NumPyjem (na Windowsu `python` umjesto `python3`):

```bash
python3 scripts/analiza.py                    # sve snimke i modeli, s upozorenjima
python3 scripts/analiza.py check P01_ucenje   # cilj i držana sila po fazama snimke
python3 scripts/analiza.py evaluate           # pogreška modela po razinama sile
python3 scripts/analiza.py predict            # prognoza procjene prema zadržavanju zadnje vrijednosti
```

## Upute

- [KRENI_OVDJE.md](KRENI_OVDJE.md) — instalacija, što se može bez senzora i redoslijed rada s opremom.
- [PROVJERA_U_LABORATORIJU.md](PROVJERA_U_LABORATORIJU.md) — kontrolni popis za termin s opremom.
- [POKRETANJE.md](POKRETANJE.md) — pokretanje, Bluetooth i dijagnostika.
- [SNIMANJE_I_MODEL.md](SNIMANJE_I_MODEL.md) — maksimalni stisak, snimanje, treniranje i učitavanje modela.
- [PREDIKCIJA.md](PREDIKCIJA.md) — kako radi prognoza sile, kako je provjeriti i što je dosad pokazala.
- [PLAN_RADA.md](PLAN_RADA.md) — stanje implementacije i preostali koraci.

## Sadržaj

| Mapa ili datoteka | Sadržaj |
|---|---|
| `pokreni.sh`, `scripts/lab.py` | Pokretač laboratorija i naredbe `record`, `train`, `estimate`, `self-test`. |
| `scripts/analiza.py` | Izvještaj o snimkama i modelu bez ROS-a. |
| `src/shimmer_ros2` | Čitanje i obrada EMG-a, snimanje, treniranje, procjena i prognoza sile. |
| `src/godirect_ros2` | Čitanje sile s dinamometra i rasporedi za PlotJuggler. |
| `src/emg_grip_interfaces` | Definicije poruka i servisa. |
| `grip_data/` | Tri laboratorijske snimke jednog ispitanika i referentni model. |
| `tests/` | Testovi pokretača i izvještaja te sintetički integracijski test. |
| `diagnostics/`, `dokumenti/` | Ranija dijagnostika Shimmera 9D23 i Word vodič od 30. listopada 2026. |

## Podrijetlo i licenca

Paketi u `src/` potječu iz repozitorija autora Tomislava Bazine i izmijenjeni su za ovaj projekt; izvorne verzije i popis izmjena su u [src/README.md](src/README.md). Cijeli repozitorij je pod licencom [Apache-2.0](LICENSE).
