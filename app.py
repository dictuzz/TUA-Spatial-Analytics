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
st.set_page_config(page_title="Geo-Marketing Spatial Analytics", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 3rem; max-width: 1000px; }
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
        display: flex; flex-direction: column; margin-bottom: 16px;
    }
    .notion-gallery-card:hover { border-color: var(--text-color); box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
    .card-prop-name { font-size: 0.75rem; color: var(--text-color); opacity: 0.5; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;}
    .card-title { font-size: 0.95rem; font-weight: 600; color: var(--text-color); margin-bottom: 12px; line-height: 1.4; }
    
    .tag { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 4px; font-size: 0.85rem; line-height: 1.2; white-space: nowrap; margin-bottom: 4px; font-weight: 500;}
    .tag-gray { background-color: var(--secondary-background-color); color: var(--text-color); border: 1px solid var(--border-color); }
    
    .map-container { border: 1px solid var(--border-color); border-radius: 6px; overflow: hidden; margin-top: 8px; margin-bottom: 24px; }
    
    /* Styling untuk extra data list */
    .extra-data-row { display: flex; justify-content: space-between; border-bottom: 1px solid var(--border-color); padding: 4px 0; font-size: 0.85rem; }
    .extra-data-row:last-child { border-bottom: none; }
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
# 4. FUNGSI LOGIKA
# -------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=86400)
def cari_alamat(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
    try:
        res = requests.get(url, headers={"User-Agent": "Geo_Marketing_Analytics"}, timeout=5)
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

# FUNGSI BARU 1: Mengambil Data Terbaik beserta Metadata Ekstra
def get_best_match(df_master, lat_val, lon_val, seg_name, col_seg, col_lat, col_lon, col_id, col_name):
    df_seg = df_master[df_master[col_seg].astype(str).str.strip().str.upper() == seg_name.upper()].copy()
    if not df_seg.empty:
        df_seg['tmp_dist'] = df_seg.apply(lambda r: hitung_jarak_udara(lat_val, lon_val, r[col_lat], r[col_lon]), axis=1)
        best = df_seg.loc[df_seg['tmp_dist'].idxmin()]
        darat_km, darat_min = hitung_rute_darat(lat_val, lon_val, best[col_lat], best[col_lon])
        
        # Ekstraksi Dinamis Kolom Tambahan (Avg SPS, dll)
        kolom_inti = [col_seg, col_lat, col_lon, col_id, col_name, 'tmp_dist']
        extra_data = {col: best[col] for col in df_master.columns if col not in kolom_inti}
        
        return {
            "id": best[col_id], "nama": best[col_name], 
            "jarak_udara": round(best['tmp_dist'], 2),
            "jarak_darat": darat_km, "waktu_tempuh": darat_min,
            "lat": float(best[col_lat]), "lon": float(best[col_lon]),
            "extra_data": extra_data
        }
    return None

# FUNGSI BARU 2: Analisis Catchment Area (Radius & Wilayah)
def analyze_catchment_area(df_master, lat_val, lon_val, radius_km, col_lat, col_lon, col_seg, col_name):
    df_temp = df_master.copy()
    df_temp['jarak_km'] = df_temp.apply(lambda r: hitung_jarak_udara(lat_val, lon_val, r[col_lat], r[col_lon]), axis=1)
    df_in_radius = df_temp[df_temp['jarak_km'] <= radius_km]
    
    summary = {}
    for seg in df_in_radius[col_seg].unique():
        df_seg = df_in_radius[df_in_radius[col_seg] == seg]
        summary[seg] = {
            "jumlah": len(df_seg),
            "daftar": df_seg[[col_name, 'jarak_km']].sort_values('jarak_km').to_dict('records')
        }
    return summary, len(df_in_radius)

# -------------------------------------------------------------
# 5. SIDEBAR CONFIG
# -------------------------------------------------------------
import os # Tambahkan ini di bagian atas (bersama import lainnya) jika belum ada

# -------------------------------------------------------------
# 5. SIDEBAR CONFIG
# -------------------------------------------------------------
st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-bottom:8px;'>Database Master</div>", unsafe_allow_html=True)

# ---> LOGIKA BACA TEMPLATE LOKAL <---
template_path = "AHS_ACTIVE_FORMATTED.xlsx"
try:
    with open(template_path, "rb") as file:
        template_bytes = file.read()
        
    st.sidebar.download_button(
        label="Unduh Template Master AHS",
        data=template_bytes,
        file_name="AHS_ACTIVE_FORMATTED.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
except FileNotFoundError:
    st.sidebar.error(f"File template '{template_path}' tidak ditemukan di sistem. Pastikan file sudah di-upload ke server.")

uploaded_master = st.sidebar.file_uploader("Upload Excel File", type=["xlsx"], label_visibility="collapsed")

# ---> PASTIKAN VARIABEL MAPPING INI ADA SEBELUM MASUK KE MAIN UI <---
st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-top:24px; margin-bottom:8px;'>Mapping Kolom Master (Sheet 1)</div>", unsafe_allow_html=True)
m_id = st.sidebar.text_input("Kolom ID", "ID_PELANGGAN").upper()
m_name = st.sidebar.text_input("Kolom Nama", "NAMA_PELANGGAN").upper()
m_seg = st.sidebar.text_input("Kolom Kategori / Segmen", "SEGMEN").upper()
m_lat = st.sidebar.text_input("Kolom Latitude", "LATITUDE").upper()
m_lon = st.sidebar.text_input("Kolom Longitude", "LONGITUDE").upper()
st.sidebar.info("💡 Tip: Semua kolom lain di luar 5 mapping di atas (seperti Avg SPS, Omzet, dll) akan OTOMATIS dideteksi oleh sistem.")

st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-top:24px; margin-bottom:8px;'>Mapping Quadran (Sheet 2)</div>", unsafe_allow_html=True)
q_kel = st.sidebar.text_input("Kolom Kelurahan", "KELURAHAN").upper()
q_kec = st.sidebar.text_input("Kolom Kecamatan", "KECAMATAN").upper()
q_kab = st.sidebar.text_input("Kolom Kabupaten", "KAB_KOT").upper()
q_res = st.sidebar.text_input("Kolom Quadran", "QUADRAN").upper()

# -------------------------------------------------------------
# 6. MAIN UI
# -------------------------------------------------------------
st.markdown("<div class='notion-h1'>Geo-Marketing Spatial Analytics</div>", unsafe_allow_html=True)
st.markdown("<div class='notion-sub'>Platform pemetaan proksimitas, ekstraksi metadata, dan analisis penetrasi wilayah.</div>", unsafe_allow_html=True)

tab_single, tab_batch = st.tabs(["Single Analysis & Catchment", "Batch Processing & Ekspor Laporan"])

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
        
        # Karena m_seg sudah didefinisikan di sidebar atas, baris ini tidak akan error lagi
        if m_seg in df_master.columns:
            list_segmen = df_master[m_seg].dropna().astype(str).str.strip().str.upper().unique().tolist()
        else:
            st.error(f"Kolom '{m_seg}' tidak ditemukan di Sheet 1. Pastikan nama kolom di Excel sama persis.")
            st.stop()
    except Exception as e:
        st.error(f"Gagal membaca file: {e}")
        st.stop()

# ... (lanjutkan ke default_colors dan seterusnya seperti kode yang sebelumnya) ...
default_colors = ["#2D88FF", "#FF9900", "#00A86B", "#E03E3E", "#6B52D1", "#D9730D", "#0F7B6C"]
segmen_colors = {seg: default_colors[i % len(default_colors)] for i, seg in enumerate(list_segmen)}

# ==========================================
# TAB 1: SINGLE ANALYSIS & CATCHMENT
# ==========================================
with tab_single:
    if uploaded_master:
        st.markdown("<div class='card-prop-name'>1. Parameter Target Target Baru</div>", unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1])
        in_name = c1.text_input("Nama Target Baru", "Rencana Titik Ekspansi")
        in_lat = c2.text_input("Latitude", "-6.914744")
        in_lon = c3.text_input("Longitude", "107.609810")
        radius_filter = c4.number_input("Radius Catchment (KM)", min_value=1, max_value=50, value=3)
        
        st.write("")
        if st.button("Jalankan Analisis Komprehensif", type="primary"):
            with st.spinner("Menganalisis Proksimitas, Metadata Outlet, dan Penetrasi Wilayah..."):
                try:
                    lat_v, lon_v = float(in_lat), float(in_lon)
                    addr, kel, kec, kab = cari_alamat(lat_v, lon_v)
                    
                    quad = "Membutuhkan Tinjauan Manual"
                    if q_kel in df_quad.columns and q_kec in df_quad.columns and q_kab in df_quad.columns:
                        match = df_quad[(df_quad[q_kel].astype(str).str.contains(kel, case=False, na=False)) & 
                                        (df_quad[q_kec].astype(str).str.contains(kec, case=False, na=False)) & 
                                        (df_quad[q_kab].astype(str).str.contains(kab, case=False, na=False))]
                        if not match.empty: quad = str(match.iloc[0][q_res])

                    matches = {s: get_best_match(df_master, lat_v, lon_v, s, m_seg, m_lat, m_lon, m_id, m_name) for s in list_segmen}
                    catchment_summary, total_in_radius = analyze_catchment_area(df_master, lat_v, lon_v, radius_filter, m_lat, m_lon, m_seg, m_name)

                    st.session_state.analysis_result = {
                        "name": in_name, "lat": lat_v, "lon": lon_v, "addr": addr, "quad": quad, 
                        "matches": matches, "catchment": catchment_summary, "total_catchment": total_in_radius,
                        "radius_km": radius_filter, "admin": {"kel": kel, "kec": kec, "kab": kab}
                    }
                except ValueError: 
                    st.error("Format koordinat tidak valid.")

        if st.session_state.analysis_result:
            res = st.session_state.analysis_result
            st.write("---")
            
            # HEADER ADMINISTRATIF
            st.markdown(f"""
            <div class="notion-callout">
                <div class="callout-content">
                    <strong style="font-size: 1.1rem; display:block; margin-bottom:4px;">{res['name']}</strong>
                    <span style="color: var(--text-color); opacity: 0.7; font-size: 0.9rem; display:block; margin-bottom:4px;">{res['addr']}</span>
                    <span style="color: var(--text-color); font-size: 0.85rem; display:block; margin-bottom:12px; font-weight:600;">Wilayah: {res['admin']['kel']}, {res['admin']['kec']}, {res['admin']['kab']}</span>
                    <div><span class="tag tag-gray">Status Quadran</span><span class="tag" style="margin-left: 6px; background-color: rgba(45, 136, 255, 0.1); color: #2D88FF; border: 1px solid rgba(45, 136, 255, 0.2);">{res['quad']}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # MAP DINAMIS
            st.markdown("<div class='card-prop-name'>Visualisasi Radius & Proksimitas</div>", unsafe_allow_html=True)
            m = folium.Map(location=[res['lat'], res['lon']], zoom_start=13, tiles="cartodb positron")
            
            # Gambar Lingkaran Catchment
            folium.Circle([res['lat'], res['lon']], radius=res['radius_km'] * 1000, color='#2D88FF', fill=True, fill_opacity=0.1, weight=1).add_to(m)
            folium.Marker([res['lat'], res['lon']], popup="TARGET", icon=folium.Icon(color="black", icon="star")).add_to(m)
            
            for s, data in res['matches'].items():
                if data and data['lat']:
                    folium.Marker([data['lat'], data['lon']], popup=f"[{s}] {data['nama']}", icon=folium.Icon(color="lightgray")).add_to(m)
                    folium.PolyLine([[res['lat'], res['lon']], [data['lat'], data['lon']]], color=segmen_colors[s], weight=3, dash_array='4,4').add_to(m)
            
            st.markdown('<div class="map-container">', unsafe_allow_html=True)
            st_folium(m, height=400, use_container_width=True, key="map_analysis", returned_objects=[])
            st.markdown('</div>', unsafe_allow_html=True)

            # BAGIAN 1: KARTU PROKSIMITAS + METADATA DINAMIS
            st.markdown("<div class='card-prop-name'>Titik Terdekat per Segmen & Laporan Metadata</div>", unsafe_allow_html=True)
            cols = st.columns(3)
            col_idx = 0
            
            for s in list_segmen:
                d = res['matches'][s]
                if d:
                    col_hex = segmen_colors[s]
                    with cols[col_idx % 3]:
                        html_card = f"""
                        <div class="notion-gallery-card">
                            <div class="card-title">{d['nama']}</div>
                            <div style="margin-bottom: 6px;"><span class="tag tag-gray">ID</span> <span class="card-prop-name" style="font-family: monospace; margin-left:4px; text-transform:none;">{d['id']}</span></div>
                            <div style="margin-bottom: 12px;"><span class="tag tag-gray">Segmen</span> <span class="tag" style="margin-left:4px; background-color:{col_hex}1A; color:{col_hex}; border: 1px solid {col_hex}33;">{s}</span></div>
                            <div style="border-top: 1px dashed var(--border-color); padding-top: 12px;">
                                <div style="display: flex; justify-content: space-between; align-items: center;"><span class="card-prop-name" style="margin:0;">Jarak Udara</span> <span style="font-size: 0.85rem; font-weight: 600;">{d['jarak_udara']} KM</span></div>
                                <div style="display: flex; justify-content: space-between; align-items: center;"><span class="card-prop-name" style="margin:0; color:{col_hex};">Rute Darat</span> <span style="font-size: 0.85rem; font-weight: 600; color:{col_hex};">{d['jarak_darat']} KM ({d['waktu_tempuh']} Min)</span></div>
                            </div>
                        </div>"""
                        st.markdown(html_card, unsafe_allow_html=True)
                        
                        # FITUR COLLAPSIBLE DETAIL UNTUK AVG SPS DLL
                        with st.expander(f"Lihat Detail Laporan Tambahan"):
                            if d['extra_data']:
                                for k, v in d['extra_data'].items():
                                    val = v if pd.notna(v) else "-"
                                    st.markdown(f"<div class='extra-data-row'><strong>{k}</strong><span>{val}</span></div>", unsafe_allow_html=True)
                            else:
                                st.caption("Tidak ada kolom tambahan ditemukan di Master Database.")
                    col_idx += 1

            # BAGIAN 2: CATCHMENT AREA SUMMARY
            st.markdown(f"<div class='card-prop-name' style='margin-top:24px;'>Analisis Penetrasi Wilayah (Radius {res['radius_km']} KM)</div>", unsafe_allow_html=True)
            st.info(f"📍 Terdapat total **{res['total_catchment']} Outlet** yang berada di dalam jangkauan area target ini.")
            
            c_cols = st.columns(len(res['catchment']) if len(res['catchment']) > 0 else 1)
            idx = 0
            for seg, data in res['catchment'].items():
                with c_cols[idx]:
                    st.metric(label=f"Total Outlet {seg}", value=data['jumlah'])
                    with st.expander("Lihat Daftar Outlet"):
                        for item in data['daftar']:
                            st.caption(f"• {item[m_name]} ({round(item['jarak_km'], 1)} KM)")
                idx += 1
    else:
        st.info("Sistem standby. Silakan unggah Master Database pada panel di sebelah kiri.")

# ==========================================
# TAB 2: BATCH PROCESSING & EKSPOR
# ==========================================
with tab_batch:
    if uploaded_master:
        st.markdown("<div class='card-prop-name'>Input Data Massal</div>", unsafe_allow_html=True)
        st.download_button("Unduh Template File Batch", data=buat_template_batch(), file_name="Template_Batch_GeoMarketing.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        uploaded_batch = st.file_uploader("Upload daftar lokasi target (.xlsx)", type=["xlsx"], key="batch_upload")
        
        if uploaded_batch:
            df_batch = pd.read_excel(uploaded_batch)
            df_batch.columns = df_batch.columns.astype(str).str.strip().str.upper()
            
            st.markdown("<div class='card-prop-name' style='margin-top:24px;'>Mapping Kolom File Batch & Parameter</div>", unsafe_allow_html=True)
            bc1, bc2, bc3, bc4 = st.columns(4)
            b_name = bc1.selectbox("Kolom Nama Target", df_batch.columns)
            b_lat = bc2.selectbox("Kolom Latitude", df_batch.columns, index=min(1, len(df_batch.columns)-1))
            b_lon = bc3.selectbox("Kolom Longitude", df_batch.columns, index=min(2, len(df_batch.columns)-1))
            batch_radius = bc4.number_input("Hitung Catchment (Radius KM)", min_value=1, max_value=50, value=3, key="br")

            st.write("")
            if st.button("Mulai Ekspor Ekstraksi Data Massal"):
                results = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total = len(df_batch)
                for index, row in df_batch.iterrows():
                    progress = (index + 1) / total
                    progress_bar.progress(progress)
                    status_text.text(f"Mengekstrak baris {index+1} dari {total}...")

                    try: 
                        r_lat, r_lon = float(row[b_lat]), float(row[b_lon])
                    except: 
                        results.append({"NAMA_TARGET": row[b_name], "STATUS": "Gagal: Koordinat Invalid"})
                        continue

                    addr, kel, kec, kab = cari_alamat(r_lat, r_lon)
                    time.sleep(0.5)

                    quad = "Membutuhkan Tinjauan Manual"
                    m = df_quad[(df_quad[q_kel].astype(str).str.contains(kel, case=False, na=False)) & 
                                (df_quad[q_kec].astype(str).str.contains(kec, case=False, na=False)) & 
                                (df_quad[q_kab].astype(str).str.contains(kab, case=False, na=False))]
                    if not m.empty: quad = str(m.iloc[0][q_res])

                    # 1. Base Data
                    row_data = {
                        "NAMA_TARGET": row[b_name], "LATITUDE": r_lat, "LONGITUDE": r_lon,
                        "KELURAHAN": kel, "KECAMATAN": kec, "KOTA": kab,
                        "ALAMAT_SISTEM": addr, "QUADRAN": quad
                    }

                    # 2. Catchment Data (Jumlah Outlet di Sekitar Target)
                    catchment_summary, total_in_radius = analyze_catchment_area(df_master, r_lat, r_lon, batch_radius, m_lat, m_lon, m_seg, m_name)
                    row_data[f"TOTAL_OUTLET_RADIUS_{batch_radius}KM"] = total_in_radius
                    for seg, data in catchment_summary.items():
                        row_data[f"JUMLAH_{seg}_DI_RADIUS"] = data['jumlah']

                    # 3. Ekstraksi Titik Terdekat & Kolom Ekstra (Avg SPS, dll)
                    for s in list_segmen:
                        match_s = get_best_match(df_master, r_lat, r_lon, s, m_seg, m_lat, m_lon, m_id, m_name)
                        time.sleep(0.3)
                        
                        if match_s:
                            row_data[f"TERDEKAT_{s}_ID"] = match_s['id']
                            row_data[f"TERDEKAT_{s}_NAMA"] = match_s['nama']
                            row_data[f"TERDEKAT_{s}_JARAK_UDARA (KM)"] = match_s['jarak_udara']
                            row_data[f"TERDEKAT_{s}_JARAK_DARAT (KM)"] = match_s['jarak_darat']
                            
                            # Memasukkan semua Metadata Tambahan secara otomatis (Avg SPS, Avg Jugs, dll)
                            for extra_key, extra_val in match_s['extra_data'].items():
                                row_data[f"[{s}] {extra_key}"] = extra_val

                    results.append(row_data)

                df_final = pd.DataFrame(results)
                status_text.empty()
                progress_bar.empty()
                st.success("Ekstraksi Geo-Marketing massal selesai!")
                st.dataframe(df_final.head(), use_container_width=True)

                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_final.to_excel(writer, index=False, sheet_name='Hasil_Analisis')
                
                st.download_button("Unduh Laporan Geo-Marketing Lengkap (.xlsx)", data=output.getvalue(), file_name="GeoMarketing_Analysis.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("Sistem standby. Silakan unggah Master Database pada panel di sebelah kiri.")
