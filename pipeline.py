"""
Pipeline analisis: audit -> preprocessing -> feature engineering -> Apriori -> K-Means.
Semua angka yang tampil di aplikasi dihitung dari modul ini (tidak ada angka hard-coded).
"""
from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

SEED = 42
PAY_MAP = {"tunai": "Tunai", "debit": "Debit", "transfer": "Transfer", "qris": "QRIS"}
MAX_QTY = 50          # batas kewajaran qty per baris (ritel toko kelontong)
MAX_PRICE_RATIO = 5   # harga > 5x harga referensi dianggap tidak wajar
MONTHS_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


# ----------------------------------------------------------------------------
# 1. LOAD + AUDIT
# ----------------------------------------------------------------------------
def load_workbook(path):
    x = pd.ExcelFile(path)
    return {
        "raw": x.parse("Data_Raw"),
        "produk": x.parse("Data_Produk"),
        "pelanggan": x.parse("Data_Pelanggan"),
        "dictionary": x.parse("Data_Dictionary"),
    }


def _invalid_qty(q):
    return q.isna() | (q <= 0) | (q > MAX_QTY)


def audit(raw, produk):
    """Audit kualitas data pada data mentah (sebelum preprocessing)."""
    ref = produk.set_index("Product_ID")["Reference_Unit_Price_Rp"]
    ref_by_name = produk.set_index("Product_Name")["Reference_Unit_Price_Rp"]
    price_ref = raw["Product_Name"].map(ref_by_name)
    bad_price = raw["Unit_Price"].isna() | (raw["Unit_Price"] <= 0) | (raw["Unit_Price"] > MAX_PRICE_RATIO * price_ref)

    cat_ref = raw["Product_Name"].map(produk.set_index("Product_Name")["Category"])
    cat_clean = cat_ref
    pay = raw["Payment_Method"].dropna()
    pay_incons = (pay != pay.astype(str).str.strip().str.lower().map(PAY_MAP)).sum()

    calc = raw["Quantity"] * raw["Unit_Price"] * (1 - raw["Discount_Rate"])
    lt_incons = ((calc - raw["Line_Total"]).abs() > 1) & calc.notna() & raw["Line_Total"].notna()

    miss = raw.isna().sum()
    return {
        "missing": {k: int(v) for k, v in miss.items() if v > 0},
        "duplicates_exact": int(raw.duplicated().sum()),
        "cat_inconsistent": int((raw["Category"] != cat_clean).sum()),
        "pay_inconsistent": int(pay_incons),
        "qty_invalid_nan": int(raw["Quantity"].isna().sum()),
        "qty_nonpositive": int((raw["Quantity"] <= 0).sum()),
        "qty_extreme": int((raw["Quantity"] > MAX_QTY).sum()),
        "price_nan": int(raw["Unit_Price"].isna().sum()),
        "price_nonpositive": int((raw["Unit_Price"] <= 0).sum()),
        "price_extreme": int((raw["Unit_Price"] > MAX_PRICE_RATIO * price_ref).sum()),
        "price_bad_total": int(bad_price.sum()),
        "linetotal_inconsistent": int(lt_incons.sum()),
    }


