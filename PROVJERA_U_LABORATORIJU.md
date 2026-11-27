# Provjera u laboratoriju

Kontrolni popis za termin s opremom. Koraci idu od instalacije prema procjeni uživo. Ne prelazi na sljedeći dok prethodni ne prođe: tako se odmah vidi je li problem u senzoru, snimci ili modelu.

Primjeri koriste oznake `P02_…`. Za svakog novog ispitanika ili ponovljeni pokus uzmi novu oznaku.

## 1. Instalacija, bez opreme

Repozitorij je privatan, pa se na laboratorijskom računalu prvo prijavi na GitHub (`gh auth login` ili osobni pristupni token). Ovisnosti su u [KRENI_OVDJE.md](KRENI_OVDJE.md#prvo-kod-kuće).

```bash
git clone https://github.com/Krapic/emg2026.git
cd emg2026
source /opt/ros/humble/setup.bash
colcon build --symlink-install --cmake-args -DAMENT_CMAKE_SYMLINK_INSTALL=OFF
./pokreni.sh self-test
```

- [ ] `self-test` završava retkom s RMSE-om validacije i bez greške. Na GitHubu je dao 0,87 N.

## 2. Senzori pojedinačno

Uključi Shimmer 4C91 i dinamometar, ručku ostavi neopterećenom i pokreni `./pokreni.sh --shimmers 1`. Nakon poruke **SPREMNO** radi u drugom terminalu.

- [ ] `./pokreni.sh status` potvrđuje svježe tokove sirovog EMG-a, obrađenog EMG-a i sile.
- [ ] Dinamometar bez dodira pokazuje oko 0 N, pri stisku raste i vraća se na nulu.
- [ ] Ako postoji uteg poznate mase: 5 kg na ručki daje oko 49 N.
- [ ] Obrađeni EMG je u mirovanju nizak i miran, a pri stisku jasno raste i pada s otpuštanjem.

Ako EMG ne reagira na stisak, problem su elektrode ili njihov položaj, a ne softver. Ne snimaj dok ovo ne prođe.

## 3. Snimanje

```bash
./pokreni.sh record P02_mvc --free
./pokreni.sh record P02_pokus1 --mvc-from P02_mvc
./pokreni.sh record P02_pokus2 --mvc-from P02_mvc
./pokreni.sh record P02_pokus3 --mvc-from P02_mvc
```

U snimci `P02_mvc` ispitanik jednom stisne najjače što može. U ostalima prati ciljeve od 100, 75, 50 i 25 % tog stiska. Između pokusa odmori ruku minutu do dvije i ne pomiči elektrode.

Nakon svake snimke provjeri ispis:

- [ ] Ostvarene frekvencije su blizu 512 Hz za EMG i 200 Hz za silu, a pokrivenost je iznad 80 %.
- [ ] Vršna sila u `P02_mvc` je stvarni maksimalni stisak, a ne nekoliko njutna.
- [ ] U tablici faza držana sila prati cilj na sve četiri razine i nema retka s uskličnikom.

Ako izvještaj javi da razine nisu praćene, ponovi pokus pod novom oznakom, primjerice `P02_pokus1b`. U snimkama P01 nitko nije stiskao, pa model učen na njima ne govori ništa.

## 4. Treniranje

```bash
./pokreni.sh train P02_pokus1 --validation P02_pokus2 --activate
```

Gledaj tablicu pogreške po razinama sile, a ne samo ukupni RMSE.

- [ ] Nema upozorenja da snimka sadrži premalo stiska.
- [ ] Pogreška pri stisku nije višestruko veća nego u mirovanju.
- [ ] Pomak nije stalno negativan na višim razinama. Model učen na P01 od polovice sile naviše procjenjuje premalo.
- [ ] Zapisan je RMSE validacije u N i kao postotak maksimalnog stiska.

Prag za „dovoljno dobro” još nije dogovoren s nastavnicima. Zapisani brojevi su podloga za taj dogovor.

## 5. Procjena uživo i neovisna provjera

- [ ] Uz aktivan model ispitanik stisne nekoliko puta. U PlotJuggleru se procijenjena sila po obliku poklapa s izmjerenom, uz vidljivo kašnjenje.
- [ ] `python3 scripts/analiza.py evaluate --recordings P02_pokus3` daje pogrešku na snimci koju model nije vidio ni pri učenju ni pri validaciji. To je broj za seminar.
- [ ] Zelena krivulja prognoze nastavlja se na procijenjenu silu i pri stisku je prestiže, bez skokova i bez bježanja izvan raspona sile.
- [ ] `python3 scripts/analiza.py predict --recordings P02_pokus3` pokazuje je li prognoza bolja od zadržavanja zadnje procjene. Tumačenje je u [PREDIKCIJA.md](PREDIKCIJA.md#provjera-na-snimkama).
- [ ] Tok uživo je spremljen naredbom `ros2 bag record` iz [KRENI_OVDJE.md](KRENI_OVDJE.md#što-prvo-napraviti-kad-imaš-opremu). Bez te snimke točnost i kašnjenje procjene uživo ne mogu se izračunati naknadno.
- [ ] Po želji: demonstracija samo sa Shimmerom i modelom prema [uputama za procjenu bez dinamometra](POKRETANJE.md#procjena-bez-dinamometra), s putanjom novog modela.

## 6. Prije odlaska

- [ ] Zapisani su ispitanik (oznaka), ruka, položaj elektroda i položaj ruke tijekom pokusa.
- [ ] Snimke i model su poslani na GitHub.

  ```bash
  git add grip_data
  git commit -m "Snimke P02"
  git push
  ```

- [ ] Mapa `grip_eval/` s bag snimkom kopirana je ručno. Git je namjerno preskače, kao i zapisnike u `.lab-run/`, koje treba ponijeti ako nešto nije radilo.
