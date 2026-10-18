"""
Sistem Informasi BI Toko - UAS Business Intelligence
Jalankan:  python app.py   ->  http://127.0.0.1:5000
"""
import math
import os

import numpy as np
import pandas as pd
from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from flask.json.provider import DefaultJSONProvider

import analytics as A
import pipeline as pl

BASE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(BASE, "data", "dataset_uas.xlsx")
OUT = os.path.join(BASE, "output")


class Provider(DefaultJSONProvider):
    @staticmethod
    def default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if (math.isnan(o) or math.isinf(o)) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (pd.Timestamp,)):
            return str(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return DefaultJSONProvider.default(o)

    def dumps(self, obj, **kw):
        return super().dumps(_clean(obj), **kw)


def _clean(o):
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


app = Flask(__name__)
app.json = Provider(app)
app.json.ensure_ascii = False

print("Memuat data & menjalankan pipeline analisis ...")
S = A.build_state(XLSX, OUT)
EDA = A.eda_payload(S)
SENS = A.support_sensitivity(S)
REC = A.recommendations_payload(S)
print(f"Siap: {len(S.df):,} baris bersih, {len(S.matrix):,} transaksi, k={S.k}")


@app.template_filter("rp")
def f_rp(x):
    return A.rp(x)


@app.template_filter("rps")
def f_rps(x):
    return A.rp_short(x)


@app.template_filter("pct")
def f_pct(x, d=1):
    return A.pct(x, d)


@app.template_filter("num")
def f_num(x, d=0):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


@app.context_processor
def inject():
    return {"nav": [
        ("dashboard", "/", "Dashboard BI", "grid"),
        ("bisnis", "/bisnis", "1 · Business Understanding", "target"),
        ("eda", "/eda", "2 · Eksplorasi Data (EDA)", "search"),
        ("preprocessing", "/preprocessing", "3 · Preprocessing & Fitur", "wrench"),
        ("apriori", "/apriori", "4 · Apriori (Market Basket)", "basket"),
        ("kmeans", "/kmeans", "5 · K-Means (Segmentasi)", "users"),
        ("rekomendasi", "/rekomendasi", "6 · Rekomendasi Keputusan", "flag"),
    ], "fmt_date": lambda d: pd.Timestamp(d).strftime("%d %b %Y")}


def _list(name):
    v = request.args.get(name, "")
    return [x for x in v.split("|") if x] or None


# ------------------------------------------------------------------ halaman
@app.route("/")
def dashboard():
    return render_template("dashboard.html", page="dashboard", S=S,
                           meta={"start": str(S.date_min.date()), "end": str(S.date_max.date()), "cats": S.categories,
                                 "regions": S.regions, "segs": [p["label"] for p in S.km["profile"]],
                                 "colors": S.km["colors"], "support": A.DEFAULT_SUPPORT, "conf": A.DEFAULT_CONF})


@app.route("/bisnis")
def bisnis():
    prof = {p["label"]: p for p in S.km["profile"]}
    top = [p for p in A.unique_pairs(A.rules_records(S.rules, None, 1.2)) if len(p["ant_items"]) == 1][:4]
    m = S.df.groupby("Month")["Line_Total"].sum()
    return render_template("bisnis.html", page="bisnis", S=S, prof=prof, top=top, eda=EDA, monthly=m, months=pl.MONTHS_ID,
                           rec=REC)


@app.route("/eda")
def eda():
    return render_template("eda.html", page="eda", S=S, e=EDA)


@app.route("/preprocessing")
def preprocessing():
    X = S.X.copy()
    Zs = pd.DataFrame(S.Z, columns=["Recency_z", "Frequency_z", "Monetary_log_z"])
    cust_sample = pd.concat([S.rfm.head(8).reset_index(drop=True), X.head(8)[["Monetary_log"]].round(3).reset_index(drop=True),
                             Zs.head(8).round(3)], axis=1)
    mat_prev = S.matrix.iloc[:8, :8].astype(int)
    bs = S.trans["basket_size"].value_counts().sort_index()
    status = {"tetap": S.summary["baris_tidak_berubah"], "diperbaiki": S.summary["baris_diperbaiki"], "dihapus": S.summary["baris_dihapus"]}
    return render_template("preprocessing.html", page="preprocessing", S=S, audit=S.audit, log=S.log, sm=S.summary,
                           cust_sample=cust_sample, mat_prev=mat_prev, bs=bs, status=status, eda=EDA,
                           trans_sample=S.trans.head(8), bs_labels=[str(i) for i in bs.index])


@app.route("/apriori")
def apriori():
    return render_template("apriori.html", page="apriori", S=S, sens=SENS, rec=REC, defaults={"support": A.DEFAULT_SUPPORT, "conf": A.DEFAULT_CONF},
                           products=S.products, n=len(S.matrix))


@app.route("/kmeans")
def kmeans():
    ev = {e["k"]: e for e in S.evals}
    best = max(S.evals, key=lambda e: e["silhouette"])
    ov = {c: {"mean": float(S.rfm[c].mean()), "std": float(S.rfm[c].std())} for c in ["Recency", "Frequency", "Monetary"]}
    return render_template("kmeans.html", page="kmeans", S=S, evals=S.evals, ev=ev, best=best, km=S.km, k=S.k, rec=REC,
                           colors=S.km["colors"], ov=ov)


@app.route("/rekomendasi")
def rekomendasi():
    return render_template("rekomendasi.html", page="rekomendasi", S=S, r=REC, km=S.km)


# ------------------------------------------------------------------ API
@app.route("/api/dashboard")
def api_dashboard():
    try:
        support = float(request.args.get("support", A.DEFAULT_SUPPORT))
        conf = float(request.args.get("conf", A.DEFAULT_CONF))
    except ValueError:
        abort(400)
    payload = A.dashboard_payload(S, request.args.get("start") or None, request.args.get("end") or None,
                                  _list("cats"), _list("segs"), _list("regions"), support, conf)
    return jsonify(payload)


@app.route("/api/apriori")
def api_apriori():
    try:
        support = min(max(float(request.args.get("support", A.DEFAULT_SUPPORT)), 0.002), 0.2)
        conf = min(max(float(request.args.get("conf", A.DEFAULT_CONF)), 0.01), 0.99)
        maxlen = 3 if request.args.get("maxlen", "3") == "3" else 2
    except ValueError:
        abort(400)
    return jsonify(A.apriori_payload(S, support, conf, maxlen))


@app.route("/api/kmeans")
def api_kmeans():
    try:
        k = int(request.args.get("k", S.k))
    except ValueError:
        abort(400)
    if not 2 <= k <= 8:
        abort(400)
    res = A.run_kmeans(S, k)
    r = res["rfm"]
    return jsonify({
        "k": k, "profile": [dict(p, strat=A.strategy(p["label"])) for p in res["profile"]], "var": res["var"], "colors": res["colors"],
        "silhouette": next(e["silhouette"] for e in S.evals if e["k"] == k),
        "points": [{"id": x.Customer_ID, "R": int(x.Recency), "F": int(x.Frequency), "M": float(x.Monetary), "s": x.Segment,
                    "x": round(float(x.PC1), 3), "y": round(float(x.PC2), 3)} for x in r.itertuples()],
    })


FILES = {
    "data_bersih.csv": "Dataset hasil preprocessing",
    "transaksi_basket_size.csv": "Tabel transaksi + basket_size",
    "rfm_segmentasi_pelanggan.csv": "RFM + segmen pelanggan",
    "aturan_asosiasi.csv": "Aturan asosiasi Apriori",
    "log_preprocessing.csv": "Dokumentasi perubahan preprocessing",
}


@app.route("/download/<name>")
def download(name):
    if name not in FILES:
        abort(404)
    return send_from_directory(OUT, name, as_attachment=True)


app.jinja_env.globals["FILES"] = FILES
app.jinja_env.globals["strategy"] = A.strategy

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
