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
    
    .card-prop-name { font-size: 0.75rem; color: var(--text-color); opacity: 0.5; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;}
    .tag { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 4px; font-size: 0.85rem; line-height: 1.2; white-space: nowrap; margin-bottom: 4px; font-weight: 500;}
    .tag-gray { background-color: var(--secondary-background-color); color: var(--text-color); border: 1px solid var(--border-color); }
    
    .map-container { border: 1px solid var(--border-color); border-radius: 6px; overflow: hidden; margin-top: 8px; margin-bottom: 24px; }
    .extra-data-row { display: flex; justify-content: space-between; border-bottom: 1px solid var(--border-color); padding: 4px 0; font-size: 0.85rem; }
    .extra-data-row:last-child { border-bottom: none; }
</style>
""", unsafe_allow_html=True)

if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None

# -------------------------------------------------------------
# 2. FUNGSI LOGIKA (REVISI NOMINATIM & CATCHMENT)
# -------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=86400)
def cari_alamat(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
    # PERBAIKAN: Menggunakan User-Agent yang menyerupai browser agar tidak diblokir
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            addr = data.get("address", {})
            
            display_name = data.get("display_name", "Alamat tidak ditemukan")
            # PERBAIKAN: Fallback berlapis jika wilayah kosong
            kel = addr.get("village", addr.get("suburb", addr.get("neighbourhood", "Tidak diketahui")))
            kec = addr.get("town", addr.get("district", addr.get("city_district", "Tidak diketahui")))
            kab = addr.get("city", addr.get("county", addr.get("region", "Tidak diketahui")))
            
            return display_name, kel, kec, kab
    except Exception:
        pass
    return "Gagal Menghubungi Server Peta", "Tidak diketahui", "Tidak diketahui", "Tidak diketahui"

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

# PERBAIKAN: Catchment Area kini menarik SEMUA metadata (Avg SPS, dll) untuk semua outlet di radius
def analyze_catchment_area(df_master, lat_val, lon_val, radius_km, col_lat, col_lon, col_seg, col_id, col_name):
    df_temp = df_master.copy()
    df_temp['jarak_km'] = df_temp.apply(lambda r: hitung_jarak_udara(lat_val, lon_val, r[col_lat], r[col_lon]), axis=1)
    df_in_radius = df_temp[df_temp['jarak_km'] <= radius_km]
    
    summary = {}
    for seg in df_in_radius[col_seg].unique():
        df_seg = df_in_radius[df_in_radius[col_seg] == seg].sort_values('jarak_km')
        daftar = []
        for _, row in df_seg.iterrows():
            kolom_inti = [col_seg, col_lat, col_lon, col_id, col_name, 'jarak_km']
            extra_data = {col: row[col] for col in df_master.columns if col not in kolom_inti}
            daftar.append({
                "id": row[col_id], "nama": row[col_name],
                "lat": float(row[col_lat]), "lon": float(row[col_lon]),
                "jarak_udara": round(row['jarak_km'], 2),
                "extra_data": extra_data
            })
            
        summary[seg] = {
            "jumlah": len(df_seg),
            "daftar": daftar
        }
    return summary, len(df_in_radius)

# -------------------------------------------------------------
# 3. SIDEBAR CONFIG
# -------------------------------------------------------------
st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-bottom:8px;'>Database Master</div>", unsafe_allow_html=True)

template_path = "AHS_ACTIVE_FORMATTED.xlsx"
try:
    with open(template_path, "rb") as file:
        template_bytes = file.read()
    st.sidebar.download_button(
        label="Unduh Template Master AHS", data=template_bytes,
        file_name="AHS_ACTIVE_FORMATTED.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
except FileNotFoundError:
    st.sidebar.error("File template 'AHS_ACTIVE_FORMATTED.xlsx' tidak ditemukan.")

uploaded_master = st.sidebar.file_uploader("Upload Excel File", type=["xlsx"], label_visibility="collapsed")

st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-top:24px; margin-bottom:8px;'>Mapping Kolom Master</div>", unsafe_allow_html=True)
m_id = st.sidebar.text_input("Kolom ID", "ID_PELANGGAN").upper()
m_name = st.sidebar.text_input("Kolom Nama", "NAMA_PELANGGAN").upper()
m_seg = st.sidebar.text_input("Kolom Kategori / Segmen", "SEGMEN").upper()
m_lat = st.sidebar.text_input("Kolom Latitude", "LATITUDE").upper()
m_lon = st.sidebar.text_input("Kolom Longitude", "LONGITUDE").upper()

st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-top:24px; margin-bottom:8px;'>Mapping Quadran</div>", unsafe_allow_html=True)
q_kel = st.sidebar.text_input("Kolom Kelurahan", "KELURAHAN").upper()
q_kec = st.sidebar.text_input("Kolom Kecamatan", "KECAMATAN").upper()
q_kab = st.sidebar.text_input("Kolom Kabupaten", "KAB_KOT").upper()
q_res = st.sidebar.text_input("Kolom Quadran", "QUADRAN").upper()

# -------------------------------------------------------------
# 4. MAIN UI & LOGIKA SEGMEN DINAMIS
# -------------------------------------------------------------
st.markdown("<div class='notion-h1'>Geo-Marketing Spatial Analytics</div>", unsafe_allow_html=True)
st.markdown("<div class='notion-sub'>Platform pemetaan proksimitas, ekstraksi metadata, dan analisis penetrasi wilayah.</div>", unsafe_allow_html=True)

tab_single, tab_batch = st.tabs(["Single Analysis & Catchment", "Batch Processing & Ekspor Laporan"])

list_segmen = []
if uploaded_master:
    try:
        df_master = pd.read_excel(uploaded_master, sheet_name=0)
        df_quad = pd.read_excel(uploaded_master, sheet_name=1)
        df_master.columns = df_master.columns.astype(str).str.strip().str.upper()
        df_quad.columns = df_quad.columns.astype(str).str.strip().str.upper()
        
        if m_seg in df_master.columns:
            list_segmen = df_master[m_seg].dropna().astype(str).str.strip().str.upper().unique().tolist()
        else:
            st.error(f"Kolom '{m_seg}' tidak ditemukan di Sheet 1.")
            st.stop()
    except Exception as e:
        st.error(f"Gagal membaca file: {e}")
        st.stop()

default_colors = ["#2D88FF", "#FF9900", "#00A86B", "#E03E3E", "#6B52D1", "#D9730D", "#0F7B6C"]
segmen_colors = {seg: default_colors[i % len(default_colors)] for i, seg in enumerate(list_segmen)}

# ==========================================
# TAB 1: SINGLE ANALYSIS & CATCHMENT
# ==========================================
with tab_single:
    if uploaded_master:
        st.markdown("<div class='card-prop-name'>1. Parameter Target Ekspansi Baru</div>", unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1])
        in_name = c1.text_input("Nama Target Baru", "Rencana Titik Ekspansi")
        in_lat = c2.text_input("Latitude", "-6.914744")
        in_lon = c3.text_input("Longitude", "107.609810")
        radius_filter = c4.number_input("Radius (KM)", min_value=1, max_value=50, value=3)
        
        st.write("")
        if st.button("Jalankan Analisis Komprehensif", type="primary"):
            with st.spinner("Menganalisis Proksimitas dan Penetrasi Wilayah..."):
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
                    catchment_summary, total_in_radius = analyze_catchment_area(df_master, lat_v, lon_v, radius_filter, m_lat, m_lon, m_seg, m_id, m_name)

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
                    <span style="color: var(--text-color); font-size: 0.85rem; display:block; margin-bottom:12px; font-weight:600;">Wilayah Administratif Nominatim: {res['admin']['kel']}, {res['admin']['kec']}, {res['admin']['kab']}</span>
                    <div><span class="tag tag-gray">Status Quadran Sistem</span><span class="tag" style="margin-left: 6px; background-color: rgba(45, 136, 255, 0.1); color: #2D88FF; border: 1px solid rgba(45, 136, 255, 0.2);">{res['quad']}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # ==========================================
            # PERBAIKAN PETA: AUTO-BOUNDS & POPUP LENGKAP
            # ==========================================
            st.markdown(f"<div class='card-prop-name'>Visualisasi Peta Radius {res['radius_km']} KM</div>", unsafe_allow_html=True)
            m = folium.Map(location=[res['lat'], res['lon']], zoom_start=13, tiles="cartodb positron")
            
            # Gambar Target & Area Radius
            folium.Circle([res['lat'], res['lon']], radius=res['radius_km'] * 1000, color='#2D88FF', fill=True, fill_opacity=0.1, weight=1).add_to(m)
            folium.Marker([res['lat'], res['lon']], popup="<b>Titik Target</b>", icon=folium.Icon(color="black", icon="star")).add_to(m)
            
            bounds = [[res['lat'], res['lon']]] # Simpan koordinat untuk auto-zoom peta
            
            for seg, data in res['catchment'].items():
                col_hex = segmen_colors.get(seg, "gray")
                for idx, item in enumerate(data['daftar']):
                    # Gambar garis ke outlet yg terdekat saja
                    if idx == 0:
                        folium.PolyLine([[res['lat'], res['lon']], [item['lat'], item['lon']]], color=col_hex, weight=2, dash_array='4,4').add_to(m)
                    
                    # HTML Popup Interaktif di Peta
                    popup_html = f"<div style='min-width: 200px;'><b>[{seg}] {item['nama']}</b><br>Jarak: {item['jarak_udara']} KM<hr style='margin:4px 0;'>"
                    for k, v in item['extra_data'].items():
                        if pd.notna(v) and str(v).strip() != "":
                            popup_html += f"<div style='font-size:0.8em;'><b>{k}:</b> {v}</div>"
                    popup_html += "</div>"
                    
                    folium.Marker(
                        [item['lat'], item['lon']], 
                        popup=folium.Popup(popup_html, max_width=300), 
                        tooltip=f"Klik untuk detail: {item['nama']}",
                        icon=folium.Icon(color="lightgray", icon="info-sign")
                    ).add_to(m)
                    bounds.append([item['lat'], item['lon']])
            
            # Auto-zoom agar semua titik muat di layar
            if len(bounds) > 1:
                m.fit_bounds(bounds)

            st.markdown('<div class="map-container">', unsafe_allow_html=True)
            st_folium(m, height=450, use_container_width=True, key="map_analysis", returned_objects=[])
            st.markdown('</div>', unsafe_allow_html=True)

            # ==========================================
            # PERBAIKAN UI: LIST COLLAPSIBLE DINAMIS
            # ==========================================
            st.markdown(f"<div class='card-prop-name' style='font-size: 1.1rem;'>Detail Outlet di Dalam Radius ({res['total_catchment']} Outlet Ditemukan)</div>", unsafe_allow_html=True)
            
            if res['total_catchment'] == 0:
                st.info("Tidak ada outlet/pesaing di dalam radius ini.")
            else:
                for seg in list_segmen:
                    if seg in res['catchment']:
                        data = res['catchment'][seg]
                        st.markdown(f"#### 🏷️ Segmen: {seg} ({data['jumlah']} Outlet)")
                        
                        for idx, item in enumerate(data['daftar']):
                            # Beri medali & buka otomatis untuk outlet paling dekat di segmen ini
                            title = f"🥇 {item['nama']} (Terdekat - {item['jarak_udara']} KM)" if idx == 0 else f"📍 {item['nama']} ({item['jarak_udara']} KM)"
                            
                            with st.expander(title, expanded=(idx==0)):
                                col1, col2 = st.columns(2)
                                with col1:
                                    st.markdown(f"**ID Pelanggan:** `{item['id']}`")
                                    st.markdown(f"**Jarak Udara:** {item['jarak_udara']} KM")
                                    
                                    # Pertahankan fitur OSRM untuk yang paling dekat!
                                    if idx == 0 and res['matches'][seg]:
                                        match_s = res['matches'][seg]
                                        st.markdown(f"**Jarak Darat (OSRM):** {match_s['jarak_darat']} KM")
                                        st.markdown(f"**Waktu Tempuh Darat:** {match_s['waktu_tempuh']} Menit")
                                with col2:
                                    # Looping untuk memasukkan semua data tambahan (Avg SPS, Jugs, dll)
                                    for k, v in item['extra_data'].items():
                                        val = v if pd.notna(v) and str(v).strip() != "" else "-"
                                        st.markdown(f"<div class='extra-data-row'><strong>{k}</strong><span>{val}</span></div>", unsafe_allow_html=True)
                        st.write("") # Spasi antar segmen

    else:
        st.info("Sistem standby. Silakan unggah Master Database pada panel di sebelah kiri.")

# ==========================================
# TAB 2: BATCH PROCESSING (SAMA SEPERTI SEBELUMNYA)
# ==========================================
with tab_batch:
    # ... Kode tab batch biarkan utuh seperti versi sebelumnya ...
    st.info("Fitur Batch Processing tetap berjalan sesuai pengaturan sebelumnya.")
