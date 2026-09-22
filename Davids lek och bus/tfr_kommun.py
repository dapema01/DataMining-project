"""
Summerad fruktsamhet (TFR) per kommun i Sverige 1968-2024.

SCB publicerar färdigberäknad summerad fruktsamhet per region först från år 2000.
Det här scriptet räknar fram måttet hela vägen från 1968 ur de två underlagstabeller
som finns på kommunnivå sedan 1968:

  Täljare:  BE/BE0101/BE0101H/FoddaK
            "Födda efter region, moderns ålder och barnets kön"
  Nämnare:  BE/BE0101/BE0101A/BefolkningNy
            "Folkmängden efter region, civilstånd, ålder och kön"

Metod
-----
    ASFR(r, t, a) = födda(r, t, moder a) / kvinnor(r, t, a)
    TFR(r, t)     = summa över a = 15..49 av ASFR(r, t, a)

Nämnaren är medelfolkmängd, approximerad som medelvärdet av folkmängden
31 december år t-1 och 31 december år t. Tabellen börjar 1968, så år 1968
saknar ingående folkmängd och beräknas på 31 dec 1968 ensamt. Den raden
flaggas i kolumnen 'anm'.

Körning
-------
    pip install requests pandas
    python scb_tfr_kommun.py

Råsvaren cachas i ./scb_cache/, så en omkörning inte hämtar om allt.

Utdata i ./AntalPerKommunLangHistoria/:
    tfr_kommun_long.csv   en rad per kommun och år
    tfr_kommun_wide.csv   kommuner som rader, år som kolumner
    tfr_lan_long.csv      samma sak på länsnivå (om INCLUDE_LAN)
    asfr_kommun.csv       åldersspecifika tal (om SAVE_ASFR)
"""

from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path

import pandas as pd
import requests

# --------------------------------------------------------------------------
# Inställningar
# --------------------------------------------------------------------------

BASE = "https://api.scb.se/OV0104/v1/doris/sv/ssd"
BIRTHS_PATH = "START/BE/BE0101/BE0101H/FoddaK"
POP_PATH = "START/BE/BE0101/BE0101A/BefolkningNy"

FIRST_YEAR = 1968
LAST_YEAR = 2024          # höj när SCB publicerat ett nytt år

AGE_MIN, AGE_MAX = 15, 49

# SCB använder ingen åldersavgränsning i sin egen TFR-beräkning. Med True läggs
# födda av mödrar under 15 till åldern 15 och födda av mödrar 49+ till åldern 49,
# så att inga barn tappas bort. Sätt False för en strikt 15-49-avgränsning.
LUMP_EDGES = True

INCLUDE_LAN = True        # räkna även länsnivå (aggregeras av SCB:s länsrader)
SAVE_ASFR = False         # spara åldersspecifika tal (stor fil: ~580 000 rader)

MA_WINDOWS = (3, 5)       # centrerade glidande medelvärden

BIRTH_YEARS_PER_CALL = 4  # håll cellantalet under API:ts tak på 150 000
POP_YEARS_PER_CALL = 2
REGION_CHUNK = 300
SLEEP = 1.2               # API:t tillåter 10 anrop per 10 sekunder

CACHE_DIR = Path("scb_cache")
OUT_DIR = Path("AntalPerKommunLangHistoria")


# --------------------------------------------------------------------------
# API-hjälpare
# --------------------------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "tfr-kommun/1.0"})


def get_meta(path: str) -> dict:
    """Hämtar tabellens metadata (variabler och tillåtna värden)."""
    cache = CACHE_DIR / f"meta_{path.replace('/', '_')}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    r = SESSION.get(f"{BASE}/{path}", timeout=60)
    r.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(r.text, encoding="utf-8")
    return r.json()


def var(meta: dict, code: str) -> dict:
    """Plockar ut en variabel ur metadatan, med tydligt fel om den saknas."""
    for v in meta["variables"]:
        if v["code"].lower() == code.lower():
            return v
    have = ", ".join(v["code"] for v in meta["variables"])
    raise KeyError(f"Variabeln {code!r} saknas. Tabellen har: {have}")