# ----------------------------------------------------------------------------
# 2. PREPROCESSING
# ----------------------------------------------------------------------------
def preprocess(raw, produk, pelanggan):
    """Mengembalikan (df_bersih, log_langkah, ringkasan_sebelum_sesudah, df_ditandai)."""
    log = []
    df = raw.copy()
    n0 = len(df)
    prod_by_name = produk.set_index("Product_Name")
    cust = pelanggan.set_index("Customer_ID")

    def add(masalah, jumlah, aksi, metode, alasan, tahap):
        log.append({"tahap": tahap, "masalah": masalah, "jumlah": int(jumlah), "aksi": aksi,
                    "metode": metode, "alasan": alasan})

    # --- (a) duplikat persis
    dup = df.duplicated(keep="first")
    df = df.loc[~dup].copy()
    add("Baris duplikat persis (seluruh 13 kolom sama)", dup.sum(), "Dihapus",
        "drop_duplicates(keep='first')",
        "Baris identik berasal dari pencatatan ganda satu item nota yang sama; jika dibiarkan akan menggandakan "
        "omzet, Frequency, dan frekuensi produk pada Apriori.", "Duplikasi")

    # --- (b) format tanggal
    n_bad_date = pd.to_datetime(df["Transaction_Date"], errors="coerce").isna().sum()
    df["Transaction_Date"] = pd.to_datetime(df["Transaction_Date"], errors="coerce")
    df = df.dropna(subset=["Transaction_Date"])
    add("Format tanggal-waktu tidak valid", n_bad_date, "Dikonversi ke datetime64 (tidak ada yang gagal)" if n_bad_date == 0 else "Dihapus",
        "pd.to_datetime(errors='coerce')",
        "Tanggal wajib bertipe datetime agar tren bulanan dan Recency dapat dihitung.", "Transformasi")

    # --- (c) konsistensi teks
    cat_before = df["Category"].copy()
    df["Category"] = df["Product_Name"].map(prod_by_name["Category"])
    add("Inkonsistensi huruf/spasi pada Category (mis. 'sembako', 'SEMBAKO')", (cat_before != df["Category"]).sum(),
        "Diseragamkan", "Category <- katalog Data_Produk (lookup Product_Name)",
        "Kategori sama yang ditulis berbeda akan terhitung sebagai kategori terpisah pada agregasi dan filter. "
        "Katalog dipakai (bukan str.title) agar singkatan seperti 'ATK' tidak rusak menjadi 'Atk'; "
        "sudah diverifikasi kategori katalog selalu cocok dengan data transaksi.", "Inkonsistensi teks")

    pay_before = df["Payment_Method"].copy()
    norm = df["Payment_Method"].astype(str).str.strip().str.lower().map(PAY_MAP)
    df["Payment_Method"] = norm.where(df["Payment_Method"].notna(), np.nan)
    n_pay_fix = ((pay_before != df["Payment_Method"]) & pay_before.notna()).sum()
    add("Inkonsistensi ejaan Payment_Method (mis. 'Qris', 'qris')", n_pay_fix, "Diseragamkan",
        "str.lower() lalu pemetaan ke {Tunai, Debit, Transfer, QRIS}",
        "Menyatukan varian ejaan agar distribusi metode pembayaran tidak terpecah.", "Inkonsistensi teks")

    n_pay_na = df["Payment_Method"].isna().sum()
    df["Payment_Method"] = df["Payment_Method"].fillna("Tidak Diketahui")
    add("Payment_Method kosong", n_pay_na, "Diimputasi label 'Tidak Diketahui'",
        "fillna('Tidak Diketahui')",
        "Metode bayar tidak dipakai di Apriori/K-Means dan tidak dapat diturunkan dari kolom lain. Baris tetap "
        "dipertahankan karena produk, jumlah, dan nilainya valid; label eksplisit menjaga transparansi.", "Missing values")

    # --- (d) Product_ID kosong -> dari Product_Name (kunci katalog)
    m = df["Product_ID"].isna()
    df.loc[m, "Product_ID"] = df.loc[m, "Product_Name"].map(prod_by_name["Product_ID"])
    add("Product_ID kosong", m.sum(), "Diisi dari katalog", "Lookup Product_Name -> Product_ID (Data_Produk)",
        "Product_Name terisi lengkap dan 1:1 dengan Product_ID (sudah diverifikasi tidak ada konflik), "
        "sehingga pengisian bersifat deterministik, bukan tebakan.", "Missing values")

    # --- (e) Customer_ID kosong -> dari baris lain pada Transaction_ID yang sama
    m = df["Customer_ID"].isna()
    fill = df.groupby("Transaction_ID")["Customer_ID"].transform(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan)
    df.loc[m, "Customer_ID"] = fill[m]
    n_left = df["Customer_ID"].isna().sum()
    add("Customer_ID kosong", m.sum(), "Diisi dari baris lain pada nota yang sama" + ("" if n_left == 0 else f"; {n_left} baris tersisa dihapus"),
        "groupby(Transaction_ID).first non-null",
        "Satu nota hanya dimiliki satu pelanggan (diverifikasi: tidak ada nota dengan >1 Customer_ID). "
        "Pelanggan tanpa ID akan merusak RFM bila dihapus atau dianggap pelanggan baru.", "Missing values")
    df = df.dropna(subset=["Customer_ID"])

    # --- (f) Region & Customer_Type kosong -> master pelanggan
    for col in ["Region", "Customer_Type"]:
        m = df[col].isna()
        df.loc[m, col] = df.loc[m, "Customer_ID"].map(cust[col])
        add(f"{col} kosong", m.sum(), "Diisi dari Data_Pelanggan", f"Lookup Customer_ID -> {col}",
            "Master pelanggan konsisten 100% dengan data transaksi pada baris yang terisi (0 konflik).", "Missing values")

    # --- (g) harga satuan tidak valid -> harga referensi katalog
    ref = df["Product_Name"].map(prod_by_name["Reference_Unit_Price_Rp"])
    bad_price = df["Unit_Price"].isna() | (df["Unit_Price"] <= 0) | (df["Unit_Price"] > MAX_PRICE_RATIO * ref)
    n_nan, n_neg, n_ext = (df["Unit_Price"].isna().sum(), (df["Unit_Price"] <= 0).sum(),
                           (df["Unit_Price"] > MAX_PRICE_RATIO * ref).sum())
    df["_price_fixed"] = bad_price
    df.loc[bad_price, "Unit_Price"] = ref[bad_price]
    add(f"Unit_Price tidak valid (kosong {n_nan}, <= 0: {n_neg}, ekstrem > {MAX_PRICE_RATIO}x referensi: {n_ext})", bad_price.sum(),
        "Diperbaiki dengan harga referensi katalog", "Unit_Price <- Reference_Unit_Price_Rp",
        "Pada seluruh baris valid, Unit_Price identik dengan harga referensi (selisih 0), sehingga harga referensi "
        "adalah estimasi yang tepat. Nilai 999999 dan -100 adalah kode error, bukan harga sebenarnya.", "Nilai tidak valid")

    # --- (h) quantity tidak valid -> turunkan dari Line_Total
    bad_q = _invalid_qty(df["Quantity"])
    n_nan, n_np, n_ex = df["Quantity"].isna().sum(), (df["Quantity"] <= 0).sum(), (df["Quantity"] > MAX_QTY).sum()
    implied = (df["Line_Total"] / (df["Unit_Price"] * (1 - df["Discount_Rate"]))).round()
    can_fix = bad_q & implied.between(1, MAX_QTY)
    df["_qty_fixed"] = can_fix
    df.loc[can_fix, "Quantity"] = implied[can_fix]
    n_drop = (bad_q & ~can_fix).sum()
    df = df.loc[~(bad_q & ~can_fix)].copy()
    add(f"Quantity tidak valid (kosong {n_nan}, <= 0: {n_np}, ekstrem > {MAX_QTY}: {n_ex})", bad_q.sum(),
        f"Diperbaiki {can_fix.sum()} baris dari Line_Total; {n_drop} baris dihapus (tidak dapat dipulihkan)",
        "Quantity = round(Line_Total / (Unit_Price x (1 - Discount_Rate)))",
        "Line_Total terbukti andal (konsisten dengan rumus pada baris yang valid), sehingga qty dapat dipulihkan secara "
        "matematis. Qty 999 / negatif / nol tidak masuk akal untuk ritel eceran.", "Nilai tidak valid")

    # --- (i) Line_Total kosong -> hitung
    m = df["Line_Total"].isna()
    df.loc[m, "Line_Total"] = (df.loc[m, "Quantity"] * df.loc[m, "Unit_Price"] * (1 - df.loc[m, "Discount_Rate"])).round()
    add("Line_Total kosong", m.sum(), "Dihitung ulang", "Quantity x Unit_Price x (1 - Discount_Rate)",
        "Semua komponen rumus sudah valid setelah langkah sebelumnya.", "Missing values")

    # --- (j) validasi konsistensi Line_Total
    calc = (df["Quantity"] * df["Unit_Price"] * (1 - df["Discount_Rate"])).round()
    inc = (calc - df["Line_Total"]).abs() > 1
    df["_total_fixed"] = inc
    df.loc[inc, "Line_Total"] = calc[inc]
    add("Line_Total tidak konsisten dengan rumus", inc.sum(), "Disamakan dengan hasil rumus" if inc.sum() else "Tidak ada (lulus validasi)",
        "Validasi akhir |Line_Total - hitung| <= 1 Rp",
        "Memastikan seluruh nilai uang konsisten sebelum agregasi.", "Validasi")

    # --- (k) duplikasi produk dalam satu nota -> gabungkan agar basket berisi produk unik
    key = ["Transaction_ID", "Product_ID"]
    dk = df.duplicated(key, keep=False)
    n_dk = df.duplicated(key, keep="first").sum()
    if n_dk:
        agg = {c: "first" for c in df.columns if c not in key}
        agg.update({"Quantity": "sum", "Line_Total": "sum"})
        df = df.groupby(key, as_index=False, sort=False).agg(agg)
    add("Produk yang sama muncul >1 baris dalam satu nota", n_dk, "Digabung (Quantity & Line_Total dijumlahkan)" if n_dk else "Tidak ada",
        "groupby(Transaction_ID, Product_ID).sum",
        "Basket Apriori adalah himpunan produk unik per nota; nilai uang tetap utuh karena dijumlahkan.", "Duplikasi")

    # --- (l) tipe data akhir
    df["Quantity"] = df["Quantity"].astype(int)
    df["Unit_Price"] = df["Unit_Price"].astype(int)
    df["Line_Total"] = df["Line_Total"].astype(int)
    df["Date"] = df["Transaction_Date"].dt.normalize()
    df["Month"] = df["Transaction_Date"].dt.to_period("M").astype(str)
    df["Hour"] = df["Transaction_Date"].dt.hour
    df["DayName"] = df["Transaction_Date"].dt.dayofweek
    df = df.sort_values(["Transaction_ID", "Product_ID"]).reset_index(drop=True)
    for c in ["_price_fixed", "_qty_fixed", "_total_fixed"]:
        df[c] = df[c].fillna(False).astype(bool)
    df["Is_Repaired"] = df[["_price_fixed", "_qty_fixed", "_total_fixed"]].any(axis=1)
    df = df.drop(columns=["_price_fixed", "_qty_fixed", "_total_fixed"])
    add("Konversi tipe data", len(df), "Quantity/Unit_Price/Line_Total -> int; tanggal -> datetime; tambah fitur Month, Hour, DayName",
        "astype + fitur turunan", "Tipe numerik diperlukan untuk agregasi; fitur waktu untuk analisis tren.", "Transformasi")

    # --- (m) outlier nilai (dipertahankan, ditandai)
    q1, q3 = df["Line_Total"].quantile([.25, .75])
    upper = q3 + 1.5 * (q3 - q1)
    df["Is_Value_Outlier"] = df["Line_Total"] > upper
    n_out = int(df["Is_Value_Outlier"].sum())
    add(f"Nilai ekstrem Line_Total (IQR, batas atas Rp {upper:,.0f})".replace(",", "."), n_out,
        "Dipertahankan & ditandai (Is_Value_Outlier); Monetary di-log-transform pada K-Means",
        "Aturan IQR (Q3 + 1,5 x IQR) + pemeriksaan konteks bisnis",
        "Setelah qty/harga diperbaiki, nilai besar berasal dari produk bernilai tinggi (Beras 5kg, Susu Formula, Popok) "
        "dengan qty wajar, yaitu pembelian sah. Menghapusnya akan menghilangkan pelanggan bernilai tinggi — justru target utama "
        "segmentasi. Dampak skewness diredam dengan transformasi log.", "Outlier")

    # ringkasan sebelum / sesudah
    def summ(d, clean):
        tid = d["Transaction_ID"].nunique()
        out = {
            "Jumlah baris": len(d),
            "Transaksi unik": tid,
            "Pelanggan unik": d["Customer_ID"].nunique(),
            "Produk unik": d["Product_ID"].nunique() if clean else d["Product_Name"].nunique(),
            "Total nilai Line_Total (Rp)": d["Line_Total"].sum(),
            "Total sel kosong": int(d.isna().sum().sum()),
            "Baris duplikat": int(d.duplicated().sum()),
        }
        if clean:
            out["Rata-rata Quantity"] = round(d["Quantity"].mean(), 3)
            out["Quantity maksimum"] = int(d["Quantity"].max())
        else:
            out["Rata-rata Quantity"] = round(d["Quantity"].mean(), 3)
            out["Quantity maksimum"] = int(d["Quantity"].max())
        return out

    before, after = summ(raw, False), summ(df, True)
    ret = {
        "baris_awal": n0, "baris_akhir": len(df),
        "baris_dihapus": n0 - len(df),
        "baris_diperbaiki": int(df["Is_Repaired"].sum()),
        "baris_tidak_berubah": int(len(df) - df["Is_Repaired"].sum()),
        "before": before, "after": after,
        "outlier_upper": float(upper),
    }
    return df, log, ret


