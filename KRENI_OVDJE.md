# EMG 2026 — nastavak rada

Projekt procjenjuje silu stiska iz prvog kanala površinskog EMG-a. U repozitoriju su tri ROS 2 paketa s izmjenama za ovaj projekt, pokretač, tri laboratorijske snimke te referentni model za Shimmer **4C91 pri 512 Hz**.

## Prvo kod kuće

Kloniraj repozitorij i otvori terminal u mapi `emg2026`. Projekt je provjeren na Ubuntu 22.04 s ROS 2 Humble i sistemskim Pythonom 3.10. Ako trebaš instalirati ROS, odaberi `ros-humble-desktop` prema [službenim uputama za ROS 2 Humble](https://github.com/ros2/ros2_documentation/blob/humble/source/Installation/Ubuntu-Install-Debs.rst).

Jednokratno instaliraj ovisnosti projekta nakon što podesiš ROS repozitorij za APT.

```bash
sudo apt update
sudo apt install build-essential cmake python3-colcon-common-extensions \
  python3-pip python3-numpy python3-scipy python3-yaml python3-serial \
  python3-pexpect bluez psmisc ros-humble-plotjuggler-ros ros-humble-rosbag2
/usr/bin/python3 -m pip install --user godirect==1.2.1
```

Izgradi pakete iz korijena projekta pa pokreni integracijski test. Test koristi sintetičke tokove, snima dva pokusa i provjerava treniranje i estimaciju. Oprema za taj test nije potrebna.

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install --cmake-args -DAMENT_CMAKE_SYMLINK_INSTALL=OFF
./pokreni.sh self-test
```

Čista izgradnja sva tri paketa, sintetički integracijski test i testovi pokretača i čitanja EMG paketa prošli su 24. studenoga 2026. u ROS 2 Humble kontejneru na GitHubu. Ista se provjera ponavlja nakon svakog slanja; stanje je u [PLAN_RADA.md](PLAN_RADA.md#što-je-provjereno).

`colcon` ponovno stvara `build/`, `install/` i `log/` za tvoje računalo. Git čuva izvršnu dozvolu skripti. Ako projekt preuzmeš kao ZIP i ona nestane, vrati je naredbom `chmod +x pokreni.sh src/shimmer_ros2/scripts/bind_shimmer_to_rfcomm.sh`.

## Što možeš napraviti bez senzora

Pregledaj priložene snimke i model. Dovoljan je Python s NumPyjem, bez ROS-a, pa naredbe rade i na Windowsu (ondje `python` umjesto `python3`).

```bash
python3 scripts/analiza.py                    # sve snimke i modeli, s upozorenjima
python3 scripts/analiza.py check P01_ucenje   # cilj i držana sila po fazama snimke
python3 scripts/analiza.py evaluate           # pogreška najnovijeg modela po razinama sile
```

Snimku zadaj oznakom sesije ili početkom ID-ja. `evaluate` koristi iste funkcije za značajke i metrike kao trener i reproducira **5 900 redaka, MAE 3,57 N, RMSE 4,17 N** na snimci `P01_validacija`. Na istim redcima model bez vremenskih odgoda imao je RMSE 5,04 N.

Izvještaj pokazuje i da `P01_validacija` ne sadrži stisak, a `P01_ucenje` samo nekoliko kratkih koji ne prate zadane razine. Gornje brojke zato opisuju pogrešku u mirovanju. Za ocjenu modela trebaju nove snimke u kojima ispitanik prati ciljeve.

Testovi jezgre i izvještaja također rade bez ROS-a.

```bash
python3 tests/test_analiza.py
(cd src/shimmer_ros2 && python3 -m pytest test/test_grip_data.py test/test_grip_report.py)
```

Dok nemaš opremu, možeš pripremiti skriptu za usporedbu signala po `header.stamp` i prvi offline pokus predikcije. Za Hankel-DMD usporedi horizonte 100, 250 i 500 ms s prognozom koja zadržava posljednju dostupnu estimaciju. Pri odabiru ciljnog vremena koristi stvarni trenutak izdavanja prognoze. Za završnu provjeru pripremi odvojene cijele snimke.

## Što prvo napraviti kad imaš opremu

1. Priključi Shimmer **4C91** i Vernier Go Direct dinamometar. Ostavi ručku neopterećenom tijekom nuliranja. Pokreni `./pokreni.sh --shimmers 1`. Nakon poruke **SPREMNO**, iz drugog terminala u istoj mapi snimi maksimalni stisak i dva vođena pokusa, pa istreniraj i aktiviraj novi model. Priloženi model učen je gotovo samo na mirovanju, pa ne služi za ocjenu.

   ```bash
   ./pokreni.sh record P02_mvc --free
   ./pokreni.sh record P02_pokus1 --mvc-from P02_mvc
   ./pokreni.sh record P02_pokus2 --mvc-from P02_mvc
   ./pokreni.sh train P02_pokus1 --validation P02_pokus2 --activate
   ```

   Nakon svake snimke pročitaj izvještaj. Ako javi da zadane razine nisu praćene, ponovi pokus pod novom oznakom. Pojedinosti su u [uputama za MVC i snimanje](SNIMANJE_I_MODEL.md#snimanje).

2. Uz aktivan model napravi novi pokušaj i zabilježi oba toka sile i obrađeni EMG. U PlotJuggleru usporedi izmjerenu i estimiranu silu. Zasebna snimka ROS topica čuva i procjenu uživo, koju `record` ne sprema u CSV.

   ```bash
   source /opt/ros/humble/setup.bash
   source install/setup.bash
   mkdir -p grip_eval
   ros2 bag record -o grip_eval/pokus_01 /grip_force_stream \
     /grip_force_estimated /shimmer1/emg_processed /grip_force_target
   ```

   Nakon pokušaja zaustavi `ros2 bag record` s `Ctrl+C` i provjeri broj poruka naredbom `ros2 bag info grip_eval/pokus_01`. Za sljedeći pokušaj koristi novo ime izlaza.

3. Pogrešku modela po razinama sile na bilo kojoj spremljenoj snimci daje `python3 scripts/analiza.py evaluate --recordings OZNAKA`. Za procjenu uživo izračunaj MAE i RMSE u njutnima nakon poravnanja po vremenu uzorka. Zabilježi razliku između vremena primitka procjene i `header.stamp`, barem medijan i 95. percentil. Pogledaj i pogrešku pri stisku i otpuštanju. Zapiši položaj ruke i elektroda te dogovori pragove točnosti i prihvatljivog kašnjenja.

4. Za demonstraciju zaustavi redovno pokretanje s `./pokreni.sh stop`. Zatim provjeri način samo s 4C91 i učitanim novim modelom naredbom `./pokreni.sh --model grip_data/models/ID_MODELA.json`.

Provjera novog modela uživo s opremom i demonstracija bez dinamometra ostaju otvorene. Ako koristiš drugi primjerak dinamometra, provjeri naziv uređaja i kalibraciju u `src/godirect_ros2/config/hand_dynamometer_config.yaml` prije mjerenja.

## Gdje je što

- [PROVJERA_U_LABORATORIJU.md](PROVJERA_U_LABORATORIJU.md) — kontrolni popis za termin s opremom: što provjeriti i kada je korak prošao.
- [POKRETANJE.md](POKRETANJE.md) — pokretanje, Bluetooth i dijagnostika.
- [SNIMANJE_I_MODEL.md](SNIMANJE_I_MODEL.md) — MVC, snimanje, treniranje, učitavanje i identifikatori snimki.
- [PLAN_RADA.md](PLAN_RADA.md) — stanje implementacije, preostali koraci i radovi za predikciju.
- `grip_data/recordings/` — `P01_mvc`, `P01_ucenje` i `P01_validacija`. Svaka je u mapi označenoj ID-jem iz uputa.
- `src/shimmer_ros2/shimmer_ros2/grip_data.py` i `nodes/grip_estimator.py` unutar istog Python paketa — funkcije za poravnanje i regresiju te ROS čvor za estimaciju.
- `scripts/analiza.py` i `src/shimmer_ros2/shimmer_ros2/grip_report.py` — izvještaj o snimkama i modelu bez ROS-a te provjere na kojima se temelji.
- `tests/` i `src/shimmer_ros2/test/` — testovi pokretača i izvještaja te testovi jezgre i čitanja EMG paketa.
- `src/` — tri ROS 2 paketa preuzeta iz repozitorija autora `tbazina`. Izvorne verzije i popis izmjena su u [src/README.md](src/README.md).
- `.github/workflows/provjera.yml` — provjera na GitHubu nakon svakog slanja: testovi bez ROS-a te izgradnja i sintetički test u ROS 2 Humble.
- `diagnostics/9D23/` i `dokumenti/` — ranija dijagnostika Shimmera 9D23 i Word vodič od 30. listopada. Za trenutačno pokretanje slijedi upute iz ove mape.
