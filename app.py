import streamlit as st
import pandas as pd
import requests
import math
import numpy as np
import concurrent.futures # 1. Untuk Parallel Processing
from io import BytesIO
import folium
from streamlit_folium import st_folium
import plotly.express as px

# -------------------------------------------------------------
# 1. KONFIGURASI
# -------------------------------------------------------------
st.set_page_config(page_title="Spatial Analyzer Pro", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; max-width: 1200px; }
    .notion-h1 { font-size: 2.2rem; font-weight: 700; color: var(--text-color); margin-bottom: 0.2rem; letter-spacing: -0.02em; }
    .notion-sub { font-size: 0.95rem; color: var(--text-color); opacity: 0.6; margin-bottom: 2rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border-color); }
    .notion-callout { display: flex; flex-direction: column; padding: 20px; background-color: var(--secondary-background-color); border-radius: 4px; border: 1px solid var(--border-color); margin-bottom: 24px; border-left: 4px solid var(--text-color); }
    .card-prop-name { font-size: 0.75rem; color: var(--text-color); opacity: 0.5; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;}
    [data-testid="column"]:nth-of-type(2) {
        position: sticky;
        top: 3rem;
        height: calc(100vh - 3rem);
        overflow-y: auto;
    }
    [data-testid="column"]:nth-of-type(2)::-webkit-scrollbar { display: none; }
