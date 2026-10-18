"""
Lapisan analitik: membangun 'state' aplikasi (sekali saat start) dan fungsi-fungsi
yang menghitung data untuk setiap halaman / API. Semua teks interpretasi disusun dari angka hasil hitung.
"""
import os

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

import pipeline as pl

DEFAULT_K = 4
DEFAULT_SUPPORT = 0.01
DEFAULT_CONF = 0.20
LOW_SUPPORT = 0.005

LABEL_COLORS = {
    "Loyal Customers": "#0f9d78",
    "Potential Customers": "#3b6fd4",
    "Occasional Customers": "#e8a317",
    "Churn Risk": "#d9453d",
    "At Risk (Mulai Pasif)": "#8e5bd0",
}
FALLBACK = ["#64748b", "#0891b2", "#be185d", "#65a30d"]


def rp(x):
    return "Rp " + f"{x:,.0f}".replace(",", ".")


def rp_short(x):
    if x >= 1e9:
        return f"Rp {x/1e9:.2f} M".replace(".", ",")
    if x >= 1e6:
        return f"Rp {x/1e6:.1f} jt".replace(".", ",")
    return rp(x)


def pct(x, d=1):
    return f"{x*100:.{d}f}%".replace(".", ",")


class State:
    pass


# ----------------------------------------------------------------------------
# K-Means helper (label dihitung dari bukti data)
# ----------------------------------------------------------------------------
def label_clusters(rfm, labels):
    r = rfm.copy()
    r["c"] = labels
    prof = r.groupby("c").agg(n=("Recency", "size"), R=("Recency", "mean"), F=("Frequency", "mean"), M=("Monetary", "mean"))
    mu, sd = rfm[["Recency", "Frequency", "Monetary"]].mean(), rfm[["Recency", "Frequency", "Monetary"]].std()
    zR = (prof.R - mu["Recency"]) / sd["Recency"]
    zF = (prof.F - mu["Frequency"]) / sd["Frequency"]
    zM = (prof.M - mu["Monetary"]) / sd["Monetary"]
    v = zF + zM
    names, used = {}, {}
    for c in v.sort_values(ascending=False).index:
        if zR[c] > 1.5:
            lab = "Churn Risk"
        elif zR[c] > 0.7:
            lab = "At Risk (Mulai Pasif)"
        elif v[c] > 0.6:
            lab = "Loyal Customers"
        elif v[c] < -0.5:
            lab = "Occasional Customers"
        else:
            lab = "Potential Customers"
        used[lab] = used.get(lab, 0) + 1
        names[c] = lab if used[lab] == 1 else f"{lab} {used[lab]}"
    return names


def color_for(label, i=0):
    base = label.rsplit(" ", 1)[0] if label[-1].isdigit() else label
    return LABEL_COLORS.get(label) or LABEL_COLORS.get(base) or FALLBACK[i % len(FALLBACK)]


def run_kmeans(S, k):
    if k in S._km_cache:
        return S._km_cache[k]
    km = KMeans(n_clusters=k, n_init=20, random_state=pl.SEED).fit(S.Z)
    labs = km.labels_
    names = label_clusters(S.rfm, labs)
    r = S.rfm.copy()
    r["Cluster"] = labs
    r["Segment"] = r["Cluster"].map(names)
    pca = PCA(n_components=2, random_state=pl.SEED).fit(S.Z)
    pc = pca.transform(S.Z)
    r["PC1"], r["PC2"] = pc[:, 0], pc[:, 1]
    total_rev = r["Monetary"].sum()
    prof = []
    for c, g in r.groupby("Cluster"):
        lab = names[c]
        prof.append({
            "cluster": int(c), "label": lab, "color": color_for(lab, c), "n": int(len(g)), "share": len(g) / len(r),
            "R_mean": g["Recency"].mean(), "R_med": g["Recency"].median(),
            "F_mean": g["Frequency"].mean(), "F_med": g["Frequency"].median(),
            "M_mean": g["Monetary"].mean(), "M_med": g["Monetary"].median(),
            "rev": g["Monetary"].sum(), "rev_share": g["Monetary"].sum() / total_rev,
            "aov": g["Monetary"].sum() / g["Frequency"].sum(),
        })
    prof.sort(key=lambda p: -p["M_mean"])
    res = {"k": k, "rfm": r, "names": names, "profile": prof, "var": pca.explained_variance_ratio_.tolist(),
           "colors": {p["label"]: p["color"] for p in prof}}
    S._km_cache[k] = res
    return res


