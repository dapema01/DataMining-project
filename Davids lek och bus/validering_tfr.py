"""
Validerar TFR-beräkningen mot SCB:s egna publicerade värden.

SCB publicerar färdigberäknad summerad fruktsamhet per kommun 2000-2025 i
tabellen FruktsamhetSum. Din egen beräkning täcker 1968-2024. Överlappet är
25 år, och det är där metoden kan prövas: stämmer den för 2000-2024 på
kommunnivå, håller samma metod bakåt till 1968.

Scriptet gör fyra kontroller:

  1. Kommunnivå 2000-2024, rad för rad mot SCB. Huvudtestet.
  2. Riksnivå per år, samma period.
  3. Avvikelsernas samband med kommunstorlek.
  4. Intern konsistens: summerar kommunernas födda till rikets antal?

Körning:
    python validera_tfr.py

Förutsätter att huvudscriptet körts och skrivit AntalPerKommunLangHistoria/tfr_kommun_long.csv.
Delar cache-katalogen med huvudscriptet.
"""

from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path

import pandas as pd
import requests

BASE = "https://api.scb.se/OV0104/v1/doris/sv/ssd"
SCB_TFR_PATH = "START/BE/BE0101/BE0101H/FruktsamhetSum"

IN_KOMMUN = Path("AntalPerKommunLangHistoria/tfr_kommun_long.csv")
IN_LAN = Path("AntalPerKommunLangHistoria/tfr_lan_long.csv")
CACHE_DIR = Path("scb_cache")
OUT_DIR = Path("AntalPerKommunLangHistoria")

# Toleranser för godkänt. Avrundning hos SCB ger i sig upp till 0,005.
TOL_OK = 0.02
TOL_ACCEPT = 0.05

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "tfr-validering/1.0"})


# --------------------------------------------------------------------------

def post_query(path: str, query: list[dict]) -> dict:
    body = {"query": query, "response": {"format": "json-stat2"}}
    key = hashlib.sha1((path + json.dumps(body, sort_keys=True)).encode()).hexdigest()[:20]
    cache = CACHE_DIR / f"valid_{key}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    for attempt in range(6):
        r = SESSION.post(f"{BASE}/{path}", json=body, timeout=180)
        if r.status_code == 200:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(r.text, encoding="utf-8")
            time.sleep(1.2)
            return r.json()
        if r.status_code in (429, 502, 503, 504):
            time.sleep(5 * (attempt + 1))
            continue
        raise RuntimeError(f"{r.status_code} från SCB: {r.text[:400]}")
    raise RuntimeError("Gav upp efter upprepade fel mot SCB:s API")