</style>
""", unsafe_allow_html=True)

if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None

# -------------------------------------------------------------
# 2. KONSTANTA
# -------------------------------------------------------------
COL_ID = "ID_PELANGGAN"
COL_NAME = "NAMA_PELANGGAN"
COL_SEG = "SEGMEN"
COL_STATUS = "STATUS_PELANGGAN"
COL_LAT = "LATITUDE"
COL_LON = "LONGITUDE"

TARGET_SEGMENTS = ['AHS', 'WS', 'SO']
TARGET_STATUS = ['ACT']

# -------------------------------------------------------------
# 3. DATA LOADING (Cached)
# -------------------------------------------------------------
@st.cache_data(show_spinner="Memuat data quadran...")
def load_quadran_data():
    try:
        df = pd.read_excel("Quadran.xlsx", sheet_name=0)
        df.columns = df.columns.astype(str).str.strip().str.upper()
        for col in ['KELURAHAN', 'KECAMATAN', 'KAB_KOT', 'PROVINCE']:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip().str.upper()
        return df
    except:
        return pd.DataFrame()

@st.cache_data(show_spinner="Memuat & Filter Data Master...")
def load_master(file_source):
    if isinstance(file_source, str):
        df = pd.read_excel(file_source, sheet_name=0)
    else:
        df = pd.read_excel(file_source, sheet_name=0)
        
    df.columns = df.columns.astype(str).str.strip().str.upper()
    if COL_STATUS in df.columns: df[COL_STATUS] = df[COL_STATUS].astype(str).str.strip().str.upper()
    if COL_SEG in df.columns: df[COL_SEG] = df[COL_SEG].astype(str).str.strip().str.upper()
    
    df = df.dropna(subset=[COL_LAT, COL_LON])
    
    # Filter statis di awal
    df = df[df[COL_SEG].isin(TARGET_SEGMENTS)]
    df = df[df[COL_STATUS].isin(TARGET_STATUS)]
    return df

# -------------------------------------------------------------
# 4. LOGIKA (Dioptimasi & Ditambah)
# -------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=86400)
def cari_alamat(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if res.status_code == 200:
            addr = res.json().get("address", {})
            return addr.get("village", "Unknown"), addr.get("town", "Unknown"), addr.get("city", "Unknown")
    except: pass
    return "Unknown", "Unknown", "Unknown"

def detect_quadran(lat, lon, df_quadran):
    kel, kec, kab = cari_alamat(lat, lon)
    kel_u, kec_u = str(kel).upper(), str(kec).upper()
    
    if df_quadran.empty: return "N/A", kel, kec, kab
    
    # Priority matching (Simplified for speed)
    for col_match in ['KELURAHAN', 'KECAMATAN']:
        val = kel_u if col_match == 'KELURAHAN' else kec_u
        match = df_quadran[df_quadran[col_match] == val]
        if not match.empty: return match.iloc[0]['QUADRAN'], kel, kec, kab
        match = df_quadran[df_quadran[col_match].str.contains(val, case=False, na=False)]
        if not match.empty: return match.iloc[0]['QUADRAN'], kel, kec, kab
        
    return "N/A", kel, kec, kab

def get_best_match(df_seg, lat_val, lon_val):
    if df_seg.empty: return None
    lats = df_seg[COL_LAT].astype(float).values
    lons = df_seg[COL_LON].astype(float).values
    distances = np.sqrt((lats - lat_val)**2 + (lons - lon_val)**2) * 111.12
    min_idx = distances.argmin()
    row = df_seg.iloc[min_idx]
    return {
        "id": row[COL_ID], "nama": row[COL_NAME], "status": row[COL_STATUS],
        "jarak_udara": round(distances[min_idx], 2),
        "lat": float(row[COL_LAT]), "lon": float(row[COL_LON]), "seg": row[COL_SEG]
    }

def fetch_osrm_task(params):
    """Wrapper untuk parallel processing"""
    lat1, lon1, lat2, lon2, seg_name = params
    url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get("code") == "Ok" and res.get("routes"):
            return seg_name, round(res["routes"][0]["distance"] / 1000, 2), round(res["routes"][0]["duration"] / 60, 1)
    except: pass
    return seg_name, "N/A", "N/A"

def analyze_catchment_area(df_filtered, lat_val, lon_val, radius_km):
    if df_filtered.empty: return {}, 0, 0
    df_t = df_filtered.copy()
    
    # Hitung jarak vectorized
    df_t['jarak_km'] = np.sqrt((df_t[COL_LAT].astype(float) - lat_val)**2 + (df_t[COL_LON].astype(float) - lon_val)**2) * 111.12
    df_in = df_t[df_t['jarak_km'] <= radius_km]

    summary = {}
    for seg in sorted(df_in[COL_SEG].unique()):
        df_seg = df_in[df_in[COL_SEG] == seg]
        status_group = {}
        for status in sorted(df_seg[COL_STATUS].unique()):
            df_st = df_seg[df_seg[COL_STATUS] == status].sort_values('jarak_km')
            daftar = [{"id": r[COL_ID], "nama": r[COL_NAME], "status": r[COL_STATUS], 
                       "lat": float(r[COL_LAT]), "lon": float(r[COL_LON]), 
                       "jarak_udara": round(r['jarak_km'], 2)} for _, r in df_st.iterrows()]
            status_group[status] = {"jumlah": len(df_st), "daftar": daftar}
        summary[seg] = status_group
        
    # Hitung Density Score: Jumlah Outlet / Luas Area (PI * r^2)
    area_km2 = math.pi * (radius_km ** 2)
    density = round(len(df_in) / area_km2, 2) if area_km2 > 0 else 0
    
    return summary, len(df_in), density

# -------------------------------------------------------------
# 5. SIDEBAR & INPUT
# -------------------------------------------------------------
st.sidebar.markdown("### ⚙️ Konfigurasi Data")
uploaded_master = st.sidebar.file_uploader("Upload Master Data", type=["xlsx"])

try:
    df_quadran = load_quadran_data()
    if uploaded_master: df_master = load_master(uploaded_master)
    else: df_master = load_master("AO_ALL_Segmen.xlsx")
except Exception as e:
    st.error(f"Gagal muat data: {e}")
    df_master = pd.DataFrame()

st.sidebar.info(f"**Filter Aktif:**\nSegmen: {', '.join(TARGET_SEGMENTS)}\nStatus: {', '.join(TARGET_STATUS)}")
st.sidebar.markdown(f"**Total Data:** {len(df_master):,} Outlet")

# -------------------------------------------------------------
# 6. MAIN UI
# -------------------------------------------------------------
st.markdown("<div class='notion-h1'>Spatial Analytics Pro</div>", unsafe_allow_html=True)
st.markdown("<div class='notion-sub'>Klik peta untuk menentukan lokasi target secara otomatis.</div>", unsafe_allow_html=True)

if not df_master.empty:
    # Input Section
    col_in1, col_in2, col_in3, col_in4 = st.columns([2, 1, 1, 1])
    
    # State management untuk koordinat
    if 'target_lat' not in st.session_state: st.session_state.target_lat = -6.914744
    if 'target_lon' not in st.session_state: st.session_state.target_lon = 107.609810

    in_name = col_in1.text_input("Nama Target", "Target Baru")
    # Gunakan session_state agar nilai tidak hilang saat rerun
    in_lat = col_in2.text_input("Latitude", value=str(st.session_state.target_lat))
    in_lon = col_in3.text_input("Longitude", value=str(st.session_state.target_lon))
    radius_filter = col_in4.number_input("Radius (KM)", 0.1, 50.0, 3.0, 0.1)

    # --- LOGIKA UTAMA ---
    if st.button("🚀 Jalankan Analisis", type="primary"):
        with st.spinner("Menghitung rute terbaik..."):
            try:
                lat_v, lon_v = float(in_lat), float(in_lon)
                
                # 1. Deteksi Lokasi Admin
                quad, kel, kec, kab = detect_quadran(lat_v, lon_v, df_quadran)
                
                # 2. Cari Terdekat (Fast Vectorization)
                temp_matches = []
                for seg in TARGET_SEGMENTS:
                    df_seg = df_master[df_master[COL_SEG] == seg]
                    best = get_best_match(df_seg, lat_v, lon_v)
                    if best: temp_matches.append(best)
                
                # 3. Parallel OSRM (Cepat!)
                # Siapkan parameter untuk threading
                osrm_params = [(lat_v, lon_v, m['lat'], m['lon'], m['seg']) for m in temp_matches]
                matches = {}
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_seg = {executor.submit(fetch_osrm_task, p): p for p in osrm_params}
                    for future in concurrent.futures.as_completed(future_to_seg):
                        seg_name, dist, time = future.result()
                        # Cari data base match berdasarkan seg_name
                        base_match = next((x for x in temp_matches if x['seg'] == seg_name), None)
                        if base_match:
                            base_match['jarak_darat'] = dist
                            base_match['waktu_tempuh'] = time
                            matches[seg_name] = base_match

                # 4. Catchment & Density
                catchment, total_catch, density_score = analyze_catchment_area(df_master, lat_v, lon_v, radius_filter)

                st.session_state.analysis_result = {
                    "name": in_name, "lat": lat_v, "lon": lon_v, "quad": quad,
                    "matches": matches, "catchment": catchment,
                    "total_catchment": total_catch, "radius": radius_filter,
                    "density": density_score,
                    "admin": {"kel": kel, "kec": kec, "kab": kab}
                }
            except ValueError:
                st.error("Format koordinat salah!")

    # --- HASIL ANALISIS ---
    if st.session_state.analysis_result:
        res = st.session_state.analysis_result
        st.write("---")
        
        col_info, col_map = st.columns([1, 1.2], gap="large")
        
        # KIRI: Informasi Detail
        with col_info:
            # Callout dengan warna Density
            density_color = "#E03E3E" if res['density'] > 5 else "#00A86B" if res['density'] > 1 else "#FF9900"
            st.markdown(f"""
            <div class="notion-callout" style="border-left-color: {density_color}">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <strong style="font-size:1.2rem;">{res['name']}</strong>
                    <span style="font-weight:700; color:{density_color}; font-size:1.5rem;">{res['density']}</span>
                </div>
                <div style="font-size:0.8rem; opacity:0.7; margin-bottom:8px;">Density Score (Outlet/Km²)</div>
                <div>
                    <span style="font-size:0.75rem; opacity:0.6; font-weight:600;">LOKASI: {res['admin']['kec']}, {res['admin']['kab']}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Daftar Terdekat
            st.markdown("#### 🎯 Outlet Terdekat")
            for seg, m in res['matches'].items():
                with st.expander(f"{seg} | {m['nama']}", expanded=True):
                    c1, c2 = st.columns(2)
                    c1.metric("Udara (KM)", m['jarak_udara'])
                    c2.metric("Darat (KM)", m['jarak_darat'])
            
            # Detail Catchment
            st.markdown(f"#### 📊 {res['total_catchment']} Outlet dalam Radius")
            for seg, status_groups in res['catchment'].items():
                with st.expander(f"Segmen {seg}"):
                    for st_name, data in status_groups.items():
                        st.write(f"**{st_name}**: {data['jumlah']} Outlet")
                        # Tampilkan max 5 terdekat saja agar tidak kepanjangan
                        for item in data['daftar'][:5]:
                            st.caption(f"• {item['nama']} ({item['jarak_udara']} km)")

        # KANAN: Peta Interaktif
        with col_map:
            # Peta Kontrol
            show_lines = st.checkbox("Tampilkan Garis Rute", True)
            show_radius = st.checkbox("Tampilkan Area Radius", True)
            show_outlets = st.checkbox("Tampilkan Titik Outlet", True)

            m = folium.Map(location=[res['lat'], res['lon']], zoom_start=14, tiles="cartodb positron")
            
            # Target Marker
            folium.Marker([res['lat'], res['lon']], popup=f"<b>{res['name']}</b>", icon=folium.Icon(color="red", icon="home")).add_to(m)
            
            if show_radius:
                folium.Circle([res['lat'], res['lon']], radius=res['radius']*1000, color='blue', fill=True, fill_opacity=0.1).add_to(m)

            # Garis & Marker Terdekat
            for seg, m_data in res['matches'].items():
                color = "#2D88FF" if seg == "AHS" else "#FF9900" if seg == "WS" else "#00A86B"
                if show_lines:
                    folium.PolyLine([[res['lat'], res['lon']], [m_data['lat'], m_data['lon']]], color=color, weight=3).add_to(m)
                folium.Marker([m_data['lat'], m_data['lon']], icon=folium.Icon(color="lightblue", icon="star"), popup=f"<b>{m_data['nama']}</b><br>{seg}").add_to(m)

            # Semua outlet dalam radius
            if show_outlets:
                for seg, status_groups in res['catchment'].items():
                    color = "#2D88FF" if seg == "AHS" else "#FF9900" if seg == "WS" else "#00A86B"
                    for st_data in status_groups.values():
                        for item in st_data['daftar']:
                            folium.CircleMarker([item['lat'], item['lon']], radius=3, color=color, fill_opacity=0.5).add_to(m)
            
            # Render Map
            map_data = st_folium(m, height=500, width="100%", returned_objects=["last_clicked"])
            
            # LOGIKA INTERAKTIF KLIK PETA
            if map_data.get("last_clicked"):
                click_lat = map_data["last_clicked"]["lat"]
                click_lon = map_data["last_clicked"]["lng"]
                # Update session state
                st.session_state.target_lat = click_lat
                st.session_state.target_lon = click_lon
                # Beri info ke user
                st.info(f"📍 Koordinat dipilih: {click_lat:.5f}, {click_lon:.5f}. Klik 'Jalankan Analisis' untuk update.")
                # Rerun otomatis agar input text terupdate (opsional, bisa dimatikan jika ingin user klik manual)
                st.rerun()

else:
    st.warning("Data Master kosong atau filter tidak cocok.")