# ----------------------------------------------------------------------------
# Build state
# ----------------------------------------------------------------------------
def build_state(xlsx_path, out_dir):
    S = State()
    S._km_cache = {}
    wb = pl.load_workbook(xlsx_path)
    S.raw, S.produk, S.pelanggan, S.dictionary = wb["raw"], wb["produk"], wb["pelanggan"], wb["dictionary"]
    S.audit = pl.audit(S.raw, S.produk)
    S.df, S.log, S.summary = pl.preprocess(S.raw, S.produk, S.pelanggan)
    S.trans = pl.build_transactions(S.df)
    S.rfm, S.ref_date = pl.build_rfm(S.df)
    S.X, S.Z, S.scaler = pl.kmeans_features(S.rfm)
    S.evals = pl.evaluate_k(S.Z)
    S.k = DEFAULT_K
    km = run_kmeans(S, S.k)
    S.km = km
    S.seg_of = km["rfm"].set_index("Customer_ID")["Segment"]
    S.df["Segment"] = S.df["Customer_ID"].map(S.seg_of)
    S.trans["Segment"] = S.trans["Customer_ID"].map(S.seg_of)
    S.products = sorted(S.df["Product_Name"].unique())
    S.categories = sorted(S.df["Category"].unique())
    S.regions = sorted(S.df["Region"].unique())
    S.date_min, S.date_max = S.df["Date"].min(), S.df["Date"].max()
    S.matrix = pl.basket_matrix(S.df)
    S.its, S.rules = pl.apriori(S.matrix, DEFAULT_SUPPORT, DEFAULT_CONF, 3)
    S.its_low, S.rules_low = pl.apriori(S.matrix, LOW_SUPPORT, DEFAULT_CONF, 3)
    S.cat_of = S.produk.set_index("Product_Name")["Category"].to_dict()
    S.price_of = S.produk.set_index("Product_Name")["Reference_Unit_Price_Rp"].to_dict()

    os.makedirs(out_dir, exist_ok=True)
    S.df.drop(columns=["Month", "Hour", "DayName"]).to_csv(os.path.join(out_dir, "data_bersih.csv"), index=False)
    S.trans.to_csv(os.path.join(out_dir, "transaksi_basket_size.csv"), index=False)
    km["rfm"][["Customer_ID", "Recency", "Frequency", "Monetary", "Cluster", "Segment"]].to_csv(os.path.join(out_dir, "rfm_segmentasi_pelanggan.csv"), index=False)
    S.rules.drop(columns=["ant_items", "con_items"]).to_csv(os.path.join(out_dir, "aturan_asosiasi.csv"), index=False)
    pd.DataFrame(S.log).to_csv(os.path.join(out_dir, "log_preprocessing.csv"), index=False)
    return S


# ----------------------------------------------------------------------------
# Apriori helpers
# ----------------------------------------------------------------------------
def rules_records(rl, n=None, min_lift=1.0):
    if rl is None or len(rl) == 0:
        return []
    d = rl[rl["lift"] > min_lift].sort_values(["lift", "confidence"], ascending=False)
    if n:
        d = d.head(n)
    out = []
    for i, r in enumerate(d.itertuples(), 1):
        out.append({"rank": i, "antecedent": r.antecedent, "consequent": r.consequent, "ant_items": r.ant_items, "con_items": r.con_items,
                    "count": int(r.count), "support": float(r.support), "confidence": float(r.confidence), "lift": float(r.lift),
                    "leverage": float(r.leverage)})
    return out


def unique_pairs(recs):
    """Gabungkan arah A->B dan B->A menjadi satu pasangan (ambil yang confidence terbesar sebagai arah utama)."""
    seen, out = {}, []
    for r in recs:
        key = frozenset(r["ant_items"] + r["con_items"])
        if key not in seen:
            seen[key] = len(out)
            out.append(dict(r, conf_rev=None))
        else:
            o = out[seen[key]]
            o["conf_rev"] = r["confidence"] if r["confidence"] < o["confidence"] else o["confidence"]
            if r["confidence"] > o["confidence"]:
                for f in ("antecedent", "consequent", "ant_items", "con_items", "confidence"):
                    o[f] = r[f]
    return out


