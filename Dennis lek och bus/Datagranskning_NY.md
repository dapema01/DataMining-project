# Datagranskning inför ARM

Granskad 24 september 2026. Endast NY-filer i Dennis egen mapp har använts. Råfilerna är oförändrade. Notebooken läser nu dessa lokala filer och sparar bearbetade tabeller i resultat_NY.

## Behåll och filtrera

| Uppgift | Hantering |
|---|---|
| Fruktsamhet män | Behåll i råfil, välj kvinnor i analysen. |
| Saknade kvinnovärden | 204 av 7 540 kommun–år 2000–2025. Ingen nollfyllning eller automatisk interpolation. |
| Rikets två filer | Samma kvinnoserie. Använd som jämförelse, inte två datakällor som ska läggas ihop och inte en extra kommun. |
| Befolkningstäthet och folkmängd | Behåll. Tätheten gäller hela befolkningen, även om fruktsamheten gäller kvinnor. |
| Konjunktur 2026 | Utanför aktuell analys, eftersom fruktsamheten slutar 2025. Behåll i råfil. |
| År före 2004 | Behåll för historik, referensår och laggar. Huvudutfallen avgränsas till 2004–2025. |
| Konjunkturens två mått | Huvudförslaget använder konjunkturläge. Förändringsmåttet finns kvar för en eventuell separat analys. |
| Alla 14 indikatorer | Täckningen har granskats. Starturvalet använder konsumtion, sysselsättning och BNP-indikator månad. Andra indikatorer har inte bedömts som felaktiga eller oanvändbara. |
| Ovanliga fruktsamhetsvärden | Intervallet är 0,96–3,15 för kvinnor. Inga värden tas bort bara för att de är extrema. |
| Dubbletter | Inga hittades på de förväntade datanycklarna. |

## Separat ARM-underlag

Det föreslagna underlaget omfattar 6 380 kommun–år 2004–2025. Av dem har 6 153 kompletta värden för fruktsamhetsförändring, kommuntyp och de tre ekonomiska indikatorerna med ett års lagg. Övriga 227 rader sparas separat med saknade variabler angivna. Detta antal är inte samma sak som 204 saknade nivåvärden i hela perioden: årsförändringen kräver två intilliggande värden och perioden är annorlunda.

- resultat_NY/analysunderlag_2004_2025.csv: alla rader, inklusive bortfall.
- resultat_NY/arm_underlag_lag1.csv: föreslaget komplett ARM-starturval.
- resultat_NY/arm_bortfall_lag1.csv: exkluderade rader och orsaker.
- resultat_NY/konjunktur_tackning_alla_indikatorer.csv: alla indikatorer och mått per år.
- resultat_NY/geografiska_flaggor.csv: rader som kräver geografisk kontroll.

## Geografi och kvarstående beslut

Knivsta har nollor 2000–2001 och ett numeriskt värde 2002, trots att kommunen bildades 2003. Dessa historiska värden flaggas och används inte som aktuella utfall i huvudperioden. Det numeriska värdet 2002 ska inte raderas som ett konstaterat fel utan att den geografiska referenstidpunkten först kontrollerats mot SCB. Övriga gränsändringar behöver fortsatt känslighetsanalys.

Indelningen vid medianen 2003, 26,4 invånare/km², är ett projektförslag, inte en officiell stads-/landsbygdsindelning. Bortfallet är större i gruppen med lägre täthet. Ta inte bort hela små kommuner som en generell regel.

Nästa steg är att bestämma vilka indikatorer som ska ingå i första ARM-körningen och kategorisera deras laggade värden och fruktsamhetsförändringen. Lär kategorigränser och regler på tidigare år; utvärdera på senare år. Ingen ARM-modell har körts i denna granskning.

## Filformat

Fruktbarhet_riket.NYcsv har ovanlig filändelse men är en läsbar kommaseparerad fil med rubrikrad. Kvinnofilen saknar rubrikrad och läses därför med uttryckliga kolumnnamn. Kommunfruktsamhet och konjunktur använder semikolon. Kommunkoder bevaras som text.
