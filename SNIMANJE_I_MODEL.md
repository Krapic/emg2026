# Snimanje EMG-a i estimacija sile stiska

U terminalu u korijenu projekta pokrenite:

```bash
./pokreni.sh
```

Skripta odabire jedan dostupan Shimmer za snimanje i prikaz, pokreće
dinamometar, obradu i servise. Za izravan odabir koristite `--shimmers BROJ`.
Za snimanje sa sva četiri dodajte `--shimmers 1 2 3 4`.
Za drugo odredište snimki dodajte `--data-dir /putanja`.
Za tehničku provjeru bez opreme pokrenite `./pokreni.sh self-test`. Test radi
u zasebnoj ROS domeni i koristi privremene sintetičke snimke i model.

## Snimanje

Kad pokretač ispiše **SPREMNO**, u drugom terminalu snimite slobodni pokus
koji sadrži maksimalni stisak. Naredba ispisuje ID snimke.

```bash
./pokreni.sh record P01_mvc --free
./pokreni.sh record P01_pokus1 --mvc-from P01_mvc
./pokreni.sh record P01_pokus2 --mvc-from P01_mvc
```

Snimku u kasnijim naredbama zadajete oznakom sesije, početkom ID-ja ili
cijelim ID-jem. Svakom pokusu dajte novu oznaku, primjerice `P01_pokus1b`
za ponovljeni pokus. Ako istu oznaku ima više snimki, naredba ispisuje
njihove ID-jeve i traži da odaberete jedan.

Opcija `--mvc-from` uzima najveću izmjerenu silu iz `force.csv` odabrane
snimke i koristi je kao MVC za ciljeve vođenog pokusa. Za ručni unos
referentne vrijednosti u N možete koristiti `--mvc`.

Pratite ciljeve u terminalu ili PlotJuggleru. Vođeni pokus od 30 s uključuje
100, 75, 50 i 25 % MVC po 6 s, svaki s 1,5 s odmora. Za druga trajanja
koristite `--duration` s vrijednosti od 20 do 35 s. Za slobodan pokušaj
koristite `./pokreni.sh record OZNAKA --free`.

Nakon svake uspješne snimke terminal ispisuje ID, ostvarene i očekivane
frekvencije te pokrivenost. Zadano odredište je
`grip_data/recordings/<recording_id>/`.

Zatim ispisuje vršnu silu i, za vođeni pokus, cilj i držanu silu po fazama.
Držana sila je medijan druge polovice faze, a faza je praćena uz razliku do
15 % MVC. Ako redak s uskličnikom javi da zadane razine nisu praćene,
ponovite pokus prije treniranja. Isti pregled za bilo koju spremljenu
snimku daje `python3 scripts/analiza.py check OZNAKA`, i bez ROS-a.

- `raw_emg*.csv` i `emg*.csv` sadrže sirovi i obrađeni EMG prvog kanala po
  uređaju. PlotJuggler prikazuje prvi kanal.
- `force.csv` sadrži silu dinamometra u N. Svaki od tih tokova čuva
  vremensku oznaku uzorka, vrijeme primitka i identitet izvora.
- `aligned.csv` sadrži EMG interpoliran na vremenske oznake dinamometra
  unutar kratkih razmaka. Servis odbija snimku s manje od 80 % pokrivenosti.
- `metadata.json` sadrži sesiju, MVC, planirane granice i stvarno vrijeme
  objave svake faze, cilj u N, frekvencije i podatke o prazninama.

Poravnanje koristi ROS vremenske oznake. Shimmer ih temelji na koracima
uređajskog sata i vremenu prvog primljenog uzorka. Dinamometar rekonstruira
oznake iz vremena primitka bloka i zadanog perioda. Procjena uživo stiže
nakon prikupljanja i obrade EMG bloka pa zadržava oznaku vremena na koje
se odnosi.

## Treniranje i prikaz

Navedite prvi pokus za učenje i drugi za validaciju. Koristite isti
raspored elektroda, Shimmere i postavke obrade za oba pokusa.

```bash
./pokreni.sh train P01_pokus1 --validation P01_pokus2 --activate
```

Naredba sprema JSON model ridge regresije u `grip_data/models/` i učitava
ga u estimator. Za snimke učenja i validacije ispisuje MAE, RMSE i pomak u N,
ukupno i po razinama sile, te upozorava ako snimka sadrži premalo stiska da
bi pogreška nešto govorila o modelu. U PlotJuggleru se pojavljuje
procijenjena sila na `/grip_force_estimated`. Nakon ponovnog pokretanja
postojeći model učitajte njegovom putanjom.

```bash
./pokreni.sh estimate grip_data/models/ID_MODELA.json
```

Procjena koristi obrađeni EMG prvog kanala u trenutku procjene i na
vremenskim odgodama od 50, 100, 200, 350 i 500 ms. To je pojednostavljena
primjena vremenskih odgoda iz [rada o estimaciji sile stiska](https://arxiv.org/html/2409.17340#S2.SS3.SSS2).
Model procjenjuje silu za vremensku oznaku EMG-a. Za prikaz uživo koristi
mrežu od 200 Hz. Nakon prekida čeka novu neprekinutu EMG povijest od 500 ms.

Uz procjenu se na `/grip_force_predicted` objavljuje njezina prognoza do
500 ms unaprijed, u PlotJuggleru zelenom krivuljom. Postupak, provjera na
snimkama i dosadašnji rezultati opisani su u [PREDIKCIJA.md](PREDIKCIJA.md).

Postojeće snimke s dva kanala mogu se koristiti za treniranje jer se iz
njih očitava prvi kanal. Modele koji su učili iz oba kanala treba ponovno
istrenirati iz snimki.

## Referentni model za Shimmer 4C91

Model `5a7118ac2e564532a642e958fdc0eb69.json` treniran je s prvim kanalom
Shimmera 4C91 pri 512 Hz. Nakon pokretanja s `./pokreni.sh --shimmers 1`
i poruke **SPREMNO** učitajte ga iz druge ljuske u mapi projekta.

```bash
./pokreni.sh estimate grip_data/models/5a7118ac2e564532a642e958fdc0eb69.json
```

| Snimka | ID | Namjena |
|---|---|---|
| `P01_mvc` | `91cd7cb2f12949338e3194729093ead8` | Izvor MVC-a za vođeni pokus |
| `P01_ucenje` | `1dc9fdb23e604d32b7944ada4fbf9471` | Treniranje modela |
| `P01_validacija` | `6456c101d41044e9b6c3f8c93713bce8` | Odvojena validacija |

Na 5 900 valjanih redaka iz `P01_validacija` dobiveni su MAE **3,57 N**
i RMSE **4,17 N**. Za usporedbu, ridge s trenutačnim uzorkom prvog kanala
ima RMSE **5,04 N** na istim redcima. To su rezultati iz spremljenih
snimki. Provjera novog modela uživo s fizičkom opremom je sljedeći korak.

`python3 scripts/analiza.py` pokazuje da `P01_validacija` ne sadrži stisak,
a `P01_ucenje` samo nekoliko kratkih koji ne prate zadane razine. Gornje
brojke zato opisuju pogrešku u mirovanju. Na `P01_mvc`, jedinoj snimci s
pravim stiskom, isti model ima RMSE 25,0 N. Za ocjenu modela prvo snimite
nove pokuse u kojima ispitanik prati ciljeve.

Za demonstraciju sa spremljenim modelom i samo Shimmerom koristite
[pokretanje bez dinamometra](POKRETANJE.md#procjena-bez-dinamometra).
