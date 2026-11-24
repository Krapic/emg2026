# Stanje i plan projekta – sila stiska iz sEMG-a

Ažurirano 24. studenoga 2026. Za rad u laboratoriju koristite [pokretanje i dijagnostiku](POKRETANJE.md) te [snimanje, treniranje i učitavanje modela](SNIMANJE_I_MODEL.md).

## Implementirano

- `./pokreni.sh` odabire jedan dostupan Shimmer ili koristi uređaje navedene s `--shimmers`. Zadano uzorkovanje Shimmera je 512 Hz, a dinamometra 200 Hz. EMG obrada i novi CSV-ovi koriste prvi kanal. PlotJuggler prikazuje taj kanal uz izmjerenu, ciljnu i estimiranu silu.
- `/record_grip` (`RecordGrip.srv`) snima sirovi i obrađeni EMG te silu s vremenskim oznakama. Sprema izvorne tokove, tablicu poravnatu na oznake dinamometra i metapodatke. Snimanje ima vođeni i slobodni način. `--mvc-from SNIMKA` uzima najveću izmjerenu silu iz snimke maksimalnog stiska za ciljeve vođenog pokusa.
- `/train_grip_model` (`TrainGrip.srv`) uči ridge model iz odabranih snimki i izvještava MAE i RMSE na posebno navedenim validacijskim snimkama. Ulaz je prvi kanal u trenutku procjene i na pet vremenskih odgoda, do 500 ms u prošlost. Iste odgode koriste se za treniranje i procjenu uživo. Starije dvokanalne snimke mogu poslužiti kao ulaz.
- `/load_grip_model` (`LoadGripModel.srv`) provjerava i učitava JSON model. Estimator objavljuje `/grip_force_estimated` u njutnima i čeka novu valjanu povijest nakon prekida EMG-a. Način `./pokreni.sh --model PUTANJA` pokreće obradu i estimaciju bez dinamometra, odabire Shimmer prema modelu i automatski učitava model. Provjera tog načina rada ostaje otvorena.
- `python3 scripts/analiza.py` bez ROS-a pokazuje što snimke sadrže i kolika je pogreška modela po razinama sile. Za vođeni pokus uspoređuje cilj i držanu silu po fazama. Upozorava kad ispitanik nije pratio zadane razine ili kad snimka sadrži premalo stiska da bi pogreška nešto govorila o modelu.
- `./pokreni.sh record` ispisuje taj izvještaj nakon svake snimke, a `./pokreni.sh train` nakon treniranja. Obje naredbe primaju oznaku sesije ili početak ID-ja umjesto cijelog ID-ja snimke.

Upozorenja ispisuje pokretač. Sami servisi ih ne vraćaju, pa ih izravan `ros2 service call` ne prikazuje.

## Što je provjereno

| Provjera | Rezultat |
|---|---|
| Jedan sintetički Shimmer | `./pokreni.sh self-test` prošao je 24. studenoga u ROS 2 Humble kontejneru na GitHubu: cijeli postupak snimanja, treniranja i procjene, uključujući izvještaj nakon `record` i `train`, oznake sesija, oporavak nakon prekida EMG-a i odbijanje nevaljanog modela. Prošlo je i 9 testova pokretača i 4 testa čitanja EMG paketa. Provjera se ponavlja nakon svakog slanja na GitHub. Na računalu s opremom izmjene od 22. studenoga još nisu pokrenute. |
| Testovi bez ROS-a | 25 testova poravnanja, odgoda, regresije i izvještaja prolazi na Ubuntuu 22.04 sa sistemskim Pythonom 3.10 i NumPyjem (provjera na GitHubu) te na Windowsu s Pythonom 3.13 i NumPyjem 2.3. |
| Postojeće laboratorijske snimke | `P01_validacija` ne sadrži stisak, a `P01_ucenje` samo nekoliko kratkih koji ne prate zadane razine. MAE 3,57 N i RMSE 4,17 N na 5 900 validacijskih redaka (5,04 N bez vremenskih odgoda) zato opisuju pogrešku u mirovanju. Na `P01_mvc`, jedinoj snimci s pravim stiskom, isti model ima RMSE 25,0 N i od polovice vršne sile naviše procjenjuje premalo. |
| Fizički uređaji | Procjena uživo sa Shimmerom 4C91 i dinamometrom nije provjerena. Nije provjeren ni način bez dinamometra. |
| Kašnjenje | U tri postojeće snimke obrađeni EMG stiže s medijanom od 605 do 656 ms nakon vremenske oznake uzorka, uz 95. percentil od 801 do 854 ms. Sirovi EMG stiže nakon 303 do 359 ms. Kašnjenje same procjene nije izmjereno. |