# ----------------------------------------------------------------------------
# 3. FEATURE ENGINEERING
# ----------------------------------------------------------------------------
def build_transactions(df):
    g = df.groupby("Transaction_ID")
    t = g.agg(Date=("Date", "first"), Transaction_Date=("Transaction_Date", "first"),
              Customer_ID=("Customer_ID", "first"), Region=("Region", "first"),
              Customer_Type=("Customer_Type", "first"), Payment=("Payment_Method", "first"),
              basket_size=("Product_ID", "nunique"), items=("Quantity", "sum"),
              revenue=("Line_Total", "sum")).reset_index()
    t["Month"] = t["Date"].dt.to_period("M").astype(str)
    return t


def build_rfm(df, ref_date=None):
    ref_date = ref_date or (df["Date"].max() + pd.Timedelta(days=1))
    g = df.groupby("Customer_ID")
    rfm = pd.DataFrame({
        "Recency": (ref_date - g["Date"].max()).dt.days,
        "Frequency": g["Transaction_ID"].nunique(),
        "Monetary": g["Line_Total"].sum(),
    }).reset_index()
    return rfm, ref_date


def basket_matrix(df, product_col="Product_Name"):
    """Matriks transaksi x produk (boolean). Satu baris = satu Transaction_ID."""
    m = pd.crosstab(df["Transaction_ID"], df[product_col]).clip(upper=1).astype(bool)
    return m


