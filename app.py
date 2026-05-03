import streamlit as st
import pandas as pd
import requests
import math
import time
from io import BytesIO
import folium
from streamlit_folium import st_folium

# -------------------------------------------------------------
# 1. KONFIGURASI HALAMAN & PURE NOTION CSS
# -------------------------------------------------------------
st.set_page_config(page_title="Dynamic Spatial Analytics", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 3rem; max-width: 900px; }
    .notion-h1 { font-size: 2.2rem; font-weight: 700; color: var(--text-color); margin-bottom: 0.2rem; letter-spacing: -0.02em; }
    .notion-sub { font-size: 0.95rem; color: var(--text-color); opacity: 0.6; margin-bottom: 2.5rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border-color); }
    
    .notion-callout {
        display: flex; flex-direction: column; padding: 20px;
        background-color: var(--secondary-background-color); border-radius: 4px;
        border: 1px solid var(--border-color); margin-bottom: 24px; border-left: 4px solid var(--text-color);
    }
    .callout-content { font-size: 0.95rem; line-height: 1.5; color: var(--text-color); }
    
    .notion-gallery-card {
        background-color: var(--background-color); border: 1px solid var(--border-color);
        border-radius: 6px; padding: 16px; height: 100%; transition: border-color 0.2s ease;
        display: flex; flex-direction: column;
    }
    .notion-gallery-card:hover { border-color: var(--text-color); cursor: pointer; }
    .card-prop-name { font-size: 0.75rem; color: var(--text-color); opacity: 0.5; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;}
    .card-title { font-size: 0.95rem; font-weight: 600; color: var(--text-color); margin-bottom: 12px; line-height: 1.4; }
    
    .tag { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 4px; font-size: 0.85rem; line-height: 1.2; white-space: nowrap; margin-bottom: 4px; font-weight: 500;}
    .tag-gray { background-color: var(--secondary-background-color); color: var(--text-color); border: 1px solid var(--border-color); }
    
    .map-container { border: 1px solid var(--border-color); border-radius: 6px; overflow: hidden; margin-top: 8px; margin-bottom: 24px; }
    
    .guide-section { margin-bottom: 32px; }
    .guide-title { font-size: 1.15rem; font-weight: 600; color: var(--text-color); margin-bottom: 12px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px;}
    .guide-text { font-size: 0.95rem; color: var(--text-color); line-height: 1.7; }
    .guide-step { margin-bottom: 8px; }
    code { color: var(--text-color); background-color: var(--secondary-background-color); padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; border: 1px solid var(--border-color);}
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# 2. INISIALISASI SESSION STATE
# -------------------------------------------------------------
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None

# -------------------------------------------------------------
# 3. FUNGSI GENERATOR TEMPLATE
# -------------------------------------------------------------
def buat_template_master():
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame({
            "ID_PELANGGAN": ["TKO-001", "TKO-002", "GUD-001"],
            "NAMA_PELANGGAN": ["Toko Maju", "Toko Sejahtera", "Gudang Utama"],
            "SEGMEN": ["RETAIL", "RETAIL", "GUDANG"],
            "LATITUDE": [-6.917464, -6.918000, -6.919000],
            "LONGITUDE": [107.619123, 107.620000, 107.621000]
        }).to_excel(writer, index=False, sheet_name='Data_Outlet')
        pd.DataFrame({
            "KAB_KOT": ["BANDUNG", "BANDUNG"], "KECAMATAN": ["SUMUR BANDUNG", "SUMUR BANDUNG"],
            "KELURAHAN": ["BRAGA", "MERDEKA"], "QUADRAN": ["Q1", "Q2"]
        }).to_excel(writer, index=False, sheet_name='Panduan_Quadran')
    return output.getvalue()

def buat_template_batch():
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame({
            "NAMA_TARGET": ["Target Kunjungan 1", "Target Kunjungan 2"],
            "LATITUDE": [-6.724064, -6.725000],
            "LONGITUDE": [108.551460, 108.552000]
        }).to_excel(writer, index=False, sheet_name='Batch_Input')
    return output.getvalue()

