# Predikcija sile stiska

Estimator iz EMG-a računa silu za trenutak u kojem je EMG izmjeren. Prediktor tu procjenu produljuje do pola sekunde unaprijed. Koristi Hankelovu dinamičku dekompoziciju modova (Hankel-DMD), isti pristup kao predikcijski korak u radu [Koopman-driven Grip Force Prediction Through EMG Sensing](https://arxiv.org/html/2409.17340) (Bazina i sur.).

## Kako radi

1. Uzima zadnju sekundu procijenjene sile i svodi je na 40 uzoraka u sekundi.
2. Slaže je u Hankelovu matricu: četiri retka, svaki pomaknut za jedan uzorak.
3. Rastavom na singularne vrijednosti nalazi linearno preslikavanje koje stupac matrice prevodi u sljedeći. To je konačna aproksimacija Koopmanova operatora na vremenskim odgodama.
4. Svojstvene vrijednosti tog preslikavanja opisuju rast, gušenje i titranje signala u prozoru. Najviše četiri moda dobivaju amplitude metodom najmanjih kvadrata preko cijelog prozora.
5. Potenciranjem svojstvenih vrijednosti signal se produljuje iza zadnjeg uzorka.

Dvije zaštite čine prognozu upotrebljivom na stvarnom signalu:

- Mod koji unutar prozora raste izvan njega bi pobjegao, pa se svojstvene vrijednosti izvan jedinične kružnice vraćaju na nju.
- Prognozira se promjena u odnosu na zadnju procjenu, a ne sama vrijednost. Prognoza se zato nastavlja točno iz zadnje procjene.

Cijeli postupak je u `src/shimmer_ros2/shimmer_ros2/grip_forecast.py`, koristi samo NumPy i traje oko 0,3 ms po prognozi.

## Uživo

Čvor `grip_estimator` uz `/grip_force_estimated` objavljuje i `/grip_force_predicted`. Nakon svake nove skupine procjena ponovno prilagođava model i objavljuje prognozu od zadnje procjene do 500 ms iza nje, u koracima od 25 ms. Vremenska oznaka svake poruke je trenutak na koji se prognoza odnosi. PlotJuggler je prikazuje zelenom krivuljom uz izmjerenu i procijenjenu silu.

- Prognoza kreće kad postoji jedna sekunda neprekinute procjene, a nakon prekida EMG-a čeka novu.
- Modeli istrenirani nakon ove izmjene pamte raspon sile iz učenja i prognoza uživo ne izlazi iz njega.
- Horizont se mijenja parametrom `prediction_horizon_ms` čvora, odnosno istoimenim argumentom datoteke `grip_services.launch.py`. Vrijednost 0 isključuje prognozu.

Procjena kasni: obrađeni EMG stiže u blokovima od pola sekunde, u postojećim snimkama s medijanom od 605 do 656 ms nakon uzorka. Horizont od 500 ms zato uglavnom nadoknađuje to kašnjenje i dovodi krivulju otprilike do sadašnjeg trenutka. Za prognozu koja stvarno prethodi stisku treba ili dulji horizont ili kraći blok obrade.

## Provjera na snimkama

```bash
python3 scripts/analiza.py predict                           # snimke najnovijeg modela
python3 scripts/analiza.py predict --recordings P02_pokus3   # odabrana snimka
python3 scripts/analiza.py predict --horizons 250 500 750    # drugi horizonti u ms
```

Naredba prolazi kroz snimku, svakih 50 ms izdaje prognozu iz dotad poznate procjene i uspoređuje je s onim što je slijedilo. Uz pogrešku prognoze ispisuje pogrešku zadržavanja zadnje procjene. To je najjednostavnija moguća prognoza i mjera koju prediktor mora nadmašiti da bi imao smisla.

Stanje na priloženim snimkama, s referentnim modelom, kao promjena RMSE-a u odnosu na zadržavanje (negativno je bolje):

| Snimka | 100 ms | 250 ms | 500 ms |
|---|---|---|---|
| `P01_mvc`, prema kasnijoj procjeni | −3 % | −2 % | −1 % |
| `P01_mvc`, prema izmjerenoj sili | −1 % | +1 % | +2 % |
| `P01_ucenje`, prema kasnijoj procjeni | −2 % | −10 % | −18 % |
| `P01_ucenje`, prema izmjerenoj sili | +9 % | −3 % | −17 % |
| `P01_validacija` (mirovanje), prema kasnijoj procjeni | +1 % | +1 % | +1 % |

Prediktor na tim snimkama zasad nije pokazao jasnu korist: razlike su male i nisu dosljedne. Snimke su za tu ocjenu loša podloga, jer sadrže nekoliko naglih slobodnih stisaka i model koji pri stisku griješi 25 N. Na čistom sintetičkom valu, čiji je nastavak poznat, prognoza je točna na stoti dio njutna, pa je sam postupak ispravan.

Glavno ograničenje je osjetljivost na šum. Kad se istom valu amplitude 35 N doda šum od oko 1 N, prednost pred zadržavanjem pada na 8 do 18 %. Prozor od jedne sekunde prekratak je da se iz zašumljene procjene pouzdano odredi kamo signal ide, a dulji prozor na stvarnim snimkama daje lošije rezultate jer stisak nije pravilno titranje.

## Razlike prema radu

| | Rad | Ovaj projekt |
|---|---|---|
| Ulaz | procjena izglađena LOWESS-om | procjena bez dodatnog izglađivanja |
| Opservable | vremenske odgode i logaritamski članovi | samo vremenske odgode |
| Broj odgoda i modova | 8 i 4 | 4 i najviše 4 |
| Odabir modova | DDMD-RRR s rezidualima | prvi singularni smjerovi |
| Prozor | 0,65 s | 1 s |
| Ponovno učenje | na svakom bloku od 0,5 s | na svakoj novoj skupini procjena |
| Horizont | 0,5 s | 0,5 s, podesivo |

Rad za predikciju navodi wMAPE 17,92 % prema 5,48 % za estimaciju na 13 ispitanika, bez usporedbe sa zadržavanjem zadnje vrijednosti. Izglađivanje i logaritamski članovi isprobani su i na priloženim snimkama nisu pomogli, pa nisu ugrađeni.

## Što još treba

- Broj odgoda, modova i duljina prozora odabrani su na dvije priložene snimke sa stiskom. Odabir treba ponoviti na snimkama koje prate protokol i potvrditi na snimci koja u odabiru nije sudjelovala.
- Prognoza uživo provjerena je samo na sintetičkom valu. S opremom je treba pogledati u PlotJuggleru i spremiti u bag snimku zajedno s `/grip_force_estimated`.
- Kašnjenje procjene i prognoze pri primitku još nije izmjereno na pravim uređajima.