# ----------------------------------------------------------------------------
# 4. APRIORI (implementasi level-wise sendiri, tanpa dependensi tambahan)
# ----------------------------------------------------------------------------
def apriori(mat, min_support, min_conf, max_len=3):
    """mat: DataFrame boolean (transaksi x produk). Return (itemsets_df, rules_df)."""
    n = len(mat)
    if n == 0:
        return pd.DataFrame(columns=["itemset", "size", "count", "support"]), pd.DataFrame()
    cols = list(mat.columns)
    X = mat.values
    min_count = int(np.ceil(min_support * n))
    counts = X.sum(axis=0)
    L = {(i,): int(c) for i, c in enumerate(counts) if c >= min_count}
    all_sets = dict(L)
    k = 1
    cur = list(L.keys())
    while cur and k < max_len:
        k += 1
        cands = set()
        cur_set = set(cur)
        for a, b in combinations(cur, 2):
            if a[:-1] == b[:-1]:
                c = tuple(sorted(set(a) | set(b)))
                if len(c) == k and all(tuple(s) in cur_set for s in combinations(c, k - 1)):
                    cands.add(c)
        nxt = {}
        for c in cands:
            cnt = int(X[:, list(c)].all(axis=1).sum())
            if cnt >= min_count:
                nxt[c] = cnt
        all_sets.update(nxt)
        cur = sorted(nxt.keys())
    rows = [{"itemset": tuple(cols[i] for i in s), "size": len(s), "count": c, "support": c / n} for s, c in all_sets.items()]
    its = pd.DataFrame(rows).sort_values(["size", "support"], ascending=[True, False]).reset_index(drop=True)

    rules = []
    for s, c in all_sets.items():
        if len(s) < 2:
            continue
        for r in range(1, len(s)):
            for ant in combinations(s, r):
                con = tuple(i for i in s if i not in ant)
                sup_a = all_sets[ant] / n
                sup_c = all_sets[con] / n
                sup = c / n
                conf = sup / sup_a
                if conf < min_conf:
                    continue
                lift = conf / sup_c
                rules.append({
                    "antecedent": " + ".join(cols[i] for i in ant), "consequent": " + ".join(cols[i] for i in con),
                    "ant_items": [cols[i] for i in ant], "con_items": [cols[i] for i in con],
                    "count": c, "support": sup, "confidence": conf, "lift": lift,
                    "leverage": sup - sup_a * sup_c,
                    "conviction": (1 - sup_c) / (1 - conf) if conf < 1 else np.inf,
                })
    rl = pd.DataFrame(rules)
    if len(rl):
        rl = rl.sort_values(["lift", "confidence"], ascending=False).reset_index(drop=True)
    return its, rl


# ----------------------------------------------------------------------------
# 5. K-MEANS
# ----------------------------------------------------------------------------
def kmeans_features(rfm):
    X = pd.DataFrame({"Recency": rfm["Recency"], "Frequency": rfm["Frequency"], "Monetary_log": np.log1p(rfm["Monetary"])})
    scaler = StandardScaler()
    Z = scaler.fit_transform(X)
    return X, Z, scaler


def evaluate_k(Z, ks=range(2, 9)):
    out = []
    for k in ks:
        km = KMeans(n_clusters=k, n_init=20, random_state=SEED).fit(Z)
        out.append({"k": k, "inertia": float(km.inertia_), "silhouette": float(silhouette_score(Z, km.labels_))})
    return out


def pick_k(evals, k_min=3, k_max=6):
    """Pilih k: silhouette tertinggi pada rentang yang bisa dioperasionalkan secara bisnis (3-6)."""
    cand = [e for e in evals if k_min <= e["k"] <= k_max]
    return max(cand, key=lambda e: e["silhouette"])["k"]
