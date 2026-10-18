# Hosting gratis di Render

File sudah disiapkan untuk Render, tanpa perlu mengedit kode.

1. Buat repository baru di GitHub. Upload **semua isi folder ini** ke root repository, termasuk `render.yaml`, `data/`, `templates/`, `static/`, dan `output/`. Jangan upload file ZIP langsung sebagai satu file. Pastikan dataset aman untuk dipublikasikan karena repository publik dapat dilihat orang lain.
2. Masuk https://dashboard.render.com, pilih **New > Blueprint** dan hubungkan repository tersebut. Render membaca `render.yaml`.
3. Konfirmasi pembuatan web service pada plan Free, tunggu build dan startup selesai. URL website akan diberikan Render.
4. Jika menggunakan **New > Web Service** biasa: build command `pip install -r requirements.txt`; start command `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 180 app:app`; pilih Free.

Catatan: aplikasi memproses file Excel saat server pertama kali dijalankan. Ini bisa memerlukan waktu/memori, terutama pada layanan gratis. Penyimpanan file yang dihasilkan di Render gratis bersifat sementara dan akan dibuat ulang saat startup. Server gratis juga dapat tidur saat tidak digunakan. Jika terjadi out-of-memory atau timeout, perlu mengurangi beban pemrosesan atau menggunakan hosting dengan sumber daya lebih besar.