def jsonstat_to_frame(ds: dict) -> pd.DataFrame:
    ids, sizes, values = ds["id"], ds["size"], ds["value"]
    cats = []
    for dim in ids:
        idx = ds["dimension"][dim]["category"]["index"]
        cats.append(sorted(idx, key=idx.get) if isinstance(idx, dict) else list(idx))

    strides = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]

    cols = {dim: [] for dim in ids}
    out = []
    for flat in range(len(values) if not isinstance(values, dict) else max(int(k) for k in values) + 1):
        v = values[flat] if not isinstance(values, dict) else values.get(str(flat))
        if v is None:
            continue
        for d, dim in enumerate(ids):
            cols[dim].append(cats[d][(flat // strides[d]) % sizes[d]])
        out.append(v)

    df = pd.DataFrame(cols)
    df["value"] = out
    return df


def hamta_scb_facit() -> pd.DataFrame:
    """SCB:s publicerade TFR per region och år, kvinnor."""
    meta = json.loads(
        (CACHE_DIR / "meta_valid.json").read_text(encoding="utf-8")
    ) if (CACHE_DIR / "meta_valid.json").exists() else None

    if meta is None:
        r = SESSION.get(f"{BASE}/{SCB_TFR_PATH}", timeout=60)
        r.raise_for_status()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / "meta_valid.json").write_text(r.text, encoding="utf-8")
        meta = r.json()

    v = {x["code"]: x for x in meta["variables"]}
    regions = v["Region"]["values"]
    kvinnor = [
        c for c, t in zip(v["Kon"]["values"], v["Kon"]["valueTexts"])
        if t.lower().startswith("kvinn")
    ]
    years = v["Tid"]["values"]

    frames = []
    for i in range(0, len(years), 8):
        ych = years[i : i + 8]
        print(f"  hämtar SCB:s facit {ych[0]}-{ych[-1]}")
        q = [
            {"code": "Region", "selection": {"filter": "item", "values": regions}},
            {"code": "Kon", "selection": {"filter": "item", "values": kvinnor}},
            {"code": "ContentsCode", "selection": {"filter": "item",
                                                   "values": v["ContentsCode"]["values"]}},
            {"code": "Tid", "selection": {"filter": "item", "values": ych}},
        ]
        frames.append(jsonstat_to_frame(post_query(SCB_TFR_PATH, q)))

    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns={"Region": "regionkod", "value": "tfr_scb"})
    df["ar"] = df["Tid"].astype(int)
    return df[["regionkod", "ar", "tfr_scb"]]


# --------------------------------------------------------------------------

def main() -> None:
    if not IN_KOMMUN.exists():
        raise SystemExit(f"Hittar inte {IN_KOMMUN}. Kör huvudscriptet först.")

    egen = pd.read_csv(IN_KOMMUN, dtype={"regionkod": str})
    print(f"Egen beräkning: {len(egen)} rader, {egen['ar'].min()}-{egen['ar'].max()}")

    print("Hämtar SCB:s publicerade värden...")
    facit = hamta_scb_facit()

    # SCB redovisar inte måttet för regioner med färre än 30 födda; de raderna
    # saknas helt i facit och faller bort i en inner join, vilket är rätt.
    j = egen.merge(facit, on=["regionkod", "ar"], how="inner")
    j["diff"] = j["tfr"] - j["tfr_scb"]
    j["absdiff"] = j["diff"].abs()

    # --- 1. Kommunnivå ----------------------------------------------------
    kom = j[j["regionkod"].str.len() == 4]
    print("\n" + "=" * 62)
    print("1. KOMMUNNIVÅ mot SCB")
    print("=" * 62)
    print(f"  jämförbara rader      {len(kom)}")
    print(f"  medianavvikelse       {kom['absdiff'].median():.4f}")
    print(f"  medelavvikelse        {kom['absdiff'].mean():.4f}")
    print(f"  95:e percentilen      {kom['absdiff'].quantile(0.95):.4f}")
    print(f"  största avvikelse     {kom['absdiff'].max():.4f}")
    print(f"  systematiskt skift    {kom['diff'].mean():+.4f}   (nära 0 = ingen bias)")
    print(f"  inom +/- {TOL_OK}         {(kom['absdiff'] <= TOL_OK).mean():.1%}")
    print(f"  inom +/- {TOL_ACCEPT}         {(kom['absdiff'] <= TOL_ACCEPT).mean():.1%}")

    print("\n  Sämsta 15 raderna:")
    varst = kom.nlargest(15, "absdiff")[
        ["regionkod", "namn", "ar", "tfr", "tfr_scb", "diff", "fodda_antal"]
    ]
    print(varst.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    # --- 2. Riksnivå ------------------------------------------------------
    print("\n" + "=" * 62)
    print("2. RIKSNIVÅ per år")
    print("=" * 62)
    if IN_LAN.exists():
        lan = pd.read_csv(IN_LAN, dtype={"regionkod": str})
        riket = lan[lan["regionkod"] == "00"].merge(facit, on=["regionkod", "ar"])
        riket["diff"] = riket["tfr"] - riket["tfr_scb"]
        print(riket[["ar", "tfr", "tfr_scb", "diff"]].to_string(
            index=False, float_format=lambda x: f"{x:.3f}"))
        print(f"\n  största avvikelse på riksnivå: {riket['diff'].abs().max():.4f}")
    else:
        print("  (kör huvudscriptet med INCLUDE_LAN = True för den här kontrollen)")

    # --- 3. Avvikelse mot storlek ----------------------------------------
    print("\n" + "=" * 62)
    print("3. AVVIKELSE MOT KOMMUNSTORLEK")
    print("=" * 62)
    print("  Avvikelser ska vara störst i små kommuner. Om de är lika stora")
    print("  överallt tyder det på ett metodfel snarare än på brus.\n")
    bins = [0, 50, 100, 250, 500, 1000, 10**9]
    labels = ["<50", "50-99", "100-249", "250-499", "500-999", "1000+"]
    kom = kom.assign(storlek=pd.cut(kom["fodda_antal"], bins=bins,
                                    labels=labels, right=False))
    print(kom.groupby("storlek", observed=True)["absdiff"]
          .agg(rader="size", median="median", p95=lambda s: s.quantile(0.95))
          .to_string(float_format=lambda x: f"{x:.4f}"))

    # --- 4. Intern konsistens --------------------------------------------
    print("\n" + "=" * 62)
    print("4. INTERN KONSISTENS: kommunernas födda mot rikets")
    print("=" * 62)
    if IN_LAN.exists():
        k_sum = (egen.groupby("ar")["fodda_antal"].sum()
                 .rename("summa_kommuner"))
        r_sum = (lan[lan["regionkod"] == "00"].set_index("ar")["fodda_antal"]
                 .rename("riket"))
        cmp = pd.concat([k_sum, r_sum], axis=1).dropna()
        cmp["avvikelse_promille"] = (
            (cmp["summa_kommuner"] - cmp["riket"]) / cmp["riket"] * 1000
        )
        print(cmp.tail(12).to_string(float_format=lambda x: f"{x:,.1f}"))
        print("\n  Små avvikelser är väntade: SCB lägger till slumpmässigt brus")
        print("  i små celler för röjandeskydd (Cell Key Method), så delarna")
        print("  summerar inte exakt till totalen.")
    else:
        print("  (kräver tfr_lan_long.csv)")

    # --- Utdata -----------------------------------------------------------
    OUT_DIR.mkdir(exist_ok=True)
    j.sort_values("absdiff", ascending=False).to_csv(
        OUT_DIR / "validering_jamforelse.csv", index=False, encoding="utf-8-sig"
    )
    print(f"\nFull jämförelse sparad i {OUT_DIR / 'validering_jamforelse.csv'}")

    # --- Sammanfattande omdöme -------------------------------------------
    print("\n" + "=" * 62)
    med = kom["absdiff"].median()
    bias = abs(kom["diff"].mean())
    if med <= TOL_OK and bias <= 0.01:
        print("OMDÖME: metoden reproducerar SCB:s värden. Serien bakåt till")
        print("1968 vilar på samma beräkning och är rimlig att använda.")
    elif med <= TOL_ACCEPT:
        print("OMDÖME: nära, men inte exakt. Titta på om avvikelsen sitter i")
        print("små kommuner (då är det brus) eller överallt (då är det metod).")
    else:
        print("OMDÖME: för stora avvikelser. Troligaste orsaker är nämnaren")
        print("(medelfolkmängd mot folkmängd 31 dec) eller hanteringen av")
        print("mödrar under 15 och över 49. Prova att slå om LUMP_EDGES.")
    print("=" * 62)


if __name__ == "__main__":
    main()