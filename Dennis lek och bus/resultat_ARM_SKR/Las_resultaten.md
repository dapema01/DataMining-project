# Första ARM-analysen

Tre konjunkturindikatorer, ett års lagg och SKR:s tre huvudgrupper. Apriori sökte enbart regler från ekonomiska villkor till fruktsamhetsförändring. Alla resultat bygger på NY-filerna i Dennis egen mapp.

84 kandidatregler klarade support och struktur. En regel klarade också confidence, lift och minst tre olika stödår: grupp A, BNP vid/över trend och sysselsättning under trend föregående år, följt av ökad fruktsamhet.

## Regelns stabilitet inom grupp A

| Period | Kommun–år som matchar villkoren | Olika villkorsår | Confidence | Basfrekvens ökning | Lift |
|---|---:|---:|---:|---:|---:|
| traning | 138 | 3 | 0.630 | 0.496 | 1.270 |
| validering | 92 | 2 | 0.348 | 0.353 | 0.985 |
| senare_ar | 46 | 1 | 0.130 | 0.370 | 0.353 |

## Slutsats för denna första modell

Regelmodellen gav ingen förbättring mot att alltid gissa den vanligaste klassen i respektive grupps träningsdata. A-regeln ger samma klass som baslinjen, och B/C har inga regler som passerar samtliga krav. Det är ett negativt resultat för denna avgränsade modell, inte ett bevis för att konjunkturen saknar samband med fruktsamheten.

Träning 2004–2015, validering 2016–2019, senare år 2020–2025. Inga regler eller gränser valdes med hjälp av validerings- eller senare års resultat. SKR 2023 har applicerats bakåt i tiden och ekonomiska historikserier är reviderade: analysen är retrospektiv. Senare utfall har också tidigare visats i diagram. Den ska inte beskrivas som en verklig historisk realtidsprognos eller ett helt osedd sluttest.

Resultatfiler: kandidatregler.csv, valda_regler.csv, regeljamforelse_alla_grupper.csv, prognoser.csv, utvardering.csv, utvardering_per_ar.csv och installningar.json. Basfrekvens och lift i regeljämförelsen beräknas inom samma grupp och utvärderingsperiod. Baslinjeprognosen låses däremot från träningen.

Support räknar kommun–år, inte oberoende ekonomiska händelser. Antal olika år och täckning redovisas därför separat. Ingen automatisk borttagning av extrema värden eller nollfyllning har gjorts. Nästa försök bör vara förutbestämt och använda utvecklingsperioden för val. Fler försök mot redan granskade senare år måste beskrivas som explorativa.

Apriori har verifierats mot en fullständig uppräkning av tillåtna mängder för grupp A:s träningsdata. Prognoserna har kontrollerats för unika kommun–år och korrekt antal utvärderingsrader.
