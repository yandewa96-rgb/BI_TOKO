# Sistem BI Toko — UAS Business Intelligence / Data Mining

Aplikasi Flask yang mengolah `data/dataset_uas.xlsx` (sheet Data_Raw) menjadi: EDA, preprocessing,
Apriori, K-Means (RFM), dashboard interaktif, dan rekomendasi keputusan.

## Menjalankan
    pip install -r requirements.txt
    python app.py          # buka http://127.0.0.1:5000

Saat start, pipeline dijalankan otomatis dan hasilnya ditulis ke folder `output/`
(data_bersih.csv, transaksi_basket_size.csv, rfm_segmentasi_pelanggan.csv, aturan_asosiasi.csv, log_preprocessing.csv).

## Struktur
- `pipeline.py`  : audit, preprocessing, RFM, basket_size, Apriori (implementasi sendiri), K-Means
- `analytics.py` : state aplikasi, payload tiap halaman, rekomendasi, strategi segmen
- `app.py`       : routes Flask + API (`/api/dashboard`, `/api/apriori`, `/api/kmeans`)
- `templates/`, `static/` : tampilan (Chart.js disertakan lokal, tidak perlu internet kecuali font Google)

## Pemetaan ke soal UAS
Dashboard=Soal 9 · Business Understanding=Soal 1 · EDA=Soal 2 · Preprocessing=Soal 3–4 · Apriori=Soal 5–6 · K-Means=Soal 7–8 · Rekomendasi=Soal 10