# -------------------------------------------------------------
# 4. FUNGSI LOGIKA (Dengan Caching untuk Efisiensi)
# -------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=86400)
def cari_alamat(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
    try:
        res = requests.get(url, headers={"User-Agent": "Spatial_Analytics_Pro"}, timeout=5)
        if res.status_code == 200:
            data = res.json()
            addr = data.get("address", {})
            return data.get("display_name", "Tidak ditemukan"), \
                   addr.get("village", "") or addr.get("suburb", "") or addr.get("neighbourhood", ""), \
                   addr.get("town", "") or addr.get("district", "") or addr.get("city_district", ""), \
                   addr.get("city", "") or addr.get("county", "") or addr.get("region", "")
    except: pass
    return "Error Koneksi", "", "", ""

def hitung_jarak_udara(lat1, lon1, lat2, lon2):
    try: return math.sqrt((float(lat1) - float(lat2))**2 + (float(lon1) - float(lon2))**2) * 111.12
    except: return 999999

@st.cache_data(show_spinner=False, ttl=86400)
def hitung_rute_darat(lat1, lon1, lat2, lon2):
    url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == "Ok" and len(data.get("routes", [])) > 0:
                dist_km = data["routes"][0]["distance"] / 1000
                time_min = data["routes"][0]["duration"] / 60
                return round(dist_km, 2), round(time_min, 1)
    except: pass
    return "N/A", "N/A"

def get_best_match(df_master, lat_val, lon_val, seg_name, col_seg, col_lat, col_lon, col_id, col_name):
    df_seg = df_master[df_master[col_seg].astype(str).str.strip().str.upper() == seg_name.upper()].copy()
    if not df_seg.empty:
        df_seg['tmp_dist'] = df_seg.apply(lambda r: hitung_jarak_udara(lat_val, lon_val, r[col_lat], r[col_lon]), axis=1)
        best = df_seg.loc[df_seg['tmp_dist'].idxmin()]
        darat_km, darat_min = hitung_rute_darat(lat_val, lon_val, best[col_lat], best[col_lon])
        return {
            "id": best[col_id], "nama": best[col_name], 
            "jarak_udara": round(best['tmp_dist'], 2),
            "jarak_darat": darat_km, "waktu_tempuh": darat_min,
            "lat": float(best[col_lat]), "lon": float(best[col_lon])
        }
    return {"id": "N/A", "nama": "Data Tidak Tersedia", "jarak_udara": "N/A", "jarak_darat": "N/A", "waktu_tempuh": "N/A", "lat": None, "lon": None}

# -------------------------------------------------------------
# 5. SIDEBAR CONFIG
# -------------------------------------------------------------
st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-bottom:8px;'>Database Master</div>", unsafe_allow_html=True)
st.sidebar.download_button("Unduh Template Master", data=buat_template_master(), file_name="Template_Master_General.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
uploaded_master = st.sidebar.file_uploader("Upload Excel File", type=["xlsx"], label_visibility="collapsed")

st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-top:24px; margin-bottom:8px;'>Mapping Kolom Master (Sheet 1)</div>", unsafe_allow_html=True)
m_id = st.sidebar.text_input("Kolom ID", "ID_PELANGGAN").upper()
m_name = st.sidebar.text_input("Kolom Nama", "NAMA_PELANGGAN").upper()
m_seg = st.sidebar.text_input("Kolom Kategori / Segmen", "SEGMEN").upper()
m_lat = st.sidebar.text_input("Kolom Latitude", "LATITUDE").upper()
m_lon = st.sidebar.text_input("Kolom Longitude", "LONGITUDE").upper()

st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-top:24px; margin-bottom:8px;'>Mapping Quadran (Sheet 2)</div>", unsafe_allow_html=True)
q_kel = st.sidebar.text_input("Kolom Kelurahan", "KELURAHAN").upper()
q_kec = st.sidebar.text_input("Kolom Kecamatan", "KECAMATAN").upper()
q_kab = st.sidebar.text_input("Kolom Kabupaten", "KAB_KOT").upper()
q_res = st.sidebar.text_input("Kolom Quadran", "QUADRAN").upper()

# -------------------------------------------------------------
# 6. MAIN UI
# -------------------------------------------------------------
st.markdown("<div class='notion-h1'>Dynamic Spatial Analytics</div>", unsafe_allow_html=True)
st.markdown("<div class='notion-sub'>Platform pemetaan proksimitas dan klasifikasi teritorial universal.</div>", unsafe_allow_html=True)

tab_single, tab_batch, tab_guide = st.tabs(["Single Analysis", "Batch Processing", "Panduan Sistem"])

# ==========================================
# EKSTRAKSI SEGMEN DINAMIS DARI MASTER
# ==========================================
list_segmen = []
if uploaded_master:
    try:
        df_master = pd.read_excel(uploaded_master, sheet_name=0)
        df_quad = pd.read_excel(uploaded_master, sheet_name=1)
        df_master.columns = df_master.columns.astype(str).str.strip().str.upper()
        df_quad.columns = df_quad.columns.astype(str).str.strip().str.upper()
        
        if m_seg in df_master.columns:
            # Mengambil semua jenis kategori/segmen secara dinamis
            list_segmen = df_master[m_seg].dropna().astype(str).str.strip().str.upper().unique().tolist()
        else:
            st.error(f"Kolom '{m_seg}' tidak ditemukan di Sheet 1.")
            st.stop()
            
    except Exception as e:
        st.error(f"Gagal membaca file: {e}")
        st.stop()

# Generator Palet Warna Dinamis untuk Peta & Tag
default_colors = ["#2D88FF", "#FF9900", "#00A86B", "#E03E3E", "#6B52D1", "#D9730D", "#0F7B6C", "#9C27B0"]
segmen_colors = {seg: default_colors[i % len(default_colors)] for i, seg in enumerate(list_segmen)}

# ==========================================
# TAB 1: SINGLE ANALYSIS
# ==========================================
with tab_single:
    if uploaded_master:
        c1, c2, c3 = st.columns(3)
        in_name = c1.text_input("Nama Target", "Target Baru")
        in_lat = c2.text_input("Latitude", "-6.914744")
        in_lon = c3.text_input("Longitude", "107.609810")
        
        st.write("")
        if st.button("Jalankan Kalkulasi"):
            with st.spinner(f"Menganalisis proksimitas ke {len(list_segmen)} segmen unik..."):
                try:
                    lat_v, lon_v = float(in_lat), float(in_lon)
                    addr, kel, kec, kab = cari_alamat(lat_v, lon_v)
                    
                    quad = "Membutuhkan Tinjauan Manual"
                    if q_kel in df_quad.columns and q_kec in df_quad.columns and q_kab in df_quad.columns:
                        match = df_quad[(df_quad[q_kel].astype(str).str.contains(kel, case=False, na=False)) & 
                                        (df_quad[q_kec].astype(str).str.contains(kec, case=False, na=False)) & 
                                        (df_quad[q_kab].astype(str).str.contains(kab, case=False, na=False))]
                        if not match.empty: quad = str(match.iloc[0][q_res])

                    # Kalkulasi DInamis (Looping berdasarkan segmen yang ada)
                    matches = {s: get_best_match(df_master, lat_v, lon_v, s, m_seg, m_lat, m_lon, m_id, m_name) for s in list_segmen}
                    st.session_state.analysis_result = {"name": in_name, "lat": lat_v, "lon": lon_v, "addr": addr, "quad": quad, "matches": matches}
                except ValueError: 
                    st.error("Format koordinat tidak valid.")

        if st.session_state.analysis_result:
            res = st.session_state.analysis_result
            st.write("")
            
            st.markdown(f"""
            <div class="notion-callout">
                <div class="callout-content">
                    <strong style="font-size: 1.1rem; display:block; margin-bottom:4px;">{res['name']}</strong>
                    <span style="color: var(--text-color); opacity: 0.7; font-size: 0.9rem; display:block; margin-bottom:12px;">{res['addr']}</span>
                    <div><span class="tag tag-gray">Status Quadran</span><span class="tag" style="margin-left: 6px; background-color: rgba(45, 136, 255, 0.1); color: #2D88FF; border: 1px solid rgba(45, 136, 255, 0.2);">{res['quad']}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # MAP DINAMIS
            st.markdown("<div class='card-prop-name'>Visualisasi Jarak Udara (Euclidean)</div>", unsafe_allow_html=True)
            m = folium.Map(location=[res['lat'], res['lon']], zoom_start=13, tiles="cartodb positron")
            folium.Marker([res['lat'], res['lon']], icon=folium.Icon(color="black")).add_to(m)
            
            for s, data in res['matches'].items():
                if data['lat']:
                    folium.Marker([data['lat'], data['lon']], popup=f"[{s}] {data['nama']}", icon=folium.Icon(color="lightgray")).add_to(m)
                    folium.PolyLine([[res['lat'], res['lon']], [data['lat'], data['lon']]], color=segmen_colors[s], weight=3, dash_array='4,4').add_to(m)
            
            st.markdown('<div class="map-container">', unsafe_allow_html=True)
            st_folium(m, height=350, use_container_width=True, key="map_analysis", returned_objects=[])
            st.markdown('</div>', unsafe_allow_html=True)

            # CARD DINAMIS (Looping 3 kolom per baris)
            st.markdown("<div class='card-prop-name'>Relasi Proksimitas Multi-Metrik</div>", unsafe_allow_html=True)
            for i in range(0, len(list_segmen), 3):
                cols = st.columns(3)
                for j in range(3):
                    if i + j < len(list_segmen):
                        s = list_segmen[i + j]
                        d = res['matches'][s]
                        col_hex = segmen_colors[s]
                        
                        html_card = f"""
                        <div class="notion-gallery-card">
                            <div class="card-title">{d['nama']}</div>
                            <div style="margin-bottom: 6px;">
                                <span class="tag tag-gray">ID</span> <span class="card-prop-name" style="font-family: monospace; margin-left:4px; text-transform:none;">{d['id']}</span>
                            </div>
                            <div style="margin-bottom: 12px;">
                                <span class="tag tag-gray">Segmen</span> 
                                <span class="tag" style="margin-left:4px; background-color:{col_hex}1A; color:{col_hex}; border: 1px solid {col_hex}33;">{s}</span>
                            </div>
                            <div style="border-top: 1px dashed var(--border-color); padding-top: 12px;">
                                <div style="margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
                                    <span class="card-prop-name" style="margin:0;">Udara (Radius)</span> 
                                    <span style="font-size: 0.85rem; font-weight: 600;">{d['jarak_udara']} KM</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; align-items: center;">
                                    <span class="card-prop-name" style="margin:0; color:{col_hex};">Darat (OSRM)</span> 
                                    <span style="font-size: 0.85rem; font-weight: 600; color:{col_hex};">{d['jarak_darat']} KM ({d['waktu_tempuh']} Min)</span>
                                </div>
                            </div>
                        </div>"""
                        cols[j].markdown(html_card, unsafe_allow_html=True)
    else:
        st.info("Sistem standby. Silakan unggah Master Database pada panel di sebelah kiri.")

# ==========================================
# TAB 2: BATCH PROCESSING
# ==========================================
with tab_batch:
    if uploaded_master:
        st.markdown("<div class='card-prop-name'>Input Data Massal</div>", unsafe_allow_html=True)
        st.download_button("Unduh Template File Batch", data=buat_template_batch(), file_name="Template_Batch_General.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        uploaded_batch = st.file_uploader("Upload daftar lokasi (.xlsx)", type=["xlsx"], key="batch_upload")
        
        if uploaded_batch:
            df_batch = pd.read_excel(uploaded_batch)
            df_batch.columns = df_batch.columns.astype(str).str.strip().str.upper()
            
            st.markdown("<div class='card-prop-name' style='margin-top:24px;'>Mapping Kolom File Batch</div>", unsafe_allow_html=True)
            bc1, bc2, bc3 = st.columns(3)
            b_name = bc1.selectbox("Kolom Nama Target", df_batch.columns)
            b_lat = bc2.selectbox("Kolom Latitude Target", df_batch.columns, index=min(1, len(df_batch.columns)-1))
            b_lon = bc3.selectbox("Kolom Longitude Target", df_batch.columns, index=min(2, len(df_batch.columns)-1))

            st.write("")
            if st.button("Mulai Pemrosesan Massal"):
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total = len(df_batch)
                for index, row in df_batch.iterrows():
                    progress = (index + 1) / total
                    progress_bar.progress(progress)
                    status_text.text(f"Memproses baris {index+1} dari {total}...")

                    try: 
                        r_lat, r_lon = float(row[b_lat]), float(row[b_lon])
                    except: 
                        results.append({"NAMA_TARGET": row[b_name], "STATUS": "Gagal: Koordinat Invalid"})
                        continue

                    addr, kel, kec, kab = cari_alamat(r_lat, r_lon)
                    time.sleep(0.5) # Jeda Nominatim API

                    quad = "Membutuhkan Tinjauan Manual"
                    m = df_quad[(df_quad[q_kel].astype(str).str.contains(kel, case=False, na=False)) & 
                                (df_quad[q_kec].astype(str).str.contains(kec, case=False, na=False)) & 
                                (df_quad[q_kab].astype(str).str.contains(kab, case=False, na=False))]
                    if not m.empty: quad = str(m.iloc[0][q_res])

                    # DICTIONARY ROW DINAMIS
                    row_data = {
                        "NAMA_TARGET": row[b_name], "LATITUDE": r_lat, "LONGITUDE": r_lon,
                        "ALAMAT_SISTEM": addr, "QUADRAN": quad
                    }

                    # Loop pencarian jarak untuk setiap segmen unik
                    for s in list_segmen:
                        match_s = get_best_match(df_master, r_lat, r_lon, s, m_seg, m_lat, m_lon, m_id, m_name)
                        time.sleep(0.3) # Jeda OSRM
                        
                        row_data[f"{s}_NAMA"] = match_s['nama']
                        row_data[f"{s}_JARAK_UDARA (KM)"] = match_s['jarak_udara']
                        row_data[f"{s}_JARAK_DARAT (KM)"] = match_s['jarak_darat']
                        row_data[f"{s}_WAKTU (Min)"] = match_s['waktu_tempuh']

                    results.append(row_data)

                df_final = pd.DataFrame(results)
                status_text.empty()
                progress_bar.empty()
                st.success("Pemrosesan massal selesai.")
                st.dataframe(df_final, use_container_width=True)

                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_final.to_excel(writer, index=False, sheet_name='Hasil_Batch_Hybrid')
                
                st.download_button("Unduh Laporan Excel Multi-Metrik (.xlsx)", data=output.getvalue(), file_name="Batch_Analysis_General.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("Sistem standby. Silakan unggah Master Database pada panel di sebelah kiri.")

# ==========================================
# TAB 3: PANDUAN SISTEM (USER GUIDE)
# ==========================================
with tab_guide:
    st.markdown("""
    <div class="guide-section">
        <div class="guide-title">1. Pemahaman Metrik Jarak (Hybrid Route Engine)</div>
        <div class="guide-text">
            Sistem Universal ini menggunakan penghitungan ganda:
            <ul>
                <li class="guide-step"><strong>Jarak Udara (Euclidean/Radius):</strong> Kalkulasi ditarik secara garis lurus di atas permukaan bumi.</li>
                <li class="guide-step"><strong>Jarak Darat (OSRM API):</strong> Mencerminkan jarak tempuh aktual jika ditempuh dengan kendaraan roda empat, dihitung secara dinamis.</li>
            </ul>
        </div>
    </div>
    
    <div class="guide-section">
        <div class="guide-title">2. Fitur "Dynamic Segment Mapping"</div>
        <div class="guide-text">
            Aplikasi ini sekarang bersifat agnostik. Anda tidak lagi dibatasi pada tipe outlet tertentu. Anda dapat mengunggah file Master yang berisi segmen apapun (misalnya: Gudang, Cabang Utama, Ritel, atau ID Jadwal Kunjungan) dan aplikasi akan otomatis membaca, mengelompokkan, serta memetakan matriks jaraknya.
        </div>
    </div>
    """, unsafe_allow_html=True)