Putanja modela, ulazne snimke i naredba za učitavanje zapisane su u [uputama za snimanje i model](SNIMANJE_I_MODEL.md#referentni-model-za-shimmer-4c91).

## Preostali koraci

1. **Prenijeti projekt na računalo s opremom.** Klonirati repozitorij s GitHuba, izgraditi ga i pokrenuti `./pokreni.sh self-test` kao provjeru instalacije.
2. **Snimiti valjane pokuse i istrenirati novi model.** Sa Shimmerom 4C91 pri 512 Hz i dinamometrom snimiti maksimalni stisak, pokus za učenje i pokus za validaciju. Ponoviti svaki pokus za koji izvještaj javi da zadane razine nisu praćene. Pogledati pogrešku novog modela po razinama sile. Za svaki pokušaj zabilježiti položaj ruke i elektroda.
3. **Provjeriti estimaciju uživo s opremom.** Učitati novi model i napraviti novi pokušaj uz dinamometar. Usporediti obje krivulje u PlotJuggleru i spremiti ih za analizu, s vremenom na koje se procjena odnosi i vremenom primitka. CSV snimke sadrže referentnu silu i EMG, pa za brojčanu provjeru izlaza uživo treba zasebno zabilježiti i `/grip_force_estimated`.
4. **Izmjeriti točnost i kašnjenje na novim pokušajima.** Dogovoriti prag pogreške u N ili % MVC i prihvatljivo kašnjenje. MAE, RMSE i pomak po razinama sile daje `python3 scripts/analiza.py evaluate`. Pogrešku pri stisku i otpuštanju, starost procjene pri primitku i vremensko poravnanje dinamometra i EMG-a još treba izračunati zasebno. Odvojiti cijele snimke za učenje, odabir postavki i završni test.
5. **Dodati kratkoročnu predikciju.** Prvo izvesti offline pokus Hankel-DMD-a nad poviješću estimirane sile. Na istim ciljnim vremenima usporediti prognoze 100, 250 i 500 ms unaprijed s bazom koja zadržava posljednju dostupnu estimaciju. Uključiti stvarno kašnjenje FFT bloka i provjeriti prelazi li ciljno vrijeme trenutak izdavanja prognoze. Izmjereno kašnjenje obrađenog EMG-a veće je od najduljeg horizonta. Ako prediktor poboljša rezultate na odvojenim snimkama, dodati odvojen ROS topic s vremenom izdavanja, ciljnim vremenom i horizontom.
6. **Pripremiti demonstraciju i predaju.** Dokumentirati protokol, model, konfiguraciju, grafove i rezultate ponovljenih pokušaja. S nastavnicima potvrditi potreban broj sudionika, kriterije završetka i je li predikcija obavezna. Provjeriti i demonstraciju s priključenim samo Shimmerom i učitanim modelom.

## Radovi i primjena

- Vremenske odgode u estimaciji preuzete su kao ideja iz rada Bazina i sur. Postojeća implementacija koristi ridge regresiju, a rad opisuje i nelinearne značajke te zaseban DMD prediktor. [Koopman-driven Grip Force Prediction Through EMG Sensing](https://arxiv.org/html/2409.17340)
- Za prediktor su referenca rafiniranje Ritzovih vektora i provjera reziduala u DDMD-RRR-u te numerički stabilna procjena amplituda odabranih modova. [Data Driven Modal Decompositions](https://arxiv.org/pdf/1708.02685) · [Least Squares with Applications to DMD](https://arxiv.org/pdf/1811.12562)