def lift_matrix(mat):
    X = mat.values.astype(float)
    n = len(X)
    co = X.T @ X
    p = X.mean(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        lift = (co / n) / np.outer(p, p)
    np.fill_diagonal(lift, np.nan)
    return list(mat.columns), np.where(np.isnan(lift), None, np.round(lift, 3)).tolist(), co.astype(int).tolist()


def apriori_payload(S, support, conf, maxlen=3, mat=None, topn=10):
    mat = S.matrix if mat is None else mat
    its, rl = pl.apriori(mat, support, conf, maxlen)
    rec = rules_records(rl, None)
    top = rec[:topn]
    names, lm, co = lift_matrix(mat)
    edges = {}
    for r in rec:
        if len(r["ant_items"]) == 1 and len(r["con_items"]) == 1:
            k = tuple(sorted([r["ant_items"][0], r["con_items"][0]]))
            if k not in edges or r["lift"] > edges[k]["lift"]:
                edges[k] = {"a": k[0], "b": k[1], "lift": r["lift"], "support": r["support"], "confidence": r["confidence"]}
    edge_list = sorted(edges.values(), key=lambda e: -e["lift"])[:25]
    return {
        "n_trans": int(len(mat)), "support": support, "conf": conf, "maxlen": maxlen,
        "min_count": int(np.ceil(support * len(mat))),
        "n_itemsets": int(len(its)), "itemsets_by_size": {int(k): int(v) for k, v in its["size"].value_counts().sort_index().items()} if len(its) else {},
        "n_rules": int(len(rl)), "n_rules_lift": int((rl["lift"] > 1).sum()) if len(rl) else 0,
        "itemsets": [{"itemset": " + ".join(r.itemset), "size": int(r.size), "count": int(r.count), "support": float(r.support)}
                     for r in its.sort_values(["support"], ascending=False).head(40).itertuples()],
        "top_rules": top, "all_rules": rec[:150], "edges": edge_list,
        "heat": {"names": names, "lift": lm, "co": co},
        "pairs": unique_pairs(rec)[:8],
    }


def support_sensitivity(S):
    rows = []
    for s in [0.02, 0.015, 0.01, 0.0075, 0.005]:
        its, rl = pl.apriori(S.matrix, s, DEFAULT_CONF, 3)
        rows.append({"support": s, "min_count": int(np.ceil(s * len(S.matrix))), "itemsets": int(len(its)),
                     "rules": int(len(rl)), "rules_lift": int((rl["lift"] > 1.2).sum()) if len(rl) else 0,
                     "triples": int((its["size"] == 3).sum()) if len(its) else 0})
    return rows


# ----------------------------------------------------------------------------
# EDA (data mentah)
# ----------------------------------------------------------------------------
def eda_payload(S):
    raw = S.raw.copy()
    out = {}
    out["shape"] = {"rows": int(raw.shape[0]), "cols": int(raw.shape[1])}
    expected = S.dictionary.set_index("Nama Kolom")["Tipe yang Diharapkan"].to_dict()
    out["dtypes"] = [{"col": c, "dtype": str(raw[c].dtype).replace("str", "object (teks)").replace("StringDtype", "object (teks)"),
                      "expected": expected.get(c, "-"), "nunique": int(raw[c].nunique()), "missing": int(raw[c].isna().sum()),
                      "example": str(raw[c].dropna().iloc[0])} for c in raw.columns]
    out["date_min"], out["date_max"] = str(raw["Transaction_Date"].min()), str(raw["Transaction_Date"].max())
    out["span_days"] = int((raw["Transaction_Date"].max() - raw["Transaction_Date"].min()).days + 1)
    bs = raw.groupby("Transaction_ID")["Product_Name"].nunique()
    prod_cat = S.cat_of
    raw["Cat2"] = raw["Product_Name"].map(prod_cat)
    desc = {
        "n_trans": int(raw["Transaction_ID"].nunique()), "n_rows": int(len(raw)),
        "n_cust": int(raw["Customer_ID"].nunique()), "n_prod": int(raw["Product_Name"].nunique()),
        "avg_qty_raw": float(raw["Quantity"].mean()), "median_qty": float(raw["Quantity"].median()),
        "avg_qty_valid": float(raw.loc[raw["Quantity"].between(1, pl.MAX_QTY), "Quantity"].mean()),
        "total_sales_raw": float(raw["Line_Total"].sum()), "avg_basket": float(bs.mean()),
        "avg_line_total": float(raw["Line_Total"].mean()), "median_line_total": float(raw["Line_Total"].median()),
        "max_line_total": float(raw["Line_Total"].max()),
    }
    out["desc"] = desc
    num = raw[["Quantity", "Unit_Price", "Discount_Rate", "Line_Total"]].describe().T
    out["numdesc"] = [{"col": i, **{k: float(v) for k, v in r.items()}} for i, r in num.iterrows()]
    out["missing"] = [{"col": c, "n": int(v), "pct": v / len(raw)} for c, v in raw.isna().sum().items()]
    a = S.audit
    out["audit"] = a
    # outlier IQR
    q1, q3 = raw["Line_Total"].quantile([.25, .75])
    up = q3 + 1.5 * (q3 - q1)
    out["iqr"] = {"q1": float(q1), "q3": float(q3), "upper": float(up), "n": int((raw["Line_Total"] > up).sum())}
    # charts
    m = raw.groupby(raw["Transaction_Date"].dt.to_period("M").astype(str)).agg(rev=("Line_Total", "sum"), trx=("Transaction_ID", "nunique"))
    out["monthly"] = {"labels": [pl.MONTHS_ID[int(i[-2:]) - 1] for i in m.index], "rev": m["rev"].astype(float).tolist(), "trx": m["trx"].astype(int).tolist()}
    tp = raw.groupby("Product_Name")["Line_Total"].sum().sort_values(ascending=False).head(10)
    out["top_products"] = {"labels": tp.index.tolist(), "values": tp.astype(float).tolist()}
    cat = raw.groupby("Cat2")["Line_Total"].sum().sort_values(ascending=False)
    out["categories"] = {"labels": cat.index.tolist(), "values": cat.astype(float).tolist()}
    pm = raw["Payment_Method"].fillna("(kosong)").value_counts()
    out["payment"] = {"labels": pm.index.tolist(), "values": pm.astype(int).tolist()}
    bins = [-np.inf, 0, 1, 2, 3, 4, 5, 6, 50, np.inf]
    labs = ["<= 0", "1", "2", "3", "4", "5", "6", "7-50", "> 50"]
    qd = pd.cut(raw["Quantity"].dropna(), bins=bins, labels=labs).value_counts().reindex(labs)
    out["qty_dist"] = {"labels": labs, "values": qd.astype(int).tolist()}
    hr = raw.groupby(raw["Transaction_Date"].dt.hour)["Transaction_ID"].nunique()
    out["hourly"] = {"labels": [f"{h:02d}" for h in hr.index], "values": hr.astype(int).tolist()}
    bsd = bs.value_counts().sort_index()
    out["basket_dist"] = {"labels": [str(i) for i in bsd.index], "values": bsd.astype(int).tolist()}
    reg = raw.groupby("Region")["Line_Total"].sum().sort_values(ascending=False)
    out["region"] = {"labels": reg.index.tolist(), "values": reg.astype(float).tolist()}
    # temuan
    dup_val = float(raw[raw.duplicated()]["Line_Total"].sum())
    peak = m["rev"].idxmax()
    low = m["rev"].idxmin()
    top3 = tp.head(3)
    cat_top = cat.index[0]
    f = []
    f.append(f"Satu nota berisi beberapa baris produk: terdapat {desc['n_rows']:,} baris tetapi hanya {desc['n_trans']:,} transaksi unik "
             f"(rata-rata {desc['n_rows']/desc['n_trans']:.2f} baris per nota). Menghitung baris sebagai transaksi akan menggelembungkan jumlah transaksi {desc['n_rows']/desc['n_trans']:.1f} kali.".replace(",", "."))
    f.append(f"Data mentah mengandung {a['duplicates_exact']} baris duplikat persis senilai {rp(dup_val)} "
             f"({pct(dup_val/desc['total_sales_raw'])} dari total penjualan mentah) yang akan menggandakan omzet bila tidak dibersihkan.")
    f.append(f"Ada {a['qty_extreme']} baris dengan Quantity 999 dan {a['qty_nonpositive']} baris Quantity nol/negatif, serta {a['price_bad_total']} Unit_Price tidak masuk akal "
             f"(999999, -100, kosong). Rata-rata Quantity mentah {desc['avg_qty_raw']:.2f} terdistorsi; rata-rata sebenarnya (qty valid) hanya {desc['avg_qty_valid']:.2f}.")
    f.append(f"Penjualan bulanan tertinggi terjadi pada {pl.MONTHS_ID[int(peak[-2:])-1]} ({rp_short(m.loc[peak,'rev'])}) dan terendah pada "
             f"{pl.MONTHS_ID[int(low[-2:])-1]} ({rp_short(m.loc[low,'rev'])}); selisihnya {pct(m.loc[peak,'rev']/m.loc[low,'rev']-1,0)} sehingga ada pola musiman yang dapat dimanfaatkan untuk perencanaan stok & promosi.")
    f.append(f"Tiga produk dengan omzet terbesar: {', '.join(top3.index)} (total {pct(top3.sum()/raw['Line_Total'].sum())} dari omzet). "
             f"Kategori terbesar adalah {cat_top} ({pct(cat.iloc[0]/cat.sum())}).")
    f.append(f"Ukuran basket kecil: rata-rata {desc['avg_basket']:.2f} produk berbeda per nota (maksimum {int(bs.max())}). "
             f"Dengan 30 produk dan basket sekecil ini, ambang support Apriori harus dipilih rendah (~1%).")
    out["findings"] = f
    return out


# ----------------------------------------------------------------------------
# Dashboard dinamis
# ----------------------------------------------------------------------------
def filter_df(S, start=None, end=None, cats=None, segs=None, regions=None):
    d = S.df
    m = pd.Series(True, index=d.index)
    if start:
        m &= d["Date"] >= pd.Timestamp(start)
    if end:
        m &= d["Date"] <= pd.Timestamp(end)
    if cats:
        m &= d["Category"].isin(cats)
    if segs:
        m &= d["Segment"].isin(segs)
    if regions:
        m &= d["Region"].isin(regions)
    return d[m]


def dashboard_payload(S, start=None, end=None, cats=None, segs=None, regions=None, support=DEFAULT_SUPPORT, conf=DEFAULT_CONF):
    d = filter_df(S, start, end, cats, segs, regions)
    out = {"empty": len(d) == 0}
    if len(d) == 0:
        return out
    t = d.groupby("Transaction_ID").agg(b=("Product_ID", "nunique"), rev=("Line_Total", "sum"), cust=("Customer_ID", "first"), q=("Quantity", "sum"))
    out["kpi"] = {"revenue": float(d["Line_Total"].sum()), "transactions": int(len(t)), "customers": int(d["Customer_ID"].nunique()),
                  "avg_basket": float(t["b"].mean()), "aov": float(t["rev"].mean()), "items": int(d["Quantity"].sum()),
                  "rows": int(len(d)), "member_share": float(d.drop_duplicates("Transaction_ID")["Customer_Type"].eq("Member").mean())}
    # tren bulanan
    months = pd.period_range(S.date_min, S.date_max, freq="M").astype(str)
    mm = d.groupby("Month").agg(rev=("Line_Total", "sum"), trx=("Transaction_ID", "nunique")).reindex(months, fill_value=0)
    out["monthly"] = {"labels": [pl.MONTHS_ID[int(i[-2:]) - 1] for i in months], "rev": mm["rev"].astype(float).tolist(), "trx": mm["trx"].astype(int).tolist()}
    g = d.groupby("Product_Name").agg(rev=("Line_Total", "sum"), qty=("Quantity", "sum"), trx=("Transaction_ID", "nunique"))
    tr = g.sort_values("rev", ascending=False).head(10)
    tq = g.sort_values("qty", ascending=False).head(10)
    out["top_rev"] = {"labels": tr.index.tolist(), "values": tr["rev"].astype(float).tolist(), "cats": [S.cat_of[p] for p in tr.index]}
    out["top_qty"] = {"labels": tq.index.tolist(), "values": tq["qty"].astype(int).tolist(), "cats": [S.cat_of[p] for p in tq.index]}
    c = d.groupby("Category")["Line_Total"].sum().sort_values(ascending=False)
    out["categories"] = {"labels": c.index.tolist(), "values": c.astype(float).tolist()}
    rg = d.groupby("Region")["Line_Total"].sum().sort_values(ascending=False)
    out["region"] = {"labels": rg.index.tolist(), "values": rg.astype(float).tolist()}
    # heatmap hari x jam (jumlah transaksi)
    tt = d.drop_duplicates("Transaction_ID")
    hrs = tt.groupby(tt["Transaction_Date"].dt.hour)["Transaction_ID"].count()
    out["hourly"] = {"labels": [f"{h:02d}" for h in hrs.index], "values": hrs.astype(int).tolist()}
    pay = tt["Payment_Method"].value_counts()
    out["payment"] = {"labels": pay.index.tolist(), "values": pay.astype(int).tolist()}
    # Apriori pada data terfilter
    mat = pl.basket_matrix(d)
    ap = apriori_payload(S, support, conf, 3, mat=mat, topn=10)
    out["apriori"] = {k: ap[k] for k in ("n_trans", "min_count", "n_itemsets", "n_rules", "n_rules_lift", "top_rules", "edges", "pairs")}
    out["apriori"]["heat"] = ap["heat"]
    # K-Means (pelanggan yang aktif dalam filter)
    r = S.km["rfm"]
    act = r[r["Customer_ID"].isin(d["Customer_ID"].unique())]
    prof = []
    for p in S.km["profile"]:
        n_f = int((act["Segment"] == p["label"]).sum())
        sub = d[d["Segment"] == p["label"]]
        prof.append(dict(p, n_active=n_f, rev_f=float(sub["Line_Total"].sum()), trx_f=int(sub["Transaction_ID"].nunique())))
    out["segments"] = {"profile": prof, "var": S.km["var"],
                       "points": [{"id": x.Customer_ID, "R": int(x.Recency), "F": int(x.Frequency), "M": float(x.Monetary), "s": x.Segment,
                                   "x": round(float(x.PC1), 3), "y": round(float(x.PC2), 3)} for x in act.itertuples()]}
    # bonus: apriori x segmen + produk khas segmen
    tseg = tt.set_index("Transaction_ID")["Segment"]
    seg_rules, seg_prod = [], []
    share_all = mat.mean()
    for p in S.km["profile"]:
        lab = p["label"]
        idx = tseg[tseg == lab].index.intersection(mat.index)
        if len(idx) < 60:
            seg_rules.append({"label": lab, "color": p["color"], "n": int(len(idx)), "rules": [], "products": []})
            continue
        sm = mat.loc[idx]
        sup = max(support, 25 / len(idx))
        _, rl = pl.apriori(sm, sup, conf, 2)
        recs = unique_pairs(rules_records(rl, None, 1.2))[:3]
        idxp = (sm.mean() / share_all).sort_values(ascending=False)
        seg_rules.append({"label": lab, "color": p["color"], "n": int(len(idx)), "min_support": sup, "rules": recs,
                          "products": [{"product": k, "share": float(sm[k].mean()), "index": float(v)} for k, v in idxp.head(3).items()]})
    out["seg_rules"] = seg_rules
    return out


# ----------------------------------------------------------------------------
# Rekomendasi preskriptif (Tahap 6)
# ----------------------------------------------------------------------------
SCENARIOS = [("Konservatif", 0.05), ("Moderat", 0.10), ("Optimistis", 0.15)]


def _mean_line(S, product):
    return float(S.df.loc[S.df["Product_Name"] == product, "Line_Total"].mean())


def recommendations_payload(S):
    out = {}
    prof = {p["label"]: p for p in S.km["profile"]}
    base = {
        "revenue": float(S.df["Line_Total"].sum()), "trx": int(S.trans.shape[0]), "cust": int(S.rfm.shape[0]),
        "avg_basket": float(S.trans["basket_size"].mean()), "aov": float(S.trans["revenue"].mean()),
        "freq": float(S.rfm["Frequency"].mean()),
    }
    out["base"] = base
    n = len(S.matrix)
    cnt = S.matrix.sum()

    # --- A. cross-sell / bundling
    pairs = [p for p in unique_pairs(rules_records(S.rules, None, 1.2)) if len(p["ant_items"]) == 1 and len(p["con_items"]) == 1][:5]
    cross = []
    for p in pairs:
        a, b = p["ant_items"][0], p["con_items"][0]
        both = int(round(p["support"] * n))
        a_wo_b = int(cnt[a]) - both
        la, lb = _mean_line(S, a), _mean_line(S, b)
        sc = []
        for nm, u in SCENARIOS:
            inc_trx = a_wo_b * u
            inc_rev = inc_trx * lb
            cost = 0.05 * (both + inc_trx) * (la + lb)  # diskon bundling 5% (asumsi)
            sc.append({"name": nm, "uplift": u, "inc_trx": inc_trx, "inc_rev": inc_rev, "cost": cost, "net": inc_rev - cost})
        cross.append({"a": a, "b": b, "cat_a": S.cat_of[a], "cat_b": S.cat_of[b], "support": p["support"], "confidence": p["confidence"],
                      "conf_rev": p.get("conf_rev"), "lift": p["lift"], "both": both, "a_wo_b": a_wo_b, "scen": sc, "mean_a": la, "mean_b": lb})
    out["cross"] = cross
    # bundle 3-item dari support rendah
    triple = [r for r in rules_records(S.rules_low, None, 1.5) if len(r["ant_items"]) + len(r["con_items"]) == 3]
    out["triple"] = triple[:2]
    items3 = sorted(set(triple[0]["ant_items"] + triple[0]["con_items"])) if triple else []
    out["triple_items"] = items3
    if items3:
        sub = S.matrix[items3].all(axis=1).sum()
        out["triple_count"] = int(sub)
        out["triple_support"] = float(sub / n)
        out["triple_value"] = float(sum(_mean_line(S, i) for i in items3))

    # --- B. retensi
    seg = []
    for lab in ["Loyal Customers", "Churn Risk", "Potential Customers", "Occasional Customers"]:
        if lab in prof:
            seg.append(prof[lab])
    out["seg"] = {p["label"]: p for p in S.km["profile"]}
    churn = prof.get("Churn Risk")
    if churn:
        voucher = 15000
        sc = []
        for nm, rate in [("Konservatif", 0.10), ("Moderat", 0.20), ("Optimistis", 0.30)]:
            react = churn["n"] * rate
            rev = react * churn["M_mean"]
            cost = react * voucher + churn["n"] * 500  # biaya pesan WA/SMS Rp500 per pelanggan (asumsi)
            sc.append({"name": nm, "rate": rate, "react": react, "rev": rev, "cost": cost, "net": rev - cost})
        out["churn_scen"] = sc
        out["voucher"] = voucher
    loyal = prof.get("Loyal Customers")
    if loyal:
        sc = []
        for nm, g in [("Konservatif", 0.05), ("Moderat", 0.10), ("Optimistis", 0.15)]:
            rev = loyal["rev"] * g
            cost = rev * 0.05  # biaya program poin ~5% dari kenaikan (asumsi)
            sc.append({"name": nm, "growth": g, "rev": rev, "cost": cost, "net": rev - cost})
        out["loyal_scen"] = sc
    pot = prof.get("Potential Customers")
    if pot:
        sc = []
        for nm, tk in [("Konservatif", 0.10), ("Moderat", 0.20), ("Optimistis", 0.30)]:
            up = pot["n"] * tk
            rev = up * pot["aov"]  # tambahan 1 transaksi/tahun per pelanggan yang berhasil dinaikkan
            cost = rev * 0.08
            sc.append({"name": nm, "takeup": tk, "up": up, "rev": rev, "cost": cost, "net": rev - cost})
        out["pot_scen"] = sc

    # --- C. matriks prioritas
    def mod(sc, key="net"):
        return sc[1][key] if sc else 0
    cross_net = sum(c["scen"][1]["net"] for c in cross)
    items = [
        {"id": "R1", "nama": "Bundling & penempatan berdekatan pasangan produk berlift tinggi", "net": cross_net,
         "urgensi": 3, "biaya": 5, "mudah": 5},
        {"id": "R2", "nama": "Kampanye win-back pelanggan Churn Risk", "net": mod(out.get("churn_scen", [])),
         "urgensi": 5, "biaya": 4, "mudah": 4},
        {"id": "R3", "nama": "Program loyalitas & prioritas layanan untuk Loyal Customers", "net": mod(out.get("loyal_scen", [])),
         "urgensi": 4, "biaya": 3, "mudah": 3},
        {"id": "R4", "nama": "Dorong Potential Customers naik menjadi Loyal (frekuensi belanja)", "net": mod(out.get("pot_scen", [])),
         "urgensi": 3, "biaya": 3, "mudah": 3},
    ]
    mx = max(i["net"] for i in items) or 1
    for i in items:
        i["manfaat"] = max(1, round(1 + 4 * i["net"] / mx))
        i["skor"] = round(0.30 * i["urgensi"] + 0.35 * i["manfaat"] + 0.15 * i["biaya"] + 0.20 * i["mudah"], 2)
    items.sort(key=lambda i: -i["skor"])
    for r, i in enumerate(items, 1):
        i["rank"] = r
    out["prioritas"] = items
    return out


# ----------------------------------------------------------------------------
# Strategi per segmen (teks kebijakan; angka dirujuk dari profil hasil hitung)
# ----------------------------------------------------------------------------
STRATEGY = {
    "Loyal Customers": {
        "ciri": "Belanja paling sering dan paling besar, transaksi terakhir masih baru.",
        "aksi": ["Program poin/tier member dengan hadiah berbasis frekuensi, bukan diskon umum (menjaga margin).",
                 "Penawaran paket sembako & kebutuhan bayi langsung ke pelanggan ini (cross-sell berlift tinggi).",
                 "Akses awal stok produk musiman dan layanan antar prioritas."],
        "kpi": "Retention rate, frekuensi per pelanggan, share of wallet",
        "prioritas": "Pertahankan"},
    "Potential Customers": {
        "ciri": "Pelanggan aktif dengan frekuensi dan nilai belanja menengah; belum sebesar Loyal.",
        "aksi": ["Voucher 'belanja ke-5' / kupon berlaku 14 hari untuk menaikkan frekuensi.",
                 "Rekomendasi pelengkap saat checkout berdasarkan aturan Apriori untuk menaikkan basket size.",
                 "Tawarkan keanggotaan jika masih Non-Member."],
        "kpi": "Persentase naik kelas ke Loyal, frekuensi, basket size",
        "prioritas": "Kembangkan"},
    "Occasional Customers": {
        "ciri": "Belanja jarang dengan nilai kecil walaupun masih relatif baru aktif.",
        "aksi": ["Promo produk kebutuhan harian bervolume tinggi (air mineral, mi instan) sebagai pemicu kunjungan.",
                 "Ajakan belanja kedua dengan minimum belanja tertentu (biaya rendah).",
                 "Jangan alokasikan diskon besar: potensi nilai rendah."],
        "kpi": "Repeat purchase rate, rata-rata nilai nota",
        "prioritas": "Pantau / biaya rendah"},
    "Churn Risk": {
        "ciri": "Lama tidak berbelanja (recency tinggi) dengan frekuensi rendah — berisiko tidak kembali.",
        "aksi": ["Kampanye win-back via WhatsApp/SMS dengan voucher berbatas waktu (mis. 7 hari).",
                 "Pesan personal berisi produk yang terakhir mereka beli.",
                 "Survei singkat alasan berhenti; evaluasi ketersediaan produk di wilayah mereka."],
        "kpi": "Reactivation rate, biaya per pelanggan kembali",
        "prioritas": "Urgensi tinggi"},
    "At Risk (Mulai Pasif)": {
        "ciri": "Recency mulai memanjang di atas rata-rata; belum sepenuhnya hilang.",
        "aksi": ["Pengingat belanja ulang dan penawaran personal sebelum pelanggan benar-benar hilang."],
        "kpi": "Recency rata-rata, reactivation rate", "prioritas": "Cegah churn"},
}


def strategy(label):
    base = label.rsplit(" ", 1)[0] if label[-1].isdigit() else label
    return STRATEGY.get(label) or STRATEGY.get(base) or STRATEGY["Potential Customers"]