def post_query(path: str, query: list[dict]) -> dict:
    """POST mot PxWeb, med cache på disk och enkel omförsöksloop."""
    body = {"query": query, "response": {"format": "json-stat2"}}
    key = hashlib.sha1(
        (path + json.dumps(body, sort_keys=True)).encode()
    ).hexdigest()[:20]
    cache = CACHE_DIR / f"{path.rsplit('/', 1)[-1]}_{key}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    url = f"{BASE}/{path}"
    for attempt in range(6):
        r = SESSION.post(url, json=body, timeout=180)
        if r.status_code == 200:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(r.text, encoding="utf-8")
            time.sleep(SLEEP)
            return r.json()
        if r.status_code in (429, 502, 503, 504):
            wait = 5 * (attempt + 1)
            print(f"    {r.status_code} från API:t, väntar {wait}s")
            time.sleep(wait)
            continue
        raise RuntimeError(f"{r.status_code} från SCB: {r.text[:400]}")
    raise RuntimeError("Gav upp efter upprepade fel mot SCB:s API")


def jsonstat_to_frame(ds: dict) -> pd.DataFrame:
    """Plattar ut ett json-stat2-svar till en lång DataFrame."""
    ids, sizes = ds["id"], ds["size"]
    values = ds["value"]

    # Kategorierna ligger i angiven ordning; index-dicten ger positionen.
    cats = []
    for dim in ids:
        idx = ds["dimension"][dim]["category"]["index"]
        if isinstance(idx, dict):
            ordered = sorted(idx, key=idx.get)
        else:
            ordered = list(idx)
        cats.append(ordered)

    # Värdena ligger radvis över id/size (sista dimensionen varierar snabbast).
    strides = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]

    cols = {dim: [] for dim in ids}
    out_vals = []
    n = len(values)
    for flat in range(n):
        v = values[flat] if not isinstance(values, dict) else values.get(str(flat))
        if v is None:
            continue
        for d, dim in enumerate(ids):
            cols[dim].append(cats[d][(flat // strides[d]) % sizes[d]])
        out_vals.append(v)

    df = pd.DataFrame(cols)
    df["value"] = out_vals
    return df


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


# --------------------------------------------------------------------------
# Åldersnormalisering
# --------------------------------------------------------------------------

def mother_age_to_int(code: str) -> int | None:
    """'-14' -> 14, '15' -> 15, '49+' -> 49. Okända koder ger None."""
    c = code.strip()
    if c.startswith("-"):
        digits = "".join(ch for ch in c if ch.isdigit())
        return int(digits) if digits else None
    digits = "".join(ch for ch in c if ch.isdigit())
    return int(digits) if digits else None


def pop_age_to_int(code: str) -> int | None:
    """'0'..'100+' -> int. Totalrader ('tot' o.d.) ger None."""
    digits = "".join(ch for ch in code if ch.isdigit())
    return int(digits) if digits else None


# --------------------------------------------------------------------------
# Hämtning
# --------------------------------------------------------------------------

def pick_regions(meta: dict) -> tuple[list[str], list[str], dict[str, str]]:
    """Delar upp regionvärdena i kommuner (4 siffror) och län (2 siffror)."""
    v = var(meta, "Region")
    names = dict(zip(v["values"], v["valueTexts"]))
    kommuner = [c for c in v["values"] if len(c) == 4 and c.isdigit()]
    lan = [c for c in v["values"] if len(c) == 2 and c.isdigit() and c != "00"]
    return kommuner, lan, names


def fetch_births(regions: list[str], years: list[int]) -> pd.DataFrame:
    meta = get_meta(BIRTHS_PATH)
    age_codes = var(meta, "AlderModer")["values"]
    sex_codes = var(meta, "Kon")["values"]
    content = var(meta, "ContentsCode")["values"]

    frames = []
    for ychunk in chunks(years, BIRTH_YEARS_PER_CALL):
        for rchunk in chunks(regions, REGION_CHUNK):
            print(f"  födda {ychunk[0]}-{ychunk[-1]}  ({len(rchunk)} regioner)")
            q = [
                {"code": "Region", "selection": {"filter": "item", "values": rchunk}},
                {"code": "AlderModer", "selection": {"filter": "item", "values": age_codes}},
                {"code": "Kon", "selection": {"filter": "item", "values": sex_codes}},
                {"code": "ContentsCode", "selection": {"filter": "item", "values": content}},
                {"code": "Tid", "selection": {"filter": "item", "values": [str(y) for y in ychunk]}},
            ]
            df = jsonstat_to_frame(post_query(BIRTHS_PATH, q))
            # Barnets kön är ointressant här, summera bort det.
            df = (
                df.groupby(["Region", "AlderModer", "Tid"], as_index=False)["value"]
                .sum()
                .rename(columns={"value": "fodda"})
            )
            frames.append(df)

    out = pd.concat(frames, ignore_index=True)
    out["alder"] = out["AlderModer"].map(mother_age_to_int)
    out["ar"] = out["Tid"].astype(int)
    out = out.dropna(subset=["alder"])
    out["alder"] = out["alder"].astype(int)

    if LUMP_EDGES:
        out["alder"] = out["alder"].clip(lower=AGE_MIN, upper=AGE_MAX)
    else:
        out = out[(out["alder"] >= AGE_MIN) & (out["alder"] <= AGE_MAX)]

    return (
        out.groupby(["Region", "ar", "alder"], as_index=False)["fodda"]
        .sum()
        .rename(columns={"Region": "region"})
    )


def fetch_population(regions: list[str], years: list[int]) -> pd.DataFrame:
    """Kvinnor 15-49 per region, ålder och år (folkmängd 31 december)."""
    meta = get_meta(POP_PATH)

    age_var = var(meta, "Alder")
    age_codes = [
        c for c in age_var["values"]
        if (a := pop_age_to_int(c)) is not None and AGE_MIN <= a <= AGE_MAX
    ]

    civ_codes = var(meta, "Civilstand")["values"]

    sex_var = var(meta, "Kon")
    women = [
        c for c, t in zip(sex_var["values"], sex_var["valueTexts"])
        if t.lower().startswith("kvinn")
    ]

    cont_var = var(meta, "ContentsCode")
    folkmangd = [
        c for c, t in zip(cont_var["values"], cont_var["valueTexts"])
        if t.lower().startswith("folkmängd")
    ]

    frames = []
    for ychunk in chunks(years, POP_YEARS_PER_CALL):
        for rchunk in chunks(regions, REGION_CHUNK):
            print(f"  folkmängd {ychunk[0]}-{ychunk[-1]}  ({len(rchunk)} regioner)")
            q = [
                {"code": "Region", "selection": {"filter": "item", "values": rchunk}},
                {"code": "Civilstand", "selection": {"filter": "item", "values": civ_codes}},
                {"code": "Alder", "selection": {"filter": "item", "values": age_codes}},
                {"code": "Kon", "selection": {"filter": "item", "values": women}},
                {"code": "ContentsCode", "selection": {"filter": "item", "values": folkmangd}},
                {"code": "Tid", "selection": {"filter": "item", "values": [str(y) for y in ychunk]}},
            ]
            df = jsonstat_to_frame(post_query(POP_PATH, q))
            df["alder"] = df["Alder"].map(pop_age_to_int)
            df["ar"] = df["Tid"].astype(int)
            # Summera bort civilstånd.
            df = (
                df.groupby(["Region", "ar", "alder"], as_index=False)["value"]
                .sum()
                .rename(columns={"Region": "region", "value": "kvinnor"})
            )
            frames.append(df)

    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------
# Beräkning
# --------------------------------------------------------------------------

def build_tfr(births: pd.DataFrame, pop: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Medelfolkmängd: medel av 31 dec år t-1 och 31 dec år t.
    prev = pop.copy()
    prev["ar"] = prev["ar"] + 1
    prev = prev.rename(columns={"kvinnor": "kvinnor_ing"})

    den = pop.merge(prev, on=["region", "ar", "alder"], how="left")
    den["kvinnor_medel"] = den[["kvinnor", "kvinnor_ing"]].mean(axis=1)
    den["anm"] = den["kvinnor_ing"].isna().map(
        {True: "endast folkmängd 31 dec (ingen ingående folkmängd)", False: ""}
    )

    asfr = births.merge(
        den[["region", "ar", "alder", "kvinnor_medel", "anm"]],
        on=["region", "ar", "alder"],
        how="outer",
    )
    asfr["fodda"] = asfr["fodda"].fillna(0)
    asfr = asfr[asfr["kvinnor_medel"].notna() & (asfr["kvinnor_medel"] > 0)]
    asfr["asfr"] = asfr["fodda"] / asfr["kvinnor_medel"]

    tfr = (
        asfr.groupby(["region", "ar"], as_index=False)
        .agg(
            tfr=("asfr", "sum"),
            fodda_antal=("fodda", "sum"),
            kvinnor_15_49=("kvinnor_medel", "sum"),
            anm=("anm", "first"),
        )
        .sort_values(["region", "ar"])
    )

    # Åldersgrupper som stöd för tolkning av små kommuner.
    for w in MA_WINDOWS:
        tfr[f"tfr_ma{w}"] = (
            tfr.groupby("region")["tfr"]
            .transform(lambda s: s.rolling(w, center=True, min_periods=w).mean())
        )

    tfr["osaker_litet_underlag"] = tfr["fodda_antal"] < 30
    return tfr, asfr


def add_names(df: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    df = df.copy()
    df.insert(1, "namn", df["region"].map(names))
    return df.rename(columns={"region": "regionkod"})


# --------------------------------------------------------------------------

def main() -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    OUT_DIR.mkdir(exist_ok=True)

    meta = get_meta(BIRTHS_PATH)
    kommuner, lan, names = pick_regions(meta)
    print(f"{len(kommuner)} kommuner och {len(lan)} län i tabellen")

    regions = kommuner + (lan + ["00"] if INCLUDE_LAN else [])
    years = list(range(FIRST_YEAR, LAST_YEAR + 1))

    print("Hämtar födda...")
    births = fetch_births(regions, years)
    print("Hämtar folkmängd...")
    pop = fetch_population(regions, years)

    print("Beräknar...")
    tfr, asfr = build_tfr(births, pop)

    kom = add_names(tfr[tfr["region"].isin(kommuner)], names)
    kom.to_csv(OUT_DIR / "tfr_kommun_long.csv", index=False, encoding="utf-8-sig")

    wide = kom.pivot_table(index=["regionkod", "namn"], columns="ar", values="tfr")
    wide.round(3).to_csv(OUT_DIR / "tfr_kommun_wide.csv", encoding="utf-8-sig")

    if INCLUDE_LAN:
        lan_df = add_names(tfr[tfr["region"].isin(lan + ["00"])], names)
        lan_df.to_csv(OUT_DIR / "tfr_lan_long.csv", index=False, encoding="utf-8-sig")

    if SAVE_ASFR:
        add_names(asfr, names).to_csv(
            OUT_DIR / "asfr_kommun.csv", index=False, encoding="utf-8-sig"
        )

    # Rimlighetskontroll mot SCB:s publicerade riksvärden.
    print("\nRiket, jämför med SCB:s publicerade summerade fruktsamhet:")
    riket = tfr[tfr["region"] == "00"].set_index("ar")["tfr"]
    facit = {1970: 1.92, 1980: 1.68, 1990: 2.13, 2000: 1.54,
             2010: 1.98, 2020: 1.66, 2024: 1.43}
    for y, expect in facit.items():
        if y in riket.index:
            print(f"  {y}: beräknat {riket[y]:.2f}   SCB ca {expect:.2f}")

    print(f"\nKlart. {len(kom)} kommunrader skrivna till {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()