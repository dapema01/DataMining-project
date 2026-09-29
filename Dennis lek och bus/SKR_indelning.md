# Kommungrupper enligt SKR 2023

Huvudindelningen i notebooken är nu SKR:s A, B och C, kopplade på kommunkod. Alla 290 kommuner matchar exakt en gång. Namnen matchar också täthetsfilen. Källan är den uppladdade Kommungruppsindelning-2023-SKR.xlsx, blad Bilaga1 Lista alla kommuner.

| Huvudgrupp | Beskrivning | Kommuner |
|---|---|---:|
| A | Storstäder och storstadsnära kommuner | 46 |
| B | Större städer och kommuner nära större stad | 110 |
| C | Mindre städer/tätorter och landsbygdskommuner | 134 |

De nio undergrupperna bevaras i skr_gruppkod och skr_kommungrupp. C8 och C9 är de två landsbygdsgrupperna, med totalt 56 kommuner. Hela C innehåller även mindre städer och pendlingskommuner och får inte benämnas enbart landsbygd. A1 består av endast tre kommuner, så de tre huvudgrupperna är en rimlig utgångspunkt för ARM. Gruppspecifik support och antal olika år måste redovisas eftersom grupperna är olika stora.

Föreslagen fråga: Vilka konjunkturindikatorer föregår förändringar i fruktsamhet, och skiljer sig dessa mönster mellan SKR:s kommuntyper?

## Tid och förutsägelse

2023 års grupptillhörighet används genom hela perioden 2004–2025. Det beskriver historiska förlopp för kommuner grupperade enligt 2023 års indelning, inte deras historiskt aktuella grupptillhörighet. För strikt prognosutvärdering före 2023 krävs äldre, då tillgängliga indelningar eller den tidigare täthetsindelningen från 2003. Med aktuell indelning och reviderade konjunkturserier ska resultaten inte presenteras som en verifierad realtidsprognos.

## Filer

Notebooken läser NY-filerna i Dennis egen mapp och den lokalt extraherade kommungrupper_SKR_2023.csv. Originalarbetsboken sparas i samma mapp. Inga råfiler har raderats. Alla nio undergrupper och numerisk befolkningstäthet behålls. Den tidigare medianindelningen finns som tathetsgrupp_2003 för känslighetsanalys.

Nya bearbetade filer sparas i resultat_SKR_2023. Tidigare resultat_NY och Datagranskning_NY.md beskriver den äldre indelningen och är historik, inte aktuella SKR-resultat. ARM-underlaget har fortfarande 6 153 kompletta kommun–år; ingen kommun utesluts genom kopplingen till SKR. ARM-regler har ännu inte skattats.
