# Jämförelse av konjunkturindikatorer inför ARM

## Vad som prövats

Alla 14 indikatorers konjunkturläge har analyserats en i taget med ett års fördröjning inom SKR A, B och C. Två utfallsdefinitioner har prövats: stabilt vid exakt noll, och stabilt inom ±0,02 barn per kvinna. Totalt 84 modeller och 504 riktade träningsregler. BNP kvartal ingår som separat tabellserie, inte som oberoende månatlig BNP-mätning. Förändringsmåttet i konjunkturklockan har inte analyserats i detta försök.

Varje regel jämförs i träning 2004–2015, validering 2016–2019 och senare år 2020–2025. Alla årsvärden kräver tolv observerade månadsceller. Bortfallet hanteras per indikator, inte via ett generellt krav på fullständighet i alla 14 serier. Alla grupper använder samma trösklar: support 5 %, confidence 60 %, lift 1,10 och minst tre stödår för villkor respektive regel.

## Resultat

Ingen enindikatorregel når confidence 60 % i träning; det högsta värdet är 58,26 %. 80 av de 504 reglerna når lift 1,10, men ingen klarar alla krav. Det är därför viktigt att skilja mellan viss historisk samvariation och accepterade prognosregler.

Alla modeller faller tillbaka på respektive grupps vanligaste träningsutfall. Förbättringen jämfört med denna baslinje är därför exakt noll. Denna likhet är en följd av att inga regler används; den bevisar inte att alla indikatorer saknar prognosinformation.

Den förutbestämda parstrategin krävde två indikatorer som var för sig gav positiv förbättring i validering. Inga par kvalificerade sig och inga nya parmodeller kördes. Detta utesluter inte samspel mellan indikatorer som har svagt värde var för sig. Den tidigare första ARM-körningen med tre utvalda indikatorer redovisas separat i resultat_ARM_SKR.

## Hur ni kan skriva i presentationen

Med en uppdelning av konjunkturläget i under respektive vid/över trend och ett års tidsfördröjning hittade vi inga enindikatorregler som uppfyllde våra förvalda krav. Detta gällde båda utfallsdefinitionerna och samtliga SKR-huvudgrupper. Resultatet visar begränsningar i det prövade upplägget och ger inte belägg för att konjunkturen saknar samband med fruktsamheten.

## Begränsningar

Analysen är explorativ och retrospektiv. Senare utfall har redan granskats. SKR:s klassificering från 2023 har applicerats bakåt och konjunkturhistoriken är reviderad. Alla kommuner delar ekonomiska årsvärden, så kommun–år är inte oberoende. Inga signifikanstester har gjorts. De 504 reglerna är inte 504 oberoende hypoteser.

Neutralzonen är ett förutbestämt känslighetsantagande, inte ett mått på statistisk osäkerhet. Modeller med olika utfallskategorisering kan inte direkt jämföras enbart på rå träffsäkerhet. Jämför alltid med motsvarande baslinje.

## Filer

- indikatorjamforelse.csv: jämförelse mellan perioder per indikator, grupp och neutralzon.
- regler_alla.csv: support, confidence, lift, basfrekvens och stödår för varje regel i varje period.
- modeller_alla.csv: träffsäkerhet, balanserad träffsäkerhet och regeltäckning.
- urvalsdiagnostik_traning.csv: vilka krav varje träningsregel klarar.
- basta_confidence_traning.csv: den träningsregel som visas för varje punkt i diagrammet.
- indikatorer_traning.png och .svg: diagram för rapport eller presentation.
- bortfall.csv och datatackning.csv: analysurval och datatäckning.
- parval.csv: varför ett par valdes eller inte valdes. Parresultatfilerna har rubriker men inga rader när inga par valts.
- installningar.json: de fasta metodvalen.

Nästa steg är att diskutera detta resultat och välja en motiverad fortsättning. Ändra inte gränser enbart för att skapa fler fynd.
